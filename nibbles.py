#!/usr/bin/env python3
"""nibbles: queue YouTube videos and files, fetch them before the data expires.

One app, five tabs along the bottom: **Search · Feed · Later · Queue · More**.
``nibbles`` opens on Search, ``nibbles subs`` on Feed, ``nibbles wl`` on Later
and ``nibbles queue`` on Queue; it is the one command (``nibbles help``).
Buttons first, keys second, laid out for a phone in portrait:
``design/design.md`` is the spec this follows.

This module is the loop: one :class:`tui.Session`, the screen on top, the
guards on taps, the pressed flash, sheets over a dimmed tab, and the status
bar along the foot. The screens live in ``yt_screens.py`` (Search, Feed,
Later) and ``queue_screens.py`` (Queue, More); both import the logic modules
(``ytq``, ``expire_ui``, ``expire_sched``) that the command line uses too.
"""

from __future__ import annotations

import sys
import time

import tui
import widgets as w
from shell import Screen, Sheet

import os

#: A file to log every event to, for a test chasing a lost tap.
_DEBUG = os.environ.get("NIBBLES_DEBUG", "")

#: Tab indices, in the order they sit along the bottom.
SEARCH, FEED, LATER, QUEUE, MORE = range(5)
START = {"search": SEARCH, "feed": FEED, "later": LATER, "queue": QUEUE, "more": MORE}


class App:
    """The running app: which tab, which sheets, what is being fetched."""

    def __init__(self, session: tui.Session | None, start: int = SEARCH,
                 first: str | None = None, preloaded: dict | None = None,
                 now: bool = False, dest: str = "video",
                 size: tuple[int, int] | None = None) -> None:
        import queue_screens as qs
        import yt_screens as ys

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
        for tab in self.tabs:
            tab._app = self
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
        else:  # tests drive the app without a terminal: run it inline
            job.run(lambda: None)
        self.jobs.append((job, owner))
        return job

    def running(self) -> list[tui.Job]:
        return [job for job, _ in self.jobs if not job.finished]

    def stop_newest(self) -> bool:
        """Stop (``x``): cancel the newest fetch still running."""
        live = [job for job, _ in self.jobs if not job.finished and not job.cancelled]
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

    def switch(self, tab: int) -> None:
        self.sheets.clear()
        if tab != self.tab:
            self.said = ""
        self.tab = tab
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
        self.pressed = id
        self.pressed_until = time.monotonic() + tui.PRESSED

    # Drawing ------------------------------------------------------------- #

    def compose(self) -> w.Block:
        W, H = self.width, self.height
        pressed = self.pressed if time.monotonic() < self.pressed_until else None
        s = w.Surface(W, H, pressed)
        tab = self.tabs[self.tab]
        if getattr(tab, "fullscreen", False):
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

    # Events -------------------------------------------------------------- #

    def handle(self, event: tui.Event) -> None:
        if _DEBUG:
            with open(_DEBUG, "a") as log:
                log.write(f"{event!r}\n")
        if isinstance(event, tui.Resize):
            self.width, self.height = event.width, event.height
        elif isinstance(event, tui.Done):
            for pair in list(self.jobs):
                if pair[0] is event.job:
                    self.jobs.remove(pair)
                    if not event.job.cancelled:
                        pair[1].done(self, event.job)
                    elif pair[1] is not None:
                        cancelled = getattr(pair[1], "cancelled", None)
                        if cancelled:
                            cancelled(self, event.job)
        elif isinstance(event, tui.Tap):
            self._tap(event)
        elif isinstance(event, tui.Scroll):
            self.top.scroll(self, event)
        elif isinstance(event, tui.Key):
            self._key(event.name)

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
            self.switch((self.tab + 1) % len(self.tabs))
        elif key == "btab":
            self.switch((self.tab - 1) % len(self.tabs))

    # The loop ------------------------------------------------------------ #

    def run(self) -> list[str]:
        assert self.session is not None
        # nomut: start — a mutant in the loop does not fail a test, it hangs a
        # terminal until the timeout kills it; the loop is checked on a pty.
        while not self.done:
            self.queue.tick()
            self.session.show(self.compose())
            event = self.session.read(self.next_wake(), self.running())
            if event is not None:
                self.handle(event)
        # nomut: end
        self.queue.closing()
        return self.receipts


def run(start: str = "search", first: str | None = None, preloaded: dict | None = None,
        now: bool = False, dest: str = "video") -> list[str]:
    """The app on this terminal; the receipts once the terminal is back."""
    with tui.Session() as session:
        app = App(session, START[start], first, preloaded, now, dest)
        try:
            return app.run()
        except KeyboardInterrupt:
            return app.receipts


