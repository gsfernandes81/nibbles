#!/data/data/com.termux/files/usr/bin/python3
"""Find a video and queue it for the expiring-quota runner, at a measured size.

``EXPECT_BYTES`` is the cap the runner enforces against an item, and the queue
contract says plainly that "unknown" is not a valid answer for it. Guessing it
from a resolution is how an item ends up either refused every night for being
too big or killed by the interface watchdog for being bigger than it claimed.

So this asks yt-dlp. Paste a URL, it runs a metadata-only extraction (~0.1-0.5 MB
of internet data and no media), lists every format with the size yt-dlp reports
for it, and writes a queue item with that figure already in the header. The
number in the item is then a measurement with a stated overhead margin, not an
estimate.

It also searches. One flat search is a single request (~0.1 MB) that answers
with a title, a channel, a length, an approximate age and a view count per
result; picking one probes it exactly as a pasted URL would. The entry field
takes either, and tells them apart by looking, so there is one box rather than
two.

And it browses the subscription feed, which is the same list of the same things
and so is the same screen: ``subs`` in that one field asks YouTube for the
newest ``SUBS_RESULTS`` videos from the accounts you follow, bounded to one page
(~0.2 MB), marked with what the queue already holds, and picked from exactly as
a search result is. It is the one thing here that needs the *stored cookie* —
the jar the yt-dlp config already points at for the bot check — so whether there
is one is asked before a request is spent rather than after one comes back
empty. An empty feed is never reported as "nothing new": YouTube answers a
logged-out feed with no entries rather than with an error, so that answer means
the cookies have expired and the screen says so.

Watch Later is the other signed-in list, on the same screen by the same road:
``wl`` in the field reads the first ``SUBS_RESULTS`` of it, in the order the
playlist keeps, on the same cookie and the same bound.

Usage::

    nibbles                       # search, or paste a URL into the same field
    nibbles search crust of rust  # straight to the results
    nibbles <url>                 # straight to the video sheet
    nibbles --now <url>           # open the video sheet ready to download now
    nibbles --list <url>          # print the formats, write nothing
    nibbles --list subs           # print the feed, write nothing

The item it writes runs yt-dlp per firing (see :mod:`ytdl_item`); it never
resolves a media URL up front, because those are signed and expire in hours,
which is shorter than the queue takes to work through a large video.

Downloading now still writes that item first and then asks ``dlq`` to run it,
rather than waiting for the window. Downloading without the queue would have
been less code and worse: this way an interrupted download resumes instead of
restarting, the nightly window finishes anything that stops early, and
``nibbles list`` knows about it like everything else. It is mobile data spent now,
though, which the nightly window is not.

That run is handed to a detached process rather than held in the foreground, so
choosing it does not end the session: the sheet closes, and the status bar
along the foot says how far the download has got.

This module is the YouTube half's logic and its printing paths. The screens are
nibbles' (``nibbles.py``, ``yt_screens.py``); ``nibbles`` opens the app on its
Search tab, and ``nibbles.main`` decides what reaches :func:`main`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import tomllib
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path

from nibbles import home, ytdl_item
import contextlib

#: What a queue item puts on ``sys.path`` to import ``nibbles``: the checkout,
#: or the site-packages this was installed into (:data:`home.SOURCE`).
MODULE_DIR = home.SOURCE

#: The directory the runner works out of — :func:`home.root`: ``EXPIRE_HOME``,
#: else the checkout this package sits in, else ``~/nibbles``. Never an
#: installed copy's own directory, because an item written next to it would sit
#: where the nightly runner never looks: queued, apparently fine, and never
#: downloaded.
HERE = home.root()
QUEUE = HERE / "queue"
STAGING = QUEUE / ".staging"
DONE = HERE / "done"
FAILED = HERE / "failed"

#: The runner rejects an item whose interpreter is not on disk, and on Termux
#: /usr/bin/env is not. Written literally rather than from sys.executable so a
#: run under some other interpreter cannot emit an item that will not start.
SHEBANG = home.SHEBANG

#: Payload bytes are not wire bytes, and the item pays for one metadata
#: extraction per firing on top. Applied to the size yt-dlp reports.
OVERHEAD_EXACT = 1.03
OVERHEAD_APPROX = 1.12
OVERHEAD_FIXED = 4 * 1024 * 1024

#: Below the runner's 32 MiB default, because an extraction costs the item
#: ~0.1-0.5 MB whatever the slice is, and a 16 MiB slice still pays for itself.
SLICE_MIN_BYTES = 16 * 1024 * 1024

ITEM_RE = re.compile(r"^(\d{2,})-")

#: The highest priority a new item may be given, and the reason every one of
#: them is written with two digits.
#:
#: The runner takes its items in **file name** order, which is a string sort —
#: so ``100`` sorts before ``20`` and an item numbered past 99 does not go to
#: the back of the queue, it goes to the front. Zero-padded to two, string
#: order and number order are the same thing, and every screen that talks about
#: "lower runs first" is telling the truth. ``nibbles queue``'s reorder hands out
#: fresh two-digit keys when the room between two items runs out, which is also
#: what repairs a queue that already has three-digit ones in it.
MAX_PRIORITY = 99

#: The width the full-detail layouts need. Below it the format list drops the
#: format id and the codec detail, which are the two columns nobody chooses on,
#: and the confirm screen drops to the figures alone. Termux in portrait is
#: around 40 columns; the size and the label are what a choice is made from.
#: Matches ``expire_sched.WIDE``, so one terminal does not get two answers
#: about whether it is wide.
WIDE = 72


#: And below 40 there are only 30 of them, so a second and shorter set rather
#: than a clipped first one — the same reason the listing has three shapes and
#: not one scaled table. What each of these drops is chosen on the rule above:
#: the word that must never be the one clipped off the end is the way out.
TIGHT = 40


#: How many results one search asks for. One request either way — paging costs
#: double, because ``ytsearch40`` re-fetches the first twenty to reach the rest,
#: so a better query is always cheaper than a second page.
SEARCH_RESULTS = 20

#: ``--flat-playlist`` answers a search in one round trip, but YouTube's flat
#: entries carry no upload date at all. This asks yt-dlp to parse the relative
#: string the search page does show ("4 months ago") into a timestamp. It is
#: approximate by construction, which is why :func:`age` always marks it.
APPROX_DATE_ARGS = ("--extractor-args", "youtubetab:approximate_date")

#: The subscription feed, as yt-dlp addresses it. A signed-in page: without
#: cookies YouTube answers it with nothing at all, which is why
#: :func:`cookie_state` is asked *before* a request is spent rather than after
#: one comes back empty.
SUBS_URL = "https://www.youtube.com/feed/subscriptions"

#: How much of the feed one look asks for. YouTube serves the feed a page at a
#: time and yt-dlp will follow every continuation it is offered, so this is a
#: bound and not a preference — see :func:`subs_argv`.
SUBS_RESULTS = 30

#: What a deeper look adds to that bound, and where it stops. The cap is not a
#: technical limit: it is there because every press costs more than the last
#: (see :func:`feed_cost`) and a list you can keep extending with one thumb is
#: a list somebody extends five times without meaning to.
SUBS_PAGE = 30
SUBS_MAX = 150

#: Roughly what one page of the feed costs on the wire. An estimate by analogy
#: with the search page and NOT measured on the vessel's link — the figure to
#: correct from ``docs/data-ledger.md`` when somebody does measure it. It is
#: printed rather than kept quiet because a key whose price is unknown to the
#: person pressing it is the one thing this whole tool exists to avoid.
SUBS_PAGE_MB = 0.2

#: A fetch of *count* videos is given this long. It scales because a timeout
#: that fires part way through has spent the bytes and kept none of them —
#: the worst outcome available here, and worse the deeper the ask.
SUBS_TIMEOUT_BASE = 120
SUBS_TIMEOUT_PER = 4

#: What the feed is called in the caches the session keeps, where a search is
#: keyed on the words that produced it. Not a query anybody can type, so it
#: cannot collide with one.
SUBS_KEY = ":subs"

#: The Watch Later playlist, the other signed-in list. The playlist URL and not
#: ``:ytwatchlater``, so the argv reads the same shape as the feed's — and it
#: is the same kind of page to YouTube: without the cookie there is no list.
WL_URL = "https://www.youtube.com/playlist?list=WL"
WL_KEY = ":wl"

#: Where the docs tell you to put the cookie jar, and the config that points at
#: it. Named here so that the screen saying the feed cannot be read sends
#: somebody to the same two files ``docs/ytq.md`` does; a screen that named a
#: different one of yt-dlp's several config paths would be sending them to a
#: file that works and that nobody else has ever edited.
COOKIE_SUGGESTION = "~/.config/yt-dlp/cookies.txt"
CONFIG_SUGGESTION = "~/.config/yt-dlp/config"

#: The free grant is ~763 MiB a day and the runner keeps 100 MB of it back, so
#: this is roughly what one night can spend. Used only to colour the size
#: column — green fits comfortably in a night, amber is most of one, red will
#: take several. That is the fact the list does not otherwise state, and it is
#: the one that decides whether a choice is a good idea on this connection.
NIGHT_BYTES = 650 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


class ProbeError(RuntimeError):
    """yt-dlp could not describe the URL."""


def ask(argv: list[str], timeout: int) -> dict:
    """Run a metadata-only yt-dlp and hand back the object it printed.

    One door, because the three things that ask — a probe, a search and the
    subscription feed — differ only in the argv they hand in, and every one of
    them fails in exactly the same four ways. Written out three times it was
    three places for "yt-dlp is not installed" to drift apart in.
    """
    # Inside one of the screen's fetches, the child goes to the fetch so Stop
    # can kill it; anywhere else (the printing paths, the tests) it is the
    # plain run it always was. Looked up rather than imported: nothing that
    # prints a listing needs the terminal module loaded. By its package name:
    # under the bare ``tui`` it was never found, so Stop killed nothing and
    # yt-dlp went on spending until it answered.
    tui = sys.modules.get("nibbles.tui")
    try:
        if tui is not None and tui.current_job() is not None:
            done = tui.run_child(argv, timeout)
        else:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ProbeError("yt-dlp is not installed (pip install yt-dlp)")
    except subprocess.TimeoutExpired:
        raise ProbeError(f"yt-dlp did not answer within {timeout}s")
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        raise ProbeError(tail[-1] if tail else f"yt-dlp exited {done.returncode}")
    try:
        info = json.loads(done.stdout)
    except ValueError:
        raise ProbeError("yt-dlp returned something that is not JSON")
    if not isinstance(info, dict):
        raise ProbeError("yt-dlp returned something that is not a metadata object")
    return info


def probe_argv(url: str) -> list[str]:
    """The command a probe runs, kept separate so it can be checked.

    ``-J`` downloads no media, but on its own it is not one request: handed a
    playlist, a channel or a page of embeds it extracts *every entry in full*
    — a watch page and player calls each, following every continuation — and
    only then answers with a list this refuses. ``--no-playlist`` does not
    stop that; it only settles a ``watch?v=…&list=…`` link in the video's
    favour. ``--flat-playlist`` and ``--playlist-end 1`` are the same whole
    cost argument :func:`search_argv` and :func:`feed_argv` make: a list
    answers from its first page, and is refused there. A video at the top is
    still extracted whole — yt-dlp flattens only what sits inside a list.
    """
    return [
        *ytdl_item.ytdl_argv(),
        "-J",
        "--no-playlist",
        "--flat-playlist",
        "--playlist-end",
        "1",
        "--no-colors",
        "--no-warnings",
        url,
    ]


def probe(url: str, timeout: int = 180) -> dict:
    """Metadata only, for one video: anything holding several is refused.

    ``multi_video`` (one page, several parts) is refused beside ``playlist``:
    neither has formats of its own to pick from.
    """
    info = ask(probe_argv(url), timeout)
    if info.get("_type") in ("playlist", "multi_video"):
        raise ProbeError("that URL is a playlist; queue one video at a time")
    return cleaned(info)


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #


class Result:
    """One search hit: enough to choose on, and the URL to probe if chosen."""

    def __init__(
        self,
        title: str,
        channel: str,
        url: str,
        duration: int | None,
        timestamp: int | None,
        live: bool = False,
        key: str = "",
        views: int | None = None,
    ) -> None:
        self.title = title
        self.channel = channel
        self.url = url
        self.duration = duration
        self.timestamp = timestamp
        self.live = live
        self.views = views
        #: What :func:`find_duplicate` recognises this by, so the list can mark
        #: what is already queued *before* anything is spent probing it.
        self.key = key


def looks_like_url(text: str) -> bool:
    """Whether the entry field holds a link rather than words to search for.

    One field for both, because on a phone the alternative is a mode key to
    remember. Deliberately generous about what counts as a link and strict
    about nothing: the cost of guessing wrong is one wasted extraction either
    way, and yt-dlp gives a clearer error about a bad URL than a search for it
    would.
    """
    text = text.strip()
    if not text or " " in text:
        return False
    return "://" in text or text.startswith(("www.", "youtu.be/", "youtube.com/"))


#: The prefix that says "this is a link yt-dlp takes, whatever it looks like":
#: ``nibbles <x>`` hands the app a bare video id this way, which the field on
#: its own would search for. The same shape as :data:`SUBS_KEY`.
LINK_KEY = ":link:"

#: yt-dlp's own YouTube search keys: ``ytsearch:``, ``ytsearch5:``,
#: ``ytsearchdate:``, ``ytsearchall:``. The query after it is the app's search.
_YT_SEARCH = re.compile(r"^ytsearch(?:date)?(?:\d+|all)?:(.+)$", re.S)

#: yt-dlp's fixup for a link typed without its scheme: ``host.tld/path``.
_NO_SCHEME = re.compile(r"^[^\s/:]+\.[^\s/]+/")

#: Asked of yt-dlp's own extractors, in the interpreter that has them: does one
#: other than the catch-all take this? Offline — it compiles patterns, nothing
#: more. Exit 0 for yes, 1 for no; anything else is "could not ask".
_SUITABLE = (
    "import sys\n"
    "from yt_dlp.extractor import gen_extractor_classes\n"
    "text = sys.argv[1]\n"
    "sys.exit(0 if any(ie.suitable(text) for ie in gen_extractor_classes()\n"
    "                  if ie.ie_key() != 'Generic') else 1)\n"
)


def yt_dlp_takes(text: str, timeout: int = 30) -> bool | None:
    """Whether one of yt-dlp's extractors (not the generic one) takes *text*,
    asked of yt-dlp itself; ``None`` when there is no yt-dlp to ask.

    In this interpreter if yt-dlp is a module here, else in the one its
    command names on its first line. A single-file release names
    ``/usr/bin/env python3`` and is itself the archive the module is in, so it
    goes on ``PYTHONPATH`` too: for a console script that is a text file and
    Python passes it over.
    """
    if importlib.util.find_spec("yt_dlp") is not None:
        argv, env = [sys.executable], None
    else:
        binary = shutil.which("yt-dlp")
        if not binary:
            return None
        python = shebang_of(binary)
        if not python:
            return None
        if Path(python).name == "env":
            python = shutil.which("python3") or sys.executable
        argv = [python]
        env = {**os.environ, "PYTHONPATH": binary}
    try:
        done = subprocess.run([*argv, "-c", _SUITABLE, text], capture_output=True,
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


#: A word to the eye: letters, lower case after the first, hyphen-joined.
#: YouTube's extractor takes any eleven of ``[A-Za-z0-9_-]`` as a video id —
#: ``programming``, ``documentary`` — and a probe of one spent data on a
#: word, where a mistyped word is refused for nothing. A real id is random,
#: and shaped like this about once in ten thousand; that one still opens as
#: ``youtu.be/<id>``.
_WORDLIKE = re.compile(r"[A-Za-z][a-z]*(?:-[a-z]+)*")


def read_input(text: str) -> tuple[str, str] | None:
    """What yt-dlp would make of *text* on its command line, as ``nibbles
    <text>`` takes it: ``("url", link)``, ``("search", words)``, or ``None``
    for something it would not take either.

    A link (with or without its scheme, which is added the way yt-dlp adds
    it), ``ytsearch…:words`` (the app's own search), or anything one of
    yt-dlp's extractors takes — a bare video id, for one — asked of yt-dlp,
    unless it is shaped like a word (:data:`_WORDLIKE`).
    """
    text = text.strip()
    if not text:
        return None
    found = _YT_SEARCH.match(text)
    if found:
        words = found.group(1).strip()
        return ("search", words) if words else None
    if looks_like_url(text):
        return "url", text
    if _NO_SCHEME.match(text) and " " not in text:
        return "url", f"https://{text}"
    if " " not in text and not _WORDLIKE.fullmatch(text) and yt_dlp_takes(text):
        return "url", text
    return None


def search_argv(query: str, count: int = SEARCH_RESULTS) -> list[str]:
    """The command a search runs, kept separate so it can be checked.

    ``--flat-playlist`` is the whole cost argument: it answers from the search
    page alone, in one request, instead of extracting each result in turn — the
    difference between ~0.1 MB and twenty full extractions on a metered radio.
    A test must pin this, because the shape that is expensive looks almost
    identical to the shape that is not.

    Nothing here disables the user config: ``~/.config/yt-dlp/config`` carries
    the JS runtime and the cookies without which YouTube answers with a
    fraction of what it has, or refuses.
    """
    return [
        *ytdl_item.ytdl_argv(),
        f"ytsearch{count}:{query}",
        "--flat-playlist",
        "-J",
        "--no-colors",
        "--no-warnings",
        *APPROX_DATE_ARGS,
    ]


#: The two format characters :func:`one_line` keeps: the zero-width non-joiner
#: and joiner, which Persian and Indic words and emoji sequences are spelled
#: with, and which bewitch and Termux both count as no columns at all.
JOINERS = "\u200c\u200d"


def one_line(text: object) -> str:
    """Somebody else's words — a title, a channel — as one line that a screen
    can draw and an item can hold.

    The one cleaning for text from outside, done where it comes in
    (:func:`entries`, :func:`cleaned`) so that the row, the sheet, the item
    and the file name are all made from the same string, and done again by the
    two that must hold whoever calls them (:func:`render`, :func:`title_name`).
    yt-dlp hands a title on as the site gave it, and the sites promise no
    single line: TikTok's title is the caption with its line breaks, and a
    page's ``og:title`` decodes ``&#10;`` and ``&#27;`` to the real thing.

    Every space and every line break becomes one space: a break written into
    an item's ``# DESC:`` comment ends the comment, and what follows it is
    Python, run at the firing. Every other control goes — an ``ESC`` that
    reaches the terminal starts a sequence Termux acts on (the clipboard,
    mouse reporting off) — and so does every format character but
    :data:`JOINERS`: a soft hyphen, a byte-order mark or a bidi isolate is no
    columns to bewitch and one to Termux, and a row one column wider than the
    screen wraps its last cell onto the next and leaves it there. A lone
    surrogate goes too, because it cannot be written as UTF-8 at all.
    """
    kept = []
    for ch in "" if text is None else str(text):
        if ch.isspace():
            kept.append(" ")
        elif ch in JOINERS or unicodedata.category(ch) not in ("Cc", "Cf", "Cs"):
            kept.append(ch)
    return " ".join("".join(kept).split())


#: The fields of a video's metadata that are somebody else's words and are
#: drawn or written: the title, and the byline's two spellings of who made it.
OUTSIDE_WORDS = ("title", "channel", "uploader")


def cleaned(info: dict) -> dict:
    """*info*, with :data:`OUTSIDE_WORDS` put through :func:`one_line`.

    Asked where metadata comes in — the probe and a saved dump — so that every
    screen and the item read the cleaned words and none has to remember to.
    """
    out = dict(info)
    for key in OUTSIDE_WORDS:
        if isinstance(out.get(key), str):
            out[key] = one_line(out[key])
    return out


def entries(info: dict) -> list[Result]:
    """The videos in a search answer, tolerating every field being absent.

    A search can also come back holding channels and playlists, and neither has
    a format to pick from — they are dropped here rather than at the moment
    someone selects one and gets an error about a playlist.

    Titles and channels go through :func:`one_line` here, where they come in.
    """
    out: list[Result] = []
    for raw in info.get("entries") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("_type") in ("playlist", "channel"):
            continue
        video_id = raw.get("id")
        url = raw.get("url") or raw.get("webpage_url")
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            continue
        duration = raw.get("duration")
        timestamp = raw.get("timestamp") or raw.get("release_timestamp")
        view_count = raw.get("view_count")
        out.append(
            Result(
                title=one_line(raw.get("title")) or "(untitled)",
                channel=one_line(raw.get("channel") or raw.get("uploader")),
                url=str(url),
                duration=int(duration) if isinstance(duration, (int, float)) else None,
                timestamp=int(timestamp)
                if isinstance(timestamp, (int, float))
                else None,
                live=raw.get("live_status") in ("is_live", "is_upcoming"),
                key=source_key(raw),
                # bool is an int to isinstance, and True is not a view count.
                views=int(view_count)
                if isinstance(view_count, (int, float))
                and not isinstance(view_count, bool)
                and math.isfinite(view_count)
                else None,
            )
        )
    return out


def search(query: str, count: int = SEARCH_RESULTS, timeout: int = 120) -> list[Result]:
    """Ask yt-dlp for *count* results. One request, no media, no per-video work."""
    return entries(ask(search_argv(query, count), timeout))


# --------------------------------------------------------------------------- #
# The subscription feed
# --------------------------------------------------------------------------- #
#
# The feed is the one screen here that cannot work on its own. A search and a
# probe are anonymous requests; the feed is a signed-in page, and what signs it
# in is the cookie jar the yt-dlp config already names for the bot check
# (docs/ytq.md, "Sign in to confirm you're not a bot"). So this half is mostly
# about that jar: finding out whether there is one *before* a request is spent,
# and never letting a logged-out answer be read as good news.


def tilde(path: Path | str) -> str:
    """A path with ``$HOME`` written as ``~`` — shorter, and how it is typed."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


def config_paths() -> list[Path]:
    """The files yt-dlp reads its user config from, in its own order.

    Read rather than assumed, because the ``--cookies`` line is somebody's
    hand edit and the whole point of looking is to name the file it is missing
    from. All seven of yt-dlp's user candidates (``get_user_config_dirs``,
    each directory's ``yt-dlp.conf``, ``config`` and ``config.txt``, and the
    home one's ``yt-dlp.conf.txt``), because yt-dlp reads only the first of
    them it can open (:func:`user_config`), and a list missing one is a list
    that gets wrong which file that is. Deliberately not the portable,
    ``--paths home`` and system configs, read *beside* this one — those are
    not shapes this phone has, and a path listed here that nobody uses would
    be a path named in an error message that sends somebody to the wrong file.
    """
    home = Path.home()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    return [
        xdg / "yt-dlp.conf",
        xdg / "yt-dlp" / "config",
        xdg / "yt-dlp" / "config.txt",
        home / "yt-dlp.conf",
        home / "yt-dlp.conf.txt",
        home / ".yt-dlp" / "config",
        home / ".yt-dlp" / "config.txt",
    ]


def user_config(paths: list[Path] | None = None) -> Path | None:
    """The one user config yt-dlp reads: the first in its order that opens.

    yt-dlp takes the first candidate it can open and stops there (an empty
    file counts, and hides every file after it), so a ``--cookies`` line in
    any later one is never read. Asked the way yt-dlp asks — an ``open`` —
    rather than ``is_file``, so a directory or an unreadable file is passed
    over here exactly as it is there.
    """
    for path in config_paths() if paths is None else paths:
        try:
            with open(path, "rb"):
                return path
        except OSError:
            continue
    return None


#: The two ways a config can say where the signed-in session comes from. Both
#: count: ``--cookies-from-browser`` is not a file this can stat, but it is a
#: declaration, and a tool that refused it would be refusing a working setup.
COOKIE_FLAGS = ("--cookies", "--cookies-from-browser")


def declared_cookies(paths: list[Path] | None = None) -> tuple[str, str, Path] | None:
    """``(flag, value, the config that said so)`` for the first one found in
    the one config yt-dlp reads (:func:`user_config`).

    Only that one: a ``--cookies`` line in a file yt-dlp never opens is not a
    session, and calling it one spends a feed read to be told to sign in.
    Parsed with :mod:`shlex` per line the way yt-dlp parses these files, so a
    quoted path with a space in it reads the same here as it does there, and a
    ``#`` comment holding the word ``--cookies`` is a comment in both. Reading
    it any more loosely would mean this screen and yt-dlp disagreeing about
    whether cookies are configured, which is a worse answer than not looking.
    """
    path = user_config(paths)
    found = None if path is None else _cookies_in(path)
    return None if found is None else (*found, path)


def _cookies_in(path: Path) -> tuple[str, str] | None:
    """``(flag, value)`` for the first cookie line in the config at *path*."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            flag, _, inline = token.partition("=")
            if flag not in COOKIE_FLAGS:
                continue
            value = inline or (
                tokens[index + 1] if index + 1 < len(tokens) else ""
            )
            if value:
                return flag, value
    return None


def written(mtime: float, now: float | None = None) -> str:
    """How long ago a file was last written, in words.

    Cookies expire, and every symptom of that looks like something else — a
    short feed, an empty one, a video that lists one 320p format. This is the
    fact that turns "the feed is empty" into "the cookies are three weeks old",
    which is the sentence somebody can act on.
    """
    days = int(max(0.0, (time.time() if now is None else now) - mtime) // 86400)
    if days < 1:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def cookie_state(paths: list[Path] | None = None) -> tuple[str, str]:
    """``(state, what to say about it)``: can the feed be asked for at all?

    ``file`` and ``browser`` are a go; ``missing`` and ``none`` are not. Asked
    *before* the request, on the same rule as :func:`already_queued`: a feed
    request with no session behind it is not a small failure, it is a whole
    page of YouTube bought in order to be told to sign in — and then answered
    with an empty list rather than an error, so the money buys no explanation
    either.

    The detail is a phrase and not a sentence, because both callers put it in
    the middle of one.
    """
    declared = declared_cookies(paths)
    if declared is None:
        candidates = config_paths() if paths is None else paths
        read = user_config(candidates)
        if read is not None:
            detail = f"no --cookies line in {tilde(read)}"
            # The setup that looks right and is not: the line is there, in a
            # file yt-dlp never opens because this one comes first.
            later = candidates[candidates.index(read) + 1:]
            hidden = next((path for path in later if _cookies_in(path)), None)
            if hidden is not None:
                detail += f", the one yt-dlp reads; {tilde(hidden)} has one it never sees"
            return "none", detail
        # Named from the constant rather than by indexing the list: the list
        # is where yt-dlp looks and this is where the docs say to write, and
        # only one of those is a sentence to put in front of somebody.
        return "none", f"there is no yt-dlp config at {CONFIG_SUGGESTION}"
    flag, value, config = declared
    if flag == "--cookies-from-browser":
        return "browser", f"--cookies-from-browser {value}, from {tilde(config)}"
    # Expanded the way yt-dlp's own ``expand_path`` does — the user, then the
    # variables — so ``$HOME/…`` names the jar here that it names there.
    jar = Path(os.path.expandvars(os.path.expanduser(value)))
    try:
        stat = jar.stat()
    except OSError:
        return "missing", f"{tilde(jar)} is named by {tilde(config)} but is not there"
    if stat.st_size == 0:
        return "missing", f"{tilde(jar)} is empty"
    return "file", f"{tilde(jar)}, written {written(stat.st_mtime)}"


#: Why the two signed-in lists alone need anything. Its own entry rather than part of
#: :func:`cookie_fix`, because the two screens that do not need it each say it
#: better in their own words — the refusal has yt-dlp's line and the empty feed
#: has a paragraph about what an empty feed is — and a notice has to fit a
#: phone whole, which is checked.
COOKIE_WHY = "subs and watch later are signed-in pages — no cookies, no answer."


def cookie_fix(detail: str) -> list[str]:
    """What was found, and how to renew it.

    One spelling, appended to every screen that cannot read the feed — a
    refusal, an absent jar and an empty answer are three symptoms with one
    remedy, and three wordings of it would be three chances for two of them to
    go stale.

    Short because it has to fit a phone whole: a fix the screen had to
    truncate is not a fix. The mode and the "never in the repo" stay in it at
    that price — the jar holds live google session tokens, and yt-dlp rewrites
    it in place as they refresh.
    """
    return [
        detail,
        f"export cookies.txt from the browser, netscape format, mode 600 and "
        f"never in the repo: {COOKIE_SUGGESTION}, named by --cookies in "
        f"{CONFIG_SUGGESTION}.",
        "docs: ~/nibbles/docs/ytq.md",
    ]


def cookie_advice(state: str, detail: str) -> list[str]:
    """Why the feed cannot be read, and the one thing that fixes it.

    A screen rather than a line, and the fix written on it, for the reason
    :func:`duplicate_screen` gives: this is a dead end, and a dead end that
    does not say the way out is one somebody concludes is a broken tool.
    """
    return [
        {
            "none": "no cookies are configured",
            "missing": "the cookie jar is not there",
        }.get(state, "the subscription feed cannot be read"),
        COOKIE_WHY,
        *cookie_fix(detail),
    ]


def empty_feed_advice(detail: str) -> list[str]:
    """What an empty feed means, which is never "nothing new".

    YouTube answers a logged-out feed with an empty tab rather than with an
    error, so the honest-looking reading of that answer — you are up to date —
    is the one reading it cannot have. Saying it would hide the only fix there
    is behind a screen that looks like good news, on a tool somebody opens
    once a day.
    """
    return [
        "the feed came back empty",
        "a signed-out session, not an empty subscription list: youtube "
        "answers a logged-out feed with no entries rather than an error, so "
        "this is what expired cookies look like.",
        *cookie_fix(detail),
    ]


def empty_later_advice(detail: str) -> list[str]:
    """What an empty Watch Later means, which is one of two things.

    Unlike the feed, an empty Watch Later is a list somebody can really have —
    everything on it watched and cleared. But a signed-out session reads the
    same way, so the screen says both and how old the jar is rather than
    picking the comfortable one.
    """
    return [
        "watch later came back empty",
        "either nothing is saved there, or the cookies have expired — a "
        "signed-out session reads as an empty list too.",
        *cookie_fix(detail),
    ]


def subs_argv(count: int = SUBS_RESULTS) -> list[str]:
    """The command one look at the feed runs — :func:`feed_argv` for the feed."""
    return feed_argv(SUBS_URL, count)


def later_argv(count: int = SUBS_RESULTS) -> list[str]:
    """The command one look at Watch Later runs, on the feed's same bound.

    A playlist is served a hundred entries a page rather than the feed's
    thirty or so, and a Watch Later that has been a to-do list for years is
    thousands long — so ``--playlist-end`` is the same whole cost argument
    here as there.
    """
    return feed_argv(WL_URL, count)


def feed_argv(url: str, count: int = SUBS_RESULTS) -> list[str]:
    """The command one look at a signed-in list runs, kept separate so it can be checked.

    ``--playlist-end`` is the whole cost argument, and it is the same shape of
    trap :func:`search_argv` documents: without it this works perfectly and
    follows every continuation YouTube will serve, which for a few years of
    subscriptions is hundreds of pages on a metered radio. Bounded, yt-dlp
    stops pulling once it has *count*, so one look is one request.

    ``--flat-playlist`` is the other half: the feed is a list of videos and
    extracting each one is what the format screen is for, later, on the one
    that gets picked.

    Nothing here disables the user config, and here that is not a nicety — the
    ``--cookies`` line in it is the only reason this page answers at all.
    """
    return [
        *ytdl_item.ytdl_argv(),
        url,
        "--flat-playlist",
        "--playlist-end",
        str(count),
        "-J",
        "--no-colors",
        "--no-warnings",
        *APPROX_DATE_ARGS,
    ]


def subscriptions(count: int = SUBS_RESULTS, timeout: int | None = None) -> list[Result]:
    """The newest *count* videos from the subscription feed, newest first.

    Longer than a search's timeout because the tab page is bigger and the
    connection is the vessel's, not a datacentre's — and longer again the more
    is asked for, because giving up part way through has spent every byte
    walked so far and kept nothing.
    """
    return read_feed(SUBS, count, timeout)


def read_feed(feed: Feed, count: int = SUBS_RESULTS, timeout: int | None = None) -> list[Result]:
    """The first *count* videos of a signed-in list, in the order YouTube keeps.

    Newest first for the feed; for Watch Later, whatever order the playlist is
    sorted in on YouTube — this does not re-sort it, because that order is
    somebody's own decision about what to watch next.
    """
    if timeout is None:
        timeout = SUBS_TIMEOUT_BASE + SUBS_TIMEOUT_PER * count
    return entries(ask(feed_argv(feed.url, count), timeout))


def feed_cost(count: int) -> str:
    """Roughly what reading *count* videos off the feed costs, in words.

    The **total**, never the increment, and that is the whole point of the
    function. YouTube's continuations are sequential: there is no asking for
    videos 31 to 60 without walking 1 to 30 to reach them, so going deeper
    re-buys everything already on screen. A key labelled "+30" while spending
    the lot is a bill nobody agreed to.

    Marked ``~`` for the same reason every size on the format list is: the
    per-page figure is an estimate, not a measurement.
    """
    return f"~{count / SUBS_RESULTS * SUBS_PAGE_MB:.1f} MB"


def feed_meta(
    count: int,
    when: str,
    more: int | None,
    at_cap: bool,
    width: int,
    whole: str = "the whole feed",
) -> str:
    """The feed's second line: how much is on it, how old, and what more costs.

    Pure and width-aware rather than composed at the point of drawing, because
    the thing it carries is a **price** and a price clipped off the end of a
    line is worse than no price at all — which is exactly what happened the
    first time this was written inline: ``m 60 for ~0.4 …`` on a 40-column
    phone, the figure lost and the key still offered.

    It replaces "~ dates are approximate", which every row already says for
    itself with a ``~`` beside its age. This does not say itself anywhere.
    """
    if more:
        # No spaces inside the figure at the floor: this line is read, not
        # parsed, and the columns are better spent on the number than on the
        # gap in front of MB.
        deeper = (
            f"↓ {more} for {feed_cost(more)}"
            if width >= WIDE
            else f"↓ {more} {feed_cost(more).replace(' ', '')}"
        )
    else:
        deeper = "at the cap" if at_cap else whole
    parts = [f"{count} videos"]
    # The age is the first thing to go, and it is the right one: it is a
    # comfort, where the other two are the answer and the price.
    if when and width >= TIGHT:
        parts.append(f"read {when}" if width >= WIDE else when)
    parts.append(deeper)
    return ("  ·  " if width >= WIDE else " · ").join(parts)


def bumped_place(place: tuple[int, int], count: int) -> tuple[int, int]:
    """Where a deeper look leaves the cursor once the longer listing lands.

    ↓ at the last row is what asked for it, and that key's motion completes
    when the fetch does: one row on, onto the first video that just arrived.
    Asked from anywhere else the place stays put. No key asks from mid-list
    any more — the `m` alias that did was removed — but a listing that came
    back shorter than the row that asked for it is the same shape and lands
    here. Overshoot is :func:`viewport`'s to clamp, so a feed that came back
    no longer than it was leaves the cursor on the last row it had.
    """
    row, top = place
    if count and row == count - 1:
        return (row + 1, top)
    return place


def next_page(got: int, asked: int) -> tuple[int | None, bool]:
    """``(the total a deeper look would ask for, whether the cap stopped it)``.

    ``(None, False)`` is the end of the feed: YouTube handed back fewer than
    it was asked for, so there is nothing further back to reach and asking
    again would buy the same bytes to learn the same thing. That is the case
    worth getting right — a ``↓`` that stays live at the bottom of the feed
    spends real quota on nothing, every press, and looks exactly like one that
    is working.

    ``(None, True)`` is the cap, which is a different sentence: there IS more
    and this will not spend it. The screen says which of the two it is.
    """
    if got < asked:
        return None, False
    if asked >= SUBS_MAX:
        return None, True
    return min(SUBS_MAX, asked + SUBS_PAGE), False


#: The words the one entry field takes for the feed. ``:ytsubs`` is yt-dlp's
#: own spelling and is here so that what somebody already knows works.
FEED_WORDS = ("subs", ":subs", "subscriptions", ":subscriptions", ":ytsubs")

#: And for Watch Later, on the same rule — ``:ytwatchlater`` is yt-dlp's.
#: Not ``later`` alone: that one is a word somebody might search for.
WL_WORDS = ("wl", ":wl", "watch later", "watchlater", ":watchlater", ":ytwatchlater")

#: The playlist page itself, and only it. A *video* played out of Watch Later
#: carries ``&list=WL`` too, and pasting one of those is asking for that video.
WL_PAGE = re.compile(r"/playlist\?(?:[^#]*&)?list=wl(?:[&#]|$)")


class Feed:
    """One signed-in list: where it is, what it is called, what empty means.

    Two of them, and everything that differs between them is here, so the
    screen, the caches and ``--list`` each have one road for both.
    """

    def __init__(
        self, key: str, url: str, banner: str, name: str, whole: str, empty
    ) -> None:
        #: What the listing is cached under, where a search is keyed on words.
        self.key = key
        self.url = url
        #: The results screen's banner.
        self.banner = banner
        #: The noun in the sentences said about it — the spinner, the failure.
        self.name = name
        #: What the meta line says once there is nothing further back.
        self.whole = whole
        #: ``detail -> lines``: what an empty answer means for this list.
        self.empty = empty


SUBS = Feed(
    SUBS_KEY, SUBS_URL, " subscriptions ", "the subscription feed",
    "the whole feed", empty_feed_advice,
)
WATCH_LATER = Feed(
    WL_KEY, WL_URL, " watch later ", "watch later",
    "the whole list", empty_later_advice,
)
FEEDS = {feed.key: feed for feed in (SUBS, WATCH_LATER)}


def which_feed(text: str) -> Feed | None:
    """Which signed-in list the entry field is asking for, if either.

    Asked *before* :func:`looks_like_url` for the reason
    :func:`looks_like_feed` gives, which is true of both lists' URLs.
    """
    text = text.strip().lower()
    if text in FEED_WORDS or "/feed/subscriptions" in text:
        return SUBS
    if text in WL_WORDS or WL_PAGE.search(text):
        return WATCH_LATER
    return None


def looks_like_feed(text: str) -> bool:
    """Whether the entry field is being asked for a signed-in list.

    A third answer out of the same box, on :func:`looks_like_url`'s rule: the
    alternative on a phone is a mode key to remember, and the field is already
    telling two things apart by looking. ``subs`` is read as the feed rather
    than as words to search for, which is a guess — and the cheap one, since
    being wrong costs one press of ``/`` and being wrong the other way costs a
    search nobody wanted.

    Asked *before* :func:`looks_like_url`, because the feed's own URL is a URL
    too and probing it gets the playlist refusal instead of the feed.
    """
    return which_feed(text) is not None


def freshness(fetched: float | None, now: float | None = None) -> str:
    """How old the listing on screen is, or ``""`` when it was never fetched.

    Said for the feed and not for a search. A search is a question you re-ask
    by retyping it; a feed is a thing that changes under you, and it is cached
    for the session precisely so that backing out of a video costs nothing —
    which means the screen has to say how old what it is showing is, or the
    cache is just a quiet lie about the time.
    """
    if not fetched:
        return ""
    seconds = max(0.0, (time.time() if now is None else now) - fetched)
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)}m ago"
    return f"{int(seconds // 3600)}h ago"


def age(timestamp: int | None, now: float | None = None) -> str:
    """How long ago, roughly: ``<1d``, ``~3w``, ``~4mo``, ``~5y``, or ``?``.

    Relative rather than a date, and marked, because that is the precision we
    actually have. The timestamp comes from yt-dlp parsing YouTube's own
    rounded string ("4 months ago"), so ``2026-04-13`` would be a claim the
    number cannot support — the same reason the size column marks an estimate
    with ``~`` instead of printing it plain.

    ``?`` is a fact too: a search answer with no date must not be given one.
    """
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return "?"
    days = int(max(0.0, (time.time() if now is None else now) - timestamp) // 86400)
    if days < 1:
        return "<1d"
    if days < 14:
        return f"~{days}d"
    if days < 56:
        return f"~{days // 7}w"
    if days < 730:
        return f"~{days // 30}mo"
    return f"~{days // 365}y"


def clock(seconds: int | None, live: bool = False) -> str:
    """A length in the one spelling this repo uses, or what it is instead."""
    if live:
        return "live"
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return "?"
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


#: The steps :func:`views` names, largest first.
VIEW_UNITS = ((10**9, "B"), (10**6, "M"), (10**3, "K"))


def views(count: int | None) -> str:
    """A view count the way YouTube shortens it: ``842``, ``1.2K``, ``34M``.

    One decimal below ten of a unit and none from there up, and truncated
    rather than rounded, as YouTube does — so ``999_999`` is ``999K`` and
    never ``1000K``, and no count is ever shown as more than it is.

    Empty rather than ``?`` when there is no count: the feed and the search
    page leave it out now and then, and a row of question marks would be
    shouting about the fact the list cares least about.
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return ""
    for size, unit in VIEW_UNITS:
        if count >= size:
            whole, rest = divmod(count, size)
            if whole < 10:
                return f"{whole}.{rest * 10 // size}{unit}"
            return f"{whole}{unit}"
    return str(count)


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #


class Choice:
    """One selectable download: a format string and what it will cost."""

    def __init__(
        self,
        kind: str,
        fmt: str,
        size: int,
        exact: bool,
        ext: str,
        label: str,
        detail: str,
        merge_ext: str | None = None,
        codecs: str = "",
    ) -> None:
        self.kind = kind
        self.fmt = fmt
        self.size = size
        self.exact = exact
        self.ext = ext
        self.label = label
        self.detail = detail
        self.merge_ext = merge_ext
        #: The codec strings exactly as yt-dlp reported them ("avc1.640028",
        #: "av01.0.08M.08"), untruncated. The list columns carry only the
        #: family (:func:`_codec`), because a column has a width budget; this
        #: is for the one line that shows the selected row in full.
        self.codecs = codecs

    @property
    def expect_bytes(self) -> int:
        """The cap to declare: the measurement, plus a stated margin."""
        factor = OVERHEAD_EXACT if self.exact else OVERHEAD_APPROX
        return int(math.ceil(self.size * factor)) + OVERHEAD_FIXED


#: Extractors this can say anything useful about. The claim :func:`withheld`
#: makes is specific to YouTube — it always has adaptive streams, so their
#: total absence is evidence — and it is simply false of the many sites that
#: legitimately serve one progressive file. Named rather than assumed, so a
#: plain .mp4 URL is never accused of a bot check.
ADAPTIVE_ALWAYS = ("youtube",)


def withheld(info: dict) -> bool:
    """Whether YouTube answered with a fraction of the formats it really has.

    The signature of a failed bot check: with no PO token the adaptive streams
    are never sent, and what comes back is the legacy progressive format and
    the storyboards. A YouTube video always has adaptive streams, so none at
    all is not a video that only exists in 360p — it is an extraction that was
    refused politely.

    Read off the raw formats and deliberately **not** off :func:`choices`,
    which drops what it cannot size. Those are the two ways to end up looking
    at a single 360p row and they have completely different fixes, so the one
    thing this must not do is conflate them: `choices` reports the second as
    its ``unsized`` count and this reports the first.
    """
    who = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    if not any(name in who for name in ADAPTIVE_ALWAYS):
        return False
    adaptive = playable = 0
    for fmt in info.get("formats") or []:
        vcodec, acodec = fmt.get("vcodec"), fmt.get("acodec")
        if vcodec == "none" and acodec == "none":
            continue  # storyboards, which arrive either way
        playable += 1
        # Exactly one side absent is an adaptive stream; neither absent is the
        # progressive one that survives a refusal.
        if (vcodec == "none") != (acodec == "none"):
            adaptive += 1
    return playable > 0 and adaptive == 0


#: A ``uv tool`` venv carries this at its root; an ordinary venv does not.
#: Chosen over a path substring because it is uv's own bookkeeping rather than
#: a guess about where uv keeps things — ``UV_TOOL_DIR`` moves that — and
#: because it *lists the requirements*, so the ``--with`` packages a reinstall
#: has to re-assert are read off the machine instead of being remembered by
#: whoever last wrote the upgrade line.
#:
#: Deliberately not ``yt-dlp --version``, whose banner says ``(pip)`` under a
#: uv tool as well (measured 2026-08-28): the one thing in that output that
#: looks like an answer to this question and is not.
UV_RECEIPT = "uv-receipt.toml"


def uv_receipt(python: str) -> Path | None:
    """The receipt of the uv tool venv *python* belongs to, if it is one."""
    if not python:
        return None
    receipt = Path(python).parent.parent / UV_RECEIPT
    return receipt if receipt.is_file() else None


def uv_requirements(receipt: Path) -> list[dict]:
    """The requirements a uv tool was installed with, as uv recorded them —
    ``{"name": "yt-dlp", "extras": ["default"]}``, ``{"name": "six",
    "specifier": ">=1.10"}`` — in uv's own order.

    Read rather than remembered, because the failure this exists to prevent is
    a reinstall that silently drops a ``--with`` package — and a hard-coded
    list is that same failure with extra steps. Read as TOML, never by
    scanning for brackets: uv writes ``extras = ["default"]`` *inside* an
    entry, and the ``]`` that closes it once ended the list there, so a
    ``yt-dlp[default]`` install lost every ``--with`` after it and its own
    extras too — which is how following the line uninstalled ``yt-dlp-ejs``.
    ``[tool]`` is where uv keeps the list; a receipt with the list at its top
    is read the same.
    """
    try:
        with open(receipt, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    table = data.get("tool") if isinstance(data.get("tool"), dict) else data
    found = table.get("requirements")
    if not isinstance(found, list):
        return []
    return [
        entry for entry in found
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]
    ]


def requirement_spec(entry: dict, pinned: bool = True) -> str:
    """One requirement spelled back the way it was asked for, ready for a
    shell: ``'yt-dlp[default]'``, ``'six>=1.10'``.

    *pinned* ``False`` drops the version constraint — and only that: it is how
    the tool's own entry is spelled, since moving past whatever was pinned is
    the whole point of the line (:func:`upgrade_command`), while its extras
    are what pulls in the pieces the tool needs. Quoted, because ``[`` is a
    glob to the shell somebody pastes it into.
    """
    extras = [str(e) for e in entry.get("extras") or [] if str(e)]
    text = str(entry["name"]) + (f"[{','.join(extras)}]" if extras else "")
    if pinned and isinstance(entry.get("specifier"), str):
        text += entry["specifier"]
    if isinstance(entry.get("marker"), str) and entry["marker"]:
        text += f"; {entry['marker']}"
    return shlex.quote(text)


def _same_package(one: str, other: str) -> bool:
    """Whether two names are one package, the way pip and uv compare them."""
    return re.sub(r"[-_.]+", "-", one).lower() == re.sub(r"[-_.]+", "-", other).lower()


def shebang_of(binary: str) -> str:
    """The interpreter a console script names, or ``""`` if it names none."""
    words = _shebang_words(binary)
    return words[0] if words else ""


def _shebang_words(binary: str) -> list[str]:
    """Every word of a script's ``#!`` line, or ``[]`` if it has none."""
    try:
        with open(binary, "rb") as handle:
            first = handle.readline(4096).decode("utf-8", "replace")
    except OSError:
        return []
    return first[2:].split() if first.startswith("#!") else []


def install_of(command: str) -> tuple[str, str]:
    """``(how it was installed, the interpreter behind it)``.

    ``uv-tool``, ``pip``, ``self`` or ``absent``. The question matters because
    each has its own upgrade command and none works on another, and the
    obvious place to look — the tool's own version banner — cannot answer it.

    ``self`` is yt-dlp's own release, which updates itself: the single-file
    zipapp (``#!/usr/bin/env python3`` in front of a zip archive) and the
    built binary with no ``#!`` at all — the interpreter there is the file
    itself. Told by the archive rather than the ``env``: an ``env`` script
    that is not one is asked of the interpreter it names, as
    :func:`yt_dlp_takes` does, and never written up as ``env -m pip``.
    """
    binary = shutil.which(command)
    if not binary:
        return "absent", ""
    words = _shebang_words(binary)
    if not words or zipfile.is_zipfile(binary):
        return "self", binary
    python = words[0]
    if Path(python).name == "env":
        named = next((word for word in words[1:] if not word.startswith("-")), "")
        python = (shutil.which(named) or named) if named else ""
    return ("uv-tool" if uv_receipt(python) else "pip"), python


def short_python(python: str) -> str:
    """The interpreter as somebody would type it, if that means the same file.

    A Termux shebang is 45 characters — longer than this screen's whole fold —
    and a path broken mid-word is a path retyped wrong. The basename is what
    fits and what a person types, so it is used *only* when ``which`` resolves
    it back to the same file, and the full path stands when it does not.
    """
    if not python:
        return "python3"
    name = Path(python).name
    # Compared as written and never resolved: a venv's `python3` is a symlink
    # to the base interpreter, so `resolve()` makes every venv look like the
    # system python — and `python3 -m pip` under the system python installs
    # into a different place entirely, which is the whole failure this line
    # is meant to avoid.
    return name if shutil.which(name) == python else python


def upgrade_command(command: str) -> str:
    """The line that actually upgrades *command* on this machine.

    ``uv tool upgrade`` is deliberately not what this emits: a tool installed
    with any version constraint answers "Nothing to upgrade" and does nothing
    at all, silently (measured 2026-08-28). ``install --force`` moves it
    whatever the original requirement said — and re-asserts the ``--with``
    packages, which a plain reinstall drops, trading one silent failure for
    the other one. The tool's own extras are re-asserted too
    (``'yt-dlp[default]'``, which is what brings in ``yt-dlp-ejs``); only its
    own version pin is left behind. A release that updates itself is told to.
    """
    kind, python = install_of(command)
    if kind == "absent":
        return f"{command} is not on PATH"
    if kind == "self":
        return f"{command} -U"
    receipt = uv_receipt(python)
    if receipt is not None:
        wanted = uv_requirements(receipt)
        own = next((e for e in wanted if _same_package(e["name"], command)), None)
        withs = "".join(
            f" --with {requirement_spec(entry)}" for entry in wanted if entry is not own
        )
        tool = requirement_spec(own or {"name": command}, pinned=False)
        return f"uv tool install {tool}{withs} --force"
    return f"{short_python(python)} -m pip install -U {command}"


def checkout_root() -> Path | None:
    """The repository this package is running out of, found by its own ``.git``.

    Walked up from the package's parent (:data:`home.SOURCE`) rather than
    counted. One directory up is right in a checkout and is site-packages the
    moment it is installed — and ``git -C <site-packages> pull`` in a fix
    somebody is about to type is worse than offering no path at all.
    ``.exists`` rather than ``.is_dir`` because a worktree's ``.git`` is a file.
    """
    if not (home.SOURCE / home.CONTRACT).is_file():
        return None
    for folder in (home.SOURCE, *home.SOURCE.parents):
        if (folder / ".git").exists():
            return folder
    return None


def own_upgrade() -> str:
    """How to update *this* tool, which is a different question again.

    An editable install runs out of the checkout, so what updates it is a pull
    and not a reinstall. Told apart by where this file actually is: under the
    uv tools directory is a copy uv upgrades, a checkout is pulled, and
    anything else is a copy pip installed from PyPI.
    """
    venv = Path(sys.executable).parent.parent
    here = Path(__file__).resolve().parent
    copied = (venv / UV_RECEIPT).is_file() and str(here).startswith(str(venv.resolve()))
    if copied:
        return "uv tool upgrade nibbles"
    root = checkout_root()
    return f"git -C {tilde(root)} pull" if root else "pip install -U nibbles"


def tool_version(command: str, timeout: int = 20) -> str:
    """What ``<command> --version`` says. Free: no network, no URL."""
    binary = shutil.which(command)
    if not binary:
        return ""
    try:
        done = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "").strip().splitlines()[0].strip() if done.stdout else ""


