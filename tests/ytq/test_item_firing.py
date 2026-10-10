"""One firing of a queue item: what it asks yt-dlp for, and what it reports back.

The runner reads the exit code and the status file and nothing else, so what
these pin is the mapping from what happened to what was said about it — a
firing that declined, a firing that made progress, a video that has gone away,
and the delivery that ends the item.
"""

from __future__ import annotations

import json
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

import expire_dl
import ytdl_item


def after(argv: list[str], flag: str) -> str:
    """The value a flag was given, so a test names the pair and not an index."""
    assert flag in argv, f"{flag} is not in {argv}"
    return argv[argv.index(flag) + 1]


# --------------------------------------------------------------------------- #
# The invocation
# --------------------------------------------------------------------------- #


def test_the_firing_resumes_rather_than_restarting(tmp_path):
    """``--continue`` is the whole cross-night design: the .part is the state."""
    argv = ytdl_item.command(
        "https://youtu.be/x", "talk", "137+140", tmp_path / "dl",
        tmp_path / ".produced", "mp4", 5_000_000,
    )
    assert "--continue" in argv
    assert "--no-playlist" in argv
    assert argv[-1] == "https://youtu.be/x"


def test_the_format_and_the_rate_cap_are_what_was_asked_for(tmp_path):
    argv = ytdl_item.command(
        "https://youtu.be/x", "talk", "137+140", tmp_path / "dl",
        tmp_path / ".produced", None, 5_000_000,
    )
    assert after(argv, "-f") == "137+140"
    assert after(argv, "--limit-rate") == "5000000"
    assert after(argv, "-P") == f"home:{tmp_path / 'dl'}"
    assert after(argv, "-o") == "talk.%(ext)s"


def test_the_finished_path_is_asked_for_after_the_move(tmp_path):
    """``produced`` reads this file; the name yt-dlp prints must be the final one."""
    printed = tmp_path / ".produced"
    argv = ytdl_item.command(
        "https://youtu.be/x", "talk", "137", tmp_path / "dl", printed, None, 1
    )
    assert after(argv, "--print-to-file") == "after_move:filepath"
    assert str(printed) in argv


def test_a_merge_is_only_asked_for_when_there_is_one(tmp_path):
    merged = ytdl_item.command(
        "u", "talk", "137+140", tmp_path, tmp_path / "p", "mkv", 1
    )
    single = ytdl_item.command("u", "talk", "18", tmp_path, tmp_path / "p", None, 1)
    assert after(merged, "--merge-output-format") == "mkv"
    assert "--merge-output-format" not in single


