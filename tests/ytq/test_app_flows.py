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
from hypothesis import given, settings
from hypothesis import strategies as st

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


def heard(app):
    """Every job allowed to finish and its answer delivered, as the loop would."""
    for job, _ in list(app.jobs):
        end = time.monotonic() + 5
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))


def child_of(job):
    end = time.monotonic() + 5
    while job._child is None and time.monotonic() < end:
        time.sleep(0.01)
    assert job._child is not None, "the fetch never started its child"
    return job._child


def test_x_stops_the_fetch_and_never_a_question_asked_after_it(monkeypatch):
    """A feed read is going; a glance at More asks Android's scheduler, which
    is newer. ``x`` back on Feed kills the read's yt-dlp, and the scheduler's
    answer still lands — it is no fetch, holds no child, and dropping it left
    More saying nothing about the nightly job."""
    import threading

    from nibbles import queue_screens as qs

    release = threading.Event()
    monkeypatch.setattr(ytq, "cookie_state", lambda: ("file", "a jar"))
    monkeypatch.setattr(ytq, "read_feed",
                        lambda feed, count: tui.run_child(["sleep", "30"], 60) and [])
    monkeypatch.setattr(qs.sched, "job_rows",
                        lambda: release.wait(5) and [("job", "not armed", "1;31")])
    app = headless()
    app.switch(nibbles.FEED)
    reading = app.tabs[nibbles.FEED].job
    assert reading is not None and reading.fetch
    child = child_of(reading)
    app.switch(nibbles.MORE)
    asking = app.tabs[nibbles.MORE].job_job
    app.switch(nibbles.FEED)
    app.handle(tui.Key("x"))
    assert reading.cancelled and not asking.cancelled
    assert child.wait(5) is not None
    release.set()
    heard(app)
    assert app.tabs[nibbles.MORE].job_rows == [("job", "not armed", "1;31")]
    # With no fetch running, x stops nothing at all.
    release.clear()
    app.switch(nibbles.MORE)
    asking = app.tabs[nibbles.MORE].job_job
    assert not app.stop_newest() and not asking.cancelled
    release.set()
    heard(app)


class Reads:
    """A stand-in session for :meth:`App.run` that hands it *events* in
    turn, raising one that is an exception, as ctrl-c raises in the loop."""

    def __init__(self, *events):
        self.events = list(events)

    def start(self, job):
        job.run(lambda: None)
        return job

    def show(self, block):
        return 0

    def read(self, timeout, jobs):
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def test_leaving_the_app_stops_every_fetch_it_started(monkeypatch):
    """``q`` and ctrl-c alike: a fetch's yt-dlp runs in a session of its own,
    so nothing the terminal does reaches it — the app kills it on the way
    out. A hand-off to Android is left to finish."""
    for leaving in (tui.Key("q"), KeyboardInterrupt()):
        app = headless()
        fetch = app.start(tui.Job(lambda: tui.run_child(["sleep", "30"], 60), "reading",
                                  fetch=True), shell.Screen())
        handoff = app.start(tui.Job(lambda: tui.run_child(["sleep", "30"], 60), "copying",
                                    quiet=True), shell.Screen())
        fetching, handing = child_of(fetch), child_of(handoff)
        app.session = Reads(leaving)
        try:
            app.run()
        except KeyboardInterrupt:
            assert isinstance(leaving, KeyboardInterrupt)
        try:
            assert fetching.wait(5) is not None, leaving
            assert handing.poll() is None, leaving
        finally:
            handoff.cancel()
            handing.wait(5)


#: What a paste can hold that a key would act on: ⏎ (submit, open the
#: selected row), q (quit), x (stop), n/l/s and ⏎ on a video sheet (Now, the
#: rule, the button), esc, a tab, an arrow's escape sequence.
PASTES = ["crust of rust\rsubtyping\r", "q", "x", "n\rl\rs\r\r", "\x1b", "a\tb",
          "\x1b[A\r", "https://youtu.be/dQw4w9WgXcQ\n", "\r\n\r\n", "quit\rx\r"]