def withheld_note(width: int) -> str:
    """The one line the format list carries while the answer is a refusal.

    Three widths, measured like the hints are, because the first version was
    one string of 39 columns drawn into 38 and a phone rendered "youtube
    withheld the res" — a warning clipped mid-word, on a screen whose whole
    job at that moment is to be believed.

    Short on purpose. The notice has already said the whole of it once this
    session; what this has left to do is stop somebody queueing 360p while
    believing it is the best on offer, and "bot check" does that in two words.
    At the floor it is those two words and nothing else.

    No symbol in front of it. ``⚠`` is ambiguous-width and routinely rendered
    as a double-width emoji, which would put the clip back; and this repo's
    own rule is that the status is the word, never the decoration.
    """
    if width >= WIDE:
        return "bot check — youtube sent one format, not all of them"
    return "bot check — one format only" if width >= TIGHT else "bot check"


def withheld_advice(
    detail: str,
    version: str | None = None,
    upgrade: str | None = None,
    mine: str | None = None,
) -> list[str]:
    """What a thin answer means, and what to do — in order of likelihood.

    **The version goes first, and that is a correction.** This notice used to
    lead with the cookies and the JS runtime, and on 2026-08-28 it sent
    somebody down both of those with a correct config and a six-week-old
    yt-dlp. YouTube breaks yt-dlp faster than anything else this repo depends
    on, so "how old is it" is at once the likeliest answer and the cheapest to
    ask — ``--version`` needs no URL and no network.

    The upgrade line is composed from how the thing is *actually* installed
    (:func:`upgrade_command`) rather than guessed, because a uv tool and a pip
    install take different commands and neither works on the other. Same again
    for ``ytq`` (:func:`own_upgrade`), where an editable install is updated by
    a pull and not by a reinstall at all.

    Everything is injectable so the wording can be measured on a machine with
    no yt-dlp on it.
    """
    if version is None:
        version = tool_version("yt-dlp") or "unknown"
    if upgrade is None:
        upgrade = upgrade_command("yt-dlp")
    if mine is None:
        mine = own_upgrade()
    return [
        "youtube sent one format, not all of them",
        f"yt-dlp {version} — usually just stale. upgrade:",
        upgrade,
        f"then the cookies: {detail}",
        "and yt-dlp -v must show a JS runtime and yt_dlp_ejs.",
        # One entry, because the worst case — both of these being uv
        # commands — is a row over the phone's budget with two. The em-dash
        # is spaced so the path cannot read as part of the command.
        f"nibbles itself: {mine} — docs: ~/nibbles/docs/ytq.md",
    ]


