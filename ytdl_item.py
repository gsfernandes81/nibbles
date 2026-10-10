#!/data/data/com.termux/files/usr/bin/python3
"""yt-dlp as an expiring-quota queue item: one slice a firing, resumed natively.

Why this is not :mod:`expire_dl`
-------------------------------
The obvious shape is ``yt-dlp -g`` to resolve a direct media URL, then hand that
to :mod:`expire_dl` and let its bounded-Range machinery do the rest. That shape
**breaks across nights**: YouTube's media URLs are signed and expire in about six
hours, so a download spanning two nights resumes against a dead link.

So the item runs yt-dlp *itself* on every firing. Each firing re-extracts a fresh
URL and yt-dlp resumes its own ``.part`` from ``os.stat`` — the same append-only
prefix argument :mod:`expire_dl` makes, just enforced by yt-dlp. The cost is one
metadata extraction per firing (~0.1-0.5 MB) and a less precise slice edge: no
server stops us at a byte boundary, we watch the file grow and stop the child.

What holds the guarantees
-------------------------
Not this module. The runner's guards are unchanged and unconditional — ≥100 MB
left afterwards, nothing past 00:00 UTC, the paid reserve never touched — and
they are enforced against the *interface counters*, so they hold however an item
behaves internally. This module only tries to stop early enough that those
guards are never the thing that stops it, because a cooperative stop leaves a
resumable ``.part`` and a SIGKILL mid-write may not.

Byte metering
-------------
Bytes taken this slice are measured from ``.part`` files on disk, not from
yt-dlp's progress output. Two consequences worth naming, because both are the
reason the rule is shaped this way:

* **Only names containing** ``.part`` **are counted.** Merging writes a new file
  the size of both inputs; metering the directory would read that as a second
  download of the whole video and stop the item mid-merge, every night, forever.
* **Sizes are per-file high-water marks.** A finished stream is renamed out of
  ``x.part`` to ``x``, and a plain sum would read that as bytes being handed
  back.

Postprocessing (merge, fixup, thumbnail embed) does no network I/O, so when a
postprocessor announces itself the byte budget stops being enforced — otherwise
a video that finished downloading at the slice edge could never be merged.

Usage from a queue item::

    import sys
    sys.path.insert(0, "/data/data/com.termux/files/home/or3/termux/expire")
    import ytdl_item
    sys.exit(ytdl_item.run(url="https://...", name="some-talk", fmt="137+140",
                           total_hint=612_000_000))
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# expire_dl sits beside this file in the nibbles checkout. A queue item inserts
# the real path itself before importing this module, so the insert above is for
# running out of the checkout.
import expire_dl  # noqa: E402  (beside this file, path fixed up above)
import contextlib  # noqa: E402  (kept beside the sibling imports above)

COMPLETE = expire_dl.COMPLETE
PROGRESS = expire_dl.PROGRESS
DECLINED = expire_dl.DECLINED
FATAL = expire_dl.FATAL
EXIT = expire_dl.EXIT
log = expire_dl.log

#: Downloads live in a subdirectory of ``$EXPIRE_WORK`` so that the item's own
#: bookkeeping files are never mistaken for downloaded media.
DL_DIRNAME = "dl"

#: Item state that has to survive between firings, next to the downloads.
STATE_NAME = ".ytdl.json"

#: How often the meter looks at the disk. At 2 MB/s this bounds the overshoot
#: past the slice edge to under a megabyte, well inside the runner's own
#: allowance of ``cap * 1.15 + 8 MiB``.
POLL_SECONDS = 0.25

#: Slowest the slice is allowed to be spent, as a divisor of it: a rate limit of
#: ``ceiling / RATE_DIVISOR`` per second means a full slice takes at least that
#: many seconds, and so at least that many polls.
#:
#: This is a backstop, not a throttle. On the link this runs over it never
#: binds — the divisor is chosen so the limit sits several times above any speed
#: seen here. It exists because watching a file grow cannot stop a transfer that
#: finishes between two polls, which is precisely how a surprisingly fast link
#: would spend a whole slice before anything looked.
RATE_DIVISOR = 4
RATE_FLOOR = 2 * 1024 * 1024

#: Stop yt-dlp this long before :meth:`expire_dl.Env.deadline`, leaving room for
#: it to wind down and for delivery and the status write to happen with no
#: network work outstanding.
STOP_LEAD = 30

def time_left(deadline: float, now: float | None = None) -> str:
    """The banner's "how long have I got" phrase, safe on an endless run.

    ``dlq now`` sets ``EXPIRE_STOP_EPOCH=0`` on purpose — a download asked
    for outside the window has no stop time — and
    :meth:`expire_dl.Env.deadline` spells that ``+inf``. Every *comparison*
    against it is correct (nothing is ever past an infinite deadline), but
    the banner formatted it with ``int()``, and ``int(inf)`` raises
    OverflowError. That crashed the run in the line that says what the run
    is about to do: before a byte moved, with "unhandled error" in a log
    nobody opens and `n` simply not working.

    So the phrase is a function, and an endless run says so in words.
    """
    if deadline == float("inf"):
        return "no stop time"
    return f"{int(deadline - (time.time() if now is None else now))}s of it"


#: Keep the stop this far inside the slice. Small, because the predictive stop
#: below is what actually absorbs the overshoot; this only covers error in the
#: prediction. Both were sized generously at first, and together they gave away
#: a third of every slice.
GUARD_FRACTION = 0.005
GUARD_FLOOR = 256 * 1024

#: An extraction costs ~0.1-0.5 MB whatever happens, so a slice this small is
#: mostly overhead. Declined without invoking yt-dlp at all.
MIN_USEFUL_SLICE = 2 * 1024 * 1024

#: Firings that reached yt-dlp, moved nothing and failed. Below this the item
#: reports "not tonight" and keeps its place; at it, it takes a strike, so a
#: video that has been taken down cannot sit in the queue re-extracting nightly.
MAX_ZERO_FIRINGS = 3

#: Signals to stop the child with, in order, with how long to wait after each.
#: SIGINT first because yt-dlp handles it: it closes the output file, so the
#: ``.part`` is flushed rather than merely being a valid prefix.
#:
#: Two profiles, because the two reasons for stopping have different budgets.
#: A deadline stop has :data:`STOP_LEAD` seconds in hand and can afford to be
#: polite. A byte-budget stop is spending data for every second it waits, and a
#: hard kill there costs only the unflushed tail of an append-only file — which
#: is exactly the loss :mod:`expire_dl` already accepts.
STOP_GENTLE = ((signal.SIGINT, 10), (signal.SIGINT, 6), (signal.SIGTERM, 5))
STOP_FAST = ((signal.SIGINT, 3), (signal.SIGINT, 2), (signal.SIGTERM, 3))

#: How long yt-dlp keeps writing after being asked to stop. It reads from the
#: socket in blocks and only notices a signal between them, so the overshoot is
#: shaped by the link speed rather than by any byte count — which is why the
#: budget stop is predictive rather than a plain threshold.
STOP_REACTION = 1.5

#: Window the stop prediction measures the current rate over.
RATE_WINDOW = 3.0

#: Output lines that mean the network phase is over and CPU work has started.
PP_MARKERS = (
    "[Merger]",
    "[Fixup",
    "[ExtractAudio]",
    "[VideoConvertor]",
    "[MoveFiles]",
    "[Metadata]",
    "[EmbedSubtitle]",
    "[VideoRemuxer]",
    "[ThumbnailsConvertor]",
    "[SponsorBlock]",
    "[ModifyChapters]",
)

#: Lines worth putting in the run log. yt-dlp's progress bar is one line per
#: chunk with --newline, which would bury everything else.
PROGRESS_RE = re.compile(r"^\[download\]\s+\d")

_stop = False


def _on_term(signum, frame) -> None:
    """Only set a flag; the poll loop does the actual winding down."""
    global _stop
    _stop = True


# --------------------------------------------------------------------------- #
# Metering
# --------------------------------------------------------------------------- #


#: ``x.mp4.part`` and ``x.mp4.part-Frag7`` are both the stream ``x.mp4``.
PART_SUFFIX_RE = re.compile(r"\.part(-Frag\d+)?$")


class Meter:
    """Bytes fetched during this slice, measured from the files on disk.

    Three rules, each of which exists because the naive version is wrong:

    * **A stream is keyed by its finished name.** yt-dlp downloads to
      ``x.mp4.part`` and renames it to ``x.mp4`` when it is done. Keying by the
      name on disk would count that stream twice, once under each name.
    * **Sizes are high-water marks.** A file disappearing — renamed away, or
      deleted after a merge consumed it — must not read as bytes being handed
      back.
    * **Counting stops when postprocessing starts.** Merging writes a new file
      the size of both its inputs, and counting it would read as a second
      download of the whole video. ffmpeg's target is a ``.temp.`` name until
      it is finished, which is what keeps the freeze from racing the merge.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.high: dict[str, int] = {}
        self.frozen: int | None = None
        self.last = 0
        self.sample()
        self.base = dict(self.high)

    def sample(self) -> None:
        if self.frozen is not None:
            return
        try:
            found = list(self.root.rglob("*"))
        except OSError:
            return
        for path in found:
            if path.name.endswith(".ytdl") or ".temp." in path.name:
                continue
            try:
                if not path.is_file():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            key = PART_SUFFIX_RE.sub("", str(path.relative_to(self.root)))
            if size > self.high.get(key, 0):
                self.high[key] = size

    def _total(self) -> int:
        return sum(
            max(0, size - self.base.get(key, 0)) for key, size in self.high.items()
        )

    def freeze(self) -> None:
        """Stop counting, holding the last figure taken before postprocessing.

        The *last* figure rather than a fresh one: by the time a postprocessor
        has announced itself its output may already be on disk, and re-reading
        the directory now is exactly the double count this avoids.
        """
        if self.frozen is None:
            self.frozen = self.last

    def taken(self) -> int:
        if self.frozen is not None:
            return self.frozen
        self.sample()
        self.last = self._total()
        return self.last