def test_yt_dlp_is_this_interpreter_when_it_can_be(monkeypatch):
    """A scheduled firing inherits an unpredictable PATH; the module form does not."""
    monkeypatch.setattr(ytdl_item.importlib.util, "find_spec", lambda name: object())
    assert ytdl_item.ytdl_argv()[0] == ytdl_item.sys.executable
    monkeypatch.setattr(ytdl_item.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(ytdl_item.shutil, "which", lambda name: "/opt/bin/yt-dlp")
    assert ytdl_item.ytdl_argv() == ["/opt/bin/yt-dlp"]
    monkeypatch.setattr(ytdl_item.shutil, "which", lambda name: None)
    # Still runnable-looking, so a missing yt-dlp is reported by the callers'
    # existing "not installed" path rather than by a second one here.
    assert ytdl_item.ytdl_argv() == ["yt-dlp"]


# --------------------------------------------------------------------------- #
# The banner that says how long is left
# --------------------------------------------------------------------------- #


def test_a_run_with_no_stop_time_says_so_in_words():
    """``int(inf)`` raises, and it raised in the line before a byte moved."""
    assert ytdl_item.time_left(float("inf")) == "no stop time"


def test_a_deadline_is_a_countdown():
    assert ytdl_item.time_left(1000.0, now=940.0).startswith("60")


@given(
    deadline=st.one_of(
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.just(float("inf")),
    ),
    now=st.floats(allow_nan=False, allow_infinity=False, width=32),
)
def test_the_banner_phrase_never_raises(deadline, now):
    """Whatever the deadline is, saying what it is cannot be what kills a run."""
    assert isinstance(ytdl_item.time_left(deadline, now=now), str)


def test_an_endless_deadline_is_what_dlq_now_sets(monkeypatch):
    monkeypatch.setenv("EXPIRE_STOP_EPOCH", "0")
    assert math.isinf(expire_dl.Env().deadline())


# --------------------------------------------------------------------------- #
# Which file was produced, and where it goes
# --------------------------------------------------------------------------- #


def test_the_printed_path_is_believed_when_the_file_is_there(tmp_path):
    dl, printed = tmp_path / "dl", tmp_path / ".produced"
    dl.mkdir()
    (dl / "talk.mkv").write_bytes(b"x" * 10)
    printed.write_text(f"{dl / 'talk.mkv'}\n")
    assert ytdl_item.produced(dl, printed, "talk") == dl / "talk.mkv"


def test_the_largest_real_file_stands_in_when_nothing_was_printed(tmp_path):
    """Scaffolding is never the answer: parts, indexes and per-stream files."""
    dl, printed = tmp_path / "dl", tmp_path / ".produced"
    dl.mkdir()
    (dl / "talk.f137.mp4").write_bytes(b"x" * 900)
    (dl / "talk.mp4.part").write_bytes(b"x" * 800)
    (dl / "talk.mp4.ytdl").write_bytes(b"x" * 5)
    (dl / "talk.mkv").write_bytes(b"x" * 100)
    assert ytdl_item.produced(dl, printed, "talk") == dl / "talk.mkv"


def test_a_name_with_a_bracket_in_it_still_finds_its_file(tmp_path):
    """Matched literally: a glob would read ``[8]`` as a character class."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "talk-[8]-review.mp4").write_bytes(b"x" * 10)
    assert ytdl_item.produced(dl, dl / "none", "talk-[8]-review") is not None


def test_delivery_moves_the_file_and_says_it_is_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPIRE_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("EXPIRE_OUT", str(tmp_path / "out"))
    (tmp_path / "work").mkdir()
    source = tmp_path / "talk.mp4"
    source.write_bytes(b"x" * 4321)
    env = expire_dl.Env()
    status = expire_dl.Status(env, 4321, 0)

    assert ytdl_item.deliver(source, env.out, status) == ytdl_item.COMPLETE
    assert not source.exists()
    assert (env.out / "talk.mp4").read_bytes() == b"x" * 4321
    report = json.loads((env.work / ".status.json").read_text())
    assert report["state"] == ytdl_item.COMPLETE
    assert report["part_bytes"] == 4321


def test_a_delivery_from_an_earlier_firing_is_recognised(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "talk.mp4.part").write_bytes(b"x")
    assert ytdl_item.already_delivered(out, "talk") is None
    (out / "talk.mp4").write_bytes(b"x")
    assert ytdl_item.already_delivered(out, "talk") == out / "talk.mp4"


def test_item_state_round_trips_and_forgives_a_broken_file(tmp_path):
    ytdl_item.save_state(tmp_path, {"zero_firings": 2})
    assert ytdl_item.load_state(tmp_path) == {"zero_firings": 2}
    (tmp_path / ytdl_item.STATE_NAME).write_text("{not json")
    assert ytdl_item.load_state(tmp_path) == {}


# --------------------------------------------------------------------------- #
# A whole firing
# --------------------------------------------------------------------------- #


class FakeChild:
    """A yt-dlp that does what the test says and exits, without a subprocess."""

    def __init__(self, code=0, produces=None, postprocessing=False, tail=()):
        self.code = code
        self.produces = produces or {}
        self.postprocessing = postprocessing
        self.tail = list(tail)
        self.stopped: list[str] = []
        self.argv: list[str] = []

    def __call__(self, argv, cwd):
        self.argv = argv
        for name, size in self.produces.items():
            (cwd / name).write_bytes(b"x" * size)
        outer = self

        class Process:
            returncode = outer.code

            def poll(self):
                return outer.code

        self.process = Process()
        return self

    def stop(self, why, escalation=None):
        self.stopped.append(why)

    def finish(self):
        return self.code


@pytest.fixture
def firing(tmp_path, monkeypatch):
    """An environment shaped like the one the runner hands an item."""
    work, out = tmp_path / "work", tmp_path / "out"
    monkeypatch.setenv("EXPIRE_WORK", str(work))
    monkeypatch.setenv("EXPIRE_OUT", str(out))
    monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(200 * 1024 * 1024))
    monkeypatch.setenv("EXPIRE_STOP_EPOCH", "0")
    monkeypatch.setenv("EXPIRE_RUN_ID", "test-run")

    def install(child):
        monkeypatch.setattr(ytdl_item, "Child", child)
        return child

    return work, out, install


def state_of(work):
    return json.loads((work / ".status.json").read_text())


def test_a_slice_too_small_to_extract_in_costs_nothing(firing, monkeypatch):
    """An extraction is ~0.1-0.5 MB whatever the slice is."""
    work, _, install = firing
    monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(ytdl_item.MIN_USEFUL_SLICE - 1))

    def refuse(argv, cwd):  # pragma: no cover - the point is it is not called
        raise AssertionError("yt-dlp was invoked for a slice not worth extracting")

    install(refuse)
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.DECLINED
    assert state_of(work)["state"] == ytdl_item.DECLINED


def test_no_time_left_this_firing_is_declined_before_yt_dlp(firing, monkeypatch):
    work, _, install = firing
    import time as clock

    monkeypatch.setenv("EXPIRE_STOP_EPOCH", str(clock.time() - 5))

    def refuse(argv, cwd):  # pragma: no cover - the point is it is not called
        raise AssertionError("yt-dlp was invoked with no time to run in")

    install(refuse)
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.DECLINED


def test_a_file_delivered_on_an_earlier_firing_ends_the_item(firing):
    work, out, install = firing
    out.mkdir(parents=True)
    (out / "talk.mp4").write_bytes(b"x" * 99)

    def refuse(argv, cwd):  # pragma: no cover - the point is it is not called
        raise AssertionError("a delivered item was downloaded again")

    install(refuse)
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.COMPLETE
    assert state_of(work)["state"] == ytdl_item.COMPLETE


def test_a_finished_download_is_delivered_and_reported_complete(firing):
    work, out, install = firing
    install(FakeChild(code=0, produces={"talk.mp4": 2048}))
    assert ytdl_item.fetch("https://youtu.be/x", "talk", fmt="137+140") \
        == ytdl_item.COMPLETE
    assert (out / "talk.mp4").stat().st_size == 2048
    assert state_of(work)["state"] == ytdl_item.COMPLETE


def test_exit_zero_with_nothing_to_show_for_it_is_fatal(firing):
    """Archiving the item as done would lose the video."""
    work, _, install = firing
    install(FakeChild(code=0))
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.FATAL


def test_a_firing_that_moved_bytes_is_progress(firing):
    work, _, install = firing
    install(FakeChild(code=1, produces={"talk.f137.mp4.part": 4096}))
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.PROGRESS
    report = state_of(work)
    assert report["payload_bytes_this_slice"] == 4096
    assert ytdl_item.load_state(work).get("zero_firings") in (None, 0)


def test_a_video_that_has_gone_away_takes_a_strike_and_then_stops(firing):
    """Once is a bad night; repeatedly is something a human has to be told."""
    work, _, install = firing
    install(FakeChild(code=1, tail=["ERROR: Video unavailable"]))
    seen = [ytdl_item.fetch("https://youtu.be/x", "talk")
            for _ in range(ytdl_item.MAX_ZERO_FIRINGS)]
    assert seen[:-1] == [ytdl_item.DECLINED] * (ytdl_item.MAX_ZERO_FIRINGS - 1)
    assert seen[-1] == ytdl_item.FATAL


def test_one_good_firing_clears_the_strikes(firing):
    work, _, install = firing
    install(FakeChild(code=1))
    ytdl_item.fetch("https://youtu.be/x", "talk")
    assert ytdl_item.load_state(work)["zero_firings"] == 1
    install(FakeChild(code=1, produces={"talk.f137.mp4.part": 8192}))
    ytdl_item.fetch("https://youtu.be/x", "talk")
    assert not ytdl_item.load_state(work).get("zero_firings")


def test_the_exit_codes_are_the_ones_the_runner_reads(firing, monkeypatch):
    _, _, install = firing
    install(FakeChild(code=0, produces={"talk.mp4": 16}))
    assert ytdl_item.run("https://youtu.be/x", "talk") == 0

    def explode(*args, **kwargs):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(ytdl_item, "fetch", explode)
    # An item must never traceback out: the runner reads a code, not a stack.
    assert ytdl_item.run("https://youtu.be/x", "talk") == expire_dl.EXIT[
        ytdl_item.FATAL
    ]


def test_the_part_written_is_never_the_whole_declared_total(firing):
    """The runner asks for ``cap - part_bytes``; equal would mean nothing left."""
    work, _, install = firing
    install(FakeChild(code=1, produces={"talk.f137.mp4.part": 5000}))
    ytdl_item.fetch("https://youtu.be/x", "talk", total_hint=5000)
    assert state_of(work)["part_bytes"] < 5000


# --------------------------------------------------------------------------- #
# The poll loop, on a clock the test owns
# --------------------------------------------------------------------------- #


class Clock:
    """Time as the item sees it: every sleep is a step, and nothing waits."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class GrowingChild:
    """A yt-dlp that writes *per_poll* bytes a poll, until something stops it.

    Bounded at *polls* on purpose: this stands in for a download that would run
    for ever, and the tests below are about which of the item's own conditions
    ends it. Unbounded, a mutant that removed one of those conditions would not
    fail a test — it would spin until a timeout, which is a slow way of being
    told the same thing.
    """

    def __init__(self, per_poll: int, name: str = "talk.f137.mp4.part",
                 polls: int = 200):
        self.per_poll = per_poll
        self.name = name
        self.polls = polls
        self.written = 0
        self.stopped: list[str] = []

    def __call__(self, argv, cwd):
        self.cwd = cwd
        outer = self

        class Process:
            returncode = 1

            def poll(self):
                if outer.stopped or outer.polls <= 0:
                    return 1
                outer.polls -= 1
                outer.written += outer.per_poll
                (cwd / outer.name).write_bytes(b"x" * outer.written)
                return None

        self.process = Process()
        self.postprocessing = False
        self.tail: list[str] = []
        return self

    def stop(self, why, escalation=None):
        self.stopped.append(why)

    def finish(self):
        # An interrupted yt-dlp does not exit 0, and the item must not read a
        # stopped slice as a finished download.
        return 1


def test_the_slice_is_stopped_before_it_is_spent(firing, monkeypatch):
    """Stopped on where the child will be when it actually stops, not on where
    it is now: everything it reads between the signal and noticing it is spent
    either way, and overshooting eats the runner's margin above the floor."""
    work, _, install = firing
    budget = 4 * 1024 * 1024
    monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(budget))
    monkeypatch.setattr(ytdl_item, "time", Clock())
    child = install(GrowingChild(per_poll=256 * 1024))

    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.PROGRESS
    assert child.stopped == ["slice budget reached"]
    assert state_of(work)["payload_bytes_this_slice"] <= budget


