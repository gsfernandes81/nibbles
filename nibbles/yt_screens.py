"""The YouTube half: the Search, Feed and Later tabs, the video sheet, Formats.

``design/design.md`` §5 is the spec and ``design/mockups/k-search``,
``k-results``, ``k-sheet*``, ``k-formats`` and ``k-feed`` are how it looks.
Every fetch here is a :class:`tui.Job`: the screen stays live while it runs,
a spinner says what is running, and ``x`` stops the newest.

What spends data, and only on a deliberate act: the search (``⏎ Go``, ~0.1
MB), the format probe (one tap on a row, ~0.3 MB), the feed's first read on
first opening its tab, ``r Re-read``, and the deeper look (``↓ 30 more``, a
tap, ↓ on the last row, or a fresh drag down once the list has rested at the
end). A fling's momentum never fetches.
"""

from __future__ import annotations

import time

from nibbles import shell
from nibbles import tui
from nibbles import widgets as w
from nibbles import ytq
from nibbles.shell import SHORT, Entry, ListView, Notice, Screen, Sheet, spin
from nibbles.widgets import T, Btn, Piece, Surface

APP_NAME = "nibbles"

#: What one search costs, said under the bar.
SEARCH_COST = "~0.1 MB"
#: What one format probe costs, said while it runs.
PROBE_COST = "~0.3 MB"
#: How long the list must rest at its end before a drag down counts as a pull.
REST = 0.5


def feed_mb(count: int) -> str:
    """What reading *count* videos off a feed costs, the total: ``0.6 MB``.

    ``ytq.feed_cost``'s figure (the total, never the increment), drawn as the
    mockup draws it, without the estimate's ``~``."""
    return ytq.feed_cost(count).lstrip("~")


def byline(r: ytq.Result) -> str:
    """``Jon Gjengset · ~3d · 90m34s · 41K``."""
    parts = [r.channel or "?", ytq.age(r.timestamp), ytq.clock(r.duration, r.live)]
    seen = ytq.views(r.views)
    if seen:
        parts.append(seen)
    return " · ".join(parts)


def size_of(choice: ytq.Choice) -> str:
    return ("" if choice.exact else "~") + shell.size(choice.size)


def size_fg(choice: ytq.Choice):
    """The size's colour: green while it fits a night, warning past a third
    of one, red past a whole one (ytq's nights rule)."""
    band = ytq.cost_band(choice.size)
    return {"fits": T.success, "night": T.warning}.get(band, T.error)


# --------------------------------------------------------------------------- #
# The session's YouTube state
# --------------------------------------------------------------------------- #


class YouTube:
    """What the YouTube tabs share for the session: every listing fetched
    (searches and both feeds, reopened for free), every probe, and which
    duplicates have been agreed to."""

    def __init__(self, app, dest: str = "video", now: bool = False) -> None:
        self.app = app
        self.dest = dest
        self.now = now
        self.searched: dict[str, list[ytq.Result]] = {}
        self.stamps: dict[str, float] = {}
        self.views: dict[str, ListView] = {}
        self.recent: list[str] = []
        self.probed: dict[str, tuple[dict, list[ytq.Choice], int]] = {}
        self.probing: dict[str, tui.Job] = {}
        self.agreed: set[str] = set()
        self.warned = False
        self.asked = {key: ytq.SUBS_RESULTS for key in ytq.FEEDS}
        self.want = dict(self.asked)
        self.queued_urls: set[str] = set()
        self._held: dict[str, set[int]] = {}

    def begin(self, first: str | None, preloaded: dict | None) -> None:
        """Where the command line said to start: a saved dump, a feed word,
        a URL, or words to search for."""
        app = self.app
        if preloaded is not None:
            if preloaded.get("entries") is not None:
                key = preloaded.get("title") or "(saved search)"
                self.landed(key, ytq.entries(preloaded))
                app.tabs[0].show(key)
                app.switch(0)
            else:
                url = preloaded.get("webpage_url") or preloaded.get("url") or first or ""
                self.probed[url] = (preloaded, *ytq.choices(preloaded))
                app.switch(0)
                app.open(VideoSheet(app, url, preloaded.get("title") or url, ""))
            return
        if first:
            self.route(first)

    def route(self, text: str) -> None:
        """The field's three answers: a feed, a URL, or a search."""
        app = self.app
        text = text.strip()
        if not text:
            return
        if text.startswith(ytq.LINK_KEY):
            # A link yt-dlp takes that the field would search for (a bare
            # video id), handed over by ``nibbles <x>``.
            link = text[len(ytq.LINK_KEY):]
            app.switch(0)
            app.open(VideoSheet(app, link, link, ""))
            return
        feed = ytq.which_feed(text)
        if feed is not None:
            app.switch(1 if feed is ytq.SUBS else 2)
            return
        if ytq.looks_like_url(text):
            app.switch(0)
            app.open(VideoSheet(app, text, text, ""))
            return
        app.switch(0)
        app.tabs[0].search(text)

    def landed(self, key: str, hits: list[ytq.Result]) -> None:
        self.searched[key] = hits
        self.stamps[key] = time.time()
        if key in self.recent:
            self.recent.remove(key)
        self.recent.insert(0, key)
        self._held.pop(key, None)

    def view(self, key: str) -> ListView:
        return self.views.setdefault(key, ListView())

    def held(self, key: str) -> set[int]:
        """Rows the queue already holds (✓), asked of the queue once per
        listing and again after something is queued."""
        if key not in self._held:
            hits = self.searched.get(key, [])
            got = ytq.already_queued(hits)
            got |= {i for i, r in enumerate(hits) if r.url in self.queued_urls}
            self._held[key] = got
        return self._held[key]

    def queued(self, url: str) -> None:
        self.queued_urls.add(url)
        self._held.clear()

    def probe(self, url: str, owner: Screen) -> tui.Job | None:
        """The format fetch for *url*, started once and kept for the session:
        closing the sheet does not cancel it."""
        if url in self.probed:
            return None
        job = self.probing.get(url)
        if job is not None and not job.finished and not job.cancelled:
            return job
        job = tui.Job(lambda u=url: ytq.probe(u), "asking YouTube for formats", key=url,
                      fetch=True)
        self.probing[url] = job
        self.app.start(job, ProbeOwner(self, url))
        return job