def test_a_paste_goes_into_the_field_and_does_nothing_else(clean_queue, monkeypatch):
    """Whatever it holds and wherever the field's focus was, with a listing
    up whose selected row's formats are already in: the field takes it as
    one line, and nothing is searched, opened, stopped, queued or quit."""
    started = []
    for text in PASTES:
        for focused in (True, False):
            app = headless()
            monkeypatch.setattr(app.queue, "start_now", lambda name: started.append(name))
            with_listing(app, info=video_info())
            app.yt.view("crust").cursor = 0
            search = app.tabs[0]
            search.focus = focused
            before = (search.value, len(app.jobs), app.tab)
            event = tui.Paste(tui.one_line(text))
            app.handle(event)
            assert not app.done and not app.sheets, text
            assert (len(app.jobs), app.tab) == before[1:], text
            assert search.value == before[0] + event.text and search.value.isprintable()
            assert search.focus
    assert started == [] and ytq.items() == []


def test_a_paste_into_a_sheets_field_never_sets_it(monkeypatch):
    """Rename and the settings: the field takes what it accepts of a paste,
    the sheet stays up, and only Set or ⏎ submits."""
    from nibbles import queue_screens as qs

    class Field(qs.FieldSheet):
        submitted = False

        def submit(self, app):
            self.submitted = True

    class Digits(Field):
        def accepts(self, ch):
            return ch.isdigit()

    for sheet, text, value in ((Field("rename", "old"), "new\rname\r", "oldnew name"),
                               (Digits("window", ""), "45 min\rq\r", "45")):
        app = headless(tab=nibbles.QUEUE)
        app.open(sheet)
        app.handle(tui.Paste(tui.one_line(text)))
        assert app.sheets[-1] is sheet and not sheet.submitted and not app.done
        assert sheet.value == value


def test_a_pressed_button_on_a_sheet_unfills_after_one_frame(monkeypatch):
    """Filled for one frame wherever it is (``tui.PRESSED``): the sheets read
    ``app.pressed`` themselves, and once it stayed set the last button tapped
    on one stayed filled until the next tap."""
    app = headless()
    with_listing(app, info=video_info())
    tap(app, "row")
    tier = f"tier:{app.sheets[-1].tier[1]}"
    tap(app, tier)
    pressed = app.compose()
    later = time.monotonic() + tui.PRESSED + 0.05
    monkeypatch.setattr(nibbles.time, "monotonic", lambda: later)
    after = app.compose()
    app.pressed, app.pressed_until = None, 0.0
    assert after == app.compose(), "drawn as if nothing had been pressed"
    assert pressed != after, "and the press itself was drawn"


def test_what_the_door_hands_the_app_lands_where_the_field_would(monkeypatch):
    """``nibbles :ytsubs`` opens Feed and ``nibbles :ytwatchlater`` Later,
    as the same words typed into the field do — never a video sheet probing
    the list as one video. A bare id is still a link, and probed."""
    seen = {}
    probed = []
    monkeypatch.setattr(nibbles, "run",
                        lambda start, first, preloaded, now, dest: seen.update(first=first)
                        or [])
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: True)
    monkeypatch.setattr(ytq, "probe", lambda url: probed.append(url) or video_info())
    for word, tab in ((":ytsubs", nibbles.FEED), (":ytwatchlater", nibbles.LATER),
                      ("dQw4w9WgXcQ", nibbles.SEARCH)):
        assert nibbles.main([word]) == 0
        typed, door = headless(), headless()
        typed.yt.route(word)
        door.yt.begin(seen["first"], None)
        assert door.tab == tab
        assert any(isinstance(s, ys.VideoSheet) for s in door.sheets) == (tab == nibbles.SEARCH)
        if tab != nibbles.SEARCH:
            assert typed.tab == door.tab and not typed.sheets
        heard(door)
    assert probed == ["dQw4w9WgXcQ"]


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
                    search.search(app, "rust")
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


# --------------------------------------------------------------------------- #
# Stepping with Tab
# --------------------------------------------------------------------------- #

#: The dwell, made longer than any test takes between two keys however busy
#: the machine: a quick run of Tab presses, made certain.
SLOW_DWELL = 60.0

#: The list each tab reads, for the two that read one.
LISTS = {nibbles.FEED: ytq.SUBS, nibbles.LATER: ytq.WATCH_LATER}


