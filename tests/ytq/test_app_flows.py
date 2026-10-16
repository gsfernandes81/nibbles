"""The app's flows with no terminal: what a tap or a key leads to.

The real :class:`nibbles.App`, headless (``App(None, tab, size=...)``), driven
with the events the terminal would hand it. Asserted on the state the next
frame is drawn from — which sheet is on top, what was written, what was asked
for — never on wording.
"""

from __future__ import annotations

import errno
import threading
import time

import pytest

from nibbles import app as nibbles
from nibbles import shell
from nibbles import tui
from nibbles import widgets
from nibbles import ytq
from nibbles import yt_screens as ys
from conftest import fmt, search_info, video_info

MiB = 1024**2


def headless(tab=0, size=(40, 24)):
    app = nibbles.App(None, tab, size=size)
    app.guard.opened = -10.0
    return app


def settle(app):
    """Every job the app started, finished and its Done delivered."""
    for job, _ in list(app.jobs):
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))


def tap(app, id):
    """A tap on the middle of the target *id*, as the terminal reports one."""
    app.compose()
    hit = next((h for h in app.hits.hits if h.id == id), None)  # the first one
    assert hit is not None, (id, app.hits.ids())
    app.guard.opened = -10.0
    app.handle(tui.Tap(hit.x + hit.w // 2, hit.y + hit.h // 2))


def with_listing(app, info=None):
    hits = ytq.entries(search_info(["Crust of Rust: Lifetimes", "Another One"]))
    app.yt.landed("crust", hits)
    app.tabs[0].show("crust")
    if info is not None:
        app.yt.probed[hits[0].url] = (info, *ytq.choices(info))
    return hits


def test_one_tap_on_a_row_opens_its_sheet_and_starts_its_probe(monkeypatch):
    """Selected, its sheet up, its format fetch going — in the one tap."""
    asked = []
    monkeypatch.setattr(ytq, "probe", lambda url: asked.append(url) or video_info())
    app = headless()
    hits = with_listing(app)
    tap(app, "row")
    assert isinstance(app.sheets[-1], ys.VideoSheet)
    assert app.yt.view("crust").cursor == 0
    for job, _ in list(app.jobs):
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))
    assert asked == [hits[0].url]
    assert app.sheets[-1].tier is not None


def test_closing_the_sheet_keeps_the_probe_for_the_session(monkeypatch):
    asked = []
    monkeypatch.setattr(ytq, "probe", lambda url: asked.append(url) or video_info())
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    app.handle(tui.Key("esc"))
    assert not app.sheets
    tap(app, "row")
    assert asked == [] and app.sheets[-1].tier is not None


def test_the_withheld_notice_opens_over_its_sheet_once_a_session():
    """Said twice on purpose: the whole notice once a session, over the sheet
    it is about, and a line on every sheet it applies to."""
    withheld = video_info(formats=[
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", height=360, filesize=10 * MiB),
    ])
    assert ytq.withheld(withheld)
    app = headless()
    with_listing(app, info=withheld)
    tap(app, "row")
    assert isinstance(app.sheets[-1], shell.Notice)
    assert isinstance(app.sheets[-2], ys.VideoSheet)
    app.handle(tui.Key("esc"))
    assert isinstance(app.sheets[-1], ys.VideoSheet)
    app.handle(tui.Key("esc"))
    tap(app, "row")
    assert isinstance(app.sheets[-1], ys.VideoSheet), "once a session, not once a sheet"


def test_stop_closes_the_sheet_that_was_waiting(monkeypatch):
    """``x`` stops the newest fetch; the sheet waiting on it does not wait on."""
    def slow(url):
        time.sleep(5)
        return video_info()

    monkeypatch.setattr(ytq, "probe", slow)
    app = headless()
    with_listing(app)
    tap(app, "row")
    job = next(job for job, _ in app.jobs if job.key == app.sheets[-1].url)
    app.handle(tui.Key("x"))
    assert job.cancelled
    app.handle(tui.Done(job))
    assert not any(isinstance(s, ys.VideoSheet) for s in app.sheets)


