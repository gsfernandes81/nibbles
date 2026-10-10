"""What every test in this suite gets: a queue root that is not the real one.

``ytq`` anchors ``HERE``/``QUEUE``/``DONE``/``FAILED`` at **import time**, to
the dlq checkout, so a suite that imported it first and pointed it somewhere
afterwards would be writing items into whatever queue this machine has. So the
pointing happens here, before the first ``import ytq`` anywhere: ``EXPIRE_HOME``
names a throwaway root built in a temp directory, holding copies of dlq's
modules so that the cross-repo imports resolve exactly as they do on the phone
— copies and not symlinks, because ``expire_runner`` anchors *its* root on
``Path(__file__).resolve().parent`` and a symlink resolves back to the real
checkout, config file and all.

Nothing here reaches the network, and nothing outside the temp tree is written:
``$HOME`` is redirected too, so the yt-dlp config the cookie screens read is
this suite's and not the person's running it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path

import pyte

import pytest
from hypothesis import HealthCheck, Phase
from hypothesis import settings as hypothesis_settings

#: How much work the property tests do, in one place rather than on each of
#: them. ``too_slow`` is suppressed because several of these render whole items
#: or walk a temp directory per example, which is the work and not a warning.
hypothesis_settings.register_profile(
    "default",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
#: What ``make mutants`` runs with (``--hypothesis-profile=mutants``): fewer
#: examples, a fixed seed and **no shrinking**. Shrinking is what makes a
#: failing property test slow, and under mutation almost every run has one —
#: poodle only needs to know that the suite noticed, not a minimal example.
hypothesis_settings.register_profile(
    "mutants",
    deadline=None,
    max_examples=25,
    derandomize=True,
    suppress_health_check=list(HealthCheck),
    phases=[Phase.explicit, Phase.reuse, Phase.generate],
)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

REPO = Path(__file__).resolve().parent.parent

#: dlq's modules, which ytq imports across the checkouts. ``$YTQ_TEST_DLQ``
#: first so the mutation runner — which copies this repo somewhere with no
#: sibling beside it — can still say where the real one is.
_DLQ_MODULES = ("expire_dl.py", "expire_runner.py", "expire_sched.py", "expire_ui.py")


def _dlq_checkout() -> Path | None:
    for candidate in (
        os.environ.get("YTQ_TEST_DLQ"),
        REPO.parent / "dlq",
        Path.home() / "dlq",
    ):
        if not candidate:
            continue
        folder = Path(candidate).expanduser()
        if all((folder / name).is_file() for name in _DLQ_MODULES):
            return folder
    return None


def _zwana_checkout(dlq: Path) -> Path | None:
    for candidate in (
        os.environ.get("YTQ_TEST_ZWANA"),
        os.environ.get("ZWANA_HOME"),
        dlq.parent / "zwana-quota",
        Path.home() / "zwana-quota",
    ):
        if not candidate:
            continue
        folder = Path(candidate).expanduser()
        if (folder / "quota_widget.py").is_file():
            return folder
    return None


DLQ = _dlq_checkout()
if DLQ is None:  # pragma: no cover - the environment, not a behaviour
    raise pytest.UsageError(
        "the dlq checkout is not beside this one and $YTQ_TEST_DLQ names none; "
        "the suite imports across the two the way a real run does"
    )

_ZWANA = _zwana_checkout(DLQ)

#: One root for the session. Per-test isolation is the ``clean_queue`` fixture
#: emptying it, not a fresh tree: the paths are module constants in ytq and
#: cannot be re-pointed once it is imported.
ROOT = Path(tempfile.mkdtemp(prefix="ytq-tests-"))
QUEUE_ROOT = ROOT / "dlq"
HOME = ROOT / "home"

for folder in (QUEUE_ROOT, HOME, QUEUE_ROOT / "queue"):
    folder.mkdir(parents=True, exist_ok=True)
(QUEUE_ROOT / "queue" / "README.md").write_text("a throwaway queue\n")
for name in _DLQ_MODULES:
    shutil.copy2(DLQ / name, QUEUE_ROOT / name)

os.environ["EXPIRE_HOME"] = str(QUEUE_ROOT)
os.environ["YTQ_HOME"] = str(REPO)
if _ZWANA is not None:
    os.environ["ZWANA_HOME"] = str(_ZWANA)
os.environ["HOME"] = str(HOME)
os.environ.pop("XDG_CONFIG_HOME", None)
# The runner's own guards read these; nothing in this suite fires a run, but a
# stray inherited value must not be what decides a test.
for leaked in ("EXPIRE_SLICE_BYTES", "EXPIRE_BUDGET_BYTES", "EXPIRE_STOP_EPOCH",
               "EXPIRE_TOTAL_BYTES", "EXPIRE_WORK", "EXPIRE_OUT", "EXPIRE_RUN_ID"):
    os.environ.pop(leaked, None)

sys.path.insert(0, str(REPO))

import ytq  # noqa: E402  (after the environment above, deliberately)

#: Everything a test may empty between cases. ``ytq``'s constants are the
#: authority for the three it knows about, so a rename there reaches here.
_SCRATCH = (ytq.QUEUE, ytq.DONE, ytq.FAILED, QUEUE_ROOT / "work",
            QUEUE_ROOT / "out", QUEUE_ROOT / "logs")


@pytest.fixture(autouse=True)
def clean_queue():
    """An empty queue root before and after every test."""
    def wipe():
        for folder in _SCRATCH:
            shutil.rmtree(folder, ignore_errors=True)
        for leftover in ("config.json", "state.json", "runner.lock"):
            (QUEUE_ROOT / leftover).unlink(missing_ok=True)
        for entry in HOME.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    wipe()
    yield QUEUE_ROOT
    wipe()


# --------------------------------------------------------------------------- #
# Metadata a test can hand to the code under test
# --------------------------------------------------------------------------- #


def fmt(
    format_id: str,
    *,
    vcodec: str = "none",
    acodec: str = "none",
    ext: str = "mp4",
    filesize: int | None = None,
    approx: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    abr: int | None = None,
) -> dict:
    """One yt-dlp format entry, with only the keys the code actually reads."""
    out: dict = {"format_id": format_id, "ext": ext, "vcodec": vcodec, "acodec": acodec}
    if filesize is not None:
        out["filesize"] = filesize
    if approx is not None:
        out["filesize_approx"] = approx
    if height is not None:
        out["height"] = height
    if fps is not None:
        out["fps"] = fps
    if abr is not None:
        out["abr"] = abr
    return out


def video_info(
    *,
    ident: str = "abc123",
    title: str = "Crust of Rust: Lifetime Annotations",
    formats: list[dict] | None = None,
    extractor: str = "Youtube",
    duration: int = 5434,
) -> dict:
    """A ``yt-dlp -J`` answer for one video, sized like a real one."""
    if formats is None:
        formats = [
            fmt("137", vcodec="avc1.640028", ext="mp4", height=1080,
                filesize=480 * 1024 * 1024),
            fmt("248", vcodec="vp9", ext="webm", height=1080,
                approx=310 * 1024 * 1024),
            fmt("18", vcodec="avc1.42001E", acodec="mp4a.40.2", ext="mp4",
                height=360, filesize=38 * 1024 * 1024),
            fmt("140", acodec="mp4a.40.2", ext="m4a", abr=129,
                filesize=10 * 1024 * 1024),
            fmt("251", acodec="opus", ext="webm", abr=141,
                filesize=9 * 1024 * 1024),
            fmt("sb0", ext="mhtml"),
        ]
    return {
        "id": ident,
        "title": title,
        "duration": duration,
        "extractor_key": extractor,
        "ie_key": extractor,
        "webpage_url": f"https://www.youtube.com/watch?v={ident}",
        "formats": formats,
    }


def search_info(titles: list[str], *, playlist_title: str = "saved search") -> dict:
    """A flat ``--flat-playlist`` search answer holding *titles*."""
    return {
        "_type": "playlist",
        "title": playlist_title,
        "entries": [
            {
                "id": f"vid{index:02d}",
                "ie_key": "Youtube",
                "title": title,
                "channel": "Jon Gjengset",
                "url": f"https://www.youtube.com/watch?v=vid{index:02d}",
                "duration": 600 + index,
                "timestamp": int(time.time()) - 86400 * (index + 1),
            }
            for index, title in enumerate(titles)
        ],
    }


@pytest.fixture
def make_dump(tmp_path):
    """Write a metadata object where ``--from-json`` can read it."""
    def write(info: dict, name: str = "dump.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(info))
        return path
    return write


@pytest.fixture
def queued(clean_queue):
    """Put an item in the queue and hand back its path."""
    def write(name: str, *, source: str = "", where: str = "queued",
              body: str = "") -> Path:
        folder = {"queued": ytq.QUEUE, "done": ytq.DONE,
                  "failed": ytq.FAILED}[where]
        folder.mkdir(parents=True, exist_ok=True)
        head = f"{ytq.SHEBANG}\n# EXPIRE: v1\n"
        head += f"# SOURCE: {source}\n" if source else ""
        path = folder / name
        path.write_text(head + (body or '"""an item."""\n'))
        return path
    return write


# --------------------------------------------------------------------------- #
# Driving the curses screens
# --------------------------------------------------------------------------- #


class Tui:
    """ytq under a pty, with pyte reading what it drew.

    Assertions are made on *structure* — which screen is up, that a row for a
    given video exists, that the key letters are on the hint line — because
    every word on these screens is meant to be rewritten without breaking a
    test that was checking something else.
    """

    def __init__(self, argv: list[str], cols: int, rows: int, extra_env: dict):
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = bytearray()
        env = dict(os.environ)
        env.update({"TERM": "xterm", "LINES": str(rows), "COLUMNS": str(cols)})
        env.update(extra_env)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.pid = os.fork()
        if self.pid == 0:  # pragma: no cover - the child execs immediately
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for target in (0, 1, 2):
                os.dup2(slave, target)
            os.close(master)
            if slave > 2:
                os.close(slave)
            os.execve(sys.executable, [sys.executable, str(REPO / "ytq.py"), *argv],
                      env)
        os.close(slave)
        self.fd = master

    def pump(self, seconds: float = 0.2) -> int:
        """Read whatever the app has drawn. Returns how many bytes arrived."""
        got = 0
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return got
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
            self.stream.feed(chunk)

    def wait_for(self, wants, seconds: float = 8.0) -> str:
        """Pump until *wants* is happy with the screen, then return the screen."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(0.2)
            if wants(self.text):
                return self.text
        raise AssertionError(
            f"the screen never satisfied {getattr(wants, 'name', wants)}:\n{self.text}"
        )

    def send(self, keys: str) -> None:
        os.write(self.fd, keys.encode())
        time.sleep(0.15)

    @property
    def hints(self) -> str:
        """The key hints, which every screen draws on its second-to-last row."""
        return self.screen.display[-2]

    @property
    def text(self) -> str:
        return "\n".join(line.rstrip() for line in self.screen.display)

    def row_with(self, needle: str) -> str:
        for line in self.screen.display:
            if needle in line:
                return line.strip()
        raise AssertionError(f"no row holding {needle!r}:\n{self.text}")

    def wait_exit(self, seconds: float = 8.0) -> int:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(0.2)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.pid = 0
                return os.waitstatus_to_exitcode(status)
        raise AssertionError(f"ytq did not exit:\n{self.text}")

    def close(self) -> None:
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
        with contextlib.suppress(OSError):
            os.close(self.fd)


#: The arrow keys as ytq's screens receive them: keypad mode is on, so a
#: terminal sends SS3 and not CSI.
UP, DOWN = "\x1bOA", "\x1bOB"
ESC, ENTER = "\x1b", "\r"


@pytest.fixture
def tui():
    """Start ytq on a pty of a stated size and drive it."""
    started: list[Tui] = []

    def start(*argv: str, cols: int = 40, rows: int = 24, **env: str) -> Tui:
        session = Tui(list(argv), cols, rows, env)
        started.append(session)
        return session

    yield start
    for session in started:
        session.close()