def fetched_bytes(dl: Path) -> int:
    """Everything downloaded so far: finished streams plus partial ones.

    ``.ytdl`` is yt-dlp's fragment index and ``.temp.`` files are a merge in
    progress — neither is downloaded payload.
    """
    total = 0
    try:
        found = list(dl.rglob("*"))
    except OSError:
        return 0
    for path in found:
        if path.name.endswith(".ytdl") or ".temp." in path.name:
            continue
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


# --------------------------------------------------------------------------- #
# Item state
# --------------------------------------------------------------------------- #


def load_state(work: Path) -> dict:
    try:
        return json.loads((work / STATE_NAME).read_text())
    except (OSError, ValueError):
        return {}


def save_state(work: Path, state: dict) -> None:
    try:
        expire_dl._atomic(
            work / STATE_NAME, json.dumps(state, indent=2, sort_keys=True)
        )
    except OSError:
        pass  # Bookkeeping must never be able to fail a download.


# --------------------------------------------------------------------------- #
# The child
# --------------------------------------------------------------------------- #


def ytdl_argv() -> list[str]:
    """How to invoke yt-dlp: as a module of *this* interpreter if it can, else
    the binary on ``PATH``.

    The module form is preferred because a scheduled firing inherits an
    unpredictable ``PATH``. It is not always available, though: ``ytq`` and
    ``dlq`` are installed as a ``uv`` tool whose venv deliberately declares no
    dependencies, so under *that* interpreter ``-m yt_dlp`` fails before the URL
    is ever looked at. Falling back to the binary is what makes the packaged
    entry points work.

    When neither exists this still returns something runnable-looking, so the
    resulting ``FileNotFoundError`` is reported by the callers' existing
    "yt-dlp is not installed" path rather than by a second one here.
    """
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return [shutil.which("yt-dlp") or "yt-dlp"]