def _size_of(fmt: dict) -> tuple[int, bool]:
    """``(bytes, exact)``. Zero means yt-dlp would not say."""
    size = fmt.get("filesize")
    if isinstance(size, (int, float)) and size > 0:
        return int(size), True
    size = fmt.get("filesize_approx")
    if isinstance(size, (int, float)) and size > 0:
        return int(size), False
    return 0, False


def _family(ext: str) -> str:
    if ext in ("mp4", "m4a"):
        return "mp4"
    if ext in ("webm", "opus"):
        return "webm"
    return ext or "?"


def _quality(fmt: dict) -> int | None:
    """The quality a video format is sold as (``1080``), which is not always
    its height.

    YouTube's own word first, where it leads with one (``1080p``, ``720p60``,
    ``1080p Premium``). Otherwise the frame's height inside a 16:9 box, as
    YouTube reckons it: the short side, or nine sixteenths of the long side if
    that is more. A 2:1 film's 1080p is 3840x1920's little brother at
    1920x960, and a short's 1080p stands 1920 tall; read off the height, the
    first offered 960p and the second 1920p, and neither met a quality button.
    """
    said = _height_of(str(fmt.get("format_note") or ""))
    if said:
        return said
    width, height = fmt.get("width"), fmt.get("height")
    if not height:
        return None
    if not width:
        return int(height)
    short, long = sorted((int(width), int(height)))
    return max(short, round(long * 9 / 16))