def reading(mp):
    """A cookie jar on disk, and every feed read recorded: the lists asked
    for, in the order asked."""
    asked = []
    mp.setattr(ytq, "cookie_state", lambda *a: ("file", "cookies.txt, 2d old"))
    mp.setattr(ytq, "read_feed", lambda feed, count: asked.append(feed) or Feeds.LISTING)
    mp.setattr(ys, "DWELL", SLOW_DWELL)
    return asked


@settings(max_examples=25, deadline=None)
@given(keys=st.lists(st.sampled_from(["tab", "btab"]), min_size=1, max_size=7),
       after=st.lists(st.sampled_from(["tab", "btab"]), max_size=7))
def test_tab_reads_no_list_it_passes_and_only_the_one_it_stops_on(keys, after):
    """Any run of Tab and Shift-Tab with no rest between reads nothing —
    Search to Queue passes Feed and Later. Stopped on, a list reads itself
    once the keys have rested there; and however the keys go on, resting on
    every tab, each list stopped on is read, and none twice."""
    with pytest.MonkeyPatch.context() as mp:
        asked = reading(mp)
        app = headless()
        for key in keys:
            app.handle(tui.Key(key))
            app.tick()  # the loop goes round between keys
        settle(app)
        assert asked == []
        stopped = {LISTS[app.tab]} if app.tab in LISTS else set()
        app.tick(time.monotonic() + SLOW_DWELL)
        settle(app)
        assert asked == list(stopped)
        for key in after:
            app.handle(tui.Key(key))
            app.tick(time.monotonic() + SLOW_DWELL)
            settle(app)
            stopped |= {LISTS[app.tab]} if app.tab in LISTS else set()
        assert sorted(asked, key=id) == sorted(stopped, key=id)


def test_a_tap_on_a_list_reads_it_at_once_and_so_does_r(monkeypatch):
    """A tap on its tab is the deliberate act, with no rest to wait out; so
    is ``r`` on a list the keys are passing, and the rest that follows reads
    nothing more."""
    asked = reading(monkeypatch)
    app = headless()
    app.compose()
    hit = next(h for h in app.hits.hits if h.id == "tab" and h.data == nibbles.FEED)
    app.handle(tui.Tap(hit.x + 1, hit.y + 1))
    settle(app)
    assert asked == [ytq.SUBS]
    app.handle(tui.Key("tab"))
    assert app.tab == nibbles.LATER and asked == [ytq.SUBS]
    app.handle(tui.Key("r"))
    settle(app)
    app.tick(time.monotonic() + SLOW_DWELL)
    settle(app)
    assert asked == [ytq.SUBS, ytq.WATCH_LATER]


def test_the_rest_on_a_list_is_a_wake_that_ends(monkeypatch):
    """The tab wakes the loop for the end of the rest and for nothing after
    it: once the list is read and in, a screen of short titles sleeps until
    something happens. (The status bar's countdown is the queue's wake, and
    stands either way.)"""
    asked = reading(monkeypatch)
    app = headless()
    feed = app.tabs[nibbles.FEED]
    assert feed.wake(app) is None
    app.handle(tui.Key("tab"))
    wait = feed.wake(app)
    assert wait is not None and 0 < wait <= SLOW_DWELL
    assert app.next_wake() <= wait
    app.tick(time.monotonic() + SLOW_DWELL)
    settle(app)
    assert asked == [ytq.SUBS] and feed.wake(app) is None


def test_every_tab_is_where_its_name_says():
    """One order along the bottom: the labels drawn, the door's words for
    them and the names the screens go to a tab by agree, so a tab moved is
    moved everywhere or the suite says so."""
    app = headless()
    assert [label.lower() for label in widgets.TABS] == list(nibbles.START)
    assert list(nibbles.START.values()) == list(range(len(app.tabs)))
    assert isinstance(app.tabs[nibbles.SEARCH], ys.SearchTab)
    for feed in ytq.FEEDS.values():
        assert app.tabs[ys.feed_tab(feed)].feed is feed
        assert LISTS[ys.feed_tab(feed)] is feed
    assert type(app.tabs[nibbles.QUEUE]).__name__ == "QueueTab"
    assert type(app.tabs[nibbles.MORE]).__name__ == "MoreTab"


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