def command(
    url: str,
    name: str,
    fmt: str,
    dl: Path,
    printed: Path,
    merge_ext: str | None,
    rate_limit: int,
) -> list[str]:
    """The yt-dlp invocation for one firing."""
    argv = [
        *ytdl_argv(),
        "--no-playlist",
        "--no-colors",
        "--newline",
        "--progress",
        "--continue",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--extractor-retries",
        "2",
        "--socket-timeout",
        "30",
        "--concurrent-fragments",
        "1",
        "--limit-rate",
        str(rate_limit),
        "-f",
        fmt,
        "-P",
        f"home:{dl}",
        "-o",
        f"{name}.%(ext)s",
        "--print-to-file",
        "after_move:filepath",
        str(printed),
    ]
    if merge_ext:
        argv += ["--merge-output-format", merge_ext]
    argv.append(url)
    return argv


class Child:
    """A running yt-dlp, with its output tee'd to the run log."""

    def __init__(self, argv: list[str], cwd: Path) -> None:
        # Deliberately *not* start_new_session: the item is already in its own
        # session, created by the runner so it can signal the whole tree. A new
        # session here would put yt-dlp outside that group and let it survive a
        # kill of the item.
        self.process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.postprocessing = False
        self.tail: list[str] = []
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """Drain the pipe, echo the interesting lines, notice postprocessing.

        Draining matters on its own: a full pipe would block yt-dlp forever, and
        the progress bar alone is thousands of lines.
        """
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            if line.startswith(PP_MARKERS):
                self.postprocessing = True
            self.tail.append(line)
            del self.tail[:-40]
            if not PROGRESS_RE.match(line):
                log(f"  | {line}")

    def stop(self, why: str, escalation=STOP_GENTLE) -> None:
        """Wind the child down, escalating only as far as it makes us."""
        if self.process.poll() is not None:
            return
        log(f"stopping yt-dlp: {why}")
        for sig, grace in escalation:
            try:
                self.process.send_signal(sig)
            except (ProcessLookupError, OSError):
                return
            try:
                self.process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue
        try:
            self.process.kill()
            self.process.wait(timeout=10)
        except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
            pass

    def finish(self) -> int:
        """Wait for the reader to drain so the log is complete before we exit."""
        self._reader.join(timeout=10)
        return self.process.returncode if self.process.returncode is not None else -1


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def _named(directory: Path, name: str) -> list[Path]:
    """Files called ``name.something``, matched literally.

    Not ``glob``: the name comes from the item, and a title that slugified to
    something containing a bracket would be read as a character class and match
    nothing — silently, at the moment of delivery.
    """
    try:
        return [
            path for path in directory.iterdir() if path.name.startswith(f"{name}.")
        ]
    except OSError:
        return []