class ProbeOwner(Screen):
    """Takes a probe's answer into the session's cache, whichever sheet (if
    any) is still waiting for it."""

    def __init__(self, yt: YouTube, url: str) -> None:
        self.yt, self.url = yt, url

    def done(self, app, job) -> None:
        self.yt.probing.pop(self.url, None)
        sheet = next((s for s in app.sheets if isinstance(s, VideoSheet) and s.url == self.url), None)
        if job.error is not None:
            if sheet is not None:
                app.close(sheet)
                app.open(Notice("Could not read it", ["could not read that URL", str(job.error)],
                                border=T.error))
            return
        info = job.result
        self.yt.probed[self.url] = (info, *ytq.choices(info))
        if sheet is not None:
            sheet.ready(app)

    def cancelled(self, app, job) -> None:
        """Stopped: the sheet waiting for it closes, and says so."""
        self.yt.probing.pop(self.url, None)
        sheet = next((s for s in app.sheets if isinstance(s, VideoSheet) and s.url == self.url), None)
        if sheet is not None:
            app.close(sheet)
            app.say("stopped asking for its formats")


# --------------------------------------------------------------------------- #
# Lists of videos
# --------------------------------------------------------------------------- #


#: A row's title room: the row less its padding, mark and gap (list_item's).
TITLE_PAD = 4


