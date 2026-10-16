#!/data/data/com.termux/files/usr/bin/python3
"""Resumable, budget-bounded downloader for expiring-quota queue items.

A queue item gets a *slice* of tonight's spendable data, not the whole file. It
takes that slice, stops cleanly, and continues on a later firing or a later
night. This module is the shared machinery for doing that safely.

The three ideas that make it work
---------------------------------
**Bounded Range requests.** Every request asks for ``bytes=off-(off+slice-1)``,
so the *server* ends the transfer at the slice boundary. Stopping exactly at
budget stops being a timing race against a local abort, and the response ends
with a clean EOF instead of a killed socket.

**The resume offset is always ``os.stat(part).st_size``.** Never a counter in a
metadata file. Writes are append-only, so whatever survives on disk is a valid
prefix of the remote file no matter how the process died — SIGKILL included.
The sidecar metadata holds validators and history, never position.

**The item stops itself before the runner would.** The slice it is handed is
already derated below the runner's kill thresholds, and it stops ~20s before the
hard deadline. The runner's guards remain as a backstop that a well-behaved item
never trips, because a cooperative stop leaves a resumable file and a SIGKILL
mid-write may not.

Contract with the runner
------------------------
Read from the environment: ``EXPIRE_WORK``, ``EXPIRE_OUT``,
``EXPIRE_SLICE_BYTES``, ``EXPIRE_STOP_EPOCH``, ``EXPIRE_RUN_ID``, and
``EXPIRE_TOTAL_BYTES`` -- the item's cap, which bounds what may be spent and is
never taken for the file's size.

Progress is reported through ``$EXPIRE_WORK/.status.json``, rewritten atomically
every few seconds so a killed item still leaves a nearly-current figure. It
carries the run id it was given, so the runner can never mistake last night's
report for tonight's.

Typical item::

    #!/data/data/com.termux/files/usr/bin/python3
    # EXPIRE: v1
    # EXPECT_BYTES: 4200000000
    # PARTIAL: yes
    import sys; sys.path.insert(0, "/data/data/com.termux/files/home/nibbles")
    from nibbles import expire_dl
    sys.exit(expire_dl.run("https://example/big.iso", "big.iso"))

Note the shebang: on Termux ``/usr/bin/env`` does not exist, and the runner
rejects an item whose interpreter is not on disk.

A file smaller than one CHUNK must be fetched, not declined. The runner hands a
partial item a slice of exactly what it still needs, so every such file asks
for less than a chunk, and a sub-chunk guard that refused it before opening a
connection would strand it: exit 75 with nothing moved is "not tonight" to the
runner, and a cap under a MiB counts no stall against it, so no strike is taken
and no attempt is spent -- the item would be offered the same too-small slice
again on every firing, for ever, saying only that it was still queued.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import time
import urllib.error
import urllib.request
from pathlib import Path

#: Four TLS records per read. At satellite speeds the syscall overhead is
#: irrelevant, while stop-condition checks between chunks stay sub-second.
CHUNK = 64 * 1024

#: Bounds how much paid-for data a SIGKILL can lose from the page cache.
FSYNC_EVERY = 16 * 1024 * 1024

#: Stop this long before the runner's hard stop, leaving room to flush, fsync
#: and write the status file without doing any network work.
QUIT_MARGIN = 20

#: Give up if the link is this slow for this long — the satellite equivalent of
#: curl's --speed-limit / --speed-time.
SLOW_BPS = 2 * 1024
SLOW_SECONDS = 60

SOCKET_TIMEOUT = 30
STATUS_EVERY_SECONDS = 5
STATUS_EVERY_BYTES = 8 * 1024 * 1024

#: Hashing is CPU-bound; refuse to start it without time to finish.
HASH_BPS = 100 * 1024 * 1024
HASH_SLACK = 30

COMPLETE, PROGRESS, DECLINED, FATAL = "complete", "progress", "declined", "fatal"

#: What the runner expects back: 0 done, 75 not tonight, anything else a strike.
EXIT = {COMPLETE: 0, PROGRESS: 75, DECLINED: 75, FATAL: 1}

#: What a page is, as opposed to a file (see :func:`is_page`).
PAGE_TYPES = ("text/html", "application/xhtml+xml")

#: Answers in a row that are not the file -- a client error (a link that has
#: died: 403, 404, 410) or a web page where the file should be (a sign-in or
#: "link expired" page) -- before they are a fault rather than a bad night.
#: One is a hiccup a later firing gets past; "not tonight" for ever is an item
#: that never fails and is never seen, asked for again every firing of every
#: night. So the third in a row is a strike, and the runner's strikes bring it
#: to a human. Any answer that is the file starts the count again.
MAX_REFUSALS = 3

#: Client errors that mean "not now" rather than "not ever": a timeout, too
#: early, too many requests. Every 5xx is the same, and so is an unreachable
#: host -- an offline phone is not a dead link.
TRANSIENT = (408, 425, 429)

#: Left free on the destination by a move that has to copy (:func:`move_file`).
#: Shared storage and $HOME are one /data partition on a phone, so a copy needs
#: the file's size again, and a phone filled to its last byte stops working.
MOVE_SPARE = 64 * 1024 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}")

_stop = False


def _on_term(signum, frame) -> None:
    """Only set a flag. Doing I/O here risks being killed mid-write."""
    global _stop
    _stop = True


class Env:
    """The runner's instructions, with defaults that make a manual run safe."""

    def __init__(self) -> None:
        self.work = Path(os.environ.get("EXPIRE_WORK", "."))
        self.out = Path(os.environ.get("EXPIRE_OUT", "."))
        self.slice = int(
            os.environ.get("EXPIRE_SLICE_BYTES")
            or os.environ.get("EXPIRE_BUDGET_BYTES")
            or 0
        )
        self.stop_epoch = float(os.environ.get("EXPIRE_STOP_EPOCH") or 0)
        self.run_id = os.environ.get("EXPIRE_RUN_ID", "manual")
        self.total_hint = int(os.environ.get("EXPIRE_TOTAL_BYTES") or 0)

    def deadline(self) -> float:
        """When to stop, or +inf when run by hand outside the scheduler."""
        return self.stop_epoch - QUIT_MARGIN if self.stop_epoch else float("inf")