def test_the_button_writes_the_item_under_the_videos_own_name(clean_queue):
    app = headless()
    info = video_info(title="Crust of Rust: Lifetimes")
    with_listing(app, info=info)
    tap(app, "row")
    tap(app, "go")
    written = list(ytq.QUEUE.glob("*.py"))
    assert [p.name for p in written] == [ytq.item_name(10, "Crust of Rust - Lifetimes")]
    assert not any(isinstance(s, ys.VideoSheet) for s in app.sheets)
    assert app.receipts and written[0].name in app.receipts[0]
    # And the row is marked as held now, before anything else is spent.
    assert 0 in app.yt.held("crust")


def test_now_is_the_one_yes(clean_queue, monkeypatch):
    """Now turns the button into Start now; that tap writes and starts, with
    no second question."""
    started = []
    app = headless()
    monkeypatch.setattr(app.queue, "start_now", lambda name: started.append(name))
    with_listing(app, info=video_info())
    tap(app, "row")
    tap(app, "when:1")
    tap(app, "go")
    assert len(started) == 1 and list(ytq.QUEUE.glob("*.py"))
    # Off Termux the runner objects to the item's shebang, which is a notice;
    # the video sheet itself is gone either way.
    assert not any(isinstance(s, ys.VideoSheet) for s in app.sheets)


def test_a_duplicate_is_answered_on_the_sheet(clean_queue, queued):
    info = video_info()
    queued("10-old.py", source=ytq.source_key(info))
    app = headless()
    with_listing(app, info=info)
    tap(app, "row")
    app.compose()
    assert app.hits.find("go") is None and app.hits.find("again") is not None
    tap(app, "again")
    assert len(list(ytq.QUEUE.glob("*.py"))) == 2


