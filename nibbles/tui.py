"""The terminal: one blessed session, read as events, drawn through bewitch.

nibbles is buttons first and keys second, on a phone, in Termux. Everything
the screens need from the terminal comes through here and nowhere else:

- **one** :class:`Session` — one blessed ``Terminal``, fullscreen, cbreak, the
  cursor hidden, clicks and the wheel reported in SGR. The Queue and More tabs
  draw into it too: nothing opens a second ``Terminal``.
- :meth:`Session.read` turns what arrives into one of six events —
  :class:`Key`, :class:`Tap`, :class:`Scroll`, :class:`Paste`,
  :class:`Resize`, :class:`Done` — and drops everything else: a release, a
  motion report, a byte of an escape sequence nobody asked for. A mouse report
  never arrives as a key, and neither does a paste.
- :class:`Job` is a fetch in a thread, holding its yt-dlp so Stop can kill it.
  When one finishes, the loop wakes with a :class:`Done`.
- :meth:`Session.show` hands a whole screen to :class:`bewitch.screen.Frame`,
  which writes only the lines that changed, and **nothing at all for an
  unchanged screen**.

What Termux sends (its ``TerminalView``, read in its source): a tap is a press
and a release together, sent when the finger lifts and only if it did not
move; a drag is wheel events, one per row, each stamped with the cell where
the drag *began*; a fling is more of them; a long press is Termux's own text
selection and never reaches us. So a drag can never press anything, and
:class:`Scroll` carries the drag's starting cell, which is what makes a
scrollbar draggable.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import sys
import termios
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# bewitch draws every screen. A checkout of it wins where there is one — beside
# this one, or under ~, the way every sibling here is found — so the phone draws
# with the bewitch it pulls; otherwise the one installed with nibbles from PyPI.
_SOURCE = Path(__file__).resolve().parent.parent


def _bewitch_root() -> Path | None:
    override = os.environ.get("BEWITCH_HOME")
    if override:
        return Path(override).expanduser()
    for candidate in (_SOURCE.parent / "bewitch", Path.home() / "bewitch"):
        if (candidate / "bewitch" / "__init__.py").is_file():
            return candidate
    return None


_BEWITCH = _bewitch_root()
if _BEWITCH is not None and str(_BEWITCH) not in sys.path:
    sys.path.insert(0, str(_BEWITCH))

from bewitch.colorprofile import detect  # noqa: E402
from bewitch.lipgloss import Block  # noqa: E402
from bewitch.screen import Frame  # noqa: E402

# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Key:
    """A key: a printable character as itself, anything else by a short name
    (``enter``, ``esc``, ``up``, ``down``, ``left``, ``right``, ``pgup``,
    ``pgdn``, ``home``, ``end``, ``backspace``, ``tab``, ``ctrl-u``…)."""

    name: str


@dataclass(frozen=True)
class Tap:
    """A finger lifted without moving, at column *x*, row *y* (0-based)."""

    x: int
    y: int


@dataclass(frozen=True)
class Scroll:
    """One row of a drag or a fling: *dy* is +1 to move the view down the
    list, -1 to move it up; *x*, *y* are where the gesture **began**."""

    dy: int
    x: int
    y: int


@dataclass(frozen=True)
class Paste:
    """Text pasted whole, as one line a field can hold (:func:`one_line`).

    Termux wraps a paste in ``ESC[200~ … ESC[201~`` once the app asks for it
    (bracketed paste, DECSET 2004), and otherwise types it, every line break a
    carriage return: each of those was ⏎, and whatever followed it landed on
    the screen under the field as keys — a search, then a probe for the
    selected row, then ``q``. A paste is never a key, so it can submit, stop,
    quit or press nothing; only a screen with a text field takes it, into
    the field.
    """

    text: str


@dataclass(frozen=True)
class Resize:
    width: int
    height: int


@dataclass(frozen=True)
class Done:
    job: Job


Event = Key | Tap | Scroll | Paste | Resize | Done

#: blessed's names for the keys the screens use, in the short spelling.
_NAMES = {
    "KEY_ENTER": "enter",
    "KEY_ESCAPE": "esc",
    "KEY_UP": "up",
    "KEY_DOWN": "down",
    "KEY_LEFT": "left",
    "KEY_RIGHT": "right",
    "KEY_PGUP": "pgup",
    "KEY_PGDOWN": "pgdn",
    "KEY_HOME": "home",
    "KEY_END": "end",
    "KEY_BACKSPACE": "backspace",
    "KEY_DELETE": "delete",
    "KEY_TAB": "tab",
    "KEY_BTAB": "btab",
}

#: Control characters a field needs, by their byte.
_CONTROLS = {
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x15": "ctrl-u",
    "\x17": "ctrl-w",
    "\x1b": "esc",
}


def one_line(text: str) -> str:
    """Pasted text as a one-line field holds it: the line breaks at either
    end dropped, and every one inside it, every tab and every other control
    character a space, so what reaches a field is all printable and nothing
    in it can act as ⏎ or ``esc``."""
    return "".join(ch if ch.isprintable() else " " for ch in text.strip("\r\n"))


def event_of(ks) -> Event | None:
    """One blessed keystroke as an event, or ``None`` for one nobody wants.

    Pure on the keystroke, so it is tested without a terminal. A mouse report
    becomes a Tap or a Scroll or nothing; it is never handed on as a key,
    whatever blessed calls it. A bracketed paste is a :class:`Paste`, whole.
    """
    if not ks:
        return None
    name = ks.name or ""
    if name == "BRACKETED_PASTE":
        text = one_line(ks.text or "")
        return Paste(text) if text else None
    if name.startswith("MOUSE_"):
        x, y = ks.mouse_xy
        if name == "MOUSE_LEFT":
            return Tap(x, y)
        if name == "MOUSE_SCROLL_UP":
            return Scroll(-1, x, y)
        if name == "MOUSE_SCROLL_DOWN":
            return Scroll(1, x, y)
        # A release (Termux sends one with every tap), a motion report, another
        # button: nothing a screen acts on.
        return None
    if name in _NAMES:
        return Key(_NAMES[name])
    text = str(ks)
    if text in _CONTROLS:
        return Key(_CONTROLS[text])
    if ks.is_sequence or not text or not text.isprintable() or len(text) != 1:
        # An escape sequence blessed could not name: dropped whole rather than
        # let a byte of it through as a letter that presses something.
        return None
    return Key(text)


# --------------------------------------------------------------------------- #
# Fetches
# --------------------------------------------------------------------------- #

#: The job the current thread is running, if it is one, so the code that
#: spawns a child (``ytq.ask``) can hand it over to be killed.
_local = threading.local()


def current_job() -> Job | None:
    return getattr(_local, "job", None)


class Cancelled(RuntimeError):
    """The job was stopped before it answered."""


@dataclass(eq=False)
class Job:
    """A fetch in a thread. ``result`` or ``error`` once it is done.

    *what* says what it is doing (``asking YouTube for formats``), for
    whoever reads it: the screens draw their own words, and it is there in
    the job's ``repr`` in the ``NIBBLES_DEBUG`` log. *key* says what it is a
    fetch *of*, so a screen can tell its own answer from another's. The
    thread never touches a screen: it fills ``result`` and wakes the loop,
    and the loop is the only thing that reads it.
    """

    work: Callable[[], object]
    what: str
    key: object = None
    #: Not a fetch: a hand-off to Android (the clipboard, an opener) that
    #: draws no spinner, so it neither wakes the loop to animate one nor
    #: answers ``x``, which is for stopping what spends data.
    quiet: bool = False
    #: A yt-dlp fetch — a search, a probe, a feed read — whose child is
    #: handed over through :func:`run_child`: the only kind ``x`` stops.
    #: Asking zwana or Android's scheduler spends nothing and holds no child
    #: to kill; cancelling one only threw its answer away, and left the fetch
    #: beside ``x stop`` spending.
    fetch: bool = False
    result: object = None
    error: BaseException | None = None
    cancelled: bool = False
    finished: bool = False
    started: float = field(default_factory=time.monotonic)
    _child: subprocess.Popen | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def run(self, wake: Callable[[], None]) -> None:
        def body() -> None:
            _local.job = self
            try:
                self.result = self.work()
            except BaseException as exc:  # noqa: BLE001 - handed to the screen
                self.error = exc
            finally:
                _local.job = None
                self.finished = True
                wake()

        threading.Thread(target=body, daemon=True).start()

    def adopt(self, child: subprocess.Popen) -> None:
        """Called from the job's thread with the child it just spawned."""
        with self._lock:
            self._child = child
            if self.cancelled:
                self._kill()

    def cancel(self) -> None:
        """Stop it: kill whatever it spawned. Its answer, if any, is dropped."""
        with self._lock:
            self.cancelled = True
            self._kill()

    def _kill(self) -> None:
        child = self._child
        if child is not None and child.poll() is None:
            with contextlib.suppress(OSError):
                os.killpg(os.getpgid(child.pid), signal.SIGTERM)


def run_child(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    """``subprocess.run`` for a job's thread: the child in a session of its
    own, handed to the job so Stop can kill it. Raises what ``run`` raises."""
    job = current_job()
    child = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    if job is not None:
        job.adopt(child)
    try:
        out, err = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # SIGKILL, and the whole group: anything left holding the pipes would
        # keep the wait below, and the job, from ever coming back.
        with contextlib.suppress(OSError):
            os.killpg(child.pid, signal.SIGKILL)
        child.communicate()
        raise
    if job is not None and job.cancelled:
        raise Cancelled("stopped")
    return subprocess.CompletedProcess(argv, child.returncode, out, err)


# --------------------------------------------------------------------------- #
# The session
# --------------------------------------------------------------------------- #


#: How long a lone ESC waits for the rest of a sequence. Termux writes a
#: whole sequence at once, so a short wait loses nothing and keeps ``esc``
#: (close the sheet) from feeling slow.
ESC_DELAY = 0.05


class Session:
    """The terminal, owned: entered with ``with``, restored on the way out,
    on Ctrl-Z and on any exception — a hangup and SIGTERM included, which
    leave by the same road as an exception (:meth:`read`)."""

    def __init__(self) -> None:
        import blessed

        self.term = blessed.Terminal()
        self.frame = Frame(self._write, profile=detect(), flush=self._flush)
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        #: Held while the wake pipe is written or let go (:meth:`wake`).
        #: Re-entrant, because a signal handler that wakes the loop runs on
        #: the main thread, and may run inside another wake.
        self._wake_lock = threading.RLock()
        self._resized = False
        self._suspend = False
        self._ended = 0
        self._stack: contextlib.ExitStack | None = None
        self._old: dict[int, object] = {}
        self.size = (self.term.width, self.term.height)

    # Writing ------------------------------------------------------------- #

    def _write(self, text: str) -> None:
        self.term.stream.write(text)

    def _flush(self) -> None:
        self.term.stream.flush()

    def show(self, block: Block) -> int:
        """Bring the terminal to *block*; the characters written."""
        return self.frame.show(block)

    # Entering and leaving ------------------------------------------------ #

    def _enter(self) -> None:
        stack = contextlib.ExitStack()
        try:
            stack.enter_context(self.term.fullscreen())
            stack.enter_context(self.term.cbreak())
            stack.enter_context(self.term.hidden_cursor())
            # Clicks only: Termux sends a drag as wheel events whatever the
            # mode, and motion reports would be bytes nobody reads.
            stack.enter_context(self.term.mouse_enabled(clicks=True))
            # A paste arrives whole (:class:`Paste`) rather than typed, its
            # line breaks a ⏎ each. Asked like the mouse modes, and a
            # terminal that does not have it keeps typing pastes as before.
            stack.enter_context(self.term.bracketed_paste())
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        self._flush()
        self.frame.invalidate()

    def _leave(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            # A terminal that hung up has nothing left to restore, and saying
            # so would only bury why the app is leaving.
            with contextlib.suppress(OSError, termios.error):
                stack.close()
                self._flush()

    def __enter__(self) -> Session:
        self._enter()
        for sig, handler in (
            (signal.SIGWINCH, self._on_winch),
            (signal.SIGTSTP, self._on_tstp),
            (signal.SIGCONT, self._on_cont),
            (signal.SIGHUP, self._on_end),
            (signal.SIGTERM, self._on_end),
        ):
            self._old[sig] = signal.signal(sig, handler)
        return self

    def __exit__(self, *exc) -> None:
        for sig, handler in self._old.items():
            signal.signal(sig, handler)
        self._leave()
        with self._wake_lock:
            fds = (self._wake_r, self._wake_w)
            self._wake_r = self._wake_w = -1
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)

    # Signals: each only notes what happened and wakes the loop, which acts on
    # it at a safe point. Nothing here touches the terminal.

    def wake(self) -> None:
        """Wake the loop. A job still running when the session ended — a
        fetch on its way down after the app stopped it, or a hand-off to
        Android, which is left to finish — calls this when it finishes,
        after the pipe is closed and its number perhaps given to a file
        opened since: it writes nothing then, rather than a byte into
        whatever that file is."""
        with self._wake_lock:
            if self._wake_w < 0:
                return
            with contextlib.suppress(OSError):
                os.write(self._wake_w, b".")

    def _on_winch(self, *_: object) -> None:
        self._resized = True
        self.wake()

    def _on_tstp(self, *_: object) -> None:
        self._suspend = True
        self.wake()

    def _on_cont(self, *_: object) -> None:
        self._resized = True
        self.wake()

    def _on_end(self, signum: int, *_: object) -> None:
        """The session closed (SIGHUP) or the app was told to end (SIGTERM).
        Left to its default, either killed the app where it stood, and the
        fetches it had started — in sessions of their own, so hearing
        neither — went on spending with nobody to read them."""
        self._ended = signum
        self.wake()

    def _do_suspend(self) -> None:
        self._suspend = False
        self._leave()
        old = signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        try:
            os.kill(os.getpid(), signal.SIGTSTP)
        finally:
            signal.signal(signal.SIGTSTP, old)
        self._enter()
        self._resized = True

    # Reading ------------------------------------------------------------- #

    def start(self, job: Job) -> Job:
        job.run(self.wake)
        return job

    def read(self, timeout: float | None, jobs: list[Job] = ()) -> Event | None:
        """The next event, or ``None`` when *timeout* runs out first.

        ``None`` for *timeout* blocks until something happens: a key, a tap,
        a resize, a job finishing. That is what keeps an idle screen silent.
        *jobs* is every job whose :class:`Done` is still owed, finished ones
        included: one that finished before this was called is answered at
        once rather than waited for.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        # nomut: start — checked on a pty, where a terminal answers it.
        while True:
            if self._ended:
                # Out through every ``finally`` on the way, as an exception
                # would: the app's stops its fetches, this one restores the
                # terminal. Not KeyboardInterrupt, which prints the receipts
                # to a terminal that may be gone.
                raise SystemExit(128 + self._ended)
            for job in jobs:
                if job.finished:
                    return Done(job)
            if self._suspend:
                self._do_suspend()
            if self._resized:
                self._resized = False
                self.size = (self.term.width, self.term.height)
                self.frame.invalidate()
                return Resize(*self.size)
            ks = self.term.inkey(timeout=0, esc_delay=ESC_DELAY)
            if ks:
                event = event_of(ks)
                if event is not None:
                    return event
                continue
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            if left == 0.0:
                return None
            fds = [self._wake_r]
            if self.term._keyboard_fd is not None:
                fds.append(self.term._keyboard_fd)
            try:
                ready, _, _ = select.select(fds, [], [], left)
            except InterruptedError:
                continue
            if self._wake_r in ready:
                with contextlib.suppress(OSError):
                    while os.read(self._wake_r, 64):
                        pass
            if len(ready) == 1 and ready[0] == self._wake_r:
                continue
            if not ready and deadline is not None and time.monotonic() >= deadline:
                return None
            if self.term._keyboard_fd in ready:
                # Bytes are waiting: let blessed resolve a whole sequence,
                # with Termux's short escape delay.
                ks = self.term.inkey(timeout=ESC_DELAY, esc_delay=ESC_DELAY)
                event = event_of(ks)
                if event is not None:
                    return event
        # nomut: end


# --------------------------------------------------------------------------- #
# Taps: the guards and the pressed flash
# --------------------------------------------------------------------------- #

#: A tap this soon after a screen or sheet appears is the tail of the tap
#: that opened it, and is ignored wherever it lands.
GUARD_ALL = 0.100
#: Android's double-tap window: inside it, only a tap on the same cell as the
#: one that opened the screen is dropped. A tap anywhere else acts at once.
GUARD_SAME_CELL = 0.300
#: How long a pressed button stays filled.
PRESSED = 0.120


class Guard:
    """Decides whether a tap is a new tap or the echo of the last one."""

    def __init__(self) -> None:
        self.opened = -10.0
        self.cell: tuple[int, int] | None = None

    def opened_by(self, tap: Tap | None, at: float | None = None) -> None:
        """A screen or sheet just appeared, opened by *tap* (or by a key)."""
        self.opened = time.monotonic() if at is None else at
        self.cell = (tap.x, tap.y) if tap else None

    def allows(self, tap: Tap, at: float | None = None) -> bool:
        now = time.monotonic() if at is None else at
        since = now - self.opened
        if since < GUARD_ALL:
            return False
        return not (since < GUARD_SAME_CELL and self.cell == (tap.x, tap.y))
