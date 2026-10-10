"""A Termux stand-in for the pty tests: the app on a pty, read back with pyte.

blessed asks the terminal things when it starts (where the cursor is, and
whether the mouse modes are supported) and waits for the answers. Termux
answers both, so this does too:

- a cursor-position request (``ESC[6n``) gets ``ESC[1;1R``;
- a DECRQM query (``ESC[?<mode>$p``) gets ``ESC[?<mode>;2$y``: supported, and
  off until asked for, which is what Termux says about 1000 and 1006
  (checked on the phone, 2026-10-10).

Without the second, blessed never decodes a mouse report and a tap arrives as
the letters of its escape sequence; without the first, it waits out a five
second timeout before drawing anything.

What Termux sends, this sends: a tap is a press and a release together at one
cell (``ESC[<0;x;yM`` then ``ESC[<0;x;ym``), and a drag is wheel events, one
per row, every one of them stamped with the cell the drag began at.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time

import pyte

class Term(pyte.Screen):
    """pyte, plus ``CSI S`` and ``CSI T`` (scroll a region up or down), which
    it answers neither of: fed a redraw that uses them, its screen would keep
    text a terminal had already scrolled away."""

    def scroll_up(self, count: int | None = None) -> None:
        for _ in range(count or 1):
            self.index()

    def scroll_down(self, count: int | None = None) -> None:
        for _ in range(count or 1):
            self.reverse_index()


pyte.Stream.csi["S"] = "scroll_up"
pyte.Stream.csi["T"] = "scroll_down"

QUERY_CPR = b"\x1b[6n"
QUERY_DECRQM = re.compile(rb"\x1b\[\?(\d+)\$p")
#: Both, so they are answered in the order they were asked: blessed sends a
#: DECRQM query and then a cursor-position request as its boundary, and an
#: answer to the second arriving first tells it the first got none — the late
#: answer is then read as typing.
QUERIES = re.compile(rb"\x1b\[6n|\x1b\[\?(\d+)\$p")

UP, DOWN, LEFT, RIGHT = b"\x1b[A", b"\x1b[B", b"\x1b[D", b"\x1b[C"
ENTER, ESC, TAB = b"\r", b"\x1b", b"\t"


class Termux:
    """One app on one pty, a pyte screen over it, and the queries answered."""

    def __init__(self, argv: list[str], cols: int, rows: int, env: dict[str, str],
                 cwd: str | None = None) -> None:
        self.cols, self.rows = cols, rows
        self.screen = Term(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = bytearray()
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # pragma: no cover - the child execs immediately
            if cwd:
                os.chdir(cwd)
            os.execve(argv[0], argv, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self._pending = b""

    # Reading ---------------------------------------------------------------

    def _answer(self, chunk: bytes) -> None:
        data = self._pending + chunk
        for found in QUERIES.finditer(data):
            if found.group(1) is None:
                os.write(self.fd, b"\x1b[1;1R")
            else:
                os.write(self.fd, b"\x1b[?" + found.group(1) + b";2$y")
        # A query split across two reads is answered when its tail arrives.
        # A query cut off at the end of a read is kept, unanswered, until its
        # tail arrives.
        tail = data[data.rfind(b"\x1b"):] if b"\x1b" in data else b""
        partial = re.fullmatch(rb"\x1b(\[(6|\?\d*\$?)?)?", tail)
        self._pending = tail if partial else b""

    def pump(self, seconds: float = 0.2) -> int:
        """Read for *seconds*; how many bytes arrived."""
        got = 0
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            ready, _, _ = select.select([self.fd], [], [], left)
            if not ready:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                return got
            if not chunk:
                return got
            got += len(chunk)
            self.raw += chunk
            self._answer(chunk)
            self.stream.feed(chunk)
        return got

    def settle(self, quiet: float = 0.4, limit: float = 10.0) -> None:
        """Read until nothing has arrived for *quiet* seconds."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            if not self.pump(quiet):
                return

    def wait_for(self, wants, seconds: float = 10.0) -> list[str]:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(0.15)
            if wants(self.lines):
                return self.lines
        raise AssertionError("the screen never got there:\n" + self.text)

    @property
    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.screen.display]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def find(self, needle: str) -> tuple[int, int]:
        """The cell in the middle of *needle*'s first appearance."""
        for y, line in enumerate(self.screen.display):
            x = line.find(needle)
            if x >= 0:
                return x + len(needle) // 2, y
        raise AssertionError(f"{needle!r} is not on the screen:\n{self.text}")

    # Writing ---------------------------------------------------------------

    def send(self, keys: bytes, settle: float = 0.3) -> None:
        os.write(self.fd, keys)
        self.settle(settle)

    def tap(self, x: int, y: int, settle: float = 0.3) -> None:
        """A finger lifted without moving: press and release, one cell."""
        cell = f"{x + 1};{y + 1}".encode()
        os.write(self.fd, b"\x1b[<0;" + cell + b"M\x1b[<0;" + cell + b"m")
        self.settle(settle)

    def tap_on(self, needle: str, settle: float = 0.3) -> None:
        self.tap(*self.find(needle), settle=settle)

    def drag(self, rows: int, x: int, y: int, gap: float = 0.0, settle: float = 0.3) -> None:
        """A drag of *rows* rows (positive: the finger moves up, the view
        moves down the list), each wheel event stamped with where it began."""
        button = b"65" if rows > 0 else b"64"
        cell = f"{x + 1};{y + 1}".encode()
        for _ in range(abs(rows)):
            os.write(self.fd, b"\x1b[<" + button + b";" + cell + b"M")
            if gap:
                time.sleep(gap)
        self.settle(settle)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.pid, signal.SIGWINCH)
        self.settle()

    def wait_exit(self, seconds: float = 10.0) -> int:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(0.1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.pid = 0
                return os.waitstatus_to_exitcode(status)
        raise AssertionError("the app did not exit:\n" + self.text)

    def close(self) -> None:
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            self.pid = 0
        with contextlib.suppress(OSError):
            os.close(self.fd)

    # The shell's own landmarks ---------------------------------------------

    @property
    def tab_row(self) -> str:
        """The tab labels, third row from the bottom on every tab screen."""
        return self.lines[-3] if len(self.lines) >= 3 else ""

    @property
    def header(self) -> str:
        return self.lines[0]