def test_the_deadline_stops_a_slice_that_still_had_budget(firing, monkeypatch):
    work, _, install = firing
    clock = Clock()
    monkeypatch.setattr(ytdl_item, "time", clock)
    # Room to start, and then a stop time a few polls away.
    monkeypatch.setenv(
        "EXPIRE_STOP_EPOCH",
        str(clock.now + ytdl_item.STOP_LEAD + expire_dl.QUIT_MARGIN + 1),
    )
    child = install(GrowingChild(per_poll=1024))

    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.PROGRESS
    assert child.stopped == ["deadline"]


def test_being_asked_to_stop_stops_it(firing, monkeypatch):
    """The runner unwinding is what stops a download; the item only sets a flag
    and the poll loop does the winding down."""
    work, _, install = firing
    monkeypatch.setattr(ytdl_item, "time", Clock())
    monkeypatch.setattr(ytdl_item, "_stop", True)
    child = install(GrowingChild(per_poll=1024))
    try:
        assert ytdl_item.fetch("https://youtu.be/x", "talk") in (
            ytdl_item.PROGRESS, ytdl_item.DECLINED
        )
        assert child.stopped == ["asked to stop"]
    finally:
        ytdl_item._stop = False


def test_postprocessing_lifts_the_byte_ceiling_but_not_the_clock(
    firing, monkeypatch
):
    """Merging is CPU, not network — a video that finished downloading at the
    slice edge could otherwise never be merged. The deadline still applies,
    which is also what ends this test."""
    work, _, install = firing
    clock = Clock()
    monkeypatch.setattr(ytdl_item, "time", clock)
    monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(4 * 1024 * 1024))
    monkeypatch.setenv(
        "EXPIRE_STOP_EPOCH",
        str(clock.now + ytdl_item.STOP_LEAD + expire_dl.QUIT_MARGIN + 2),
    )
    made = GrowingChild(per_poll=2 * 1024 * 1024)

    def start(argv, cwd):
        child = made(argv, cwd)
        child.postprocessing = True
        return child

    install(start)
    ytdl_item.fetch("https://youtu.be/x", "talk")
    # Far past the byte ceiling, and stopped by the clock rather than by it.
    assert made.stopped == ["deadline"]
    assert made.written > 4 * 1024 * 1024