def marquee_tick() -> int:
    return int(time.monotonic() * 1000 // ytq.MARQUEE_MS)


def overflows(title: str, width: int) -> bool:
    """Whether *title* is too long for a row *width* wide: the one question
    that decides both drawing it moving and waking to move it."""
    return w.string_width(title) > width - TITLE_PAD


def video_entries(hits: list[ytq.Result], held: set[int]) -> list[Entry]:
    def make(i: int, r: ytq.Result) -> Entry:
        mark = "✓" if i in held else ""

        def draw(width: int, selected: bool) -> w.Block:
            title = r.title
            # The selected title scrolls; nothing else does.
            if selected and overflows(title, width):
                title = ytq.marquee(title, width - TITLE_PAD, marquee_tick(),
                                    measure=w.string_width)
            return w.row_item(title, width, subtitle=byline(r), selected=selected,
                              mark=mark, mark_color=T.success if mark else None,
                              dimmed=bool(mark) and not selected)

        return Entry(2, draw, key=i)

    return [make(i, r) for i, r in enumerate(hits)]


def moving(app, key: str | None) -> float | None:
    """How soon the list *key* needs drawing again: only while its selected
    title is too long for its row. A screen of short titles never wakes."""
    if not key or app.sheets:
        return None
    view = app.yt.views.get(key)
    hits = app.yt.searched.get(key, [])
    if view is None or not 0 <= view.cursor < len(hits) or not view.width:
        return None
    if overflows(hits[view.cursor].title, view.width - 1):
        return ytq.MARQUEE_MS / 1000
    return None


def open_row(app, key: str, index: int) -> None:
    """One tap opens a row: selected, its sheet up, its format fetch going."""
    yt = app.yt
    hits = yt.searched.get(key, [])
    if not 0 <= index < len(hits):
        return
    yt.view(key).cursor = index
    r = hits[index]
    app.open(VideoSheet(app, r.url, r.title, byline(r)))


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


class SearchTab(Screen):
    """The search bar, then either the recent listings or a search's results."""

    def __init__(self, app) -> None:
        self.value = ""
        self.focus = False
        self.key_shown: str | None = None
        self.job: tui.Job | None = None
        self.recents = ListView()

    @property
    def typing(self) -> bool:  # type: ignore[override]
        return self.focused(self._app)

    def focused(self, app) -> bool:
        """Whether the field holds the keyboard: tapped, or (``k-search``)
        the keyboard is up with nothing searched and no search running.

        The one answer the drawing, :attr:`typing` and :meth:`key` all ask:
        a field drawn ready to type into while the keys went elsewhere let
        ``q`` quit the app and swallowed the ``x`` of ``xbox``. A running
        search leaves the keys to the screen, so ``x`` is the Stop its line
        offers, and the field is drawn as letting go of them."""
        if self.focus:
            return True
        shown = app.yt.searched.get(self.key_shown) if self.key_shown else None
        searching = self.job is not None and not self.job.finished
        return shown is None and not searching and app.height < SHORT

    def show(self, key: str) -> None:
        self.key_shown = key
        self.value = key if not key.startswith(":") else ""
        self.focus = False

    def search(self, query: str) -> None:
        app = self._app
        yt = app.yt
        self.value = query
        self.focus = False
        if query in yt.searched:
            yt.landed(query, yt.searched[query])
            self.show(query)
            return
        asking = self.job
        if asking is not None and not asking.cancelled and asking.key == query:
            # Already asking for exactly these words, or asked with the answer
            # still on its way (``self.job`` is let go only when its Done is
            # heard): a second Go or Enter would kill a fetch half paid for
            # and buy the same one again. Stop, then Go, still starts afresh.
            return
        if self.job is not None and not self.job.finished:
            self.job.cancel()
        self.job = app.start(
            tui.Job(lambda q=query: ytq.search(q), f"searching for {query}", key=query,
                    fetch=True), self
        )

    def shown(self, app) -> None:
        self._app = app

    def done(self, app, job) -> None:
        if job is not self.job:
            return
        self.job = None
        query = job.key
        if job.error is not None:
            app.open(Notice("Search", ["that search did not come back", str(job.error)],
                            border=T.error))
            self.focus = True
            return
        if not job.result:
            app.open(Notice("Search", ["nothing found for that", "try different words"]))
            self.focus = True
            return
        app.yt.landed(query, job.result)
        self.show(query)

    def cancelled(self, app, job) -> None:
        if job is self.job:
            self.job = None

    # Drawing --------------------------------------------------------------

    def draw(self, app, s: Surface, height: int) -> None:
        self._app = app
        W = s.width
        yt = app.yt
        hits = yt.searched.get(self.key_shown or "", None) if self.key_shown else None
        details = [self.key_shown, str(len(hits))] if hits is not None else ["search"]
        s.put(w.header(APP_NAME, details, W), 0, 0)
        focus = self.focused(app)
        s.put(w.hstack(
            w.field(self.value, W - 10, focus=focus, id="field"),
            w.button("Go", "⏎", 10, "primary" if focus else "normal", id="go",
                     pressed=s.pressed),
        ), 0, 1)
        if self.job is not None and not self.job.finished:
            s.put(w.hstack(
                w.Piece(w.spans([(spin(), T.secondary), (f"searching {SEARCH_COST}", T.fg_more_subtle)],
                                W - 8)),
                w.piece(w.text("x stop", 8, T.fg_most_subtle), "stop")), 0, 4)
        elif hits is not None:
            s.put(w.text(f"{len(hits)} results · ~ dates approx", W, T.fg_most_subtle), 0, 4)
        else:
            s.put(w.text(f"a search is {SEARCH_COST}", W, T.fg_most_subtle), 0, 4)
        if hits is not None:
            view = yt.view(self.key_shown)
            view.entries = video_entries(hits, yt.held(self.key_shown))
            view.draw(s, 0, 5, W, max(0, height - 5), "row")
            return
        y = 5 if app.height < SHORT else 6
        if y >= height:
            return
        s.put(w.section("Recent", W, "free to reopen"), 0, y)
        self.recents.entries = [self._recent_entry(app, key) for key in yt.recent]
        self.recents.draw(s, 0, y + 1, W, max(0, height - y - 1), "row-recent")

    def _recent_entry(self, app, key: str) -> Entry:
        yt = app.yt
        feed = ytq.FEEDS.get(key)
        count = len(yt.searched.get(key, []))
        title = {ytq.SUBS_KEY: "subscriptions", ytq.WL_KEY: "watch later"}.get(key, key)
        noun = "videos" if feed else "results"
        sub = f"{count} {noun} · {shell.ago(time.time() - yt.stamps.get(key, time.time()))}"

        def draw(width: int, selected: bool) -> w.Block:
            return w.row_item(title, width, subtitle=sub, selected=selected)

        return Entry(2, draw, key=key)

    def wake(self, app) -> float | None:
        return moving(app, self.key_shown)

    # Events ---------------------------------------------------------------

    def _submit(self, app) -> None:
        text = self.value.strip()
        if not text:
            return
        self.focus = False
        app.yt.route(text)

    def tap(self, app, hit, event) -> None:
        yt = app.yt
        if hit.id == "field":
            self.focus = True
        elif hit.id == "go":
            self._submit(app)
        elif hit.id == "stop":
            if self.job is not None:
                self.job.cancel()
        elif hit.id == "row" and self.key_shown:
            open_row(app, self.key_shown, hit.data)
        elif hit.id == "row-bar" and self.key_shown:
            yt.view(self.key_shown).bar_tap(event.y)
        elif hit.id == "row-recent":
            key = self.recents.entries[hit.data].key
            if key in ytq.FEEDS:
                app.switch(1 if key == ytq.SUBS_KEY else 2)
            else:
                yt.landed(key, yt.searched[key])
                self.show(key)
        elif hit.id == "row-recent-bar":
            self.recents.bar_tap(event.y)

    def scroll(self, app, event) -> None:
        view = app.yt.view(self.key_shown) if self.key_shown else self.recents
        if view.in_bar(event.x, event.y):
            view.bar_drag(event.dy)
        else:
            view.view(event.dy)

    def paste(self, app, text: str) -> None:
        """A paste (``tui.Paste``) goes into the field, focused, and does no
        more: it never searches, whatever line breaks it held — ⏎ or Go
        does that."""
        self.value += text
        self.focus = True

    def key(self, app, key: str) -> bool:
        yt = app.yt
        if self.focused(app):
            if key == "enter":
                self._submit(app)
            elif key == "esc":
                self.focus = False
            elif key == "backspace":
                self.value = self.value[:-1]
            elif key == "ctrl-u":
                self.value = ""
            elif key == "ctrl-w":
                self.value = self.value.rstrip().rsplit(" ", 1)[0] if " " in self.value.strip() else ""
            elif len(key) == 1:
                self.value += key
            return True
        if key == "/":
            self.focus = True
            return True
        if self.key_shown:
            view = yt.view(self.key_shown)
            steps = {"up": -1, "down": 1, "pgup": -max(1, view.visible() - 1),
                     "pgdn": max(1, view.visible() - 1), "left": -max(1, view.visible() - 1),
                     "right": max(1, view.visible() - 1)}
            if key in steps:
                view.move(steps[key])
                return True
            if key == "enter" and view.cursor >= 0:
                open_row(app, self.key_shown, view.cursor)
                return True
            if key == "esc":
                self.key_shown = None
                self.value = ""
                return True
        elif key == "enter":
            self._submit(app)
            return True
        elif len(key) == 1 and key not in "qx":
            self.focus = True
            self.value += key
            return True
        return False


# --------------------------------------------------------------------------- #
# Feed and Later
# --------------------------------------------------------------------------- #


class FeedTab(Screen):
    """One signed-in list (the subscription feed, or Watch Later), read on
    first opening the tab in a session."""

    def __init__(self, app, feed: ytq.Feed) -> None:
        self.feed = feed
        self.job: tui.Job | None = None
        self.problem: list[str] = []
        self.read_once = False
        self.last_scroll = 0.0
        self.bump = False
        #: A failure not yet said: it came back while something else was up.
        self.unsaid = False
        self.error = False

    @property
    def key_(self) -> str:
        return self.feed.key

    def shown(self, app) -> None:
        if not self.read_once:
            self.read_once = True
            self.read(app)
        elif self.unsaid:
            self.say_problem(app)

    def failed(self, app, lines: list[str], error: bool) -> None:
        """A read that did not bring a list: *lines* say why.

        With nothing listed yet they are drawn where the list would be. With
        a listing already on screen the old rows stay, so the failure is a
        notice over them, as a search's is — or a Re-read, a deeper look or
        an expired cookie would come back to the same rows and say nothing,
        which reads as nothing new. Said when this tab is up with nothing over
        it, so it never lands on another tab or on a sheet in use."""
        self.problem = lines
        self.error = error
        self.unsaid = bool(app.yt.searched.get(self.key_))
        if self.unsaid and app.tabs[app.tab] is self and not app.sheets:
            self.say_problem(app)

    def say_problem(self, app) -> None:
        self.unsaid = False
        title = {ytq.SUBS_KEY: "Feed", ytq.WL_KEY: "Later"}[self.key_]
        app.open(Notice(title, self.problem, border=T.error if self.error else None))

    def read(self, app, deeper: bool = False) -> None:
        """Read the list at the depth wanted, after the cookie is asked
        about: a list with no session behind it comes back empty, so that
        question is asked before anything is spent."""
        yt = app.yt
        if self.job is not None and not self.job.finished:
            return
        state, detail = ytq.cookie_state()
        if state in ("none", "missing"):
            yt.want[self.key_] = yt.asked[self.key_]
            self.failed(app, ytq.cookie_advice(state, detail), error=False)
            return
        self.problem = []
        self.unsaid = False
        count = yt.want[self.key_]
        self.job = app.start(
            tui.Job(lambda c=count, f=self.feed: ytq.read_feed(f, c),
                    f"reading {self.feed.name}", key=(count, detail, deeper), fetch=True),
            self,
        )

    def done(self, app, job) -> None:
        if job is not self.job:
            return
        self.job = None
        yt = app.yt
        count, detail, deeper = job.key
        if job.error is not None:
            yt.want[self.key_] = yt.asked[self.key_]
            self.failed(app, [f"{self.feed.name} did not come back", str(job.error),
                              *ytq.cookie_fix(detail)], error=True)
            return
        hits = job.result or []
        if not hits:
            yt.want[self.key_] = yt.asked[self.key_]
            self.failed(app, self.feed.empty(detail), error=False)
            return
        old = len(yt.searched.get(self.key_, []))
        view = yt.view(self.key_)
        yt.landed(self.key_, hits)
        yt.asked[self.key_] = count
        if deeper and self.bump:
            # The deeper look completes the ↓ that asked for it.
            view.cursor, _ = ytq.bumped_place((view.cursor, view.top), old)
        self.bump = False

    def cancelled(self, app, job) -> None:
        if job is self.job:
            self.job = None
            app.yt.want[self.key_] = app.yt.asked[self.key_]

    def more(self, app, bump: bool = False) -> None:
        """The deeper look: the whole list again, a page further back."""
        yt = app.yt
        hits = yt.searched.get(self.key_, [])
        nxt, _ = ytq.next_page(len(hits), yt.asked[self.key_])
        if not nxt or (self.job is not None and not self.job.finished):
            return
        yt.want[self.key_] = nxt
        self.bump = bump
        self.read(app, deeper=True)

    # Drawing --------------------------------------------------------------

    def draw(self, app, s: Surface, height: int) -> None:
        W = s.width
        yt = app.yt
        hits = yt.searched.get(self.key_)
        noun = {ytq.SUBS_KEY: "subscriptions", ytq.WL_KEY: "watch later"}[self.key_]
        details = [noun] + ([str(len(hits))] if hits is not None else [])
        s.put(w.header(APP_NAME, details, W), 0, 0)
        reading = self.job is not None and not self.job.finished
        if reading and not (self.job.key[2] and hits):
            line1 = w.spans([(spin(), T.secondary), (f"reading {noun}", T.fg_base)], W - 14)
            line2 = w.text(f"{feed_mb(yt.want[self.key_])} · x stop", W - 14, T.fg_most_subtle)
        elif hits is not None:
            line1 = w.text(f"{len(hits)} videos", W - 14, T.fg_base)
            when = shell.ago(time.time() - yt.stamps.get(self.key_, time.time()))
            line2 = w.text(f"read {when} · {feed_mb(yt.asked[self.key_])}", W - 14,
                           T.fg_most_subtle)
        else:
            line1 = w.text(noun, W - 14, T.fg_base)
            line2 = w.text("not read yet", W - 14, T.fg_most_subtle)
        info = w.vstack(line1, line2, w.gap(W - 14), width=W - 14)
        s.put(w.hstack(w.gap(1, 3), info,
                       w.button("Re-read", "r", 13, "off" if reading else "normal",
                                id="reread", pressed=s.pressed)), 0, 1)
        top = 4
        if self.problem and not hits:
            s.put(w.vstack(*[w.wrapped(line, W - 2, T.fg_base if i == 0 else T.fg_more_subtle)
                             for i, line in enumerate(self.problem)], width=W - 2), 1, top + 1)
            return
        if hits is None:
            return
        more, at_cap = ytq.next_page(len(hits), yt.asked[self.key_])
        deeper = reading and self.job.key[2]
        short = app.height < SHORT
        foot = 1 if (short or not (more or deeper)) else 3
        view = yt.view(self.key_)
        view.entries = video_entries(hits, yt.held(self.key_))
        view.draw(s, 0, top, W, max(0, height - top - foot), "row")
        y = height - foot
        if deeper:
            text = f"reading {yt.want[self.key_]} · {feed_mb(yt.want[self.key_])}"
            if foot == 3:
                s.put(w.button(f"{spin()}{text}", "", W, "off", id="pull"), 0, y)
            else:
                s.put(w.spans([("  " + spin(), T.secondary), (text, T.fg_more_subtle)], W), 0, y)
        elif more:
            extra = more - len(hits)
            cost = f"{feed_mb(more)} in all"
            if foot == 3:
                s.put(w.button(f"{extra} more", "↓", W, "spend", f"· {cost}", id="pull",
                               pressed=s.pressed), 0, y)
            else:
                s.put(w.piece(w.spans([("  ↓ ", T.warning),
                                       (f"pull again: {extra} more · {cost}", T.fg_more_subtle)],
                                      W), "pull"), 0, y)
        else:
            end = (f"at the {ytq.SUBS_MAX} cap" if at_cap else f"that is {self.feed.whole}")
            s.put(w.text("  " + end, W, T.fg_most_subtle), 0, y)

    # Events ---------------------------------------------------------------

    def tap(self, app, hit, event) -> None:
        yt = app.yt
        if hit.id == "reread":
            if self.job is None or self.job.finished:
                yt.want[self.key_] = yt.asked[self.key_]
                self.read(app)
        elif hit.id == "pull":
            self.more(app)
        elif hit.id == "row":
            open_row(app, self.key_, hit.data)
        elif hit.id == "row-bar":
            yt.view(self.key_).bar_tap(event.y)

    def scroll(self, app, event) -> None:
        """A swipe moves the view. A **fresh** drag down after the list has
        rested at its end for :data:`REST` reads the next page; momentum is
        an unbroken stream of wheel events, so it never can."""
        yt = app.yt
        now = time.monotonic()
        rested = now - self.last_scroll >= REST
        self.last_scroll = now
        view = yt.view(self.key_)
        if view.in_bar(event.x, event.y):
            view.bar_drag(event.dy)
            return
        was_end = view.at_end()
        view.view(event.dy)
        if event.dy > 0 and was_end and rested and view.entries:
            self.more(app)

    def wake(self, app) -> float | None:
        return moving(app, self.key_)

    def key(self, app, key: str) -> bool:
        yt = app.yt
        view = yt.view(self.key_)
        if key == "r":
            self.tap(app, w.Hit(0, 0, 1, 1, "reread"), None)
            return True
        if key == "down" and view.entries and view.cursor == len(view.entries) - 1:
            self.more(app, bump=True)
            return True
        page = max(1, view.visible() - 1)
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page, "left": -page, "right": page}
        if key in steps:
            view.move(steps[key])
            return True
        if key == "enter" and view.cursor >= 0:
            open_row(app, self.key_, view.cursor)
            return True
        if key == "/":
            app.switch(0)
            app.tabs[0].focus = True
            return True
        return False