def produced(dl: Path, printed: Path, name: str) -> Path | None:
    """The finished file, as yt-dlp reported it, or the best guess otherwise."""
    try:
        lines = [
            line.strip() for line in printed.read_text().splitlines() if line.strip()
        ]
    except OSError:
        lines = []
    for line in reversed(lines):
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = dl / candidate
        if candidate.is_file():
            return candidate

    # --print-to-file did not fire (an older yt-dlp, or the file was already in
    # place). Fall back to the largest thing that is not scaffolding.
    best: Path | None = None
    for path in sorted(_named(dl, name)):
        if ".part" in path.name or path.name.endswith(".ytdl"):
            continue
        if ".temp." in path.name or re.search(r"\.f\d+\.", path.name):
            continue
        if not path.is_file():
            continue
        if best is None or path.stat().st_size > best.stat().st_size:
            best = path
    return best


def deliver(source: Path, out: Path, status: expire_dl.Status) -> str:
    """Move the finished file to ``$EXPIRE_OUT``, per the queue contract."""
    out.mkdir(parents=True, exist_ok=True)
    dest = out / source.name
    size = source.stat().st_size
    shutil.move(str(source), str(dest))
    log(f"complete: {dest} ({size:,} bytes)")
    status.state = COMPLETE
    status.part = size
    status.total = max(status.total, size)
    status.write(force=True)
    return COMPLETE


def already_delivered(out: Path, name: str) -> Path | None:
    """A file this item delivered on an earlier firing that was not archived."""
    for path in sorted(_named(out, name)):
        if path.is_file() and ".part" not in path.name:
            return path
    return None


# --------------------------------------------------------------------------- #
# One firing
# --------------------------------------------------------------------------- #