# --------------------------------------------------------------------------- #
# The real child, with a real process on the end of it
# --------------------------------------------------------------------------- #


def test_the_child_notices_postprocessing_and_keeps_the_last_lines(tmp_path):
    """A postprocessor announcing itself is what lifts the byte ceiling, and
    the tail is what a failed firing reports to a human."""
    script = (
        "import sys\n"
        "print('[download]  12.3% of 100MiB')\n"
        "print('[Merger] Merging formats into \"talk.mp4\"')\n"
        "print('ERROR: something went wrong')\n"
    )
    child = ytdl_item.Child([ytdl_item.sys.executable, "-c", script], tmp_path)
    while child.process.poll() is None:  # what the firing's own loop does
        pass
    assert child.finish() == 0
    assert child.postprocessing is True
    assert any("ERROR" in line for line in child.tail)


def test_stopping_starts_with_an_interrupt_and_escalates_only_if_it_must(
    tmp_path,
):
    """SIGINT first because yt-dlp handles it: it closes the output file, so
    the .part is flushed rather than merely being a valid prefix."""
    import signal

    ignores_interrupts = (
        "import signal, time\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    child = ytdl_item.Child(
        [ytdl_item.sys.executable, "-c", ignores_interrupts], tmp_path
    )
    child.stop("a test", ((signal.SIGINT, 0.3), (signal.SIGTERM, 5)))
    assert child.process.poll() is not None
    # It took the terminate, which is the escalation and not the first ask.
    assert child.process.returncode != 0


