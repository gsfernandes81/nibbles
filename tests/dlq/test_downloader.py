"""The downloader: one slice at a time, and always resumable afterwards.

``expire_dl`` is the only code here that touches a socket, so it is the only
thing checked against a server — one on the loopback interface, which is where
"offline" still means offline. What it is checked for is the three ideas the
module is built on: the *server* ends the transfer at the slice boundary, the
resume offset is whatever survived on the disk, and the item stops itself
before the runner would.

The first test is the one that matters most and reads like the least. **A file
smaller than one chunk must be fetched, not declined.** The runner hands a
partial item a slice of exactly what it still needs, so every such file asks
for less than a chunk on its first firing; a sub-chunk guard that refused it
would exit 75 with nothing moved, which the runner reads as "not tonight" — no
strike, no attempt spent — and the item would be offered the same too-small
slice again every firing, for ever, saying only that it was still queued.
"""

from __future__ import annotations

import errno
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import signal
import threading

import pytest
from hypothesis import given
from hypothesis import strategies as st

MiB = 1024**2


@pytest.fixture
def fetching(dlq, monkeypatch, tmp_path):
    """``EXPIRE_WORK`` and ``EXPIRE_OUT``, and a slice a test chooses."""
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    monkeypatch.setenv("EXPIRE_WORK", str(work))
    monkeypatch.setenv("EXPIRE_OUT", str(out))
    monkeypatch.setenv("EXPIRE_RUN_ID", "run-1")
    monkeypatch.setenv("EXPIRE_STOP_EPOCH", "0")
    monkeypatch.setattr(dlq.dl, "_stop", False, raising=False)
    # ``fetch`` installs its own SIGINT and SIGTERM handlers, which is right
    # for an item and wrong for the process running the suite.
    kept = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}

    def slice_of(size: int) -> None:
        monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(size))

    slice_of(64 * MiB)
    yield type(
        "Fetching",
        (),
        {"work": work, "out": out, "slice_of": staticmethod(slice_of)},
    )
    for number, handler in kept.items():
        signal.signal(number, handler)


def status(work) -> dict:
    return json.loads((work / ".status.json").read_text())


class Odd(http.server.ThreadingHTTPServer):
    """A server with the manners the shared one does not have.

    It honours If-Range the way RFC 9110 has it (a validator that does not
    match is answered with the whole file), it can leave a body's length
    unstated — sent until the connection closes, or chunked — or state a
    206's total as ``*``, and a test can queue one-off answers that are not
    the file: a web page behind a redirect (the way a portal sends one), a
    200 to one ranged request, a chunked body cut off part-way, a status line
    that is not HTTP. Every request for the file is in ``asked``.
    """

    daemon_threads = True
    allow_reuse_address = True

    payload = b""
    etag = '"v1"'
    honour_range = True
    #: "length", "close" (sent until the connection closes) or "chunked".
    framing = "length"
    #: Whether a 206 states the file's size after the slash, or says ``*``.
    total_known = True


class OddHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A003 - the suite is not a web log
        pass

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        server = self.server
        if self.path == "/login":
            body = b"<html><body>Please sign in to continue</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        server.asked.append(self.headers.get("Range", ""))
        once = server.once.pop(0) if server.once else {}
        if once.get("garbage"):
            self.wfile.write(b"garbage\r\n\r\n")
            self.close_connection = True
            return
        if once.get("page"):
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = server.payload
        wanted = self.headers.get("Range", "")
        ranged = wanted.startswith("bytes=") and server.honour_range
        ranged = ranged and not once.get("whole")
        if self.headers.get("If-Range", server.etag) != server.etag:
            ranged = False
        if ranged:
            first, _, last = wanted[6:].partition("-")
            start = int(first)
            if start >= len(payload):
                self.send_response(416)
                if server.total_known:
                    self.send_header("Content-Range", f"bytes */{len(payload)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(int(last) if last else len(payload) - 1, len(payload) - 1)
            body = payload[start : end + 1]
            self.send_response(206)
            size = len(payload) if server.total_known else "*"
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            body = payload
            self.send_response(200)
        self.send_header("ETag", server.etag)
        self._body(body, once.get("cut"))

    def _body(self, body: bytes, cut: int | None) -> None:
        framing = self.server.framing
        if framing == "length":
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if framing == "close":
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        step = 16 * 1024
        for at in range(0, len(body), step):
            piece = body[at : at + step]
            self.wfile.write(f"{len(piece):x}\r\n".encode())
            if cut is not None and at + len(piece) > cut:
                # Part of a chunk and then the connection closes, cleanly.
                self.wfile.write(piece[: cut - at])
                self.close_connection = True
                return
            self.wfile.write(piece + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")


@pytest.fixture
def odd():
    """An :class:`Odd` server on the loopback interface."""
    server = Odd(("127.0.0.1", 0), OddHandler)
    server.once, server.asked = [], []
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    host, port = server.server_address[:2]
    server.url = f"http://{host}:{port}/file.bin"
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def fetch_until_done(dlq, url: str, name: str, firings: int, **kw) -> list[str]:
    """Fire *url* up to *firings* times, stopping at the first COMPLETE."""
    answers = []
    for _ in range(firings):
        answers.append(dlq.dl.fetch(url, name, **kw))
        if answers[-1] == dlq.dl.COMPLETE:
            break
    return answers


# --------------------------------------------------------------------------- #
# The one that reads like the least
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size", [1, 1024, 15 * 1024])
def test_a_file_smaller_than_a_chunk_is_fetched_rather_than_declined(
    dlq, serving, fetching, size
):
    """A 15 KiB wheel is not a slow download; it is one that can never happen.

    The exemption is for the slice that is the whole of what is left, which is
    exactly what every sub-chunk file is handed on its first firing.
    """
    assert size < dlq.dl.CHUNK
    serving.payload = b"x" * size
    fetching.slice_of(size)
    assert dlq.dl.fetch(serving.url, "small.bin", total_hint=size) == dlq.dl.COMPLETE
    assert (fetching.out / "small.bin").read_bytes() == serving.payload
    assert serving.state_of_the_world["asked"], "it never even asked"


def test_a_small_slice_of_something_bigger_is_still_declined(
    dlq, serving, fetching
):
    """Below a chunk and not the end of the file: mostly connection setup.

    And it is declined *before* a request, which is the difference between the
    two cases — this one strikes nothing off the queue however often it is
    tried, and the one above finishes the item.
    """
    serving.payload = b"x" * (10 * MiB)
    fetching.slice_of(1024)
    answer = dlq.dl.fetch(serving.url, "big.bin", total_hint=10 * MiB)
    assert answer == dlq.dl.DECLINED
    assert serving.state_of_the_world.get("asked") is None
    assert status(fetching.work)["state"] == dlq.dl.DECLINED


# --------------------------------------------------------------------------- #
# Slices, and what survives between them
# --------------------------------------------------------------------------- #


def test_a_slice_takes_what_it_was_given_and_stops(dlq, serving, fetching):
    """The server ends the transfer at the boundary; nothing races an abort."""
    serving.payload = bytes(range(256)) * 2048  # 512 KiB
    fetching.slice_of(200 * 1024)
    answer = dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
    assert answer == dlq.dl.PROGRESS
    part = fetching.work / "part.bin.part"
    assert part.stat().st_size == 200 * 1024
    assert part.read_bytes() == serving.payload[: 200 * 1024]
    assert serving.state_of_the_world["asked"][0] == "bytes=0-204799"


def test_the_resume_offset_is_whatever_is_on_the_disk(dlq, serving, fetching):
    """Never a counter in a metadata file: writes are append-only.

    So whatever survives is a valid prefix of the remote file however the
    process died, SIGKILL included — which is what a truncated part is made to
    prove here.
    """
    serving.payload = bytes(range(256)) * 2048
    part = fetching.work / "part.bin.part"
    part.write_bytes(serving.payload[: 100 * 1024])

    fetching.slice_of(100 * 1024)
    dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
    assert serving.state_of_the_world["asked"][-1] == "bytes=102400-204799"
    assert part.read_bytes() == serving.payload[: 200 * 1024]

    # Half of it lost to a kill: the next slice starts from what is there.
    with part.open("r+b") as handle:
        handle.truncate(50 * 1024)
    dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
    assert serving.state_of_the_world["asked"][-1].startswith("bytes=51200-")
    assert part.read_bytes() == serving.payload[: 150 * 1024]


def test_the_last_slice_delivers_the_file_and_takes_the_scratch_with_it(
    dlq, serving, fetching
):
    serving.payload = b"y" * (300 * 1024)
    fetching.slice_of(len(serving.payload))
    assert dlq.dl.fetch(serving.url, "done.bin", total_hint=0) == dlq.dl.COMPLETE
    assert (fetching.out / "done.bin").read_bytes() == serving.payload
    assert not (fetching.work / "done.bin.part").exists()
    assert not (fetching.work / "done.bin.part.meta.json").exists()
    report = status(fetching.work)
    assert report["state"] == dlq.dl.COMPLETE
    assert report["run_id"] == "run-1"
    assert report["part_bytes"] == len(serving.payload)


def test_the_size_a_server_states_beats_any_hint(dlq, serving, fetching):
    """``Content-Range`` carries the truth; the hint is only a starting guess."""
    serving.payload = b"z" * (300 * 1024)
    fetching.slice_of(100 * 1024)
    dlq.dl.fetch(serving.url, "sized.bin", total_hint=999)
    assert status(fetching.work)["total_bytes"] == len(serving.payload)


# --------------------------------------------------------------------------- #
# The ways it refuses
# --------------------------------------------------------------------------- #


def test_a_server_that_will_not_resume_is_refused_rather_than_looped_on(
    dlq, serving, fetching
):
    """Restart, and then say so: the oscillation costs real data.

    Every attempt would download a slice, discover it cannot resume, throw it
    away and start over — spending money every other night and never
    converging. One 200 is not yet that server (a cold edge, a mirror's
    hiccup), so the part is kept once; a second in a row is.
    """
    serving.payload = b"w" * (400 * 1024)
    serving.honour_range = False
    part = fetching.work / "part.bin.part"
    part.write_bytes(b"w" * (10 * 1024))
    fetching.slice_of(100 * 1024)

    seen = [
        dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
        for _ in range(5)
    ]
    # Nothing worse than "not tonight" while it finds out, and never a slice
    # appended; once it is known that the server ignores Range and the file is
    # bigger than a slice, it is refused outright and stays refused.
    first = seen.index(dlq.dl.FATAL)
    assert first <= 2
    assert set(seen[:first]) == {dlq.dl.DECLINED}
    assert set(seen[first:]) == {dlq.dl.FATAL}
    # Refused without asking: the requests stop where the finding-out does.
    assert len(serving.state_of_the_world["asked"]) == first
    # A partial that could not be resumed is not left to be appended to, and
    # the runner is not told it still has one.
    assert not part.exists()
    assert status(fetching.work)["part_bytes"] == 0


def test_a_file_that_is_not_what_was_asked_for_is_never_delivered(
    dlq, serving, fetching
):
    """A sha256 mismatch is the runaway a human should see a strike for."""
    serving.payload = b"q" * (200 * 1024)
    fetching.slice_of(len(serving.payload))
    wrong = hashlib.sha256(b"something else").hexdigest()
    answer = dlq.dl.fetch(
        serving.url, "checked.bin", expect_sha256=wrong, total_hint=len(serving.payload)
    )
    assert answer == dlq.dl.FATAL
    assert not (fetching.out / "checked.bin").exists()
    assert not (fetching.work / "checked.bin.part").exists()


def test_the_right_file_passes_the_same_check(dlq, serving, fetching):
    serving.payload = b"q" * (200 * 1024)
    fetching.slice_of(len(serving.payload))
    right = hashlib.sha256(serving.payload).hexdigest()
    answer = dlq.dl.fetch(
        serving.url, "checked.bin", expect_sha256=right, total_hint=len(serving.payload)
    )
    assert answer == dlq.dl.COMPLETE
    assert (fetching.out / "checked.bin").read_bytes() == serving.payload


def test_a_server_that_cannot_be_reached_is_declined_and_says_so(dlq, fetching):
    """No traceback out of an item, and no strike either: it is not tonight."""
    answer = dlq.dl.fetch("http://127.0.0.1:1/gone.bin", "gone.bin", total_hint=MiB)
    assert answer == dlq.dl.DECLINED
    assert status(fetching.work)["state"] == dlq.dl.DECLINED


def test_an_item_never_tracebacks_out(dlq, monkeypatch):
    """Whatever happens, the runner gets an exit code it understands."""

    def boom(*args, **kw):
        raise RuntimeError("something nobody thought of")

    monkeypatch.setattr(dlq.dl, "fetch", boom)
    assert dlq.dl.run("http://127.0.0.1:1/x", "x.bin") == dlq.dl.EXIT[dlq.dl.FATAL]
    assert set(dlq.dl.EXIT) == {
        dlq.dl.COMPLETE,
        dlq.dl.PROGRESS,
        dlq.dl.DECLINED,
        dlq.dl.FATAL,
    }
    # "Not tonight" and "nothing to do" are the same answer to the runner; only
    # a fault is a strike.
    assert dlq.dl.EXIT[dlq.dl.COMPLETE] == 0
    assert dlq.dl.EXIT[dlq.dl.PROGRESS] == dlq.dl.EXIT[dlq.dl.DECLINED] == 75
    assert dlq.dl.EXIT[dlq.dl.FATAL] not in (0, 75)


def test_a_deadline_stops_a_slice_and_leaves_it_resumable(
    dlq, serving, fetching, monkeypatch
):
    """The item stops itself before the runner would, and keeps what it has."""
    serving.payload = b"r" * (2 * MiB)
    fetching.slice_of(2 * MiB)
    # A stop time that has already passed by the margin: the first check inside
    # the read loop ends the slice.
    monkeypatch.setenv("EXPIRE_STOP_EPOCH", str(int(dlq.runner.now()) - 60))
    answer = dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
    assert answer == dlq.dl.DECLINED
    assert not (fetching.out / "part.bin").exists()
    # Whatever it did take is a valid prefix and can be resumed from.
    part = fetching.work / "part.bin.part"
    got = part.read_bytes() if part.exists() else b""
    assert serving.payload.startswith(got)


def test_a_finished_part_from_last_night_is_delivered_without_a_request(
    dlq, serving, fetching
):
    """Last night moved the final bytes but died before verifying."""
    serving.payload = b"s" * (100 * 1024)
    part = fetching.work / "late.bin.part"
    part.write_bytes(serving.payload)
    (fetching.work / "late.bin.part.meta.json").write_text(
        json.dumps({"total": len(serving.payload)})
    )
    fetching.slice_of(1024)
    assert dlq.dl.fetch(serving.url, "late.bin") == dlq.dl.COMPLETE
    assert serving.state_of_the_world.get("asked") is None
    assert (fetching.out / "late.bin").read_bytes() == serving.payload


def test_progress_is_reported_under_the_run_id_it_was_given(dlq, serving, fetching):
    """So the runner can never mistake last night's report for tonight's."""
    serving.payload = b"t" * (300 * 1024)
    fetching.slice_of(100 * 1024)
    dlq.dl.fetch(serving.url, "part.bin", total_hint=len(serving.payload))
    assert dlq.runner.read_status(fetching.work, "run-1", 10 * MiB)["spent"] == 100 * 1024
    assert dlq.runner.read_status(fetching.work, "another-run", 10 * MiB) is None


def test_a_claim_is_clamped_to_what_crossed_the_interface(dlq, tmp_path):
    """The count is the item's claim, and an under-report would flatter it."""
    work = tmp_path / "claiming"
    work.mkdir()
    (work / ".status.json").write_text(
        json.dumps({"run_id": "r", "payload_bytes_this_slice": 10 * MiB})
    )
    assert dlq.runner.read_status(work, "r", 4 * MiB)["spent"] == 4 * MiB
    assert dlq.runner.read_status(work, "r", 40 * MiB)["spent"] == 10 * MiB
    (work / ".status.json").write_text(
        json.dumps({"run_id": "r", "payload_bytes_this_slice": -5})
    )
    assert dlq.runner.read_status(work, "r", 40 * MiB)["spent"] == 0


def test_a_file_it_has_no_time_to_verify_keeps_until_the_next_firing(
    dlq, serving, fetching, monkeypatch
):
    """Hashing is not interruptible-and-resumable, so it refuses to start it
    without room to finish — and says "not tonight" rather than delivering an
    unverified file or throwing a verified one away."""
    serving.payload = b"v" * (300 * 1024)
    part = fetching.work / "checked.bin.part"
    part.write_bytes(serving.payload)
    (fetching.work / "checked.bin.part.meta.json").write_text(
        json.dumps({"total": len(serving.payload)})
    )
    # A stop time a second away: there is no room to hash anything.
    monkeypatch.setenv("EXPIRE_STOP_EPOCH", str(int(dlq.runner.now()) + 1))
    right = hashlib.sha256(serving.payload).hexdigest()
    answer = dlq.dl.fetch(serving.url, "checked.bin", expect_sha256=right)

    assert answer == dlq.dl.PROGRESS
    assert not (fetching.out / "checked.bin").exists()
    assert part.read_bytes() == serving.payload


def test_a_remote_file_that_changed_under_us_is_never_appended_to(
    dlq, serving, fetching
):
    """Appending would corrupt silently, and the corruption is only found — if
    ever — by a hash at the end of a file that has already been paid for."""
    serving.payload = b"a" * (300 * 1024)
    fetching.slice_of(100 * 1024)
    assert dlq.dl.fetch(serving.url, "part.bin") == dlq.dl.PROGRESS
    part = fetching.work / "part.bin.part"
    assert part.stat().st_size == 100 * 1024

    serving.payload = b"b" * (300 * 1024)
    serving.etag = '"second"'
    assert dlq.dl.fetch(serving.url, "part.bin") == dlq.dl.DECLINED
    assert not part.exists()
    # And the next firing starts from nothing rather than from half of each.
    assert dlq.dl.fetch(serving.url, "part.bin") == dlq.dl.PROGRESS
    assert part.read_bytes() == serving.payload[: 100 * 1024]
    # The runner is told the part it had is gone, so it does not plan the
    # next slice from bytes that were thrown away.
    assert status(fetching.work)["part_bytes"] == 100 * 1024


def test_one_odd_answer_never_condemns_a_download(dlq, odd, fetching, monkeypatch):
    """A file re-published, a 200 to one ranged request, a sign-in page in
    place of the file — each of them once, at any firing, and the download
    still ends with the file the server has now, without a strike.

    One 200 used to delete the paid-for part and mark the server as unable to
    resume for good: every firing after that was a strike made without a
    request, against a server that was answering 206 again.
    """
    size, slice_ = 400 * 1024, 100 * 1024
    monkeypatch.setenv("EXPIRE_TOTAL_BYTES", str(size + MiB))
    fetching.slice_of(slice_)
    part = fetching.work / "big.bin.part"
    for injected in ("changed", "whole", "page"):
        for at in (2, 3):
            for path in fetching.work.iterdir():
                path.unlink()
            for path in fetching.out.iterdir():
                path.unlink()
            odd.payload, odd.etag = os.urandom(size), '"v1"'
            answers = []
            for firing in range(1, 12):
                before = part.stat().st_size if part.exists() else 0
                if firing == at and injected == "changed":
                    odd.payload, odd.etag = os.urandom(size), '"v2"'
                elif firing == at:
                    odd.once.append({injected: True})
                answers.append(dlq.dl.fetch(odd.url, "big.bin", total_hint=size))
                if firing == at and injected != "changed":
                    # The part was paid for, and nothing said was about it.
                    assert (part.stat().st_size if part.exists() else 0) >= before
                if answers[-1] == dlq.dl.COMPLETE:
                    break
            assert dlq.dl.FATAL not in answers, (injected, at, answers)
            assert answers[-1] == dlq.dl.COMPLETE, (injected, at, answers)
            assert (fetching.out / "big.bin").read_bytes() == odd.payload


def test_a_server_once_thought_not_to_resume_is_believed_when_it_does(
    dlq, serving, fetching
):
    """Nothing learned from a 200 outlives a 206: a flag that never cleared
    refused the item on every firing after the server came right."""
    serving.payload = os.urandom(300 * 1024)
    meta = fetching.work / "x.bin.part.meta.json"
    meta.write_text(json.dumps({"no_range": True, "range_200s": 1}))
    fetching.slice_of(100 * 1024)
    assert dlq.dl.fetch(serving.url, "x.bin") == dlq.dl.PROGRESS
    said = json.loads(meta.read_text())
    assert "no_range" not in said and "range_200s" not in said
    fetching.slice_of(MiB)
    assert dlq.dl.fetch(serving.url, "x.bin") == dlq.dl.COMPLETE
    assert (fetching.out / "x.bin").read_bytes() == serving.payload


def test_a_server_that_ignores_range_is_not_read_a_slice_it_cannot_resume(
    dlq, serving, fetching
):
    """A 200 to a ranged request, bigger than the slice, is a server that will
    not resume — known from its headers, before a byte of the body. Reading
    the slice anyway bought bytes the next firing threw away."""
    serving.payload = os.urandom(400 * 1024)
    serving.honour_range = False
    fetching.slice_of(100 * 1024)
    size = len(serving.payload)
    assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.DECLINED
    assert status(fetching.work)["payload_bytes_this_slice"] == 0
    assert not (fetching.work / "x.bin.part").exists()
    # Refused without asking while a slice cannot hold it...
    asked = len(serving.state_of_the_world["asked"])
    assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.FATAL
    assert len(serving.state_of_the_world["asked"]) == asked
    # ...and fetched whole by a firing that can.
    fetching.slice_of(size)
    assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.COMPLETE
    assert (fetching.out / "x.bin").read_bytes() == serving.payload


# --------------------------------------------------------------------------- #
# Answers that are not the file
# --------------------------------------------------------------------------- #


def test_a_web_page_is_never_delivered_as_the_file(dlq, odd, fetching):
    """A portal's sign-in page, behind the redirect a portal sends, in place
    of a 6 GB file: it used to be written under the file's name, complete the
    item and land in Downloads as something nothing opens. And "not tonight"
    for ever is not the answer either: in a row, it becomes a strike."""
    odd.payload = os.urandom(300 * 1024)
    odd.once = [{"page": True} for _ in range(dlq.dl.MAX_REFUSALS)]
    fetching.slice_of(MiB)
    answers = [
        dlq.dl.fetch(odd.url, "distro.iso", total_hint=6_000_000_000)
        for _ in range(dlq.dl.MAX_REFUSALS)
    ]
    assert dlq.dl.COMPLETE not in answers
    assert list(fetching.out.iterdir()) == []
    assert answers[-1] == dlq.dl.FATAL
    assert set(answers[:-1]) == {dlq.dl.DECLINED}


def test_a_web_page_leaves_a_resumed_download_exactly_as_it_was(dlq, odd, fetching):
    """Nothing a page says is a fact about the file: the part, its validators,
    its size and whether the server resumes all stand, and the next firing
    resumes from the same byte."""
    odd.payload = os.urandom(300 * 1024)
    fetching.slice_of(100 * 1024)
    size = len(odd.payload)
    assert dlq.dl.fetch(odd.url, "x.bin", total_hint=size) == dlq.dl.PROGRESS
    part, meta = fetching.work / "x.bin.part", fetching.work / "x.bin.part.meta.json"
    had, said = part.read_bytes(), json.loads(meta.read_text())

    odd.once.append({"page": True})
    assert dlq.dl.fetch(odd.url, "x.bin", total_hint=size) == dlq.dl.DECLINED
    assert part.read_bytes() == had
    now = json.loads(meta.read_text())
    now.pop("refused", None)
    assert now == said

    odd.asked.clear()
    answers = fetch_until_done(dlq, odd.url, "x.bin", 5, total_hint=size)
    assert answers[-1] == dlq.dl.COMPLETE
    assert odd.asked[0].startswith(f"bytes={len(had)}-")
    assert (fetching.out / "x.bin").read_bytes() == odd.payload


@pytest.mark.parametrize(
    "kind", ["text/html; charset=utf-8", "application/xhtml+xml", "application/zip", None]
)
@pytest.mark.parametrize("disposition", [None, 'attachment; filename="a.html"'])
def test_what_nibbles_calls_a_page_is_what_the_download_refuses(
    dlq, serving, fetching, kind, disposition
):
    """One test at both ends (``expire_dl.is_page``): a link ``nibbles``
    would queue as a file is one the download fetches, an HTML attachment
    included, and one it would call a page is one the download refuses."""
    serving.payload = b"<html></html>" * 100
    serving.content_type, serving.disposition = kind, disposition
    fetching.slice_of(MiB)
    page = dlq.queuer.kind_of(serving.url) == "page"
    answer = dlq.dl.fetch(serving.url, "a.html", total_hint=len(serving.payload))
    assert (answer == dlq.dl.COMPLETE) is not page
    assert (fetching.out / "a.html").exists() is not page


@pytest.mark.parametrize("code", [401, 403, 404, 410])
def test_a_dead_link_becomes_a_strike_rather_than_not_tonight_for_ever(
    dlq, serving, fetching, code
):
    """An expired signature or a file taken down is refused in milliseconds,
    and as "not tonight" it was asked for every firing of every night, logged
    as progress, never a strike and never seen."""
    serving.get_code = code
    answers = [
        dlq.dl.fetch(serving.url, "gone.bin", total_hint=MiB)
        for _ in range(dlq.dl.MAX_REFUSALS)
    ]
    assert answers[-1] == dlq.dl.FATAL
    assert set(answers[:-1]) == {dlq.dl.DECLINED}


@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_a_link_that_is_only_busy_is_never_a_strike(dlq, serving, fetching, code):
    serving.get_code = code
    assert {
        dlq.dl.fetch(serving.url, "busy.bin", total_hint=MiB) for _ in range(10)
    } == {dlq.dl.DECLINED}


def test_an_unreachable_server_is_never_a_strike(dlq, fetching):
    """An offline phone is not a dead link."""
    assert {
        dlq.dl.fetch("http://127.0.0.1:1/gone.bin", "gone.bin", total_hint=MiB)
        for _ in range(10)
    } == {dlq.dl.DECLINED}


def test_an_answer_that_is_the_file_starts_the_count_again(dlq, serving, fetching):
    """It is answers *in a row*: a hiccup now and then never adds up to one."""
    serving.payload = os.urandom(300 * 1024)
    fetching.slice_of(100 * 1024)
    size = len(serving.payload)
    serving.get_code = 404
    for _ in range(dlq.dl.MAX_REFUSALS - 1):
        assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.DECLINED
    serving.get_code = 200
    assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.PROGRESS
    serving.get_code = 404
    answers = [
        dlq.dl.fetch(serving.url, "x.bin", total_hint=size)
        for _ in range(dlq.dl.MAX_REFUSALS)
    ]
    assert answers[-1] == dlq.dl.FATAL
    assert set(answers[:-1]) == {dlq.dl.DECLINED}


@pytest.mark.parametrize("cut", [1, 30_000, 64 * 1024, 100_000])
def test_a_body_cut_off_mid_chunk_is_a_dropped_link_not_a_strike(
    dlq, odd, fetching, cut
):
    """The same dropped link a reset is: what arrived is kept and reported,
    the slice ends as "not tonight", and the next firing resumes from it.
    It used to escape the read loop as an unhandled error — a strike, with
    the bytes in flight thrown away and the report left behind the disk."""
    odd.payload = os.urandom(300 * 1024)
    odd.framing = "chunked"
    odd.once.append({"cut": cut})
    fetching.slice_of(len(odd.payload))
    size = len(odd.payload)
    assert dlq.dl.run(odd.url, "c.bin", total_hint=size) == 75
    part = fetching.work / "c.bin.part"
    got = part.read_bytes() if part.exists() else b""
    assert odd.payload.startswith(got)
    assert status(fetching.work)["payload_bytes_this_slice"] == len(got)

    odd.asked.clear()
    answers = fetch_until_done(dlq, odd.url, "c.bin", 3, total_hint=size)
    assert answers[-1] == dlq.dl.COMPLETE
    assert odd.asked[0].startswith(f"bytes={len(got)}-")
    assert (fetching.out / "c.bin").read_bytes() == odd.payload


def test_an_answer_that_is_not_http_is_not_tonight(dlq, odd, fetching):
    odd.payload = os.urandom(100 * 1024)
    odd.once.append({"garbage": True})
    answer = dlq.dl.fetch(odd.url, "g.bin", total_hint=len(odd.payload))
    assert answer == dlq.dl.DECLINED
    assert not (fetching.work / "g.bin.part").exists()


# --------------------------------------------------------------------------- #
# Files no server sized
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("framing", ["close", "chunked"])
@pytest.mark.parametrize(
    ("size", "cap"),
    [
        (5_000, 10_000),  # under a chunk: fetched, never "too small"
        (100_000, 300_000),
        (300_000, 300_000),  # ends exactly where the cap does
        (300_001, 300_000),
        (800_000, 300_000),
    ],
)
def test_a_file_no_server_sized_is_delivered_whole_or_not_at_all(
    dlq, odd, fetching, monkeypatch, framing, size, cap
):
    """The cap bounds what may be spent; it is never the file's size.

    Taken for one, a file smaller than its cap was never "complete" — fetched,
    thrown away and fetched again until it failed — and one larger was
    delivered cut off at the cap and archived as done.
    """
    odd.payload = os.urandom(size)
    odd.framing = framing
    odd.honour_range = False
    monkeypatch.setenv("EXPIRE_TOTAL_BYTES", str(cap))
    fetching.slice_of(cap)
    answer = dlq.dl.fetch(odd.url, "export.bin", total_hint=0)
    said = status(fetching.work)
    out = fetching.out / "export.bin"
    assert said["total_bytes"] in (0, size)
    if size <= cap:
        assert answer == dlq.dl.COMPLETE
        assert out.read_bytes() == odd.payload
        return
    # Bigger than its declaration: a strike, nothing delivered, no part the
    # runner would read as "nothing left to fetch" -- and never bought again
    # to find that out.
    assert answer == dlq.dl.FATAL
    assert not out.exists()
    assert said["part_bytes"] == 0
    odd.asked.clear()
    assert dlq.dl.fetch(odd.url, "export.bin", total_hint=0) == dlq.dl.FATAL
    assert odd.asked == []


def test_an_unsized_file_that_will_not_resume_waits_for_a_slice_of_its_cap(
    dlq, odd, fetching, monkeypatch
):
    """A slice of an unsized file from a server that ignores Range cannot be
    resumed: it is thrown away once, and after that only a firing that can
    take the whole cap asks for it again."""
    odd.payload = os.urandom(800_000)
    odd.framing = "close"
    odd.honour_range = False
    monkeypatch.setenv("EXPIRE_TOTAL_BYTES", str(MiB))
    fetching.slice_of(300_000)
    assert dlq.dl.fetch(odd.url, "e.bin", total_hint=0) == dlq.dl.DECLINED
    assert status(fetching.work)["part_bytes"] == 0
    asked = len(odd.asked)
    assert dlq.dl.fetch(odd.url, "e.bin", total_hint=0) == dlq.dl.FATAL
    assert len(odd.asked) == asked
    fetching.slice_of(MiB)
    assert dlq.dl.fetch(odd.url, "e.bin", total_hint=0) == dlq.dl.COMPLETE
    assert (fetching.out / "e.bin").read_bytes() == odd.payload


@pytest.mark.parametrize("size", [250_000, 200_000])
def test_a_file_whose_size_is_never_stated_is_delivered_where_it_ends(
    dlq, odd, fetching, size
):
    """A 206 that says ``*`` for the total: the file ends where a slice comes
    back short, or — when a slice ended exactly at the end — where the next
    request is answered "nothing there". Neither used to deliver it."""
    odd.payload = os.urandom(size)
    odd.total_known = False
    fetching.slice_of(100_000)
    answers = fetch_until_done(dlq, odd.url, "s.bin", size // 100_000 + 1)
    assert answers[-1] == dlq.dl.COMPLETE
    assert (fetching.out / "s.bin").read_bytes() == odd.payload


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def test_a_file_already_delivered_is_never_bought_again(dlq, serving, fetching):
    """Delivered, and the runner stopped before it archived the item (a Pause
    during the hand-over): the next firing finds the file where only a
    finished, verified download is ever put, and asks for nothing."""
    serving.payload = os.urandom(300 * 1024)
    fetching.slice_of(MiB)
    size = len(serving.payload)
    assert dlq.dl.fetch(serving.url, "done.bin", total_hint=size) == dlq.dl.COMPLETE
    serving.state_of_the_world.clear()
    for _ in range(3):
        assert dlq.dl.fetch(serving.url, "done.bin", total_hint=size) == dlq.dl.COMPLETE
    assert serving.state_of_the_world.get("asked") is None
    assert (fetching.out / "done.bin").read_bytes() == serving.payload
    report = status(fetching.work)
    assert report["state"] == dlq.dl.COMPLETE
    assert report["part_bytes"] == size


def test_bookkeeping_that_cannot_be_tidied_never_undoes_a_delivery(
    dlq, serving, fetching, monkeypatch
):
    """A name near the limit has a ``.part.meta.json`` longer than a name may
    be. The file had already moved when removing it raised, and the item
    exited as a strike — to download the delivered file again."""
    serving.payload = os.urandom(100 * 1024)
    fetching.slice_of(MiB)
    real = pathlib.Path.unlink

    def unlink(self, missing_ok=False):
        if self.name.endswith(".meta.json"):
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(self))
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    assert dlq.dl.run(serving.url, "x.bin", total_hint=len(serving.payload)) == 0
    assert (fetching.out / "x.bin").read_bytes() == serving.payload


def test_the_longest_name_a_file_is_given_is_one_it_can_be_delivered_under(
    dlq, serving, fetching
):
    serving.payload = os.urandom(50 * 1024)
    fetching.slice_of(MiB)
    name = dlq.queuer.file_name("ü" * 400 + ".iso")
    assert dlq.dl.run(serving.url, name, total_hint=len(serving.payload)) == 0
    assert (fetching.out / name).read_bytes() == serving.payload


SPELLINGS = {
    "upper": str.upper,
    "mixed": lambda hexed: hexed[:32] + hexed[32:].upper(),
    "prefixed": lambda hexed: f"sha256:{hexed}",
    "prefixed upper": lambda hexed: f"SHA256:{hexed.upper()}",
    "padded": lambda hexed: f"  {hexed}\n",
    "sha256sum line": lambda hexed: f"{hexed}  checked.bin",
}


@pytest.mark.parametrize("spell", SPELLINGS.values(), ids=SPELLINGS.keys())
def test_a_digest_however_it_was_pasted_passes_the_right_file(
    dlq, serving, fetching, spell
):
    """Upper-case hex, a ``sha256:`` prefix, a ``sha256sum`` line: the same
    digest, and the right file passes it first time. Compared as typed, each
    failed a correct file, deleted it and bought it again per strike."""
    serving.payload = os.urandom(200 * 1024)
    fetching.slice_of(len(serving.payload))
    digest = spell(hashlib.sha256(serving.payload).hexdigest())
    answer = dlq.dl.fetch(
        serving.url, "checked.bin", expect_sha256=digest, total_hint=len(serving.payload)
    )
    assert answer == dlq.dl.COMPLETE
    assert (fetching.out / "checked.bin").read_bytes() == serving.payload
    assert len(serving.state_of_the_world["asked"]) == 1


@pytest.mark.parametrize(
    "wrong",
    [
        hashlib.md5(b"x").hexdigest(),  # noqa: S324 - a digest someone might paste
        hashlib.sha1(b"x").hexdigest(),  # noqa: S324
        hashlib.sha256(b"x").hexdigest()[:-1],
        "not a digest",
    ],
)
def test_a_digest_that_is_not_one_is_refused_before_a_byte_is_spent(
    dlq, serving, fetching, wrong
):
    serving.payload = os.urandom(100 * 1024)
    fetching.slice_of(MiB)
    answer = dlq.dl.fetch(
        serving.url, "checked.bin", expect_sha256=wrong, total_hint=len(serving.payload)
    )
    assert answer == dlq.dl.FATAL
    assert serving.state_of_the_world.get("asked") is None


@given(data=st.binary(max_size=64), spelling=st.sampled_from(list(SPELLINGS.values())))
def test_every_spelling_of_a_digest_is_hashlibs(dlq, data, spelling):
    digest = hashlib.sha256(data).hexdigest()
    assert dlq.dl.sha256_digest(spelling(digest)) == digest


# --------------------------------------------------------------------------- #
# The one move that crosses onto shared storage
# --------------------------------------------------------------------------- #


@pytest.fixture
def across(monkeypatch):
    """Renames out of the paths a test names fail with EXDEV, as a rename
    onto shared storage does; the rename beside the destination still works."""
    real = os.rename
    sources: set[str] = set()

    def rename(src, dst, *args, **kw):
        if os.fspath(src) in sources:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dst, *args, **kw)

    monkeypatch.setattr(os, "rename", rename)
    return sources


@pytest.fixture
def moving(tmp_path, across):
    """A file in ``out/`` and an empty ``shared/`` on "another filesystem"."""
    src = tmp_path / "out" / "Some Talk.mp4"
    src.parent.mkdir()
    src.write_bytes(os.urandom(10_000))
    shared = tmp_path / "shared"
    shared.mkdir()
    across.add(os.fspath(src))
    return type(
        "Moving",
        (),
        {"src": src, "data": src.read_bytes(), "shared": shared,
         "dst": shared / src.name},
    )


@pytest.mark.parametrize(
    "failure",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(errno.EIO, "Input/output error"),
        KeyboardInterrupt(),
    ],
    ids=["ENOSPC", "EIO", "Pause"],
)
@pytest.mark.parametrize("landed", [0, 1, 6_000])
def test_a_copy_that_fails_leaves_nothing_at_the_destination(
    dlq, moving, monkeypatch, failure, landed
):
    """Never a truncated file under the real name in Downloads for a gallery
    to index, and never the paid-for copy lost: whatever stops the copy, the
    destination is as it was and the source is whole."""

    def copyfile(src, dst, **kw):
        with open(dst, "wb") as handle:
            handle.write(moving.data[:landed])
        raise failure

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    with pytest.raises(type(failure)):
        dlq.dl.move_file(moving.src, moving.dst)
    assert list(moving.shared.iterdir()) == []
    assert moving.src.read_bytes() == moving.data