def log(message: str) -> None:
    """Item output is captured to the run log by the runner."""
    print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {message}", flush=True)


def _atomic(path: Path, payload: str) -> None:
    """Write via temp + rename, so a reader never sees a torn file."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(payload)
    temp.replace(path)


class Status:
    """The progress report the runner reads back."""

    def __init__(self, env: Env, total: int, part_bytes: int) -> None:
        self.path = env.work / ".status.json"
        self.run_id = env.run_id
        self.total = total
        self.part = part_bytes
        self.slice_bytes = 0
        self.state = PROGRESS
        self._last = 0.0
        self._last_bytes = 0

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and (
            now - self._last < STATUS_EVERY_SECONDS
            and self.slice_bytes - self._last_bytes < STATUS_EVERY_BYTES
        ):
            return
        self._last, self._last_bytes = now, self.slice_bytes
        # Reporting must never be able to fail the download.
        with contextlib.suppress(OSError):
            _atomic(
                self.path,
                json.dumps(
                    {
                        "v": 1,
                        "run_id": self.run_id,
                        "state": self.state,
                        "payload_bytes_this_slice": self.slice_bytes,
                        "part_bytes": self.part,
                        "total_bytes": self.total,
                        "updated": now,
                    }
                ),
            )


def _meta_path(part: Path) -> Path:
    return part.with_suffix(part.suffix + ".meta.json")


def _load_meta(part: Path) -> dict:
    try:
        return json.loads(_meta_path(part).read_text())
    except (OSError, ValueError):
        return {}


def _save_meta(part: Path, meta: dict) -> None:
    with contextlib.suppress(OSError):
        _atomic(_meta_path(part), json.dumps(meta))


def _validators(response) -> tuple[str, str]:
    """ETag and Last-Modified, used to notice the remote file changing."""
    return (
        response.headers.get("ETag") or "",
        response.headers.get("Last-Modified") or "",
    )


def _stated_length(headers) -> int:
    """The Content-Length a response states, or 0 when it states none."""
    length = (headers.get("Content-Length") or "").strip()
    return int(length) if length.isdigit() else 0


def _span_end(content_range: str) -> int | None:
    """The last byte a ``bytes a-b/...`` Content-Range covers, or None."""
    if not content_range.startswith("bytes "):
        return None
    span = content_range[6:].split("/")[0]
    last = span.partition("-")[2].strip()
    return int(last) if last.isdigit() else None


def _changed(meta: dict, etag: str, modified: str) -> bool:
    """Whether the validators a server just sent prove the file is not the one
    the part holds. Only a validator on both sides proves anything: one that
    is missing on either side is "cannot tell", which is not "changed"."""
    old_etag, old_modified = meta.get("etag") or "", meta.get("modified") or ""
    if old_etag and etag:
        return old_etag != etag
    if old_modified and modified:
        return old_modified != modified
    return False


def _more(response) -> bool:
    """Whether a body has anything left after what was read: one byte asked.

    How a slice that ends exactly where an unsized file ends is told from one
    that ends inside a longer file, at the cost of at most that byte. A read
    that fails is "cannot tell", which never delivers.
    """
    try:
        return bool(response.read(1))
    except (OSError, TimeoutError, http.client.HTTPException):
        return True


def _arrived(exc: http.client.HTTPException) -> bytes:
    """The bytes a body cut off mid-chunk had already handed over.

    ``http.client`` raises :class:`~http.client.IncompleteRead` carrying the
    whole chunks it finished, chained to the one that tore, which carries what
    arrived of the torn chunk; together they are the next bytes of the body,
    in order, already off the wire and paid for.
    """
    got = getattr(exc, "partial", b"") or b""
    cause = exc.__cause__
    if isinstance(cause, http.client.IncompleteRead):
        got += cause.partial or b""
    return bytes(got)


def _answer(status: Status, state: str, said: str = "") -> str:
    """Say *said*, report *state* and hand it back: how an answer ends."""
    if said:
        log(said)
    status.state = state
    status.write(force=True)
    return state


def _refused(part: Path, meta: dict, status: Status, said: str) -> str:
    """An answer that is not the file: "not tonight", until it is the
    :data:`MAX_REFUSALS`-th in a row and a strike.

    Only the count changes. The part, the validators, the size and whether
    the server resumes are all left exactly as they were, because nothing an
    answer that is not the file says is a fact about the file.
    """
    refused = int(meta.get("refused") or 0) + 1
    meta["refused"] = refused
    _save_meta(part, meta)
    if refused >= MAX_REFUSALS:
        return _answer(
            status, FATAL, f"FATAL: {said}; {refused} answers in a row that are not the file"
        )
    return _answer(
        status,
        DECLINED,
        f"{said}; left as it was ({refused} of {MAX_REFUSALS} in a row before it is a strike)",
    )


def sha256_digest(text: str) -> str:
    """The SHA-256 a person pasted, spelled as :mod:`hashlib` spells it.

    Upper-case hex (PowerShell's Get-FileHash, Microsoft's pages), a
    ``sha256:`` prefix (GitHub's release pages) and a whole ``sha256sum`` line
    (the hash, then the name) are all the same digest -- and compared with
    ``!=`` against ``hexdigest()``, each of them failed a correct file, threw
    it away and bought it again at every strike. Anything that is not 64 hex
    digits once cleaned (an MD5, a SHA-1, a typo) is :class:`ValueError`, so it
    is refused where it is given and before a byte is spent, never found out
    after paying for the file.

    Called by both ends: ``dlq`` cleans what it writes into an item, and
    :func:`fetch` cleans what an item hands it, so an item queued before this
    existed verifies by the same rule.
    """
    word = str(text).strip().lower().removeprefix("sha256:").strip()
    word = (word.split() or [""])[0]
    if not _SHA256.fullmatch(word):
        raise ValueError(f"not a SHA-256 digest (64 hex digits): {text!r}")
    return word


def is_page(headers) -> bool:
    """Whether an answer is a web page rather than a file -- the one test.

    ``nibbles <url>`` asks it of a link before anything is queued
    (``dlq.kind_of``: a page goes to yt-dlp, which reads the page for the
    video in it), and :func:`fetch` asks it of every answer a download is
    given, and the two must agree. A page where a file was asked for is a
    sign-in page, a captive portal or a "this link has expired" page, never
    the file; an attachment is a file whatever type it names, and a file that
    names no type is still a file.
    """
    if "attachment" in (headers.get("Content-Disposition") or "").lower():
        return False
    kind = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return kind in PAGE_TYPES


def _fsync(path: Path) -> None:
    """Flush *path* to the disk; a filesystem that cannot is not an error."""
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise
    finally:
        os.close(handle)


def move_file(src: Path, dst: Path) -> None:
    """Put *src* at *dst*: all of it, or nothing at *dst* and *src* untouched.

    The one move that may cross onto shared storage. A rename where it can be
    one -- the same filesystem, atomic, and an existing *dst* is replaced as a
    rename replaces it. Where it cannot (EXDEV: anything under /storage is a
    different mount from $HOME), the bytes are copied to a hidden name in
    *dst*'s directory, flushed to the disk and renamed onto *dst*, so *dst* is
    never there half-written under its own name for a gallery to index or a
    person to open; only then is *src* removed. On any failure on the way --
    ENOSPC, EIO, a ctrl-c or Pause -- the hidden copy is removed and *src* is
    left as it was: the bytes were paid for, and they stay where they are.

    Never ``shutil.move``: across filesystems that is ``copy2``, which copies
    the times and the mode after every byte has landed, and Android's shared
    storage refuses those with EPERM -- a whole copy in both places and an
    error saying the move failed. :func:`shutil.copyfile` copies the bytes
    and nothing else. And never a copy the disk cannot hold: refused before
    it starts (ENOSPC) rather than on its last byte, with :data:`MOVE_SPARE`
    left over.
    """
    try:
        os.rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    size = os.stat(src).st_size
    free = shutil.disk_usage(dst.parent).free
    if free < size + MOVE_SPARE:
        raise OSError(
            errno.ENOSPC,
            f"{size:,} bytes will not fit beside {free:,} free",
            str(dst.parent),
        )
    # Short and fixed rather than spelled from the name, which may already be
    # near the 255 bytes a name can have.
    temp = dst.parent / f".nibbles-{os.getpid()}.part"
    try:
        shutil.copyfile(src, temp)
        _fsync(temp)
        os.rename(temp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
    os.unlink(src)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _deliver(
    part: Path, dest: Path, expect_sha256: str | None, env: Env, status: Status
) -> str:
    """Verify a complete .part and move it into place.

    *expect_sha256* is already in :func:`sha256_digest`'s spelling.
    """
    size = part.stat().st_size
    if expect_sha256:
        # Hashing is not interruptible-and-resumable, so refuse to start it
        # without room to finish; the file keeps until the next firing.
        need = size / HASH_BPS + HASH_SLACK
        if time.time() + need > env.deadline():
            log(f"complete but no time to verify ({need:.0f}s needed); next firing")
            status.state = PROGRESS
            status.write(force=True)
            return PROGRESS
        found = _sha256(part)
        if found != expect_sha256:
            # Never silently re-download a whole file: that is exactly the
            # runaway a human should see a strike for.
            log(f"FATAL sha256 mismatch: got {found}, want {expect_sha256}")
            part.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                _meta_path(part).unlink(missing_ok=True)
            status.state = FATAL
            status.part = 0
            status.write(force=True)
            return FATAL
        log(f"sha256 verified {found}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Not Path.replace: a rename cannot cross a filesystem, and ``$EXPIRE_OUT``
    # is not guaranteed to be on the same one as the scratch directory. On the
    # phone, anything under /storage is a different mount from $HOME, and
    # replace() there fails with EXDEV *after* the whole file has been paid
    # for. move_file copies there, and never leaves half a file under the name.
    move_file(part, dest)
    # The sidecar is only history once the file has moved. A name near the
    # limit can be one whose ``.part.meta.json`` is longer than a name may be,
    # and a delivered file must never become a strike -- and a second
    # download of itself -- over the bookkeeping beside it.
    with contextlib.suppress(OSError):
        _meta_path(part).unlink(missing_ok=True)
    log(f"complete: {dest} ({size:,} bytes)")
    status.state = COMPLETE
    status.part = size
    status.write(force=True)
    return COMPLETE


def fetch(
    url: str, name: str, expect_sha256: str | None = None, total_hint: int = 0
) -> str:
    """Take one slice of *url* into ``$EXPIRE_WORK``, delivering when complete.

    Returns one of :data:`COMPLETE`, :data:`PROGRESS`, :data:`DECLINED`,
    :data:`FATAL`.
    """
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    env = Env()
    env.work.mkdir(parents=True, exist_ok=True)
    part = env.work / f"{name}.part"
    dest = env.out / name
    offset = part.stat().st_size if part.exists() else 0

    if expect_sha256:
        try:
            expect_sha256 = sha256_digest(expect_sha256)
        except ValueError as exc:
            # A digest that can never match would pay for the whole file once
            # per strike to find that out; say so before a byte moves.
            return _answer(Status(env, 0, offset), FATAL, f"FATAL {exc}")

    if not part.exists() and dest.is_file():
        # Delivered by an earlier firing whose runner never got as far as
        # archiving the item: paused or killed during the hand-over, which
        # copies to shared storage and takes a while for a big file. _deliver
        # is the only writer of dest, and only of a whole, verified file, so it
        # is the file, and fetching it again would pay for it twice.
        # (ytdl_item asks the same question: already_delivered.)
        size = dest.stat().st_size
        with contextlib.suppress(OSError):
            _meta_path(part).unlink(missing_ok=True)
        return _answer(
            Status(env, size, size), COMPLETE, f"already delivered: {dest} ({size:,} bytes)"
        )

    meta = _load_meta(part)
    # A size is what a server stated, or what the item was sized at when it
    # was queued; never the cap the runner echoes back (EXPIRE_TOTAL_BYTES).
    # Taken for a size, the cap made a file smaller than it never "complete"
    # -- fetched, thrown away and fetched again until it failed -- and a file
    # larger than it "complete" at the cap, delivered cut off. The cap is a
    # bound on spending, and that is all it is used for here.
    total = int(meta.get("total") or total_hint or 0)
    cap = env.total_hint
    status = Status(env, total, offset)

    if total and offset >= total:
        # Last night moved the final bytes but died before verifying.
        return _deliver(part, dest, expect_sha256, env, status)

    budget = env.slice

    # The most there can be to fetch: the size, else the cap (and more than
    # the cap, once a whole cap was spent without reaching the end).
    at_least = int(meta.get("at_least") or 0)
    least = total or max(cap, at_least)

    # Known not to support Range, and too big for one slice: every attempt
    # would download a slice, discover it cannot resume, throw it away, and
    # start over. That oscillation spends real data every other night and never
    # converges, so refuse once and let a human see the strike.
    if meta.get("no_range") and least and least > budget:
        if total:
            size = f"{total:,} bytes"
        elif at_least > cap:
            size = f"more than {at_least - 1:,} bytes"
        else:
            size = f"up to {cap:,} bytes"
        return _answer(
            status,
            FATAL,
            f"FATAL: this server ignores Range and the file is {size}, "
            f"larger than a {budget:,} byte slice; it cannot be fetched in parts",
        )

    # A slice below one chunk is mostly connection setup and strikes nothing
    # off the queue -- unless it is the whole of what is left, in which case
    # the request finishes the file and retires the item.
    #
    # That exemption is not a nicety. The runner hands a partial item a slice
    # of exactly what it still needs, so *every* file smaller than CHUNK asks
    # for less than CHUNK on its first firing and was refused here having made
    # no request at all. It then exits 75, which the runner reads as "not
    # tonight" and -- because the cap it was given is under a MiB, so no stall
    # is counted -- logs as "made progress but is not finished; left queued".
    # Nothing raises, no strike is taken, no attempt is spent, and the item is
    # offered the same too-small slice again on the next firing for ever. A
    # 15 KiB wheel is not a slow download; it is one that can never happen.
    # (Unsized, the cap is the most that can be left, which is what counts.)
    left = max(0, least - offset) if least else 0
    if budget < CHUNK and not (left and budget >= left):
        short = f"{left:,} still to fetch" if left else "size unknown"
        log(f"slice of {budget} bytes is too small to be worth a request ({short})")
        status.state = DECLINED
        status.write(force=True)
        return DECLINED

    want_end = offset + budget - 1
    headers = {
        # Ranges and byte counting are both meaningless if the server gzips.
        "Accept-Encoding": "identity",
        "Range": f"bytes={offset}-{want_end}",
        "User-Agent": "expire-dl/1",
    }
    # Let the protocol do the same-file check: a compliant server answers 206
    # if unchanged and 200 with the whole body if not. A weak ETag is not
    # allowed in If-Range, so fall back to the date in that case.
    etag, modified = meta.get("etag", ""), meta.get("modified", "")
    if offset and etag and not etag.startswith("W/"):
        headers["If-Range"] = etag
    elif offset and modified:
        headers["If-Range"] = modified

    log(f"requesting bytes {offset}-{want_end} ({budget:,} byte slice)")
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=SOCKET_TIMEOUT
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset:
            # Nothing at or after the bytes already here. With a size known,
            # that is the part being whole; with none stated, it is where the
            # file ends -- the slice before this one stopped exactly at its end,
            # which a body of unstated length cannot say. Unless the server
            # names a different end, the file ends where the part does.
            end = (exc.headers or {}).get("Content-Range") or ""
            end = end.rpartition("/")[2].strip()
            if (total and offset >= total) or (
                not total and (not end.isdigit() or int(end) == offset)
            ):
                status.total = total or offset
                return _deliver(part, dest, expect_sha256, env, status)
        said = f"HTTP {exc.code} {exc.reason}"
        if exc.code in TRANSIENT or not 400 <= exc.code < 500:
            return _answer(status, DECLINED, said)
        # A link that has died -- an expired signature (403), a file taken
        # down (404, 410) -- is refused in milliseconds, and as "not tonight"
        # it was asked for again every firing for ever, logged each time as
        # progress, never a strike and never seen.
        return _refused(part, meta, status, said)
    except (
        urllib.error.URLError,
        OSError,
        TimeoutError,
        http.client.HTTPException,
    ) as exc:
        # HTTPException: a status line or headers that are not HTTP, which is
        # the same "cannot be talked to tonight" an unreachable host is.
        log(f"cannot reach {url}: {exc}")
        status.state = DECLINED
        status.write(force=True)
        return DECLINED

    with response:
        code = response.getcode()
        new_etag, new_modified = _validators(response)
        stated = _stated_length(response.headers)

        if is_page(response.headers):
            # Not the file: written under its name it would complete the item
            # and land in Downloads as something nothing opens, and on a
            # resumed download a 200 here used to throw the paid-for part away
            # and mark the server as unable to resume. Closed unread.
            return _refused(
                part,
                meta,
                status,
                f"{url} answered with a web page, not the file "
                "(a sign-in or error page?)",
            )
        meta.pop("refused", None)

        if not offset and code == 200:
            # A 200 to a ranged request is the whole file in one piece: this
            # server ignores Range (or the range asked for was the whole
            # file). Bigger than the slice, reading a slice of it would buy
            # bytes no later firing can resume from, so it is closed unread,
            # and what was learned is kept: the refusal above stops every
            # firing whose slice cannot hold it, before it spends anything.
            whole = stated or total
            if whole > budget:
                meta.update(
                    {
                        "no_range": True,
                        "total": whole,
                        "etag": new_etag,
                        "modified": new_modified,
                    }
                )
                _save_meta(part, meta)
                status.total = whole
                return _answer(
                    status,
                    DECLINED,
                    f"this server ignores Range and the file is {whole:,} bytes, "
                    f"more than a {budget:,} byte slice; not started",
                )

        if offset and code == 200:
            # Range ignored, or the file changed under us. Appending here would
            # corrupt silently, so the part is never appended to -- but a
            # single 200 is not yet a server that cannot resume.
            if _changed(meta, new_etag, new_modified):
                # The validators prove it: the file was re-published, and the
                # 200 is what If-Range is for. The part is another file's now,
                # but the server is not one that ignores Range.
                restarts = int(meta.get("restarts") or 0) + 1
                log(f"remote file changed (validators differ); restart {restarts}")
                if restarts > 2:
                    return _answer(
                        status,
                        FATAL,
                        "FATAL: the file has changed three times while being "
                        "fetched; it cannot be fetched in slices",
                    )
                part.unlink(missing_ok=True)
                _save_meta(
                    part,
                    {
                        "restarts": restarts,
                        "etag": new_etag,
                        "modified": new_modified,
                        "total": stated,
                    },
                )
                status.part, status.total = 0, stated
                return _answer(status, DECLINED, "discarding partial")
            seen = int(meta.get("range_200s") or 0) + 1
            if seen < 2:
                # Once is a cold edge, a mirror's hiccup, a stray answer: the
                # part was paid for and stays, and the next firing asks again.
                meta["range_200s"] = seen
                _save_meta(part, meta)
                return _answer(
                    status,
                    DECLINED,
                    "server returned 200 for a ranged request; the part is kept "
                    "and the next firing asks again",
                )
            restarts = int(meta.get("restarts") or 0) + 1
            log(f"server returned 200 for a ranged request again (restart {restarts})")
            if restarts > 2:
                log(
                    "FATAL: this server will not resume; it cannot be fetched in slices"
                )
                status.state = FATAL
                status.write(force=True)
                return FATAL
            part.unlink(missing_ok=True)
            whole = stated or total
            _save_meta(
                part,
                {
                    "restarts": restarts,
                    "no_range": True,
                    "etag": new_etag,
                    "modified": new_modified,
                    "total": whole,
                },
            )
            status.part, status.total = 0, whole
            status.state = DECLINED
            status.write(force=True)
            return DECLINED

        if offset and code == 206:
            content_range = response.headers.get("Content-Range", "")
            start = -1
            if content_range.startswith("bytes "):
                try:
                    start = int(content_range[6:].split("-")[0])
                except ValueError:
                    start = -1
            if start != offset:
                log(f"FATAL: asked for {offset}, server sent {content_range!r}")
                status.state = FATAL
                status.write(force=True)
                return FATAL
            if etag and new_etag and etag != new_etag:
                log("remote file changed (ETag differs); discarding partial")
                part.unlink(missing_ok=True)
                _save_meta(part, {"etag": new_etag, "modified": new_modified})
                status.part = 0
                status.state = DECLINED
                status.write(force=True)
                return DECLINED

        # Content-Range carries the true total; it is better than any hint.
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            tail = content_range.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                total = int(tail)
        elif code == 200 and stated:
            total = stated
        status.total = total

        # Where no size is stated, the end of the file is where the body ends:
        # a 200 from the first byte runs to the end of the file, and a 206
        # that stops short of what was asked stops there because the file does.
        span_end = _span_end(content_range) if code == 206 else None
        to_eof = not total and (
            (code == 200 and not offset)
            or (span_end is not None and span_end < want_end)
        )

        if code == 206:
            # It resumes after all: nothing learned from a 200 still stands.
            for key in ("no_range", "range_200s", "at_least"):
                meta.pop(key, None)
        meta.update(
            {
                "url": url,
                "etag": new_etag,
                "modified": new_modified,
                "total": total,
                "restarts": int(meta.get("restarts") or 0),
            }
        )
        _save_meta(part, meta)

        taken = 0
        since_sync = 0
        started = time.time()
        window_start, window_bytes = started, 0
        reason = "slice complete"

        with part.open("ab") as sink:
            while True:
                if _stop:
                    reason = "asked to stop"
                    break
                if time.time() >= env.deadline():
                    reason = "deadline"
                    break
                if taken >= budget:
                    reason = "slice budget reached"
                    if to_eof and code == 200 and not _more(response):
                        reason = "end of slice"
                    break
                failed = ""
                try:
                    block = response.read(min(CHUNK, budget - taken))
                except (OSError, TimeoutError) as exc:
                    reason = f"read failed: {exc}"
                    break
                except http.client.HTTPException as exc:
                    # A chunked body cut off mid-chunk: the same dropped link a
                    # reset is, not a fault in the item. What had arrived is
                    # kept, and the slice ends the ordinary way -- flushed, its
                    # report written, "not tonight" -- rather than as a strike.
                    block = _arrived(exc)[: budget - taken]
                    failed = f"read failed: {exc!r}"
                if not block:
                    reason = failed or "end of slice"
                    break

                sink.write(block)
                taken += len(block)
                since_sync += len(block)
                window_bytes += len(block)
                status.slice_bytes = taken
                status.part = offset + taken
                if failed:
                    reason = failed
                    break

                if since_sync >= FSYNC_EVERY:
                    sink.flush()
                    os.fsync(sink.fileno())
                    since_sync = 0

                now = time.time()
                if now - window_start >= SLOW_SECONDS:
                    if window_bytes / (now - window_start) < SLOW_BPS:
                        reason = "link too slow"
                        break
                    window_start, window_bytes = now, 0

                status.write()

            sink.flush()
            os.fsync(sink.fileno())

    have = part.stat().st_size
    rate = taken / max(1e-6, time.time() - started)
    log(
        f"took {taken:,} bytes ({reason}); {have:,} of "
        f"{total or '?'} at {rate / 1024:,.0f} KiB/s"
    )

    status.part = have
    status.slice_bytes = taken
    if (
        to_eof
        and reason == "end of slice"
        and (span_end is None or taken == span_end - offset + 1)
    ):
        # The body ran out before the slice did, and nothing was cut off on
        # the way: that is the end of the file, and its size.
        total = status.total = meta["total"] = have
        _save_meta(part, meta)
    if total and have >= total:
        return _deliver(part, dest, expect_sha256, env, status)

    if to_eof and code == 200 and reason == "slice budget reached":
        # The whole slice and still no end, from a server that answered a
        # ranged request with a 200: it ignores Range, so this part can never
        # be resumed. Kept, it would be thrown away at the next request after
        # that request was paid for too.
        part.unlink(missing_ok=True)
        meta.update({"no_range": True, "at_least": have + 1})
        meta.pop("total", None)
        _save_meta(part, meta)
        status.part = 0
        if cap and budget >= cap:
            # A slice of the whole declaration, spent without reaching the
            # end: the file is bigger than the cap it was queued under. Never
            # delivered cut off at it, and never fetched again to find out.
            return _answer(
                status,
                FATAL,
                f"FATAL: the file is larger than the {cap:,} bytes it was queued "
                "under, and this server will not send it in parts",
            )
        return _answer(
            status,
            DECLINED,
            "this server ignores Range and the file is larger than this slice; "
            "the slice cannot be resumed and is discarded",
        )

    status.state = PROGRESS if taken else DECLINED
    status.write(force=True)
    return status.state


def run(
    url: str, name: str, expect_sha256: str | None = None, total_hint: int = 0
) -> int:
    """:func:`fetch`, mapped to the exit code the runner expects."""
    try:
        return EXIT[fetch(url, name, expect_sha256, total_hint)]
    except Exception as exc:  # noqa: BLE001 - an item must never traceback out
        log(f"unhandled error: {exc!r}")
        return EXIT[FATAL]


if __name__ == "__main__":
    print(__doc__)
    raise SystemExit(0)
