#!/usr/bin/env python3
"""nibbles: queue YouTube videos and files, fetch them before the data expires.

One app, five tabs along the bottom: **Search · Feed · Later · Queue · More**.
``nibbles`` opens on Search and ``nibbles queue`` on Queue; it is the one
command (``nibbles help``).
Buttons first, keys second, laid out for a phone in portrait:
``design/design.md`` is the spec this follows.

This module is the loop: one :class:`tui.Session`, the screen on top, the
guards on taps, the pressed flash, sheets over a dimmed tab, and the status
bar along the foot. The screens live in ``yt_screens.py`` (Search, Feed,
Later) and ``queue_screens.py`` (Queue, More); both import the logic modules
(``ytq``, ``expire_ui``, ``expire_sched``) that the command line uses too.

It is also the door (:func:`main`), and every word the door answers without
the app — ``status``, ``dump``, ``arm``, ``--list``, a file's URL, the
detached ``nibbles now`` — comes through this module. So the screens' own
modules (``tui``, ``widgets``, ``shell``, and bewitch and blessed behind them)
are imported where the app uses them, never at the top: a word that prints
must not need them, and a stale bewitch checkout took every one of those words
down with an import traceback, ``dump`` — the bug report — among them.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nibbles import tui
    from nibbles import widgets as w
    from nibbles.shell import Screen, Sheet

#: A file to log every event to, for a test chasing a lost tap.
_DEBUG = os.environ.get("NIBBLES_DEBUG", "")

#: Tab indices, in the order they sit along the bottom (``widgets.TABS``
#: names them, and :class:`App` builds them in this order). The screens go
#: to a tab by these names, never by its number.
SEARCH, FEED, LATER, QUEUE, MORE = range(5)
START = {"search": SEARCH, "feed": FEED, "later": LATER, "queue": QUEUE, "more": MORE}


class App:
    """The running app: which tab, which sheets, what is being fetched."""

    def __init__(self, session: tui.Session | None, start: int = SEARCH,
                 first: str | None = None, preloaded: dict | None = None,
                 now: bool = False, dest: str = "video",
                 size: tuple[int, int] | None = None) -> None:
        from nibbles import queue_screens as qs
        from nibbles import tui
        from nibbles import widgets as w
        from nibbles import yt_screens as ys

        self.session = session
        self.width, self.height = size or (session.size if session else (40, 24))
        self.guard = tui.Guard()
        self.pressed: str | None = None
        self.pressed_until = 0.0
        self.jobs: list[tuple[tui.Job, Screen]] = []
        self.sheets: list[Sheet] = []
        self.receipts: list[str] = []
        self.said = ""
        self.said_tone = None
        self.done = False
        self.hits = w.HitMap()
        self.last_tap: tui.Tap | None = None
        #: The tab on top was reached by stepping (Tab, Shift-Tab) rather
        #: than chosen: passed on the way to another, it may be gone again
        #: before anybody looks at it (:meth:`switch`).
        self.stepped = False
        self.queue = qs.QueueModel(self)
        self.yt = ys.YouTube(self, dest=dest, now=now)
        self.tabs: list[Screen] = [
            ys.SearchTab(self),
            ys.FeedTab(self, ys.ytq.SUBS),
            ys.FeedTab(self, ys.ytq.WATCH_LATER),
            qs.QueueTab(self),
            qs.MoreTab(self),
        ]
        self.tab = start
        self.tabs[self.tab].shown(self)
        if preloaded is not None or first:
            self.yt.begin(first, preloaded)

    # State changes the screens ask for ----------------------------------- #

    @property
    def top(self) -> Screen:
        return self.sheets[-1] if self.sheets else self.tabs[self.tab]

    def start(self, job: tui.Job, owner: Screen) -> tui.Job:
        """Run *job* in the background; *owner* hears when it is done."""
        if self.session is not None:
            self.session.start(job)
        else:
            # Tests drive the app without a terminal: the job still runs on
            # its own thread, with no loop to wake, and the test hands its
            # Done back the way the loop would.
            job.run(lambda: None)
        self.jobs.append((job, owner))
        return job

    def running(self) -> list[tui.Job]:
        """The jobs still going, but for the quiet hand-offs to Android: what
        the spinner turns for."""
        return [job for job, _ in self.jobs if not job.finished and not job.quiet]

    def unheard(self) -> list[tui.Job]:
        """Every job whose owner has not yet heard it is done: running, or
        finished with its :class:`tui.Done` still to be delivered.

        What the loop waits on. Not :meth:`running`: a job that finishes
        while a frame is being drawn would be left out of the next wait,
        its answer never delivered, and the sheet waiting on it would spin
        no more and never fill.
        """
        return [job for job, _ in self.jobs]

    def stop_newest(self) -> bool:
        """Stop (``x``): cancel the newest fetch still running.

        A fetch (:attr:`tui.Job.fetch`), never the newest job of any kind:
        glancing at More starts a question to Android's scheduler, and ``x``
        back on Feed cancelled that — which killed nothing, threw its answer
        away (an arming done but never said) and left the feed read beside
        ``x stop`` spending.
        """
        live = [job for job in self.running() if job.fetch and not job.cancelled]
        if not live:
            return False
        live[-1].cancel()
        return True

    def open(self, sheet: Sheet) -> None:
        self.sheets.append(sheet)
        self.guard.opened_by(self.last_tap)
        sheet.shown(self)

    def close(self, sheet: Sheet | None = None) -> None:
        if not self.sheets:
            return
        if sheet is None or sheet is self.sheets[-1]:
            self.sheets.pop()
        elif sheet in self.sheets:
            self.sheets.remove(sheet)
        self.guard.opened_by(self.last_tap)
        self.top.shown(self)

    def switch(self, tab: int, step: bool = False) -> None:
        """*tab* on top. *step*: reached by Tab or Shift-Tab, which pass
        every tab between where they start and where they stop; a tab that
        spends when it is first shown (Feed, Later) waits to be stopped on
        (``yt_screens.DWELL``) rather than spending on the way past."""
        self.sheets.clear()
        if tab != self.tab:
            self.said = ""
        self.tab = tab
        self.stepped = step
        self.guard.opened_by(self.last_tap)
        self.tabs[tab].shown(self)

    def say(self, text: str, tone=None) -> None:
        """What a change did, on the line above the tabs."""
        self.said = text
        self.said_tone = tone

    def receipt(self, text: str) -> None:
        """A line printed once the terminal is given back."""
        self.receipts.append(text)

    def quit(self) -> None:
        self.done = True

    def flash(self, id: str) -> None:
        from nibbles import tui

        self.pressed = id
        self.pressed_until = time.monotonic() + tui.PRESSED

    # Drawing ------------------------------------------------------------- #

    def compose(self) -> w.Block:
        from nibbles import widgets as w

        W, H = self.width, self.height
        # A pressed button fills for one frame (tui.PRESSED), wherever it is:
        # cleared here, at the one place every frame passes, and not only for
        # the Surface — the sheets and the window card read ``app.pressed``,
        # and the last button tapped on one stayed filled until the next tap.
        if self.pressed is not None and time.monotonic() >= self.pressed_until:
            self.pressed = None
        pressed = self.pressed
        s = w.Surface(W, H, pressed)
        tab = self.tabs[self.tab]
        if hasattr(tab, "settle"):
            tab.settle(self)
        if tab.fullscreen:
            tab.draw(self, s, H)
        else:
            said = 1 if self.said else 0
            room = max(0, H - 4 - said)
            tab.draw(self, s, room)
            if said:
                s.put(w.text(self.said, W, self.said_tone or w.T.info), 0, H - 5)
            s.put(w.tab_bar(self.tab, W, self.queue.status(W)), 0, H - 4)
        if self.sheets:
            under = s.render()
            s = w.Surface(W, H, pressed)
            s.put(w.dim(under))
            s.target("outside", 0, 0, W, H)
            self.sheets[-1].draw(self, s, H)
        self.hits = s.hits
        return s.render()

    def next_wake(self) -> float | None:
        """How long the loop may sleep. ``None``: until something happens."""
        now = time.monotonic()
        waits = []
        if self.pressed and now < self.pressed_until:
            waits.append(self.pressed_until - now)
        if self.running():
            waits.append(0.1)
        for screen in (self.tabs[self.tab], *self.sheets[-1:]):
            got = screen.wake(self)
            if got is not None:
                waits.append(got)
        got = self.queue.wake()
        if got is not None:
            waits.append(got)
        return max(0.0, min(waits)) if waits else None

    def tick(self, now: float | None = None) -> None:
        """Before each frame: the queue's reading, and whatever the tab on
        top was waiting on time for (a list stopped on, read once the keys
        have rested there)."""
        self.queue.tick()
        self.tabs[self.tab].tick(self, now)

    # Events -------------------------------------------------------------- #

    def handle(self, event: tui.Event) -> None:
        from nibbles import tui

        if _DEBUG:
            with open(_DEBUG, "a") as log:
                log.write(f"{event!r}\n")
        if isinstance(event, tui.Resize):
            self.width, self.height = event.width, event.height
        elif isinstance(event, tui.Done):
            for pair in list(self.jobs):
                job, owner = pair
                if job is not event.job:
                    continue
                self.jobs.remove(pair)
                if not job.cancelled:
                    owner.done(self, job)
                else:
                    # Not every owner is a screen (the queue's model owns its
                    # readings), so not every owner has a word for a stop.
                    cancelled = getattr(owner, "cancelled", None)
                    if cancelled:
                        cancelled(self, job)
        elif isinstance(event, tui.Tap):
            self._tap(event)
        elif isinstance(event, tui.Scroll):
            self.top.scroll(self, event)
        elif isinstance(event, tui.Key):
            self._key(event.name)
        elif isinstance(event, tui.Paste):
            # Into the field on top, if there is one; nowhere else, and never
            # as keys, so a paste cannot submit, stop, quit or open a thing.
            self.last_tap = None
            paste = getattr(self.top, "paste", None)
            if paste is not None:
                paste(self, event.text)

    def _tap(self, event: tui.Tap) -> None:
        if not self.guard.allows(event):
            return
        self.last_tap = event
        hit = self.hits.at(event.x, event.y)
        if self.sheets:
            sheet = self.sheets[-1]
            if hit is None or hit.id == "outside":
                self.close(sheet)
                return
            if hit.id == "close":
                self.close(sheet)
                return
            if hit.id == "sheet":
                return
            if hit.id == "sheet-bar":
                if sheet.layout and sheet.layout.scrolls:
                    room = sheet.layout.room
                    frac = (event.y - sheet.layout.body_y) / max(1, room - 1)
                    sheet.offset = round(frac * (sheet.layout.total - room))
                return
            if not hit.id.startswith("row"):
                self.flash(hit.id)
            sheet.tap(self, hit, event)
            return
        if hit is None:
            return
        if hit.id == "tab":
            self.switch(hit.data)
            return
        if not hit.id.startswith("row"):
            self.flash(hit.id)
        self.tabs[self.tab].tap(self, hit, event)

    def _key(self, key: str) -> None:
        self.last_tap = None
        top = self.top
        if top.key(self, key):
            return
        if top.typing:
            return
        if key == "q":
            self.quit()
        elif key == "x":
            self.stop_newest()
        elif key == "tab":
            self.switch((self.tab + 1) % len(self.tabs), step=True)
        elif key == "btab":
            self.switch((self.tab - 1) % len(self.tabs), step=True)

    # The loop ------------------------------------------------------------ #

    def run(self) -> list[str]:
        assert self.session is not None
        try:
            # nomut: start — a mutant in the loop does not fail a test, it hangs a
            # terminal until the timeout kills it; the loop is checked on a pty.
            while not self.done:
                self.tick()
                self.session.show(self.compose())
                event = self.session.read(self.next_wake(), self.unheard())
                if event is not None:
                    self.handle(event)
            # nomut: end
        finally:
            self.closing()
        return self.receipts

    def closing(self) -> None:
        """On every way out — ``q``, ctrl-c, a hangup, an exception — cancel
        every job still running, which kills a fetch's yt-dlp the way ``x``
        does. That child runs in a session of its own, so the terminal's
        signals never reach it, and its timeout lives in a thread that dies
        with the app: left alone, it went on to fetch the whole listing with
        nobody to read it. A quiet hand-off to Android is left to finish, and
        a ``nibbles now`` download is detached on purpose and no job of this
        app's."""
        for job in self.running():
            job.cancel()
        self.queue.closing()