def test_a_destination_that_refuses_times_and_modes_still_gets_the_file_once(
    dlq, moving, monkeypatch
):
    """Android's shared storage refuses chmod and utime with EPERM after every
    byte has landed. Copying them is what made a whole copy in both places
    and an error saying the move failed."""

    def refuse(*args, **kw):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    for name in ("utime", "chmod"):
        monkeypatch.setattr(os, name, refuse)
    dlq.dl.move_file(moving.src, moving.dst)
    assert moving.dst.read_bytes() == moving.data
    assert not moving.src.exists()
    assert [path.name for path in moving.shared.iterdir()] == [moving.dst.name]


def test_a_copy_the_disk_cannot_hold_is_never_started(dlq, moving, monkeypatch):
    copied = []
    monkeypatch.setattr(shutil, "copyfile", lambda *args, **kw: copied.append(args))
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: type("Usage", (), {"free": 100})()
    )
    with pytest.raises(OSError) as raised:
        dlq.dl.move_file(moving.src, moving.dst)
    assert raised.value.errno == errno.ENOSPC
    assert copied == []
    assert list(moving.shared.iterdir()) == []
    assert moving.src.read_bytes() == moving.data


def test_a_move_on_one_filesystem_is_a_rename(dlq, tmp_path):
    src, dst = tmp_path / "a.bin", tmp_path / "b.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    dlq.dl.move_file(src, dst)
    assert dst.read_bytes() == b"new"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["b.bin"]