def test_stopping_something_already_gone_is_not_an_error(tmp_path):
    child = ytdl_item.Child([ytdl_item.sys.executable, "-c", "pass"], tmp_path)
    child.finish()
    child.stop("nothing to stop")


# --------------------------------------------------------------------------- #
# Every way out of a firing writes the report the runner reads
# --------------------------------------------------------------------------- #


def test_a_yt_dlp_that_will_not_start_is_fatal_and_says_so(firing):
    """Not a night lost quietly: the runner reads a state, not a log."""
    work, _, install = firing

    def cannot_start(argv, cwd):
        raise OSError("no such file")

    install(cannot_start)
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.FATAL
    assert state_of(work)["state"] == ytdl_item.FATAL


def test_no_time_left_is_written_down_as_well_as_returned(firing, monkeypatch):
    work, _, install = firing
    import time as clock

    monkeypatch.setenv("EXPIRE_STOP_EPOCH", str(clock.time() - 5))
    install(FakeChild(code=0))
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.DECLINED
    assert state_of(work)["state"] == ytdl_item.DECLINED


def test_success_with_no_file_is_written_down_as_fatal(firing):
    work, _, install = firing
    install(FakeChild(code=0))
    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.FATAL
    assert state_of(work)["state"] == ytdl_item.FATAL