def run(start: str = "search", first: str | None = None, preloaded: dict | None = None,
        now: bool = False, dest: str = "video") -> list[str]:
    """The app on this terminal; the receipts once the terminal is back."""
    from nibbles import tui

    with tui.Session() as session:
        app = App(session, START[start], first, preloaded, now, dest)
        try:
            return app.run()
        except KeyboardInterrupt:
            return app.receipts


USAGE = """\
usage: nibbles [WHERE | COMMAND | URL] ...

the app:
  nibbles                    the app, on Search
  nibbles search WORDS       ...searching YouTube for WORDS (~0.1 MB)
  nibbles queue              ...on the queue (alias: ui)
  nibbles more               ...on the settings
  nibbles URL                a video page: its sheet (--now starts it);
                             a file: queued as a download (asks its
                             headers first, ~1 KB, to tell which)

with no app:
  nibbles --list URL         a video's formats and caps; writes nothing
  nibbles --list subs | wl   print the feed or Watch Later
  nibbles status             what happens next, and what it turns on
  nibbles list               every download, and how much of it is here
  nibbles path NAME          where a finished download landed
  nibbles dest | settings    show or set where files go, and the window
  nibbles run-now [--blind]  run the whole queue now
  nibbles arm | cancel       register or unregister the nightly job
  nibbles logs | dump

docs: github.com/gsfernandes81/nibbles/tree/main/docs"""