USAGE = """\
usage: nibbles [WHERE | COMMAND | URL] ...

the app, opened on a tab:
  nibbles                    Search (no terminal: the status, printed)
  nibbles search WORDS       search YouTube for WORDS (~0.1 MB)
  nibbles subs               your subscriptions (alias: feed)
  nibbles wl                 your Watch Later (alias: later)
  nibbles queue              the queue (alias: ui)
  nibbles more               the settings
  nibbles URL                that video's sheet; --now starts it

with no app:
  nibbles --list URL         a video's formats and caps; writes nothing
  nibbles --list subs | wl   print the feed or Watch Later
  nibbles file URL           queue a direct file download
  nibbles status             what happens next, and what it turns on
  nibbles list               every download, and how much of it is here
  nibbles path NAME          where a finished download landed
  nibbles dest | settings    show or set where files go, and the window
  nibbles run-now [--blind]  run the whole queue now
  nibbles arm | cancel       register or unregister the nightly job
  nibbles logs | files | dump

docs: ~/nibbles/docs/ytq.md and ~/nibbles/docs/download-queue.md"""

#: The tab words, and what each opens. ``subs``/``wl`` and ``ui`` are the
#: words ytq and dlq used for the same places.
TAB_WORDS = {"search": "search", "feed": "feed", "subs": "feed", "later": "later",
             "wl": "later", "queue": "queue", "ui": "queue", "more": "more"}

#: Flags only the YouTube side takes. Any of them, or a URL anywhere, sends the
#: whole line to ``ytq.main``.
YT_FLAGS = ("--from-json", "--subs", "--wl", "--watch-later", "--dest")

#: The queue's printing verbs, as the queue's own command line spells them;
#: ``files`` is its ``queue`` (the item files), renamed because ``queue`` is
#: the tab.
QUEUE_WORDS = {"files": "queue"}


def _youtube(argv: list[str]) -> bool:
    return any("://" in arg or arg.split("=")[0] in YT_FLAGS for arg in argv)


def main(argv: list[str] | None = None) -> int:
    """``nibbles``: the one command. Every word ytq and dlq took is here, and
    each goes to the module that always answered it; what changed is only the
    door (2026-10-10, the owner's: one executable, never clashing with an old
    ``ytq`` or ``dlq`` still installed)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        if not sys.stdout.isatty():
            # dlq's half to keep pinned: with no terminal, the status.
            import expire_sched

            return expire_sched.main(["status"])
        for line in run("search"):
            print(line)
        return 0
    head, rest = argv[0], argv[1:]
    if head in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    if head == "file":
        import dlq

        return dlq.main(rest)
    if head in TAB_WORDS:
        return _open(TAB_WORDS[head], rest)
    if _youtube(argv):
        import ytq

        return ytq.main(argv)
    if "--list" in argv and any(arg in TAB_WORDS for arg in argv):
        # ``nibbles --list subs``: the feed printed, the same as ``subs --list``.
        word = next(arg for arg in argv if arg in TAB_WORDS)
        return _open(TAB_WORDS[word], [arg for arg in argv if arg != word])
    import expire_sched

    words = [arg for arg in argv if arg != "--yes"]
    verb = QUEUE_WORDS.get(words[0], words[0]) if words else ""
    if verb in expire_sched.ACTIONS or verb in expire_sched.HIDDEN or verb in expire_sched.ALIASES:
        if words and words[0] in QUEUE_WORDS:
            argv = [verb if arg == words[0] else arg for arg in argv]
        return expire_sched.main(argv)
    print(f"nibbles: {head!r} is not a command; nibbles search {' '.join(argv)} "
          "searches YouTube for it", file=sys.stderr)
    print("         nibbles help lists the commands", file=sys.stderr)
    return 2


def _open(tab: str, rest: list[str]) -> int:
    """The app on *tab*, through the module that has always opened it, so the
    cookie checks, ``--list`` and the receipts are theirs."""
    if tab in ("feed", "later"):
        import ytq

        flag = "--subs" if tab == "feed" else "--wl"
        return ytq.main([flag, *rest])
    if tab == "search":
        import ytq

        return ytq.main(rest)
    if rest:
        print(f"nibbles {tab} takes nothing after it", file=sys.stderr)
        return 2
    if tab == "queue":
        import expire_sched

        return expire_sched.main(["ui"])
    if not sys.stdout.isatty():
        print("nibbles needs a terminal; nibbles help lists what prints", file=sys.stderr)
        return 2
    for line in run(tab):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