def test_a_download_delivered_across_filesystems_is_the_file(
    dlq, serving, fetching, across
):
    serving.payload = os.urandom(300 * 1024)
    fetching.slice_of(MiB)
    across.add(os.fspath(fetching.work / "x.bin.part"))
    size = len(serving.payload)
    assert dlq.dl.fetch(serving.url, "x.bin", total_hint=size) == dlq.dl.COMPLETE
    assert [path.name for path in fetching.out.iterdir()] == ["x.bin"]
    assert (fetching.out / "x.bin").read_bytes() == serving.payload


# --------------------------------------------------------------------------- #
# What the runner reads back, and what a manual run gets
# --------------------------------------------------------------------------- #


def test_progress_is_written_often_enough_and_never_torn(dlq, fetching):
    """Rewritten atomically every few seconds, so a killed item still leaves a
    nearly-current figure — and never a half-written one for the runner to
    read.

    The throttle is why it can be called on every chunk: a 64 KiB read is not
    worth a write, and a slice of many gigabytes is not worth a million of
    them.
    """
    env = dlq.dl.Env()
    status = dlq.dl.Status(env, total=1000, part_bytes=0)

    status.slice_bytes = 10
    status.write(force=True)
    first = json.loads(status.path.read_text())
    assert first["part_bytes"] == 0 and first["run_id"] == "run-1"

    # A moment later and a few bytes on: not worth a write.
    status.slice_bytes = 20
    status.write()
    assert json.loads(status.path.read_text())["payload_bytes_this_slice"] == 10

    # Enough bytes, and it is worth one whenever it happens.
    status.slice_bytes = 10 + dlq.dl.STATUS_EVERY_BYTES
    status.write()
    assert json.loads(status.path.read_text())["payload_bytes_this_slice"] > 10

    # Forced always writes, which is what the end of a slice does.
    status.slice_bytes = 3
    status.state = dlq.dl.COMPLETE
    status.write(force=True)
    said = json.loads(status.path.read_text())
    assert said["payload_bytes_this_slice"] == 3
    assert said["state"] == dlq.dl.COMPLETE