#: The words that open the app on a tab (``ui`` is dlq's word for the queue).
#: Feed and Later have none: they are a tap away, and reading either spends.
TAB_WORDS = {"search": "search", "queue": "queue", "ui": "queue", "more": "more"}

#: What only a video page takes, and what only a file download takes: either
#: settles what a URL is without asking it.
VIDEO_FLAGS = ("--now", "--list", "--from-json")
FILE_FLAGS = ("--name", "--number", "--sha256", "--expect-bytes", "--probe",
              "--dry-run", "--again")

#: The flags whose value is the word after them (``--dest DIR``): ytq's and
#: dlq's both. That word is the flag's, never the link — taken for one, a
#: documented ``nibbles --dest DIR URL`` asked yt-dlp about the directory and
#: was refused, and a value shaped like a host was asked for its headers.
VALUE_FLAGS = ("--dest", "--from-json", "--name", "--number", "--sha256",
               "--expect-bytes")

#: The words ``--list`` prints with no URL: the two signed-in lists.
LISTS = {"subs": "--subs", "wl": "--wl"}

#: The queue's verbs nibbles answers with no app; ``queue`` (its raw file
#: listing) and ``ui`` are not among them, ``queue`` being the tab. Nor are
#: ``--now`` and ``--list``, which the queue takes as ``now`` and ``list``
#: (``expire_sched.ALIASES``): here they are a video's flags, as the usage
#: and the completions say, so ``nibbles --now <id>`` reaches the video —
#: only a bare ``nibbles --list`` is the queue's listing.
QUEUE_VERBS = ("status", "list", "path", "dest", "settings", "logs", "dump", "run-now",
               "arm", "cancel", "now", "names")