def no_space(*args, **kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


def said(app, text):
    """Whether a notice up holds *text* among its lines."""
    return any(isinstance(s, shell.Notice) and any(text in line for line in s.lines)
               for s in app.sheets)


def test_an_item_that_cannot_be_written_is_said_and_the_sheet_kept(clean_queue, monkeypatch):
    """A full phone: a notice over the sheet, never the app gone. The sheet
    keeps its probe and its choice for the next try; nothing queued, no
    receipt."""
    monkeypatch.setattr(ytq, "write_item", no_space)
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    tap(app, "go")
    assert isinstance(app.sheets[-1], shell.Notice)
    assert said(app, str(OSError(errno.ENOSPC, "No space left on device")))
    assert isinstance(app.sheets[-2], ys.VideoSheet) and app.sheets[-2].chosen()[0] is not None
    assert not list(ytq.QUEUE.glob("*.py")) and not app.receipts


def test_a_start_that_fails_still_says_what_was_queued(clean_queue, monkeypatch):
    """Now, and the download cannot be started: the item is written, so its
    receipt is given, and a notice says why it did not start."""
    monkeypatch.setattr(ytq, "queue_busy", lambda: False)
    monkeypatch.setattr(ytq, "start_now", no_space)
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    tap(app, "when:1")
    tap(app, "go")
    written = list(ytq.QUEUE.glob("*.py"))
    assert len(written) == 1
    assert any(written[0].name in receipt for receipt in app.receipts)
    assert said(app, str(OSError(errno.ENOSPC, "No space left on device")))
    assert not any(isinstance(s, ys.VideoSheet) for s in app.sheets)


def test_looking_at_the_queue_does_not_read_the_portal_every_time(monkeypatch):
    """A reading is a network call; opening the tab or closing a sheet over it
    asks again only once the one on screen has gone stale."""
    app = headless(tab=3)
    asked = []
    real = app.queue.refresh

    def counted(force=True):
        asked.append(force)
        real(force)

    for job, _ in list(app.jobs):
        while not job.finished:
            time.sleep(0.01)
        app.handle(tui.Done(job))
    monkeypatch.setattr(app.queue, "refresh", counted)
    started = len(app.jobs)
    for _ in range(5):
        app.switch(0)
        app.switch(3)
    assert len(app.jobs) == started


def test_tabs_are_a_tap_away_and_q_quits():
    app = headless()
    for index in range(5):
        app.compose()
        hit = next(h for h in app.hits.hits if h.id == "tab" and h.data == index)
        app.guard.opened = -10.0  # a person's taps, not a double-tap's echo
        app.handle(tui.Tap(hit.x + 1, hit.y + 1))
        assert app.tab == index
    app.handle(tui.Key("q"))
    assert app.done


def test_q_types_into_a_focused_field_rather_than_quitting():
    app = headless()
    tap(app, "field")
    for ch in "quiz":
        app.handle(tui.Key(ch))
    assert not app.done and app.tabs[0].value == "quiz"


@pytest.mark.parametrize("state", ["nothing searched", "results", "tapped", "searching"])
def test_the_search_field_does_what_it_is_drawn_as(monkeypatch, state):
    """Drawn focused is typing: ``q`` and ``x`` are letters. Drawn otherwise
    they are Quit and Stop. At every height, the keyboard up and down, since
    with the keyboard up and nothing searched the bar takes focus (k-search)."""
    drawn = []
    real = widgets.field

    def field(value, width, *args, focus=True, **kwargs):
        drawn.append(focus)
        return real(value, width, *args, focus=focus, **kwargs)

    monkeypatch.setattr(widgets, "field", field)
    release = threading.Event()
    monkeypatch.setattr(ytq, "search", lambda q: release.wait(5) and [])
    try:
        for width in (32, 40):
            for height in range(11, 31):
                app = headless(size=(width, height))
                search = app.tabs[0]
                if state == "results":
                    with_listing(app)
                elif state == "tapped":
                    tap(app, "field")
                elif state == "searching":
                    search.search("rust")
                app.compose()
                label = (state, width, height)
                assert search.typing == drawn[-1], label
                before = search.value
                app.handle(tui.Key("q"))
                app.handle(tui.Key("x"))
                if drawn[-1]:
                    assert not app.done and search.value == before + "qx", label
                else:
                    assert app.done, label
    finally:
        release.set()


def test_a_second_go_on_the_same_words_buys_nothing_more(monkeypatch):
    """Go, then Go or Enter again while those words are being fetched: one
    search, the first, kept — also once it has finished with its answer not
    yet heard. Other words are another search, and the first is stopped."""
    asked = []
    release = threading.Event()

    def search(q):
        asked.append(q)
        release.wait(5)
        return ytq.entries(search_info([f"{q} one", f"{q} two"]))

    monkeypatch.setattr(ytq, "search", search)
    app = headless()
    tab = app.tabs[0]
    tap(app, "field")
    for ch in "rust":
        app.handle(tui.Key(ch))
    tap(app, "go")
    first = tab.job
    tap(app, "go")
    app.handle(tui.Key("enter"))
    assert tab.job is first and not first.cancelled
    release.set()
    end = time.monotonic() + 5
    while not first.finished and time.monotonic() < end:
        time.sleep(0.01)
    tap(app, "go")
    assert tab.job is first
    settle(app)
    assert asked == ["rust"] and tab.key_shown == "rust"

    release.clear()
    tap(app, "field")
    for ch in " lifetimes":
        app.handle(tui.Key(ch))
    tap(app, "go")
    second = tab.job
    tap(app, "field")
    app.handle(tui.Key("s"))
    tap(app, "go")
    assert second.cancelled and tab.job is not second
    release.set()
    settle(app)
    assert sorted(asked) == ["rust", "rust lifetimes", "rust lifetimess"]


def test_the_formats_sheet_picks_with_the_arrows_too():
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    video = app.sheets[-1]
    app.handle(tui.Key("f"))
    before, _ = video.chosen()
    app.handle(tui.Key("down"))
    after, _ = video.chosen()
    assert after is not before
    app.handle(tui.Key("enter"))
    assert app.sheets[-1] is video and video.explicit is after


def test_a_video_too_big_for_one_night_says_so_in_words():
    big = video_info(formats=[
        fmt("137", vcodec="avc1.640028", ext="mp4", height=480, filesize=4 * 1024 * MiB),
        fmt("140", acodec="mp4a.40.2", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    app = headless()
    with_listing(app, info=big)
    tap(app, "row")
    assert "nights" in app.compose().plain()


def test_a_link_only_yt_dlp_knows_opens_its_sheet_and_probes_it(monkeypatch):
    """``nibbles dQw4w9WgXcQ``: the bare id reaches the app marked as a link,
    and is probed as one rather than searched for."""
    asked = []
    monkeypatch.setattr(ytq, "probe", lambda url: asked.append(url) or video_info())
    monkeypatch.setattr(ytq, "search", lambda q: (_ for _ in ()).throw(AssertionError(q)))
    app = headless()
    app.yt.route(ytq.LINK_KEY + "dQw4w9WgXcQ")
    app.compose()
    assert isinstance(app.sheets[-1], ys.VideoSheet)
    for job, _ in list(app.jobs):
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))
    assert asked == ["dQw4w9WgXcQ"]


class Feeds:
    """Feed and Later with stand-ins for the cookie jar and the read: *jar*
    is what ``cookie_state`` says, and each read takes the next of *answers*
    (a list of videos, or an exception to raise)."""

    LISTING = ytq.entries(search_info([f"Video number {n}" for n in range(ytq.SUBS_RESULTS)]))

    def __init__(self, monkeypatch):
        self.jar = "file"
        self.answers: list = []
        monkeypatch.setattr(ytq, "cookie_state", lambda *a: (self.jar, "cookies.txt, 2d old"))
        monkeypatch.setattr(ytq, "read_feed", self.read)

    def read(self, feed, count):
        got = self.answers.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got

    def fail(self, failure):
        if failure == "no cookie":
            self.jar = "missing"
        else:
            self.answers.append(ytq.ProbeError("HTTP Error 429: Too Many Requests")
                                if failure == "error" else [])


@pytest.mark.parametrize("failure", ["error", "empty", "no cookie"])
@pytest.mark.parametrize("when", ["first read", "re-read", "deeper look"])
def test_a_feed_read_that_fails_is_said_whatever_is_on_screen(monkeypatch, failure, when):
    """A read that fails, an empty answer and a missing cookie jar each reach
    the person whether or not a listing is up: in the list's place, or a
    notice over the old rows — never the old rows saying nothing, which
    reads as nothing new. Feed and Later alike."""
    feeds = Feeds(monkeypatch)
    for tab in (1, 2):
        feeds.jar = "file"
        if when == "first read":
            feeds.fail(failure)
        else:
            feeds.answers.append(Feeds.LISTING)
        app = headless(tab=tab, size=(80, 24))
        settle(app)
        feed = app.tabs[tab]
        if when != "first read":
            assert not feed.problem and not app.sheets
            feeds.fail(failure)
            if when == "re-read":
                app.handle(tui.Key("r"))
            else:
                tap(app, "pull")
            settle(app)
        label = (failure, when, tab)
        assert feed.problem, label
        top = app.sheets[-1] if app.sheets else None
        if isinstance(top, shell.Notice):
            assert top.lines[0] == feed.problem[0], label
        else:
            assert when == "first read" and feed.problem[0] in app.compose().plain(), label


def test_a_feed_failure_waits_for_its_tab_and_a_good_read_clears_it(monkeypatch):
    """A Re-read that fails while another tab or a sheet is up is said when
    the feed is back on top, not over what is in use; one that succeeds
    afterwards leaves nothing to say."""
    feeds = Feeds(monkeypatch)
    feeds.answers.append(Feeds.LISTING)
    monkeypatch.setattr(ytq, "probe", lambda url: video_info())
    app = headless(tab=1)
    settle(app)
    feed = app.tabs[1]
    for away in ("another tab", "a sheet"):
        release = threading.Event()

        def late(feed_, count, release=release):
            release.wait(5)
            raise ytq.ProbeError("HTTP Error 429: Too Many Requests")

        monkeypatch.setattr(ytq, "read_feed", late)
        app.handle(tui.Key("r"))
        if away == "another tab":
            app.switch(0)
        else:
            ys.open_row(app, ytq.SUBS_KEY, 0)
        release.set()
        settle(app)
        assert feed.problem
        assert not any(isinstance(s, shell.Notice) for s in app.sheets), away
        if away == "another tab":
            app.switch(1)
        else:
            app.close(app.sheets[-1])
        assert isinstance(app.top, shell.Notice) and app.top.lines[0] == feed.problem[0], away
        app.handle(tui.Key("esc"))
        assert app.top is feed
    monkeypatch.setattr(ytq, "read_feed", feeds.read)
    feeds.answers.append(Feeds.LISTING)
    app.handle(tui.Key("r"))
    settle(app)
    assert not feed.problem and not app.sheets


class Loop:
    """A stand-in session for :meth:`App.run`: the real loop, no terminal.

    ``read`` keeps the real one's first promise — a finished job it was
    handed comes back as its ``Done`` — and otherwise reports nothing, a few
    times over, before quitting. ``on_show`` runs while a frame is drawn.
    """

    def __init__(self, app, on_show=lambda: None):
        self.app, self.on_show, self.idle = app, on_show, 0

    def start(self, job):
        job.run(lambda: None)
        return job

    def show(self, block):
        self.on_show()
        return 0

    def read(self, timeout, jobs):
        for job in jobs:
            if job.finished:
                return tui.Done(job)
        self.idle += 1
        if self.idle > 3:
            self.app.quit()
        return None


def test_a_probe_that_lands_while_a_frame_is_drawn_still_fills_its_sheet(monkeypatch):
    """The frozen spinner: a probe finishing between one wait and the next
    was left out of the next, its answer never heard, and the sheet waited
    on it for good."""
    import threading

    release = threading.Event()

    def probe(url):
        release.wait(5)
        return video_info()

    monkeypatch.setattr(ytq, "probe", probe)
    app = headless()
    with_listing(app)
    tap(app, "row")
    job = next(job for job, _ in app.jobs)

    def land_now():
        # The job finishes during the frame, after the last wait looked.
        release.set()
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)

    app.session = Loop(app, land_now)
    app.run()
    sheet = app.sheets[-1]
    assert isinstance(sheet, ys.VideoSheet)
    assert sheet.url in app.yt.probed
    assert sheet.tier is not None
    assert not app.jobs


def test_copying_the_link_never_holds_the_app(monkeypatch):
    """``c`` on a video sheet: the clipboard tool can wait out its whole
    timeout (no Termux:API app), and the app answers meanwhile."""
    import threading

    release = threading.Event()

    def slow(text):
        release.wait(5)
        return "copied"

    monkeypatch.setattr(ytq, "to_clipboard", slow)
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    sheet = app.sheets[-1]
    began = time.monotonic()
    app.handle(tui.Key("c"))
    assert time.monotonic() - began < 1
    # A second press while it runs starts nothing more, and ``x`` is for a
    # fetch: a copy is neither stopped by it nor a reason to keep drawing.
    app.handle(tui.Key("c"))
    copies = [job for job, _ in app.jobs if job.key == "clipboard"]
    assert len(copies) == 1
    app.stop_newest()
    assert not copies[0].cancelled
    assert copies[0] not in app.running()
    release.set()
    for job, _ in list(app.jobs):
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))
    assert sheet.said == "copied"