# --------------------------------------------------------------------------- #
# The video sheet
# --------------------------------------------------------------------------- #


def around(items: list, at, room: int) -> list:
    """*room* of *items*, in their order, with *at* as near the middle as the
    ends allow (from the start when *at* is not among them); all of them when
    they fit. What the tier row keeps when its buttons outnumber its room: a
    button is never narrowed to make space, the row holds fewer."""
    if len(items) <= room:
        return items
    i = items.index(at) if at in items else 0
    lo = max(0, min(i - room // 2, len(items) - room))
    return items[lo:lo + room]


class VideoSheet(Sheet):
    """One video: pick a quality, then queue it for the window or start it
    now. It replaces the old formats, confirm and duplicate screens; every
    choice on it is a tap."""

    def __init__(self, app, url: str, title: str, by: str) -> None:
        super().__init__()
        self.url = url
        self.title = title
        self.by = by
        self.prefs = ytq.prefs()
        self.mode = "video"
        self.tier: tuple[str, int] | None = None
        self.rules = {"video": ytq.rule_for("video", self.prefs),
                      "audio": ytq.rule_for("audio", self.prefs)}
        self.explicit: ytq.Choice | None = None
        self.when = 1 if app.yt.now else 0
        self.clash: ytq.Duplicate | None = None
        self.checked = False
        self.said = ""
        self.copying: tui.Job | None = None
        self._app = app
        app.yt.probe(url, self)

    def shown(self, app) -> None:
        """On top: if the formats are already in (a probe kept from earlier,
        or a saved dump), the sheet is ready now, and any notice it raises
        opens over it rather than under it."""
        self._app = app
        if self.url in app.yt.probed and not self.checked:
            self.ready(app)

    # State ----------------------------------------------------------------

    @property
    def info(self) -> dict | None:
        got = self._app.yt.probed.get(self.url)
        return got[0] if got else None

    def ready(self, app) -> None:
        """The probe is in: the title, the tier the sheet opens on, the
        duplicate check, and the once-a-session notice for a withheld list."""
        self._app = app
        info, options, _ = app.yt.probed[self.url]
        self.title = info.get("title") or self.title
        if not self.by:
            self.by = " · ".join(p for p in (info.get("channel") or info.get("uploader") or "",
                                             ytq.clock(info.get("duration")))
                                 if p)
        if not options:
            app.close(self)
            app.open(Notice("Nothing to queue", [
                "no format has a size yt-dlp will state",
                "nothing can be queued without one",
                "nibbles <url> in a shell queues a plain file by Range instead",
            ]))
            return
        remembered = ytq.recalled_format()
        start = options[ytq.preferred_index(options, remembered)]
        if remembered is None:
            heights = sorted({h for h in (ytq.height_of(o) for o in options) if h})
            if heights:
                near = min(heights, key=lambda h: (abs(h - 480), h))
                start = next(o for o in options if ytq.height_of(o) == near)
        self.tier = ytq.tier_of(start)
        self.mode = self.tier[0]
        if not self.checked:
            self.checked = True
            if self.url not in app.yt.agreed:
                self.clash = ytq.find_duplicate(ytq.source_key(info), ytq.title_name(self.title))
            if ytq.withheld(info) and not app.yt.warned:
                app.yt.warned = True
                app.open(Notice("Only 360p", ytq.withheld_advice(ytq.cookie_state()[1])))

    def options(self) -> list[ytq.Choice]:
        got = self._app.yt.probed.get(self.url)
        return got[1] if got else []

    def tiers(self, mode: str) -> list[tuple[str, int]]:
        found = sorted({ytq.tier_of(o) for o in self.options() if ytq.tier_of(o)[0] == mode},
                       key=lambda t: t[1])
        return found

    def chosen(self) -> tuple[ytq.Choice | None, list[str]]:
        if self.explicit is not None:
            return self.explicit, []
        if self.tier is None:
            return None, []
        return ytq.pick_in_tier(self.options(), self.tier, self.rules[self.tier[0]],
                                ytq.skip_codecs(self.prefs))

    def window(self, app) -> str:
        """``03:00``: when the next window opens, on the phone's clock."""
        return app.queue.window_word()

    def counted(self, app) -> bool | None:
        """Whether zwana answers (``None`` until the queue's reading is in)."""
        return app.queue.counted()

    # Drawing --------------------------------------------------------------

    def body(self, app, width: int, height: int) -> Piece:
        short = height < SHORT
        parts: list = [w.text(self.by, width, T.fg_more_subtle)]
        if not short:
            parts.append(w.gap(width))
        when_labels = [f"At {self.window(app)}", "Now"]
        if self.url not in app.yt.probed:
            parts += [
                w.section("Quality", width),
                w.gap(width),
                w.spans([(spin(), T.secondary), ("asking YouTube for formats", T.fg_base)], width),
                w.text(f"  {PROBE_COST}", width, T.fg_most_subtle),
            ]
            if not short:
                parts += [w.gap(width, 5), w.segmented(when_labels, self.when, width, "when"),
                          w.gap(width, 2)]
            else:
                parts.append(w.gap(width, 3))
            return w.vstack(*parts, width=width)
        choice, passed = self.chosen()
        tier_options = ytq.in_tier(self.options(), self.tier) if self.tier else []
        if self.tier and self.tier[0] == "audio":
            label = f"{self.tier[1]}k"
        else:
            label = f"{self.tier[1]}p" if self.tier else ""
        n = len(tier_options)
        if not (short and self.clash is not None):
            parts.append(w.section("Quality", width, f"{label} · {n} format{'s' if n != 1 else ''}"))
        info = self.info
        if info is not None and ytq.withheld(info):
            # Said on every sheet it applies to; the whole notice is once a
            # session. ytq measures it against the whole screen, frame and all.
            parts.append(w.text(ytq.withheld_note(width + 4), width, T.warning))
        parts.append(self.tier_row(app, width))
        side = 11
        parts.append(w.hstack(
            w.segmented(["Smallest", "Largest"],
                        0 if self.rules[self.mode] == "smallest" or self.explicit else 1,
                        width - side, "rule", pressed=app.pressed),
            w.button("Formats", "", side, id="formats", pressed=app.pressed),
        ))
        if choice is not None:
            if choice.kind == "audio":
                codecs = " ".join(ytq.codec_families(choice)) + f" {ytq.bitrate_of(choice)}k"
            else:
                codecs = "+".join(ytq.codec_families(choice))
            # The nights it will take, in words as well as colour.
            nights = ytq.nights_note(choice.size).strip()
            parts.append(w.spans([(size_of(choice), size_fg(choice), True),
                                  (f" {nights}" if nights else "", size_fg(choice)),
                                  (f" · {choice.ext} · {codecs}", T.fg_more_subtle)], width))
            parts.append(w.text(f"skipped {' '.join(passed)}", width, T.fg_most_subtle)
                         if passed else w.gap(width))
        parts.append(w.segmented(when_labels, self.when, width, "when", pressed=app.pressed))
        if self.when == 1 and self.clash is None:
            counted = self.counted(app)
            line = ("asking zwana…" if counted is None else
                    "today's allowance, no reserve kept" if counted else
                    "on mobile data, charged")
            parts.append(w.text(line, width, T.fg_most_subtle))
        if self.said:
            parts.append(w.text(self.said, width, T.info))
        return w.vstack(*parts, width=width)

    def tier_row(self, app, width: int) -> Piece:
        """The tier buttons: your heights plus ``audio``, or ``← video`` and
        the bitrates. A wider screen adds buttons rather than narrowing them."""
        slots = max(3, width // 9)
        current = self.tier
        buttons: list[Btn] = []
        if self.mode == "audio":
            buttons.append(Btn("← video", "", id="tier-video"))
            have = self.tiers("audio")
            for t in around(have, current, slots - 1):
                buttons.append(Btn(f"{t[1]}k", "", "primary" if t == current else "normal",
                                   id=f"tier:{t[1]}", data=t))
        else:
            have = {t[1] for t in self.tiers("video")}
            heights = ytq.chip_heights(self.prefs, slots - 1)
            on = current[1] if current and current[0] == "video" else None
            if on is not None and on not in heights:
                heights = sorted(heights[1:] + [on]) if len(heights) == slots - 1 \
                    else sorted(heights + [on])
            # Heights set by hand are every one of them (More's row reads the
            # whole range), so more than the room is possible: the ones around
            # the tier the sheet is on, and the rest live under Formats.
            heights = around(heights, on, slots - 1)
            for h in heights:
                kind = "primary" if current == ("video", h) else ("normal" if h in have else "off")
                buttons.append(Btn(f"{h}p", "", kind, id=f"tier:{h}", data=("video", h)))
            buttons.append(Btn("audio", "", "off" if not self.tiers("audio") else "normal",
                               id="tier-audio"))
        return w.dock(buttons, width, app.pressed)

    def footer(self, app, width: int, height: int) -> Piece:
        when = self.window(app)
        if self.url not in app.yt.probed:
            return w.button(f"Queue for {when}", "⏎", width, "off", id="go")
        choice, _ = self.chosen()
        figure = f"· {size_of(choice)}" if choice else ""
        if self.clash is not None:
            return w.vstack(
                w.spans([("✓ ", T.success), (self.clash.says(), T.fg_base)], width),
                w.button("Queue it again anyway", "a", width, "normal", id="again",
                         pressed=app.pressed),
                width=width,
            )
        if self.when == 1:
            kind = "danger" if self.counted(app) is False else "spend"
            return w.button("Start now", "⏎", width, kind, figure, id="go", pressed=app.pressed)
        return w.button(f"Queue for {when}", "⏎", width, "primary", figure, id="go",
                        pressed=app.pressed)

    def wake(self, app) -> float | None:
        return None

    def done(self, app, job) -> None:
        """The copy has come back: said inside the sheet, because the line
        above the tabs is under it — or above the tabs, once it is closed."""
        self.copying = None
        said = job.result if job.error is None else f"clipboard failed: {job.error}"
        if self in app.sheets:
            self.said = said
        else:
            app.say(said)

    # Events ---------------------------------------------------------------

    def tap(self, app, hit, event) -> None:
        if self.url not in app.yt.probed:
            if hit.id.startswith("when:"):
                self.set_when(app, hit.data)
            return
        if hit.id.startswith("tier:"):
            self.tier, self.explicit = hit.data, None
        elif hit.id == "tier-audio":
            self.to_mode("audio")
        elif hit.id == "tier-video":
            self.to_mode("video")
        elif hit.id.startswith("rule:"):
            self.rules[self.mode] = ("smallest", "largest")[hit.data]
            self.explicit = None
        elif hit.id == "formats":
            app.open(FormatsSheet(self))
        elif hit.id.startswith("when:"):
            self.set_when(app, hit.data)
        elif hit.id == "go":
            self.commit(app)
        elif hit.id == "again":
            app.yt.agreed.add(self.url)
            self.clash = None
            self.commit(app)

    def set_when(self, app, when: int) -> None:
        self.when = when
        if when == 1:
            app.queue.check_reach()

    def to_mode(self, mode: str) -> None:
        tiers = self.tiers(mode)
        if not tiers:
            return
        self.mode = mode
        self.explicit = None
        if mode == "video":
            want = 480
            heights = [t[1] for t in tiers]
            self.tier = ("video", min(heights, key=lambda h: (abs(h - want), h)))
        else:
            self.tier = tiers[len(tiers) // 2] if len(tiers) > 2 else tiers[-1]

    def key(self, app, key: str) -> bool:
        if key == "esc":
            app.close(self)
            return True
        if self.url not in app.yt.probed:
            return False
        if key == "enter":
            if self.clash is None:
                self.commit(app)
            return True
        if key == "a" and self.clash is not None:
            app.yt.agreed.add(self.url)
            self.clash = None
            self.commit(app)
            return True
        if key == "f":
            app.open(FormatsSheet(self))
            return True
        if key == "c":
            # In the background: termux-clipboard-set without the Termux:API
            # app waits out its whole timeout, and the app with it.
            if self.copying is None or self.copying.finished:
                self.copying = app.start(tui.Job(lambda u=self.url: ytq.to_clipboard(u),
                                                 "copying", key="clipboard", quiet=True), self)
            return True
        if key == "n":
            self.set_when(app, 1 - self.when)
            return True
        if key in ("left", "right"):
            tiers = self.tiers(self.mode)
            if self.tier in tiers:
                at = tiers.index(self.tier) + (1 if key == "right" else -1)
                self.tier = tiers[max(0, min(len(tiers) - 1, at))]
                self.explicit = None
            return True
        if key in ("s", "l"):
            self.rules[self.mode] = "smallest" if key == "s" else "largest"
            self.explicit = None
            return True
        return False

    # Queueing -------------------------------------------------------------

    def commit(self, app) -> None:
        """Write the item through the one door (``ytq.write_item``), then, if
        Now was chosen, start it. The button was the one yes."""
        info = self.info
        choice, _ = self.chosen()
        if info is None or choice is None:
            return
        yt = app.yt
        name = ytq.title_name(info.get("title") or self.title)
        item = ytq.render(
            self.url, name, choice, info.get("title") or name,
            time.strftime("%Y-%m-%d", time.gmtime()),
            ytq.dest_for(choice, yt.dest), ytq.source_key(info),
        )
        try:
            path = ytq.write_item(ytq.next_number(), name, item, again=self.url in yt.agreed)
        except ytq.Duplicate as clash:
            self.clash = clash
            return
        except OSError as exc:
            # A full phone, mostly. Said over the sheet, which stays with its
            # probe and its choice: nothing bought is lost, and the next try
            # is the same tap.
            app.open(Notice("Not queued", ["the item could not be written", str(exc)],
                            border=T.error))
            return
        problem = ytq.validate(path)
        ytq.learn(choice, "largest" if self.rules[self.mode] == "largest" else "smallest")
        yt.queued(self.url)
        receipt = (f"queued {path.name} — {ytq.human(choice.size)} "
                   f"({choice.label}), cap {ytq.human(choice.expect_bytes)}")
        app.close(self)
        app.queue.changed()
        if self.when == 1:
            try:
                refused = app.queue.start_now(path.name)
            except OSError as exc:
                # The item is written; only the start failed. Said like any
                # other refusal, receipt and all, so it is not queued unseen.
                refused = ["it could not be started", str(exc),
                           f"{name} is queued and will run in the window"]
            if refused:
                app.receipt(receipt)
                app.open(Notice("Queued, not started", refused))
            else:
                app.receipt(f"downloading {path.name} now — {ytq.human(choice.size)} "
                            f"({choice.label})")
                app.say(f"started {name} · {size_of(choice)}")
        else:
            app.receipt(receipt)
            app.say(f"queued {name} · {size_of(choice)}")
        if problem:
            app.open(Notice("The runner would refuse it", [
                "the runner would reject this item", problem, f"written anyway at {path}"],
                border=T.error))


class FormatsSheet(Sheet):
    """Every format, grouped by tier, smallest first, opened at the tier the
    video sheet was on. A tap picks the row and goes back."""

    def __init__(self, video: VideoSheet) -> None:
        super().__init__()
        self.video = video
        tier = video.tier
        label = (f"{tier[1]}k" if tier and tier[0] == "audio" else f"{tier[1]}p") if tier else ""
        self.title = f"Formats · {label}" if label else "Formats"
        self._placed = False

    def groups(self) -> list[tuple[tuple[str, int], list[ytq.Choice]]]:
        options = self.video.options()
        tiers = sorted({ytq.tier_of(o) for o in options},
                       key=lambda t: (t[0] == "audio", -t[1]))
        return [(t, sorted(ytq.in_tier(options, t), key=lambda o: o.size)) for t in tiers]

    def body(self, app, width: int, height: int) -> Piece:
        chosen, _ = self.video.chosen()
        skip = ytq.skip_codecs(self.video.prefs)
        got = self.video._app.yt.probed.get(self.video.url)
        unsized = got[2] if got else 0
        head = "smallest first · ~ an estimate"
        if unsized:
            # Formats yt-dlp states no size for are never offered: counted.
            head += f" · {unsized} unsized"
        parts: list = [w.text(head, width, T.fg_most_subtle)]
        anchor = 0
        for tier, options in self.groups():
            if tier == self.video.tier:
                anchor = sum(p.height for p in parts)
            label = f"{tier[1]}k" if tier[0] == "audio" else f"{tier[1]}p"
            parts.append(w.section(label, width - 1, str(len(options))))
            for o in options:
                sel = o is chosen
                avoid = bool(set(ytq.codec_families(o)) & set(skip))
                sz = shell.size(o.size) + ("~" if not o.exact else "")
                fg = None if sel else (T.fg_more_subtle if avoid else size_fg(o))
                title = [w.Span(f"{sz:>9}  ", w.Pen(fg=fg, bold=True)), w.Span(o.label)]
                # The selected row says its codecs exactly; the rest by family.
                sub = o.codecs if sel else " + ".join(ytq.codec_families(o))
                if not sel:
                    sub += " · skipped" if avoid else " · merged" if o.kind == "merge" else ""
                block = w.row_item(title, width - 1, subtitle=sub, selected=sel,
                                   mark="●" if sel else "", mark_color=T.success_most_subtle,
                                   dimmed=avoid)
                parts.append(w.piece(block, "pick", o))
        if not self._placed:
            self._placed = True
            self.offset = anchor if anchor > 1 else 0
        return w.vstack(*parts, width=width)

    def tap(self, app, hit, event) -> None:
        if hit.id == "pick":
            self.video.explicit = hit.data
            self.video.tier = ytq.tier_of(hit.data)
            self.video.mode = self.video.tier[0]
            app.close(self)

    def flat(self) -> list[ytq.Choice]:
        return [o for _, options in self.groups() for o in options]

    def key(self, app, key: str) -> bool:
        """↑ and ↓ move the pick through every format in the order drawn, and
        ⏎ takes it back to the video sheet; pgup/pgdn scroll."""
        if key in ("up", "down"):
            flat = self.flat()
            chosen, _ = self.video.chosen()
            at = flat.index(chosen) if chosen in flat else 0
            pick = flat[max(0, min(len(flat) - 1, at + (1 if key == "down" else -1)))]
            self.video.explicit = pick
            self.video.tier = ytq.tier_of(pick)
            self.video.mode = self.video.tier[0]
            self.offset = max(0, self.offset + (1 if key == "down" else -1) * 2)
            return True
        if key in ("pgup", "pgdn"):
            self.offset = max(0, self.offset + (5 if key == "pgdn" else -5))
            return True
        if key == "enter":
            app.close(self)
            return True
        return super().key(app, key)