def fetch(
    url: str,
    name: str,
    fmt: str = "bv*+ba/b",
    total_hint: int = 0,
    merge_ext: str | None = None,
) -> str:
    """Take one slice of *url* with yt-dlp, delivering when it completes."""
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    env = expire_dl.Env()
    env.work.mkdir(parents=True, exist_ok=True)
    dl = env.work / DL_DIRNAME
    dl.mkdir(parents=True, exist_ok=True)
    printed = env.work / ".produced"

    total = int(total_hint or env.total_hint or 0)
    state = load_state(env.work)

    done = already_delivered(env.out, name)
    if done:
        log(f"already delivered: {done}")
        status = expire_dl.Status(env, total, done.stat().st_size)
        status.state = COMPLETE
        status.write(force=True)
        return COMPLETE

    have = fetched_bytes(dl)
    # Clamped so the runner, which computes the next slice as cap - part_bytes,
    # can never conclude that nothing is left to do and stop offering slices.
    status = expire_dl.Status(env, total, min(have, total - 1) if total else have)

    budget = env.slice
    if budget < MIN_USEFUL_SLICE and not state.get("downloads_complete"):
        # Not worth an extraction: the metadata alone would be a visible share
        # of the slice. Costs nothing and takes no strike.
        log(
            f"slice of {budget:,} bytes is below the {MIN_USEFUL_SLICE:,} byte "
            f"minimum for an extraction"
        )
        status.state = DECLINED
        status.write(force=True)
        return DECLINED

    guard = max(GUARD_FLOOR, int(budget * GUARD_FRACTION))
    ceiling = max(budget // 2, budget - guard)
    deadline = env.deadline() - STOP_LEAD

    if time.time() >= deadline:
        log("no time left this firing for an extraction")
        status.state = DECLINED
        status.write(force=True)
        return DECLINED

    with contextlib.suppress(OSError):
        printed.unlink()

    rate_limit = max(RATE_FLOOR, ceiling // RATE_DIVISOR)
    log(
        f"yt-dlp -f {fmt}  slice {budget:,} B (stopping at {ceiling:,} B), "
        f"{time_left(deadline)}, {have:,} B already on disk, "
        f"rate capped at {rate_limit:,} B/s"
    )

    meter = Meter(dl)
    started = time.time()
    try:
        child = Child(command(url, name, fmt, dl, printed, merge_ext, rate_limit), dl)
    except OSError as exc:
        log(f"FATAL cannot start yt-dlp: {exc}")
        status.state = FATAL
        status.write(force=True)
        return FATAL

    reason = "finished"
    window: list[tuple[float, int]] = [(started, 0)]
    while child.process.poll() is None:
        time.sleep(POLL_SECONDS)
        moment = time.time()
        if child.postprocessing:
            meter.freeze()
        taken = meter.taken()
        status.slice_bytes = taken
        status.part = have + taken

        window.append((moment, taken))
        while len(window) > 2 and moment - window[0][0] > RATE_WINDOW:
            window.pop(0)
        span = moment - window[0][0]
        rate = (taken - window[0][1]) / span if span > 0 else 0.0

        if _stop:
            reason = "asked to stop"
            child.stop(reason)
            break
        if time.time() >= deadline:
            reason = "deadline"
            child.stop(reason)
            break
        # Postprocessing is CPU, not network, so the byte ceiling stops applying
        # once it starts; the deadline above still does.
        #
        # Stop on where the child will be when it actually stops, not on where
        # it is now: everything it reads between the signal and noticing it is
        # spent either way. On a fast link this ends the slice early, which is
        # only ever a smaller slice; overshooting instead would eat the runner's
        # margin above the 100 MB floor.
        if not child.postprocessing and taken + rate * STOP_REACTION >= ceiling:
            reason = "slice budget reached"
            child.stop(reason, STOP_FAST)
            break

        status.write()

    code = child.finish()
    if child.postprocessing:
        meter.freeze()
    taken = meter.taken()
    have_now = fetched_bytes(dl)
    elapsed = max(1e-6, time.time() - started)
    log(
        f"yt-dlp exit {code} ({reason}); took {taken:,} bytes at "
        f"{taken / elapsed / 1024:,.0f} KiB/s, {have_now:,} B on disk"
    )

    if child.postprocessing:
        state["downloads_complete"] = True

    status.slice_bytes = taken
    status.part = min(have_now, total - 1) if total else have_now

    if code == 0:
        result = produced(dl, printed, name)
        if result is not None:
            state.pop("zero_firings", None)
            save_state(env.work, state)
            return deliver(result, env.out, status)
        # Exit 0 with nothing to show for it should never happen; treat it as a
        # failure rather than archiving the item as done and losing the video.
        log("FATAL yt-dlp reported success but produced no file")
        status.state = FATAL
        status.write(force=True)
        save_state(env.work, state)
        return FATAL

    if taken > 0 or reason in ("deadline", "slice budget reached", "asked to stop"):
        state.pop("zero_firings", None)
        save_state(env.work, state)
        status.state = PROGRESS if taken else DECLINED
        status.write(force=True)
        return status.state

    # Reached yt-dlp, moved nothing, and it failed on its own. Once is a bad
    # night; repeatedly is a video that has gone away, and something a human
    # should be told about rather than an item extracting metadata nightly for
    # the rest of time.
    zero = int(state.get("zero_firings") or 0) + 1
    state["zero_firings"] = zero
    save_state(env.work, state)
    for line in child.tail[-6:]:
        log(f"  ! {line}")
    if zero >= MAX_ZERO_FIRINGS:
        log(f"FATAL yt-dlp failed {zero} firings running without moving a byte")
        state["zero_firings"] = 0
        save_state(env.work, state)
        status.state = FATAL
        status.write(force=True)
        return FATAL
    log(f"yt-dlp failed without moving a byte ({zero}/{MAX_ZERO_FIRINGS})")
    status.state = DECLINED
    status.write(force=True)
    return DECLINED


def run(
    url: str,
    name: str,
    fmt: str = "bv*+ba/b",
    total_hint: int = 0,
    merge_ext: str | None = None,
) -> int:
    """:func:`fetch`, mapped to the exit code the runner expects."""
    try:
        return EXIT[fetch(url, name, fmt, total_hint, merge_ext)]
    except Exception as exc:  # noqa: BLE001 - an item must never traceback out
        log(f"unhandled error: {exc!r}")
        return EXIT[FATAL]


if __name__ == "__main__":
    print(__doc__.strip().split("\n")[0])
    print("\nThis is a library for queue items; see ytq.py to make one.")
    sys.exit(0)