def _video_label(fmt: dict) -> str:
    height = _quality(fmt)
    where = f"{height}p" if height else (fmt.get("format_note") or "video")
    fps = fmt.get("fps")
    if fps and fps > 30:
        where += f"{int(fps)}"
    return where


def _codec(name: str | None) -> str:
    if not name or name == "none":
        return "-"
    return name.split(".")[0]


def _exact_codec(name: str | None) -> str:
    """The codec exactly as yt-dlp said it, profile and all.

    :func:`_codec` cuts "avc1.640028" to "avc1" for the columns; this keeps
    it whole for :attr:`Choice.codecs`, because which av01 profile a stream
    is decides whether a player can play it at all.
    """
    if not name or name == "none":
        return "-"
    return name


def choices(info: dict) -> tuple[list[Choice], int]:
    """Selectable downloads, best first, plus a count of unsized formats.

    Formats yt-dlp will not put a size on are dropped rather than offered with
    a guessed cap, because that cap is the only thing standing between a
    mis-sized item and the runner's watchdog killing it every night.
    """
    formats = [
        f
        for f in (info.get("formats") or [])
        if f.get("ext") != "mhtml" and f.get("format_id")
    ]
    unsized = 0

    videos, audios, progressive = [], [], []
    for fmt in formats:
        # A missing codec means yt-dlp does not know, which is not the same as
        # the string "none" meaning the stream is absent. Only the explicit
        # "none" on both is a storyboard rather than something playable.
        vcodec, acodec = fmt.get("vcodec"), fmt.get("acodec")
        if vcodec == "none" and acodec == "none":
            continue
        size, exact = _size_of(fmt)
        if not size:
            unsized += 1
            continue
        entry = (fmt, size, exact)
        if acodec == "none" and vcodec != "none":
            videos.append(entry)
        elif vcodec == "none" and acodec != "none":
            audios.append(entry)
        else:
            progressive.append(entry)

    # A dubbed video carries its audio once per language, every copy at the
    # same bitrate: only the original is offered, as an audio choice or in a
    # merge. yt-dlp ranks it highest (``language_preference``), and the rank
    # is read off every audio track, sized or not, so an original that came
    # without a size leaves no dub to stand in for it. Where nothing is
    # ranked, or every track is ranked alike, nothing is dropped.
    ranks = {
        fmt.get("language_preference")
        for fmt in formats
        if fmt.get("vcodec") == "none" and fmt.get("acodec") not in (None, "none")
        and isinstance(fmt.get("language_preference"), (int, float))
    }
    if len(ranks) > 1:
        top = max(ranks)
        audios = [e for e in audios if e[0].get("language_preference") == top]

    # One best audio per container family, so a merge does not have to transcode
    # or fall back to Matroska when it does not need to.
    best_audio: dict[str, tuple[dict, int, bool]] = {}
    for fmt, size, exact in audios:
        family = _family(fmt.get("ext") or "")
        current = best_audio.get(family)
        if current is None or (fmt.get("abr") or 0) > (current[0].get("abr") or 0):
            best_audio[family] = (fmt, size, exact)
    overall_audio = max(audios, key=lambda e: e[0].get("abr") or 0, default=None)

    out: list[Choice] = []

    for fmt, size, exact in progressive:
        out.append(
            Choice(
                "single",
                str(fmt["format_id"]),
                size,
                exact,
                fmt.get("ext") or "mp4",
                f"{_video_label(fmt)} {fmt.get('ext')}",
                f"one file, {_codec(fmt.get('vcodec'))}+{_codec(fmt.get('acodec'))}",
                codecs=f"{_exact_codec(fmt.get('vcodec'))} + "
                f"{_exact_codec(fmt.get('acodec'))}",
            )
        )

    for fmt, size, exact in videos:
        family = _family(fmt.get("ext") or "")
        pair = best_audio.get(family) or overall_audio
        if pair is None:
            continue
        afmt, asize, aexact = pair
        merge = (
            "mp4"
            if family == "mp4" and _family(afmt.get("ext") or "") == "mp4"
            else (
                "webm"
                if family == "webm" and _family(afmt.get("ext") or "") == "webm"
                else "mkv"
            )
        )
        out.append(
            Choice(
                "merge",
                f"{fmt['format_id']}+{afmt['format_id']}",
                size + asize,
                exact and aexact,
                merge,
                f"{_video_label(fmt)} {merge}",
                f"{_codec(fmt.get('vcodec'))} + "
                f"{_codec(afmt.get('acodec'))} {int(afmt.get('abr') or 0)}k, merged",
                merge_ext=merge,
                codecs=f"{_exact_codec(fmt.get('vcodec'))} + "
                f"{_exact_codec(afmt.get('acodec'))}",
            )
        )

    for fmt, size, exact in audios:
        out.append(
            Choice(
                "audio",
                str(fmt["format_id"]),
                size,
                exact,
                fmt.get("ext") or "m4a",
                f"audio {int(fmt.get('abr') or 0)}k {fmt.get('ext')}",
                f"{_codec(fmt.get('acodec'))}, no video",
                codecs=_exact_codec(fmt.get("acodec")),
            )
        )

    rank = {"single": 0, "merge": 0, "audio": 1}
    out.sort(key=lambda c: (rank[c.kind], -c.size))
    return out, unsized


# --------------------------------------------------------------------------- #
# Writing the item
# --------------------------------------------------------------------------- #


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB"):
        if abs(n) < 1024:
            return f"{n:,.0f} {unit}"
        n /= 1024
    return f"{n:,.2f} GiB"