def test_each_strike_is_written_down_and_the_last_one_is_fatal(firing):
    work, _, install = firing
    install(FakeChild(code=1, tail=["ERROR: Video unavailable"]))
    for firing_number in range(1, ytdl_item.MAX_ZERO_FIRINGS + 1):
        last = firing_number == ytdl_item.MAX_ZERO_FIRINGS
        ytdl_item.fetch("https://youtu.be/x", "talk")
        assert state_of(work)["state"] == (
            ytdl_item.FATAL if last else ytdl_item.DECLINED
        )
        # The count is kept between firings, and reset once it has been acted on.
        assert ytdl_item.load_state(work)["zero_firings"] == (
            0 if last else firing_number
        )


def test_a_resumed_item_never_reports_itself_finished(firing):
    """The runner computes the next slice as cap - part_bytes; equal means it
    stops offering slices to an item that has not delivered."""
    work, _, install = firing
    dl = work / ytdl_item.DL_DIRNAME
    dl.mkdir(parents=True)
    (dl / "talk.f137.mp4.part").write_bytes(b"x" * 5000)
    install(FakeChild(code=1))
    ytdl_item.fetch("https://youtu.be/x", "talk", total_hint=5000)
    assert state_of(work)["part_bytes"] < 5000


def test_the_slice_stop_lands_inside_the_budget(firing, monkeypatch):
    """Overshooting eats the runner's margin above the 100 MB floor; stopping
    far short of the slice buys a night's worth of extractions for nothing."""
    work, _, install = firing
    budget = ytdl_item.MIN_USEFUL_SLICE + 1
    monkeypatch.setenv("EXPIRE_SLICE_BYTES", str(budget))
    monkeypatch.setattr(ytdl_item, "time", Clock())
    # Slow enough that the prediction is a small correction rather than the
    # whole of the decision.
    child = install(GrowingChild(per_poll=8 * 1024, polls=2000))

    assert ytdl_item.fetch("https://youtu.be/x", "talk") == ytdl_item.PROGRESS
    assert child.stopped == ["slice budget reached"]
    taken = state_of(work)["payload_bytes_this_slice"]
    assert budget // 2 < taken <= budget


def test_a_printed_path_is_read_relative_to_the_download_directory(tmp_path):
    """yt-dlp prints what it was told to print; the path may be relative."""
    dl, printed = tmp_path / "dl", tmp_path / ".produced"
    dl.mkdir()
    (dl / "talk.mkv").write_bytes(b"x" * 10)
    printed.write_text("talk.mkv\n")
    assert ytdl_item.produced(dl, printed, "talk") == dl / "talk.mkv"


def test_the_last_printed_path_that_is_actually_there_wins(tmp_path):
    """An earlier firing's line is still in the file; the file it names may
    have been delivered and moved away since."""
    dl, printed = tmp_path / "dl", tmp_path / ".produced"
    dl.mkdir()
    (dl / "talk.mkv").write_bytes(b"x" * 10)
    printed.write_text(f"{dl / 'talk.mkv'}\n\n{dl / 'gone.mkv'}\n")
    assert ytdl_item.produced(dl, printed, "talk") == dl / "talk.mkv"
