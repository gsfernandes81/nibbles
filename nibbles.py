#!/usr/bin/env python3
"""nibbles: queue YouTube videos and files, fetch them before the data expires.

One app, five tabs along the bottom: **Search · Feed · Later · Queue · More**.
``ytq`` opens on Search, ``ytq subs`` on Feed, ``ytq wl`` on Later, ``dlq`` on
Queue, and a bare ``nibbles`` on Search. Buttons first, keys second, laid out
for a phone in portrait: ``design/design.md`` is the spec this follows.

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


def main(argv: list[str] | None = None) -> int:
    """``nibbles``: the app, opened on Search (or the tab named)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in START:
        start, argv = argv[0], argv[1:]
    else:
        start = "search"
    if argv:
        print("usage: nibbles [search|feed|later|queue|more]", file=sys.stderr)
        print("       ytq and dlq take the old arguments", file=sys.stderr)
        return 2
    if not sys.stdout.isatty():
        print("nibbles needs a terminal; dlq status and ytq --list print", file=sys.stderr)
        return 2
    for line in run(start):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