def literal(value: str | None) -> str:
    """*value* as Python source: a quoted string, or ``None``.

    :func:`json.dumps` alone is right for the strings — it is what stops a
    title full of quotes from writing an item that will not parse — and wrong
    for ``None``, which it spells ``null``. That spelling *parses*, so every
    check that stops at "does this file compile" passes it, and the item dies
    with ``NameError`` on the night it was finally due to run.
    """
    return "None" if value is None else json.dumps(value)


def slugify(title: str, limit: int = 42) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "video").lower()).strip("-")
    return slug[:limit].rstrip("-") or "video"


#: The header that says what an item is a download *of*, so that queueing the
#: same video twice can be noticed before it is paid for twice.
SOURCE_RE = re.compile(r"^#\s*SOURCE\s*:\s*(.+?)\s*$")


def source_key(info: dict) -> str:
    """What this download *is*, as an extractor and an id.

    Not the URL: one video has many of them — ``youtu.be/x``,
    ``watch?v=x``, ``watch?v=x&list=…`` — and the one a search hands back is
    routinely not the one somebody pastes. yt-dlp's id is stable per extractor
    and both halves of ytq have it in hand already, the search from its flat
    entries and the probe from the full answer.

    Empty when there is no id to key on, which is not an error: it means this
    item can only be recognised again by its name, and :func:`find_duplicate`
    says as much when it matches one that way.

    One line (:func:`one_line`), because it is written into the item's header:
    the generic extractor's id is the link's own file name, unquoted, so a
    ``%0A`` in a link is a line break in the id.
    """
    ident = info.get("id")
    if not ident:
        return ""
    who = (
        info.get("ie_key")
        or info.get("extractor_key")
        or info.get("extractor")
        or "video"
    )
    return one_line(f"{str(who).lower()}:{ident}")


def source_of(text: str) -> str:
    """The ``SOURCE`` an item declares, read from its header and nowhere else.

    Stops at the first line that is not a comment, the way the runner's own
    parser does: everything below is the item's docstring and its code, and a
    URL quoted in either is not a claim about what the item is.
    """
    for line in text.splitlines():
        if line.startswith("#!"):
            continue
        if not line.startswith("#"):
            break
        found = SOURCE_RE.match(line)
        if found:
            return found.group(1)
    return ""


def items() -> list[tuple[str, Path]]:
    """``(where, path)`` for every item the queue holds, in any state.

    Spelled here rather than taken from ``expire_sched._paths``, which does the
    same walk, because that module imports *this* one — the dependency only
    runs one way, and a front end that could not queue without the manager
    being importable would be a worse trade than one walk written twice.
    """
    found: list[tuple[str, Path]] = []
    for where, directory in (("queued", QUEUE), ("done", DONE), ("failed", FAILED)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue
            if ITEM_RE.match(path.name) and path.is_file():
                found.append((where, path))
    return found


class Duplicate(RuntimeError):
    """This download is already in the queue, or has already been made.

    Carried as an exception because :func:`write_item` is the one door every
    way of queueing goes through, and a door is the only place a rule like this
    can be enforced rather than remembered. Every screen catches it and says it
    in its own words.
    """

    def __init__(self, path: Path, where: str, how: str) -> None:
        self.path, self.where, self.how = path, where, how
        self.name = path.name
        super().__init__(f"{self.says()} — {self.stem}")

    @property
    def stem(self) -> str:
        return self.name[:-3] if self.name.endswith(".py") else self.name

    def says(self) -> str:
        """The verdict in one short line, fit for the narrowest screen."""
        same = "same name," if self.how == "name" else ""
        if self.where == "done":
            day = self.path.parent.name
            when = day if re.match(r"^\d{4}-\d{2}-\d{2}$", day) else ""
            # "done" rather than "downloaded" once the name qualifier is on the
            # front of it: the two together are two columns wider than the
            # narrowest screen, and this is the line that says why.
            got = f"{same} done {when}" if same else f"downloaded {when}"
            return got.strip() or "already downloaded"
        if self.where == "failed":
            return f"{same} failed before".strip() if same else "tried, and failed"
        return f"{same} already queued".strip()


def find_duplicate(key: str, slug: str) -> Duplicate | None:
    """The item this download would be a second copy of, if there is one.

    Two ways of being the same thing, and they are not equally strong. A
    matching ``SOURCE`` is the same video by id, wherever it was queued from
    and whatever it was called. A matching *name* is the fallback for items
    written before ``SOURCE`` existed, and for anything else that has no id: it
    is the same title, which is usually the same video and occasionally is not
    — so it is reported as what it is, and never silently.

    The queue is searched in the order the answer matters: still waiting, then
    already downloaded, then given up on.

    Names are compared as :func:`same_name` spells them, which is what lets a
    title-named item (``10-Crust of Rust.py``) and one written under a slug
    (``10-crust-of-rust.py``) both answer to the same title.
    """
    want = same_name(slug) if slug else ""
    named: Duplicate | None = None
    for where, path in items():
        if key:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:4096]
            except OSError:
                text = ""
            if text and source_of(text) == key:
                return Duplicate(path, where, "source")
        if want and named is None and same_name(item_slug(path.name)) == want:
            named = Duplicate(path, where, "name")
    return named


def same_name(name: str) -> str:
    """*name* as two names are compared: letters and digits in any script,
    case set aside, and every run of anything else one dash.

    Not :func:`slugify`, which keeps only ``a-z0-9``: every title written in
    another script would come out ``video`` and be the same name as every
    other one.
    """
    return re.sub(r"[\W_]+", "-", name.casefold()).strip("-")


def queued_names() -> list[str]:
    """The items waiting in ``queue/``, in the order the runner takes them:
    their file names, sorted."""
    try:
        return sorted(path.name for path in QUEUE.iterdir()
                      if ITEM_RE.match(path.name) and path.is_file())
    except OSError:
        return []


def _last_key() -> int | None:
    keys = [int(ITEM_RE.match(name).group(1)) for name in queued_names()]
    return max(keys) if keys else None


def next_number() -> int:
    """The number a new item is written under: ten past the last one queued,
    so it runs after everything already waiting. ytq queues last.

    Counted from ``queue/`` alone. ``done/`` and ``failed/`` keep the numbers
    their items ran under, and counting them reached :data:`MAX_PRIORITY` by
    the tenth download ever and stayed there: every item after that shared
    ``99``, and the runner, which sorts file names, took them in the order of
    their titles — a download queued second ran first whenever its title
    sorted first.

    Never past :data:`MAX_PRIORITY`, because the tenth item queued would
    otherwise be ``100``, which sorts *before* ``20``: a new download would go
    to the head of the queue rather than the tail, and the only symptom would
    be things running in the wrong order. So when the last queued item already
    holds it, the queue is first dealt fresh keys in its own order, the way
    Move does when the room between two items runs out (:func:`_make_room`).
    Only a queue that may not be touched — a firing or a download holds it —
    or that has no key left at all shares the last one, ordered by name until
    a Move spreads it out.
    """
    last = _last_key()
    if last is not None and last >= MAX_PRIORITY:
        _make_room()
        last = _last_key()
    return 10 if last is None else min(last + 10, MAX_PRIORITY)


def _make_room() -> None:
    """Deal every queued item a fresh key, in the order they already run.

    ``nibbles queue``'s own reindex (:func:`expire_ui._reindex`), so the item,
    its partial in ``work/``, anything in ``out/`` and its record all move
    together; and only past :func:`expire_ui.busy_problem`, because a firing
    or a ``nibbles now`` renaming an item into ``done/`` underneath a rename
    loses the download. Imported here and not at the top: ``expire_ui``
    imports ``expire_sched``, which imports this module.
    """
    try:
        from nibbles import expire_ui

        if expire_ui.busy_problem() is not None:
            return
        if expire_ui._reindex(queued_names()) is None:
            expire_ui._note("dealt the queue fresh keys to queue a download last")
    except Exception:  # noqa: BLE001 - a better place for one item, never a blocker
        pass


def _in_docstring(text: object) -> str:
    """*text* as it may stand in an item's comments and docstring: one line
    (:func:`one_line`), no backslash to begin an escape and no triple quote to
    end the string."""
    return one_line(text).replace("\\", "/").replace('"""', "'''")


def render(
    url: str,
    slug: str,
    choice: Choice,
    title: str,
    probed: str,
    dest: str = "video",
    key: str = "",
) -> str:
    """The item source. Strings go through :func:`json.dumps` so that a title
    full of quotes cannot produce a file that does not parse.

    What is not code — the header comments and the docstring — is written from
    :func:`_in_docstring`'s spelling, whoever called: a title is somebody
    else's words, and one that ended the ``DESC`` comment or the docstring
    would be an item that never compiles, or one whose second line runs."""
    safe_title = _in_docstring(title)
    desc = _in_docstring(f"{title} [{choice.label}] ({human(choice.size)} via yt-dlp)")
    margin = "3%" if choice.exact else "12%"
    sizing = textwrap.fill(
        _in_docstring(
            f"Format {choice.fmt} — {choice.detail}. yt-dlp reported "
            f"{choice.size:,} bytes "
            f"{'exactly' if choice.exact else 'approximately'} when this was queued "
            f"on {probed}; EXPECT_BYTES is that figure plus a {margin} margin and "
            f"{human(OVERHEAD_FIXED)} for the per-firing metadata extractions, "
            f"retries and container overhead."
        ),
        78,
    )
    # SOURCE is what this item is a download *of*, and it is written whether or
    # not anything reads it today: an item queued now is what tomorrow's
    # duplicate check has to recognise, and it cannot be added to a file that
    # has already been written.
    key = one_line(key)
    source = f"\n# SOURCE: {key}" if key else ""
    return f'''{SHEBANG}
# EXPIRE: v1
# EXPECT_BYTES: {choice.expect_bytes}
# PARTIAL: yes
# SLICE_MIN_BYTES: {SLICE_MIN_BYTES}
# DEST: {dest}{source}
# DESC: {desc[:160]}
"""{safe_title}

{_in_docstring(url)}

{sizing}

yt-dlp is invoked on every firing rather than resolving a media URL once,
because those URLs are signed and expire in about six hours — far less than the
queue may take to work through a video this size.
"""

import sys

sys.path.insert(0, {json.dumps(str(MODULE_DIR))})
from nibbles import ytdl_item  # noqa: E402

sys.exit(ytdl_item.run(
    url={json.dumps(url)},
    name={json.dumps(slug)},
    fmt={json.dumps(choice.fmt)},
    total_hint={choice.size},
    merge_ext={literal(choice.merge_ext)},
))
'''


def item_name(number: int, slug: str) -> str:
    """The file name an item is written under — the one spelling of it.

    Written here rather than in each of the three places that wanted it, which
    is the screen showing where the file goes, the picker being told what it is
    holding, and :func:`write_item` itself. A picker handed a name that is a
    second f-string is a picker holding a file that is never written: the two
    would agree today and drift the first time either is touched.
    """
    return f"{number:02d}-{slug}.py"


def item_slug(name: str) -> str:
    """That name read back: the number and the suffix taken off again."""
    return ITEM_RE.sub("", name).removesuffix(".py")


def write_item(number: int, slug: str, source: str, again: bool = False) -> Path:
    """Stage, make executable, then rename into the queue.

    The runner scans the queue directory on a timer, so a file must never
    appear there until it is complete and executable.

    **This is where the duplicate check lives**, and it lives here because it
    is the one door: the search, a pasted URL, ``--now``, ``--from-json`` and
    ``dlq`` all end up on this line, so a check anywhere else would be a check
    each of them could be written around. It raises :class:`Duplicate` rather
    than deciding anything — what to say and whether to override is the
    screen's business, and *again* is that override coming back.

    **Nothing already there is ever replaced.** Two videos can share a title,
    the same one can be queued twice on purpose (*again*), and a name stays
    spoken for after its item has gone (:func:`names_in_use`) — and whatever
    answers to a name next inherits its partial, its outbox and its record:
    another video's bytes resumed into this one, or a finished download's
    "nothing left to fetch" on every night for ever. So a name in use takes
    ``(2)``, ``(3)``… after the title, never another number, because the
    number is the place this item was given; the path returned is the name it
    got. The choosing and the moving in happen under one lock, so two writers
    at once cannot both find the same name free.

    A write that fails leaves nothing half-written behind in ``.staging``.
    """
    if not again:
        found = find_duplicate(source_of(source), slug)
        if found is not None:
            raise found
    STAGING.mkdir(parents=True, exist_ok=True)
    QUEUE.mkdir(parents=True, exist_ok=True)
    with (STAGING / ".lock").open("w") as door:
        fcntl.flock(door, fcntl.LOCK_EX)
        used = names_in_use()
        name, copy = item_name(number, slug), 1
        while name in used:
            copy += 1
            name = item_name(number, f"{slug} ({copy})")
        staged, final = STAGING / name, QUEUE / name
        try:
            # Written as UTF-8 because that is how the runner reads it. A
            # title can hold anything, and an item that decodes differently at
            # midnight than it did when it was queued is an item the runner
            # refuses for no visible reason.
            staged.write_text(source, encoding="utf-8")
            staged.chmod(0o755)
            staged.rename(final)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    return final