def test_a_run_by_hand_outside_the_scheduler_is_safe(dlq, monkeypatch):
    """The defaults are what a person gets when they run an item themselves:
    here, now, with no deadline and no slice — which declines rather than
    downloading something nobody bounded."""
    for name in (
        "EXPIRE_WORK",
        "EXPIRE_OUT",
        "EXPIRE_SLICE_BYTES",
        "EXPIRE_BUDGET_BYTES",
        "EXPIRE_STOP_EPOCH",
        "EXPIRE_RUN_ID",
        "EXPIRE_TOTAL_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    env = dlq.dl.Env()
    assert env.slice == 0
    assert env.total_hint == 0
    assert env.deadline() == float("inf")
    assert env.run_id  # something to tell one run from another
    assert str(env.work) == "." and str(env.out) == "."


def test_the_sidecar_holds_the_validators_and_never_the_position(dlq, tmp_path):
    """The resume offset is always the size on disk. What the sidecar carries
    is what a *server* said — the ETag, the date, the total — so losing it
    costs a re-check and never a re-download."""
    part = tmp_path / "thing.iso.part"
    assert dlq.dl._load_meta(part) == {}  # nothing written yet is not an error
    dlq.dl._save_meta(part, {"etag": '"a"', "total": 1234, "restarts": 1})
    assert dlq.dl._load_meta(part) == {"etag": '"a"', "total": 1234, "restarts": 1}
    assert "position" not in dlq.dl._load_meta(part)

    # A sidecar that will not parse is nothing rather than a crash: it is
    # written beside a file that is worth more than it is.
    dlq.dl._meta_path(part).write_text("{ truncated")
    assert dlq.dl._load_meta(part) == {}
