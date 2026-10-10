"""The app's flows with no terminal: what a tap or a key leads to.

The real :class:`nibbles.App`, headless (``App(None, tab, size=...)``), driven
with the events the terminal would hand it. Asserted on the state the next
frame is drawn from — which sheet is on top, what was written, what was asked
for — never on wording.
"""

from __future__ import annotations

import time

import nibbles
import shell
import tui
import ytq
import yt_screens as ys
from conftest import fmt, search_info, video_info

MiB = 1024**2


def headless(tab=0, size=(40, 24)):
    app = nibbles.App(None, tab, size=size)
    app.guard.opened = -10.0
    return app


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