def names_in_use() -> set[str]:
    """Every item name that something still answers to.

    The items in ``queue/``, ``done/`` and ``failed/``; a ``work/`` or
    ``out/`` directory, which an item removed with its bytes kept leaves
    behind; and every record in ``state.json``, which outlives its item
    (:func:`delivered_file` says the same) and which the runner hands, attempts
    and bytes and all, to whatever is queued under that name next.
    """
    used = {path.name for _, path in items()}
    for folder in ("work", "out"):
        with contextlib.suppress(OSError):
            used.update(os.listdir(HERE / folder))
    try:
        records = json.loads((HERE / "state.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError, TypeError):
        records = {}
    if isinstance(records, dict):
        used.update(records)
    return used


#: The two destinations ytq queues into, and the one it uses when nothing is
#: said. ``dlq`` fills the third (``file``); the runner owns the full list.
VIDEO_DEST = "video"
AUDIO_DEST = "audio"


def dest_for(choice: Choice, asked: str = VIDEO_DEST) -> str:
    """Which destination an item declares: a kind, or the path asked for.

    An audio-only pick is not a video and does not belong in the folder videos
    go to — the same argument ``DEST_KINDS`` already makes about a film and an
    installer, one step further in. A phone makes it sharper than a desktop
    would: the music player and the video player look in different places, and
    a song delivered among the films is one nothing will offer to play.

    Decided from :attr:`Choice.kind`, which is the row that was actually
    chosen, and deliberately not from the file extension — at queue time there
    is no file yet to have one, and the runner resolves this at delivery
    precisely so that changing the setting moves what is already queued.

    ``--dest`` names a directory and wins over both, which is the runner's own
    rule about an absolute path in the header, kept rather than re-decided.
    """
    if asked != VIDEO_DEST:
        return asked
    return AUDIO_DEST if choice.kind == "audio" else VIDEO_DEST


def landing(dest: str) -> str:
    """Where a ``DEST`` value will actually put the file, for a message.

    Asked of the runner rather than worked out here, because the runner is what
    resolves it at delivery — and a line printed at queue time that disagrees
    with where the file turns up is worse than no line.
    """
    try:
        from nibbles import expire_runner

        where = expire_runner.dest_of({"dest": dest})
    except Exception:  # noqa: BLE001 - a message, never a blocker
        return dest
    return str(where) if where else "out/"


def validate(path: Path) -> str | None:
    """Ask the runner's own parser whether it would admit this item."""
    try:
        from nibbles import expire_runner

        item = expire_runner.parse_item(path)
    except Exception as exc:  # noqa: BLE001 - a check, never a blocker
        return f"could not check with the runner's parser: {exc!r}"
    return item.get("error")


# --------------------------------------------------------------------------- #
# Downloading one now, in the background
# --------------------------------------------------------------------------- #


def queue_busy() -> bool:
    """Whether something already holds the runner's lock.

    A nightly firing or another download-now owns the queue exclusively, and a
    second one would exit into a log nobody reads. Asking first turns that into
    a sentence on the screen. The answer can go stale between here and the
    spawn; the child takes the lock properly and would refuse anyway, so this
    is for the message, not for the safety.
    """
    try:
        handle = (HERE / "runner.lock").open("w")
    except OSError:
        # No lock file to collide over yet, which is not the same as busy.
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def now_argv(name: str) -> list[str]:
    """The command that downloads one queued item now.

    ``nibbles now``, as ``python -m nibbles`` under this interpreter rather
    than by console script, so it is this package — the checkout or the
    installed copy that is running — whatever is first on PATH; the queue root
    it works on is :data:`HERE` either way (:func:`home.root`). ``--yes``
    because the confirm screen was the asking, and being asked twice teaches
    people to stop reading the question.
    """
    return [sys.executable, "-m", "nibbles", "now", name, "--yes"]


def start_now(name: str) -> tuple[subprocess.Popen, Path]:
    """Spawn the download detached, and say where it is writing.

    ``start_new_session`` on purpose, and the one place this disagrees with
    ``run_one``'s own choice: that avoids ``setsid`` so ctrl-c reaches the
    download through the terminal's process group. Here the screen goes back to
    the results and ytq later exits, and the download must not go with it.
    """
    logs = HERE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{time.strftime('%Y-%m-%d', time.gmtime())}-now-{name}.log"
    handle = log.open("a", encoding="utf-8")
    try:
        child = subprocess.Popen(
            now_argv(name),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(HERE),
            env=home.child_env(),
        )
    finally:
        handle.close()
    return child, log


def now_progress(name: str) -> tuple[int, int] | None:
    """``(bytes on disk, total)`` from the item's own report, or ``None``.

    Read straight off ``work/<item>/.status.json``, which the download writes
    for the runner anyway — a local file, so watching a download costs nothing.
    Half-written or absent reads as "no report yet" rather than raising: this
    is drawn on a timer, and a screen must not die because it looked a
    millisecond early.
    """
    try:
        report = json.loads((HERE / "work" / name / ".status.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    have = report.get("part_bytes")
    if not isinstance(have, (int, float)):
        return None
    total = report.get("total_bytes")
    return int(have), int(total) if isinstance(total, (int, float)) else 0


def progress_line(name: str, report: tuple[int, int] | None, width: int) -> str:
    """The one line that says a background download is still going."""
    if report is None:
        body = "starting…"
    else:
        have, total = report
        body = human(have) + (f" / {human(total)}" if total else "")
    stem = name[:-3] if name.endswith(".py") else name
    return fit(f"↓ {stem}  {body}" if width >= WIDE else f"↓ {body}", width - 1)


def delivered_file(name: str) -> Path | None:
    """The file a finished run of *name* delivered, largest first, or ``None``.

    Asked of the runner's ``state.json`` rather than of the disk: a download
    handed to a shared folder cannot be found by looking, and ``retired`` is
    the runner's own word that this item finished — a run that stopped short
    leaves the item queued and answers ``None`` here.

    And the item must have left the queue: records outlive their items, so an
    earlier item of the same name that finished last week is a ``done`` record
    this run did not write.
    """
    if (QUEUE / name).exists():
        return None
    try:
        state = json.loads((HERE / "state.json").read_text(encoding="utf-8"))
        record = state["items"][name]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(record, dict) or record.get("retired") != "done":
        return None
    found = []
    for spelled in record.get("delivered") or []:
        path = Path(str(spelled))
        with contextlib.suppress(OSError):
            if path.is_file():
                found.append((path.stat().st_size, path))
    return max(found)[1] if found else None


# --------------------------------------------------------------------------- #
# Handing a file to Android
# --------------------------------------------------------------------------- #
#
# termux-open is a broadcast and nothing more: it runs `am broadcast … -d FILE`
# and exits 0 once the broadcast is sent, whatever happens next. What happens
# next is Termux's TermuxOpenReceiver, which reads FILE with Android's
# Uri.parse, checks the file, and hands an app a content:// URI that Termux's
# own provider then serves — and every way that road fails is a line in logcat
# and nothing else. So everything that can be known beforehand is asked here,
# before the broadcast, and said on the screen instead.

#: The setting without which Termux serves no file to any other app (since
#: termux-app 0.118.0, its provider's ``checkIfAllowExternalAppsPolicyIsViolated``),
#: and the line that sets it, spelled once.
SHARE_PROPERTY = "allow-external-apps"
SHARE_LINE = f"{SHARE_PROPERTY} = true"

#: What ``Uri.parse`` makes something else of in a path — ``%`` starts an
#: escape, ``#`` a fragment, ``?`` a query — and the full-width lookalike each
#: becomes in the name of a link (:func:`uri_safe`), which parses as itself and
#: reads the same in the player's title.
URI_SPECIAL = {"%": "％", "#": "＃", "?": "？"}


def termux_properties_paths() -> list[Path]:
    """Where Termux reads its settings, in its own order.

    Termux takes the first that *exists* and nothing else
    (``TermuxPropertyConstants.getPropertiesFile``): a primary file that is
    there hides the secondary even when it is not a file Termux can read.
    """
    home = Path.home()
    return [home / ".termux" / "termux.properties",
            home / ".config" / "termux" / "termux.properties"]


def java_properties(text: str) -> dict[str, str] | None:
    """*text* read the way ``java.util.Properties.load`` reads it — which is
    how Termux reads ``termux.properties`` — or ``None`` where that load would
    throw (a malformed ``\\uXXXX``), which Termux answers with every default.

    A line runs on into the next while it ends in an odd number of
    backslashes (the last one dropped, the next line's leading blanks
    skipped); a comment is a line whose first character past the blanks is
    ``#`` or ``!`` *while the line being built is still empty* — so one after
    a lone ``\\`` is a comment too, and a comment never runs on; an empty line
    is no entry. The key ends at the first unescaped ``=``, ``:`` or blank,
    and one ``=`` or ``:`` and the blanks around it are skipped. What is left
    is the value, *trailing blanks included* — Java keeps them, so ``true `` is
    not ``true`` to Termux, and must not be here. The last of a key wins.
    Checked, when it was written, against JDK 21's own ``Properties.load``
    over 80,000 random files of blanks, line ends, backslashes, separators,
    comment marks and escapes: not one answer differed.
    """
    blanks = " \t\f"
    logical: list[str] = []
    naturals = re.split(r"\r\n|\r|\n", text)
    if len(naturals) > 1 and not naturals[-1]:
        naturals.pop()  # what follows the last line's end is not a line
    line, running_on = "", False
    for natural in naturals:
        natural = natural.lstrip(blanks)
        if not line and natural[:1] in ("#", "!"):
            running_on = False
            continue
        line += natural
        running_on = bool((len(line) - len(line.rstrip("\\"))) % 2)
        if running_on:
            line = line[:-1]
            continue
        if line:
            logical.append(line)
        line = ""
    if running_on and (line or not text.endswith("\r\n")):
        # The end of the file ends it, empty or not — unless the last ``\r\n``
        # was read as a line end first, which is how Java's reader does it.
        logical.append(line)
    out: dict[str, str] = {}
    for line in logical:
        key_end = value_start = len(line)
        has_sep = escaped = False
        for pos, ch in enumerate(line):
            if not escaped and ch in "=:":
                key_end, value_start, has_sep = pos, pos + 1, True
                break
            if not escaped and ch in blanks:
                key_end, value_start = pos, pos + 1
                break
            escaped = ch == "\\" and not escaped
        while value_start < len(line):
            ch = line[value_start]
            if ch not in blanks:
                if has_sep or ch not in "=:":
                    break
                has_sep = True
            value_start += 1
        try:
            out[_java_unescape(line[:key_end])] = _java_unescape(line[value_start:])
        except ValueError:
            return None
    return out


def _java_unescape(text: str) -> str:
    """``Properties.loadConvert``: ``\\t \\n \\r \\f``, ``\\uXXXX``, and a
    backslash before anything else is that thing."""
    out, index = [], 0
    while index < len(text):
        ch = text[index]
        index += 1
        if ch != "\\" or index >= len(text):
            out.append("" if ch == "\\" else ch)
            continue
        ch = text[index]
        index += 1
        if ch == "u":
            digits = text[index:index + 4]
            if len(digits) < 4 or any(d not in "0123456789abcdefABCDEF" for d in digits):
                raise ValueError("malformed \\uxxxx encoding")
            out.append(chr(int(digits, 16)))
            index += 4
        else:
            out.append({"t": "\t", "n": "\n", "r": "\r", "f": "\f"}.get(ch, ch))
    return "".join(out)


def termux_shares() -> str | None:
    """``None`` when Termux will serve a file to another app; otherwise why
    not, and the fix.

    Termux reads the setting once, when it starts and on
    ``termux-reload-settings``, so a line added to the file and never reloaded
    reads as set here and still fails there — which is why the fix names both.
    """
    paths = termux_properties_paths()
    found = next((path for path in paths if path.exists()), None)
    where = tilde(found or paths[0])
    then = "then run termux-reload-settings"
    unset = (f"Termux shares no file with another app until {where} has {SHARE_LINE}: "
             f"add it, {then}")
    if found is None:
        return unset
    try:
        props = (
            java_properties(found.read_text(encoding="utf-8", errors="replace"))
            if found.is_file() else None
        )
    except OSError:
        props = None
    if props is None:
        return (f"Termux cannot load {where}, so it shares no file with another app: "
                f"make it a readable file with {SHARE_LINE}, {then}")
    value = props.get(SHARE_PROPERTY)
    if value is None:
        return unset
    if value.lower() == "true":
        return None
    shown = value if value and value == value.strip() else repr(value)
    return (f"{where} has {SHARE_PROPERTY} = {shown}, and Termux shares files only when it "
            f"is true: make it {SHARE_LINE}, {then}")


def termux_serves(real: str) -> bool:
    """Whether Termux's provider serves the file whose canonical path is *real*.

    Its own test, a string prefix: Termux's files (``$PREFIX``'s parent) or
    the primary shared storage, canonical. An SD card is neither, and is
    refused ("Invalid path") where only logcat hears it.
    """
    prefix = os.environ.get("PREFIX")
    files = str(Path(prefix).parent) if prefix else "/data/data/com.termux/files"
    storage = os.path.realpath(os.environ.get("EXTERNAL_STORAGE") or "/storage/emulated/0")
    return real.startswith(files) or real.startswith(storage)


def uri_safe(real: str) -> str:
    """A path to the file at *real* that survives being parsed as a URI again.

    termux-app 0.118 — the stable release — builds the content:// URI it
    hands an app by pasting the file's path into ``Uri.parse``, and its
    provider reads the path back *decoded*: the ``%`` of ``100% Raw`` decodes
    into garbage, the ``#`` of ``C# in 100 Seconds #shorts`` cuts the path
    short, and the app is handed a file that is not there. Nothing in the URI
    sent here can mend a parse made of a path it never sees. A link can: one
    in Termux's own temp folder, named with lookalikes that parse as
    themselves, which the provider follows to the real file — its check is on
    the canonical path, so a link changes nothing about what it will serve.
    A path that needs none comes back as it is, and so does one whose link
    cannot be made: 0.119 and later build that URI properly and open it anyway.
    """
    if not any(ch in real for ch in URI_SPECIAL):
        return real
    try:
        base = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "nibbles-open"
        folder = base / hashlib.sha256(os.fsencode(real)).hexdigest()[:16]
        link = folder / "".join(URI_SPECIAL.get(ch, ch) for ch in Path(real).name)
        if any(ch in str(link) for ch in URI_SPECIAL):
            return real
        # The links of files that have gone since go with them; the rest stay,
        # because an app may open its URI again long after it was handed one.
        with contextlib.suppress(OSError):
            for old in base.iterdir() if base.is_dir() else ():
                if old.is_dir() and not old.is_symlink():
                    for stale in old.iterdir():
                        if stale.is_symlink() and not stale.exists():
                            stale.unlink()
                    with contextlib.suppress(OSError):
                        old.rmdir()
        folder.mkdir(parents=True, exist_ok=True)
        if not (link.is_symlink() and os.readlink(link) == real):
            link.unlink(missing_ok=True)
            os.symlink(real, link)
        return str(link)
    except OSError:
        return real


def file_uri(path: str) -> str:
    """``file://`` and *path* with every byte ``Uri.parse`` would read as
    syntax escaped, which its ``getPath`` decodes back exactly.

    Handed to termux-open in place of a bare path, which ``am`` parses as a
    URI too: a ``:`` made everything before it a scheme, a ``#`` a fragment
    and a ``%`` an escape. termux-open's own ``[ -f ]`` is false for it, so
    nothing on the way rewrites it, and the receiver takes ``file`` as a file.
    """
    return "file://" + urllib.parse.quote(os.fsencode(path))


def _unopenable(real: str, termux: bool) -> str | None:
    """Why the file at *real* cannot be handed to anything, or ``None``.

    Asked at the moment of opening, never of a listing read a poll ago: a
    file deleted since is broadcast all the same, and the receiver says "not
    a readable file" to logcat alone.
    """
    try:
        os.stat(real)
    except FileNotFoundError:
        return f"it is not in {tilde(os.path.dirname(real))} any more"
    except PermissionError:
        return "Termux may not read it: run termux-setup-storage" if termux else "it cannot be read"
    if not os.path.isfile(real):
        return "it is not a file"
    if not os.access(real, os.R_OK):
        return "it cannot be read: run termux-setup-storage" if termux else "it cannot be read"
    return None


def open_file(path: Path) -> str:
    """Hand *path* to Android (or a desktop) to open, and say how it went.

    The one opener: Open it on a download's sheet and Open it when done both
    come here, so the two cannot disagree about a file. Everything Termux
    would refuse in silence is refused here aloud, before anything is sent —
    a file not there or not readable, a file outside what Termux serves, and
    a Termux that serves nothing until it is told to (:func:`termux_shares`)
    — each with what to do about it. What is sent is a ``file://`` URI
    (:func:`file_uri`) of the canonical path, or of a link to it when the name
    would not survive Termux's own parse (:func:`uri_safe`). ``xdg-open`` on a
    desktop keeps the plain path.

    "opened" is the most that can be said after that: termux-open's 0 means
    the broadcast went out, and whatever the app then made of it is not told.

    Never raises and never writes to the terminal: it runs off a thread while
    the app owns the terminal, after a download that has already succeeded.
    """
    path = Path(path)
    name = path.name
    opener = next((o for o in ("termux-open", "xdg-open") if shutil.which(o)), None)
    termux = opener == "termux-open"
    try:
        real = os.path.realpath(path)
        problem = _unopenable(real, termux)
        if problem is None and termux and not termux_serves(real):
            problem = (
                f"Termux shares only files in its own folders or internal storage, and "
                f"this is in {tilde(os.path.dirname(real))}: move it to internal storage, "
                f"or set its destination there in More"
            )
        if problem is None and termux:
            problem = termux_shares()
        if problem:
            return f"could not open {name}: {problem}"
        if opener is None:
            return f"no termux-open to open {name}"
        target = file_uri(uri_safe(real)) if termux else str(path)
    except (OSError, ValueError) as exc:
        return f"could not open {name}: {exc}"
    try:
        code = subprocess.run([opener, target], timeout=60, capture_output=True).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not open {name}: {exc}"
    return f"opened {name}" if code == 0 else f"could not open {name}"


class Running:
    """The background download this session started, if it started one.

    It also holds the one thing about that download that lives nowhere else:
    whether to open the file when it is done (``o`` on a screen showing it).
    In memory and nowhere else, on purpose — the ask belongs to this run,
    watched from this screen. Close the screen and it is gone; a run that is
    stopped, or stops short, never opens anything, and nor does the later run
    that finishes the job.
    """

    def __init__(self) -> None:
        self.child: subprocess.Popen | None = None
        self.name = ""
        self.log: Path | None = None
        self.open_when_done = False
        #: Set by :meth:`stop`: a run told to stop is never opened, whatever
        #: it manages to deliver on its way down.
        self.stopped = False
        #: What opening the file came to, for a screen to say; ``""`` until then.
        self.opened = ""
        #: Whether :meth:`settle` has finished with the child, so a screen
        #: waiting to say what ``opened`` came to knows when to stop waking.
        self.settled = True

    @property
    def alive(self) -> bool:
        return self.child is not None and self.child.poll() is None

    @property
    def askable(self) -> bool:
        """Whether ``o`` means anything now: running, and not told to stop."""
        return self.alive and not self.stopped

    def start(self, name: str) -> None:
        self.child, self.log = start_now(name)
        self.name = name
        self.open_when_done = False
        self.stopped = False
        self.opened = ""
        self.settled = False
        # A daemon, so it goes with the front end: an ask outlives neither.
        threading.Thread(
            target=self.settle, args=(self.child, name), daemon=True
        ).start()

    def toggle_open(self) -> str:
        """Flip the ask, and say what is now true — for a screen to flash."""
        self.open_when_done = not self.open_when_done
        return (
            "it will open when it is done"
            if self.open_when_done
            else "it will not open when done"
        )

    def settle(self, child: subprocess.Popen, name: str) -> None:
        """Wait out *child*, then open what it delivered if that was asked.

        Keyed on the child and not on ``self``: a newer download replacing
        this one must not have its ask answered by the older one ending.
        """
        child.wait()
        if child is not self.child:
            return
        if self.open_when_done and not self.stopped:
            path = delivered_file(name)
            self.opened = (
                open_file(path)
                if path is not None
                else "it did not finish, so nothing was opened"
            )
        self.settled = True

    def stop(self) -> None:
        """Signal the whole group, which is what ctrl-c used to do.

        The part-file stays on disk and the item stays in the queue, so the
        nightly window carries on from where this stopped — the property that
        made ctrl-c cheap, kept now that there is no ctrl-c to press.
        """
        if self.child is None:
            return
        # Stopped is not done, and resuming later is a different run.
        self.stopped = True
        # SIGINT, the ctrl-c this replaces: `nibbles now` keeps the item in its own
        # process group, so the interrupt reaches yt-dlp, which closes its part
        # file and stops the way a deadline stops it. Every byte is kept.
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(self.child.pid), signal.SIGINT)

    def line(self, width: int) -> str:
        return progress_line(self.name, now_progress(self.name), width)


# --------------------------------------------------------------------------- #
# Rows and words, for the printing paths and the screens
# --------------------------------------------------------------------------- #


def cols(text: str) -> int:
    """The columns *text* takes in a terminal, which is not its ``len``.

    A title keeps its CJK and its emoji, and Termux draws those two columns
    wide, so a line measured in characters can be twice the screen. East Asian
    Wide and Fullwidth are two; combining marks, format characters (ZWJ, the
    variation selectors) and controls are none; everything else is one,
    Ambiguous included (``…``, ``≤``), as Termux draws it. The same rule as
    bewitch's ``char_width``, spelled with the standard library because the
    printing paths and the runner's ``--status`` run where bewitch may not.
    """
    if text.isascii() and text.isprintable():
        return len(text)
    return sum(_char_cols(ch) for ch in text)


def _char_cols(ch: str) -> int:
    """The columns one character takes: see :func:`cols`."""
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf", "Cc"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def fit(text: str, width: int) -> str:
    """*text* clipped to *width* columns, saying so when something was lost.

    Public because ``expire_sched`` lays out the same terminal and there is no
    second answer to be had about what a clipped string looks like. Measured
    in columns (:func:`cols`), and a wide character that would straddle the
    edge is dropped rather than split.
    """
    if width <= 0:
        return ""
    if cols(text) <= width:
        return text
    room, used, kept = max(1, width - 1), 0, []
    for ch in text:
        used += _char_cols(ch)
        if used > room:
            break
        kept.append(ch)
    return "".join(kept) + "…"


def wrapped(text: str, width: int) -> list[str]:
    """*text* broken to *width*, but never inside a word.

    ``break_on_hyphens`` off, which is the whole reason this is a function.
    What these screens wrap ends in a path, a flag or a file stem —
    ``~/.config/yt-dlp/cookies.txt``, ``--cookies``,
    ``10-crust-of-rust-subtyping`` — and the default splits all three at a
    hyphen. A name wrapped mid-word is a name somebody retypes wrong, on the
    screens whose entire job is telling them what to type.

    Everything here that wraps prose goes through it, which is also what stops
    the name being shadowed by the three loop variables it replaced.
    """
    return textwrap.wrap(text, width, break_on_hyphens=False) or [""]


#: One step of a scrolling title, and how many steps it holds still at each
#: end of a lap before moving again. Slow on purpose: this is a list somebody
#: is reading, not an animation, and a title that snaps past faster than it
#: can be read has cost a wakeup to say nothing.
MARQUEE_MS = 300
MARQUEE_HOLD = 5

#: What separates the end of a scrolling title from its own beginning, so that
#: the lap is visible as a lap. Without it a wrapped title reads as one long
#: string with a nonsense join in the middle of it.
MARQUEE_GAP = "   ·   "


def marquee(text: str, width: int, tick: int, measure=len) -> str:
    """*width* columns of *text*, scrolled to step *tick*.

    Text that fits is returned whole and unmoved, which is what makes this
    safe to call on every row: the motion is a property of the title being too
    long, never of the row being selected.

    A lap holds at the start for :data:`MARQUEE_HOLD` steps before it moves —
    the beginning of a title is the part a choice is usually made on, and a
    line already sliding when the eye arrives is one that has to be waited out
    for a whole lap to read.

    Deliberately *not* :func:`fit`: no ellipsis. The ellipsis is how a clipped
    line says something was lost, and a line that is visibly moving has
    already said it.

    *measure* is what a column is: the screens pass bewitch's
    ``string_width``, the same measure that decides whether a title moves at
    all, since a CJK character or an emoji is one character and two columns.
    Counted in characters, a title whose characters fit and whose columns did
    not was never moved, only clipped, while the loop woke three times a
    second to draw it again; a longer one moved under an ellipsis, cut at up
    to twice its room. The window is filled a character at a time to the
    room, and a wide one that would straddle the edge leaves a space instead.
    """
    if width <= 0:
        return ""
    if measure(text) <= width:
        return text
    loop = text + MARQUEE_GAP
    phase = max(0, tick) % (len(loop) + MARQUEE_HOLD)
    offset = 0 if phase < MARQUEE_HOLD else phase - MARQUEE_HOLD
    shown, used = [], 0
    for ch in (loop + loop)[offset:]:
        cols = measure(ch)
        if used + cols > width:
            break
        shown.append(ch)
        used += cols
    return "".join(shown) + " " * (width - used)


def wide_tail(result: Result) -> str:
    """The columns after the title on a :data:`WIDE` row: channel, age,
    length, views. Spelled once, because :func:`title_room` measures it and
    :func:`result_row` draws it, and the two must not disagree by a column."""
    return (
        f"{fit(result.channel or '?', 16):<16}  "
        f"{age(result.timestamp):>5}  {clock(result.duration, result.live):>7}"
        f"  {views(result.views):>4}"
    )


def title_room(result: Result, width: int) -> int:
    """The columns a result's title gets on the row that draws it.

    One function, because two things have to agree about it and they are in
    different places: :func:`result_row`, which draws the title, and
    :func:`results`, which decides whether to keep waking up to scroll it.
    Written twice they drift, and the failure is silent both ways — a title
    that moves for no reason, or an idle screen paying a wakeup every 300ms
    for ever.
    """
    if width >= WIDE:
        return max(8, width - 5 - len(wide_tail(result)))
    # Two columns for the mark, one in hand at the right — the same arithmetic
    # the narrow branch of `result_row` lays out with.
    return max(4, width - 1 - 2)


def scrolls(result: Result, width: int) -> bool:
    """Whether this title is longer than the room it has, and so has to move."""
    return len(result.title) > title_room(result, width)


def nights(size: int) -> int:
    """How many nightly windows a download this big needs, at the least.

    Rough by construction — the grant is shared with whatever else the queue is
    doing — but the distinction that matters is one night against several, and
    that one is robust.
    """
    return max(1, -(-size // NIGHT_BYTES))


def cost_band(size: int) -> str:
    """``fits``, ``night`` or ``nights``: which colour a size is worth.

    Separated from the drawing so it can be checked without a terminal, and
    named for the fact rather than for the colour — colour is one way of
    saying this and :func:`nights_note` is the other, because a terminal
    without colours must not be the terminal that loses the warning.
    """
    if size <= NIGHT_BYTES // 3:
        return "fits"
    return "night" if size <= NIGHT_BYTES else "nights"


def nights_note(size: int) -> str:
    """``(2 nights)`` when a download will not fit one window, else nothing."""
    count = nights(size)
    return f" ({count} nights)" if count > 1 else ""


def to_clipboard(text: str) -> str:
    """Put *text* on the Android clipboard. The answer is for a person.

    termux-clipboard-set is part of Termux:API — the CLI package plus the
    app, the same pair the queue's scheduler needs — so its absence gets the
    install line, not a stack trace. The text goes over stdin: an argv URL
    can hit the command line where a pasted one has quoting in it.
    """
    tool = shutil.which("termux-clipboard-set")
    if not tool:
        # Fits the line above the tabs whole at 32 columns: the fix IS the
        # message, and a command clipped at the edge of a phone is a command
        # retyped wrong.
        return "pkg install termux-api to copy"
    try:
        done = subprocess.run(
            [tool], input=text, text=True, capture_output=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"clipboard failed: {exc}"
    if done.returncode != 0:
        return "clipboard failed - Termux:API app?"
    return "copied: " + text


def format_row(option: Choice, width: int) -> str:
    """One line of the format list, at whatever width there is for it.

    The format id and the codec detail go first when room runs out: they are
    the columns a choice is never made on. What is kept at every width is the
    size, because on a metered link it is the whole question.
    """
    mark = "~" if not option.exact else " "
    if width < WIDE:
        line = f" {human(option.size):>9}{mark} {option.label}"
    else:
        line = (
            f" {human(option.size):>10}{mark} "
            f"{option.label:<16} {option.fmt:<12} {option.detail}"
        )
    # The nights note is appended before the clip, not after, so that on a
    # terminal narrow enough to lose something it is the codec detail that
    # goes and not the warning that this will take a week.
    note = nights_note(option.size)
    return (line[: max(0, width - len(note))] + note)[:width]


def result_row(
    result: Result, width: int, queued: bool = False, tick: int | None = None
) -> list[str]:
    """One search hit, as the one or two lines there is room for.

    Five facts and a 40-column phone do not share a line without mutilating the
    title, and the title is the one a choice is actually made from — so below
    :data:`WIDE` the title gets a line of its own and everything else sits
    under it.

    The tail is composed before the channel is fitted into what is left, rather
    than clipping the finished line: clipping would drop the length and the
    age, which are two of the five things this screen exists to say. The
    channel is the one that can afford to lose its end; the views are next,
    and go whole or not at all.

    *tick* is the scroll step for a title too long for its room, and ``None``
    is "do not move" — which is every row but the one under the cursor, and
    every caller with no clock at all (:func:`list_results`, printing to a
    pipe). Only one row moves because a list where every line slides is a list
    nothing can be read off, and the cursor is the row a choice is being made
    on.
    """
    when = age(result.timestamp)
    long = clock(result.duration, result.live)
    seen = views(result.views)
    channel = result.channel or "?"
    mark = "✓" if queued else " "
    room = title_room(result, width)
    title = fit(result.title, room) if tick is None else marquee(
        result.title, room, tick
    )

    if width >= WIDE:
        tail = wide_tail(result)
        # mark, a space, the title, two spaces, the tail — and one column in
        # hand, because a line drawn into the last cell is a wrapped line.
        return [f"{mark} {title:<{room}}  {tail}"[: width - 1]]

    # Two columns for the mark whether or not there is one, so that queueing a
    # result does not shift its title one to the right of its neighbours'.
    prefix = "✓ " if queued else "  "
    tail = f"{when} · {long}"
    # Right of the length, as on the wide row; left out rather than left
    # blank when there is no count, since this line is a sentence, not columns.
    # Also left out when it would not fit beside the narrowest channel: the
    # line's end is what gets clipped, and "34M" clipped to "34" is a count
    # shown as a millionth of itself.
    if seen and len(tail) + len(seen) + 3 <= width - 10:
        tail += f" · {seen}"
    # The channel's room, not the title's — a different line and a different
    # sum, named apart so the two cannot be confused for one another.
    channel_room = max(3, width - 7 - len(tail))
    return [
        (prefix + title)[: width - 1],
        # Packed left and not padded into a column: the age and the length are
        # different lengths on every row, so a column here would put the dots
        # in a different place on each line and read as a ragged table rather
        # than as the sentence it is.
        f"   {fit(channel, channel_room)} · {tail}"[: width - 1],
    ]


def _height_of(label: str) -> int | None:
    """The resolution a format label leads with, if it leads with one."""
    found = re.match(r"(\d+)p", label)
    return int(found.group(1)) if found else None


def preferred_index(options: list[Choice], remembered: dict | None) -> int:
    """Where the cursor opens: the last format chosen, or the top of the list.

    Tiers rather than one comparison, because the exact format a video offers
    varies with the video — the useful memory is "1080p, merged", not the
    string. Falling through to ``0`` is today's behaviour, so a memory that
    matches nothing changes nothing.

    Worth noting this is also the safer default: row 0 is always the largest
    file in the list, and opening there is how a tired thumb queues four
    gigabytes.
    """
    if not remembered:
        return 0
    label = remembered.get("label") or ""
    kind = remembered.get("kind") or ""
    height = _height_of(label)
    tiers = (
        lambda o: o.label == label and o.kind == kind,
        lambda o: (
            height is not None and _height_of(o.label) == height and o.kind == kind
        ),
        lambda o: height is not None and _height_of(o.label) == height,
        lambda o: o.kind == kind,
    )
    for wants in tiers:
        for index, option in enumerate(options):
            if wants(option):
                return index
    return 0


def recalled_format() -> dict | None:
    """The format chosen last time, from the queue's own config file."""
    try:
        from nibbles import expire_runner

        remembered = expire_runner.load_config().get("ytq_last_format")
    except Exception:  # noqa: BLE001 - a convenience, never a blocker
        return None
    return remembered if isinstance(remembered, dict) else None


def remember_format(choice: Choice) -> None:
    """Record the choice, at the moment an item is written and not before.

    Kept in the queue's ``config.json`` beside the destinations rather than in
    a file of its own: it is the same kind of setting, it already has an atomic
    writer, and a second place to look for preferences is how two of them end
    up disagreeing. Written through :func:`save_prefs`, the one guarded write,
    so a ``config.json`` that will not parse is left as it is rather than
    replaced by a file holding this alone — which took the destinations, the
    reserve and the budget with it, and the line saying the file was broken.
    """
    save_prefs({}, last=choice)


#: The characters Android's shared storage refuses in a file name.
REFUSED = re.compile(r'\s*[/\\:*?"<>|]+\s*')

#: A name is capped well under the 255 bytes a file name may be, leaving
#: room for the ``NN-`` prefix, ``.py`` and a container suffix.
NAME_BYTES = 120


def title_name(title: str) -> str:
    """A video's download name: its title, cleaned only of what Android's
    shared storage refuses (``/ \\ : * ? " < > |``) and capped well under 255
    bytes. ``Crust of Rust: Subtyping and Variance`` becomes ``Crust of Rust -
    Subtyping and Variance``: the same name in the queue (behind ``NN-``) and
    in Downloads. One name everywhere (design §6).

    Made from :func:`one_line`'s spelling of the title, the one the screens
    draw: a line break, a tab or a non-breaking space between two words is a
    space between them, where dropping it as unprintable glued the words
    together — a Japanese title spaced with U+3000 lost every space it had."""
    name = REFUSED.sub(" - ", one_line(title))
    name = "".join(ch for ch in name if ch.isprintable() or ch in JOINERS)
    name = re.sub(" +", " ", name).strip(" -.")
    while len(name.encode("utf-8")) > NAME_BYTES:
        name = name[:-1]
    name = name.rstrip(" -.")
    return name or "video"


def codec_families(choice: Choice) -> list[str]:
    """``["avc1", "mp4a"]``: the codec families in a choice, in its order.

    The family is the part before the first dot, with yt-dlp's two spellings
    of VP9 made one. It is what the skip-codecs setting names.
    """
    out = []
    for part in re.split(r"\s*\+\s*", choice.codecs or ""):
        family = part.split(".")[0].strip().lower()
        family = {"vp09": "vp9", "vp8.0": "vp8"}.get(family, family)
        if family and family not in ("none", "?") and family not in out:
            out.append(family)
    return out


def height_of(choice: Choice) -> int | None:
    """A video choice's height (``480``), or ``None`` for audio."""
    return None if choice.kind == "audio" else _height_of(choice.label)


def bitrate_of(choice: Choice) -> int | None:
    """An audio choice's bitrate in kb/s (``129``), or ``None``."""
    found = re.match(r"audio (\d+)k", choice.label)
    return int(found.group(1)) if choice.kind == "audio" and found else None


def tier_of(choice: Choice) -> tuple[str, int]:
    """``("video", 480)`` or ``("audio", 129)``: the button a choice is under."""
    if choice.kind == "audio":
        return ("audio", bitrate_of(choice) or 0)
    return ("video", height_of(choice) or 0)


def in_tier(options: list[Choice], tier: tuple[str, int]) -> list[Choice]:
    return [o for o in options if tier_of(o) == tier]


def pick_in_tier(
    options: list[Choice], tier: tuple[str, int], rule: str, skip: list[str]
) -> tuple[Choice | None, list[str]]:
    """The choice Smallest or Largest makes inside a tier, and the codec
    families it passed over to make it.

    A choice whose codecs the skip list names is passed over when anything
    else in the tier is left; the families passed over are only those of
    choices that would have won otherwise, which is what ``skipped vp9`` on
    the sheet reports. With nothing else left, the skipped ones are offered
    after all: a tier is never emptied by a preference.
    """
    tier_options = in_tier(options, tier)
    if not tier_options:
        return None, []
    order = sorted(tier_options, key=lambda o: o.size, reverse=rule == "largest")
    kept = [o for o in order if not set(codec_families(o)) & set(skip)]
    if not kept:
        return order[0], []
    chosen = kept[0]
    passed: list[str] = []
    for o in order:
        if o is chosen:
            break
        for family in codec_families(o):
            if family in skip and family not in passed:
                passed.append(family)
    return chosen, passed


#: The heights the quality buttons start from, before anything is learned.
DEFAULT_HEIGHTS = (240, 480, 720)
#: And the codecs passed over before anything is set.
DEFAULT_SKIP: tuple[str, ...] = ()


def prefs() -> dict:
    """The YouTube half's remembered choices, from the queue's config file:
    ``rule`` (``{"video": "smallest", "audio": "largest"}``), ``heights``
    (``{"480": 12}``, how often each was picked), ``chips`` (heights set by
    hand, or absent), ``skip`` (codec families to pass over)."""
    try:
        from nibbles import expire_runner

        found = expire_runner.load_config().get("ytq_prefs")
    except Exception:  # noqa: BLE001 - a convenience, never a blocker
        return {}
    return found if isinstance(found, dict) else {}


def save_prefs(changes: dict, last: Choice | None = None) -> str | None:
    """Merge *changes* into the remembered choices, and with *last* record it
    as the format chosen last (:func:`recalled_format`) — in one write.
    Refused (with the reason) when ``config.json`` will not parse, because
    writing over a file that could not be read is how the destinations get
    lost: every write the YouTube half makes to that file comes through here."""
    try:
        from nibbles import expire_runner

        problem = expire_runner.config_problem()
        if problem:
            return problem
        config = expire_runner.load_config()
        if changes:
            current = config.get("ytq_prefs")
            current = dict(current) if isinstance(current, dict) else {}
            current.update(changes)
            config["ytq_prefs"] = current
        if last is not None:
            config["ytq_last_format"] = {"label": last.label, "kind": last.kind}
        expire_runner.save_config(config)
    except Exception as exc:  # noqa: BLE001 - a convenience, never a blocker
        return str(exc)
    return None


def rule_for(kind: str, remembered: dict | None = None) -> str:
    """``smallest`` or ``largest``: what the sheet opens on, per kind."""
    rules = (remembered if remembered is not None else prefs()).get("rule") or {}
    got = rules.get("audio" if kind == "audio" else "video") if isinstance(rules, dict) else None
    return got if got in ("smallest", "largest") else ("largest" if kind == "audio" else "smallest")


def chip_heights(remembered: dict | None = None, count: int = 3) -> list[int]:
    """The heights the quality buttons offer, in height order: set by hand,
    or the *count* picked most often, or :data:`DEFAULT_HEIGHTS`."""
    got = remembered if remembered is not None else prefs()
    chips = got.get("chips")
    if isinstance(chips, list) and all(isinstance(h, int) and h > 0 for h in chips) and chips:
        return sorted(set(chips))[:max(count, len(chips))]
    counts = got.get("heights")
    learned: list[int] = []
    if isinstance(counts, dict):
        pairs = []
        for key, n in counts.items():
            if str(key).isdigit() and isinstance(n, int) and n > 0:
                pairs.append((n, int(key)))
        learned = [h for _, h in sorted(pairs, key=lambda p: (-p[0], p[1]))]
    for h in DEFAULT_HEIGHTS:
        if h not in learned:
            learned.append(h)
    return sorted(learned[:count])


def skip_codecs(remembered: dict | None = None) -> list[str]:
    got = (remembered if remembered is not None else prefs()).get("skip")
    if isinstance(got, list):
        return [str(f).lower() for f in got if isinstance(f, str)]
    return list(DEFAULT_SKIP)


def learn(choice: Choice, rule: str) -> None:
    """Remember a choice that was queued: its height counted, its rule kept
    for its kind, and :func:`remember_format`'s last format — one guarded
    write, so a broken ``config.json`` is refused once and not written over."""
    got = prefs()
    rules = dict(got.get("rule") or {}) if isinstance(got.get("rule"), dict) else {}
    rules["audio" if choice.kind == "audio" else "video"] = rule
    changes: dict = {"rule": rules}
    height = height_of(choice)
    if height:
        counts = dict(got.get("heights") or {}) if isinstance(got.get("heights"), dict) else {}
        counts[str(height)] = int(counts.get(str(height), 0) or 0) + 1
        changes["heights"] = counts
    save_prefs(changes, last=choice)






def already_queued(hits: list[Result]) -> set[int]:
    """Which of these are already queued, downloaded or given up on.

    Asked before anything is probed, because a duplicate noticed here has cost
    nothing and one noticed afterwards has cost an extraction — which on this
    connection is the entire point of noticing it.
    """
    known = set()
    for _, path in items():
        try:
            key = source_of(path.read_text(encoding="utf-8", errors="replace")[:4096])
        except OSError:
            continue
        if key:
            known.add(key)
    return {index for index, hit in enumerate(hits) if hit.key and hit.key in known}








# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def load_json(path: str) -> dict:
    """A saved ``yt-dlp -J`` dump, so a re-pick costs no data. Its words are
    :func:`cleaned` on the way in, as the probe's are."""
    info = json.loads(Path(path).read_text())
    if not isinstance(info, dict):
        raise ProbeError(f"{path} is not a yt-dlp metadata object")
    return cleaned(info)


def list_results(hits: list[Result], width: int) -> int:
    """A saved search, printed. The same rows, without a terminal to curse."""
    for result in hits:
        for line in result_row(result, width):
            print(line)
    return 0


def list_feed(count: int = SUBS_RESULTS, feed: Feed = SUBS) -> int:
    """A signed-in list, printed. The same rows, without a terminal.

    Here for the same reason ``dlq``'s read-only screens are: this is the one
    thing on the feed side that something with no terminal can still ask for —
    a pipe, a script, an ssh session with no tty — and the alternative is that
    the only way to see the feed at all is a full-screen app.
    """
    def refuse(lines: list[str]) -> int:
        """The same words the screen uses, one to a line, on stderr.

        The verdict first and prefixed, the working under it, which is the
        shape ``nibbles status`` prints in — and the reason it is not one long
        line is that these end in a path somebody has to read.
        """
        head, *rest = lines
        print(f"error: {head}", file=sys.stderr)
        for line in rest:
            print(f"  {line}", file=sys.stderr)
        return 1

    state, detail = cookie_state()
    if state in ("none", "missing"):
        return refuse(cookie_advice(state, detail))
    try:
        hits = read_feed(feed, count)
    except ProbeError as exc:
        return refuse([str(exc), *cookie_fix(detail)])
    if not hits:
        return refuse(feed.empty(detail))
    return list_results(hits, shutil.get_terminal_size(fallback=(80, 24)).columns)


def list_formats(url: str, dump: str | None = None) -> int:
    """The same information the TUI shows, for a terminal that cannot curse."""
    try:
        info = load_json(dump) if dump else probe(url)
    except (ProbeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    # A saved search dump is a playlist envelope, and its rows are the ones the
    # results screen draws — not formats, which it has none of.
    if info.get("entries") is not None:
        return list_results(entries(info), width)
    options, unsized = choices(info)
    title = f"{info.get('title')}"
    if width >= WIDE:
        title += f"  [{info.get('extractor_key')}]"
    print(title[:width])
    # The same verdict the format screen shows, for the path with no screen.
    # On stderr so that a pipe reading the table is not handed a row that is
    # not one, and so it survives being redirected away from.
    if withheld(info):
        for line in withheld_advice(cookie_state()[1]):
            print(f"  {line}", file=sys.stderr)
    for option in options:
        line = format_row(option, width)
        if width >= WIDE:
            line += f"  cap {human(option.expect_bytes)}"
        print(line[:width])
    if unsized:
        print(f"  ({unsized} hidden: yt-dlp states no size for them)"[:width])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nibbles",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              nibbles                       search, or paste a URL, then pick
              nibbles search crust of rust  search youtube (~0.1 MB)
              nibbles --list subs           print the feed, write nothing
              nibbles --list wl             print watch later, write nothing
              nibbles URL                   probe (~0.1-0.5 MB), pick, queue
              nibbles --now URL             pick, then start it in the background
              nibbles --list URL            print formats and caps, write nothing
              nibbles --list --from-json F  reprint a saved dump; costs no data

            a plain file URL given to nibbles is queued as a file; the queue
            itself is nibbles queue, or nibbles (status|list|arm|logs).
            docs: github.com/gsfernandes81/nibbles/tree/main/docs"""),
    )
    parser.add_argument(
        "terms",
        nargs="*",
        metavar="URL-OR-WORDS",
        help="a page to download from, or words to search youtube for",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the formats and exit, writing nothing",
    )
    parser.add_argument(
        "--subs",
        action="store_true",
        help="open the subscription feed instead of searching; needs the "
        "cookies the yt-dlp config already points at",
    )
    parser.add_argument(
        "--wl",
        "--watch-later",
        dest="wl",
        action="store_true",
        help="open your watch later playlist instead of searching; needs the "
        "same cookies as --subs",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="start it in the background instead of waiting for the nightly "
        "window; the same as Now on the video sheet",
    )
    parser.add_argument(
        "--dest",
        metavar="DIR",
        help="put this one somewhere other than the configured video or audio "
        "directory (nibbles dest sets those)",
    )
    parser.add_argument(
        "--link",
        action="store_true",
        help=argparse.SUPPRESS,  # nibbles <x>: the terms are one link yt-dlp takes
    )
    parser.add_argument(
        "--from-json",
        metavar="FILE",
        help="use a saved 'yt-dlp -J' dump or search instead of asking again; "
        "costs no data",
    )
    # Intermixed: the words are one list wherever a flag falls among them
    # (``ytsearch:crust --now of rust``), in the order they were typed.
    args = parser.parse_intermixed_args(argv)
    first = " ".join(args.terms).strip()

    if args.subs and args.wl:
        parser.error("--subs and --wl are two lists; open one, and the other "
                     "is a word away in the field")
    if args.subs and first:
        parser.error("--subs is the whole request; it takes no words or URL")
    if args.wl and first:
        parser.error("--wl is the whole request; it takes no words or URL")

    if args.list:
        if args.now:
            parser.error("--list writes nothing, so there is nothing for --now to run")
        if args.subs:
            if args.from_json:
                parser.error("--subs asks youtube; --from-json reads a saved dump")
            return list_feed()
        if args.wl:
            if args.from_json:
                parser.error("--wl asks youtube; --from-json reads a saved dump")
            return list_feed(feed=WATCH_LATER)
        if not (first or args.from_json):
            parser.error("--list needs a URL or --from-json")
        if first and not (args.link or looks_like_url(first)):
            parser.error("--list prints one video's formats, so it needs a URL")
        return list_formats(first, args.from_json)

    preloaded = None
    if args.from_json:
        try:
            preloaded = load_json(args.from_json)
        except (ProbeError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.link and first:
        first = LINK_KEY + first
    if args.subs:
        # `--subs` is the flag spelling of the word the entry field already
        # takes, handed to `app` down that one road rather than as a second
        # way in. One door: whatever routes `subs` routes this.
        first = ":subs"
    elif args.wl:
        first = ":wl"

    if not sys.stdout.isatty():
        print(
            "nibbles needs a terminal; use --list <url>, --list subs or "
            "--list wl otherwise",
            file=sys.stderr,
        )
        return 2

    dest = str(Path(args.dest).expanduser()) if args.dest else "video"
    # A list, because a session can queue several items now. The download-now
    # case is already running by the time this returns: it was handed to a
    # detached `nibbles now`, so there is nothing left here to wait for.
    # The one road: ``subs`` and ``wl`` reach the app as the words the
    # search field takes, and the app routes them to the Feed and Later tabs.
    from nibbles import app

    receipts = app.run("search", first or None, preloaded, args.now, dest)
    if not receipts:
        print("nothing queued")
        return 0
    for line in receipts:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