def _flag(arg: str) -> str:
    return arg.split("=")[0]


def _target(argv: list[str]) -> int | None:
    """Where in *argv* the link or the words are: the first word that is
    neither a flag nor a flag's value. ``--dest=DIR`` carries its own."""
    value = False
    for at, arg in enumerate(argv):
        if value:
            value = False
        elif arg.startswith("-"):
            value = arg in VALUE_FLAGS
        else:
            return at
    return None


def main(argv: list[str] | None = None) -> int:
    """``nibbles``: the one command. Every word it takes goes to the module
    that always answered it; what changed is only the door (2026-10-10, the
    owner's: one executable, ``nibbles <url>`` for a page or a file alike)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    # An installed copy makes its queue root the first time, and keeps the
    # runner's launcher pointing at wherever an upgrade put the package. A
    # checkout, or a root EXPIRE_HOME names, is never written.
    from nibbles import home

    for line in home.ensure():
        print(line, file=sys.stderr)
    if not argv:
        return _open("search", [])
    head, rest = argv[0], argv[1:]
    if head in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    if head in TAB_WORDS:
        return _open(TAB_WORDS[head], rest)
    if "--list" in argv and any(arg in LISTS for arg in argv):
        word = next(arg for arg in argv if arg in LISTS)
        from nibbles import ytq

        return ytq.main([LISTS[word], *(arg for arg in argv if arg != word)])
    if "--from-json" in map(_flag, argv):
        from nibbles import ytq

        return ytq.main(argv)
    words = [arg for arg in argv if arg != "--yes"]
    if words == ["--list"] or (
        words and words[0] in QUEUE_VERBS and not any(_looks_like_url(arg) for arg in words)
    ):
        from nibbles import expire_sched

        return expire_sched.main(argv)
    # Not a word nibbles has: what yt-dlp would take. Asked last, because the
    # last of its questions is yt-dlp's own extractors, and that is a second.
    at = _target(argv)
    if at is not None:
        from nibbles import ytq

        taken = ytq.read_input(argv[at])
        if taken is not None:
            what, value = taken
            # By place, not by value: a flag's value spelled like the link
            # stays, and the flags stay where they were typed.
            before, after = argv[:at], argv[at + 1:]
            if what == "search":
                # The words where the target was, so they are searched in
                # the order typed (``ytsearch:crust of rust``, unquoted).
                return ytq.main([*before, *value.split(), *after])
            rest = before + after
            if ytq.looks_like_url(value):
                return _url(value, rest)
            if ytq.looks_like_feed(value):
                # yt-dlp's own word for a signed-in list (``:ytsubs``): the
                # field takes it for the Feed or Later tab, so it goes in as
                # the field would have it. Marked a link, it was probed as a
                # video — the whole feed, fully extracted.
                return ytq.main([value, *rest])
            # Taken by one of yt-dlp's extractors though no link (a bare
            # video id): a page by definition, and the app is told it is one.
            return ytq.main(["--link", value, *rest])
    print(f"nibbles: {head!r} is not a command; nibbles search {' '.join(argv)} "
          "searches YouTube for it", file=sys.stderr)
    print("         nibbles help lists the commands", file=sys.stderr)
    return 2


def _looks_like_url(text: str) -> bool:
    from nibbles import ytq

    return ytq.looks_like_url(text)


def _url(url: str, rest: list[str]) -> int:
    """A page to its video sheet, a file to the queue: told apart by what the
    flags already say, else by YouTube's own hosts, else by asking the
    server's headers (``dlq.kind_of``) — never by guessing from the name.
    yt-dlp's generic extractor takes both, so "would yt-dlp take it" cannot
    tell them apart; the headers can, and a file fetched by Range resumes
    where yt-dlp's would start again.

    The link goes on in one spelling, whichever way it goes and whatever the
    flags say (``dlq.normal_url``): with its scheme, and what is not ASCII in
    it escaped. Passed on as typed, a link with a Cyrillic file name, or a
    ``www.`` one sent to the file queue by its flags, ended in a traceback
    rather than a question or a sentence."""
    from nibbles import dlq
    from nibbles import ytq

    full = dlq.normal_url(url)
    argv = [full, *rest]
    flags = {_flag(arg) for arg in rest if arg.startswith("-")}
    if flags & set(FILE_FLAGS):
        kind = "file"
    elif flags & set(VIDEO_FLAGS):
        kind = "page"
    else:
        try:
            kind = dlq.kind_of(full)
        except dlq.ProbeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if kind == "file":
        return dlq.main(argv)
    return ytq.main(argv)


def _open(tab: str, rest: list[str]) -> int:
    """The app on *tab*; ``search`` takes the words to search for, through
    ``ytq.main``, so the receipts are printed the way they always were."""
    if tab == "search" and rest:
        from nibbles import ytq

        return ytq.main(rest)
    if rest:
        print(f"nibbles {tab} takes nothing after it", file=sys.stderr)
        return 2
    if tab == "queue":
        # Through the queue's own door, which names a broken checkout first.
        from nibbles import expire_sched

        return expire_sched.main(["ui"])
    if not sys.stdout.isatty():
        print("nibbles needs a terminal; nibbles help lists what prints without one",
              file=sys.stderr)
        return 2
    for line in run(tab):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
