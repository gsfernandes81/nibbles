"""Every screen, at every size a phone gives it: design §8's layout sweep.

Widths 32 to 80 and heights 11 to 30 — the keyboard up and down, portrait and
a small landscape window — and at each one, for every tab and every sheet:

- every line is exactly the terminal's width, and there are exactly its rows;
- every tap target is on the screen, and no two of them overlap;
- buttons are three rows tall (one that a scrolling sheet body has cut at its
  edge is the only exception: it is half under the edge, not shrunk);
- a sheet's pinned answers and its ``esc ×`` are always on the screen;
- the five tabs are always there under a tab screen.

These are properties of the drawing, not of the words: what a button says is
free to change, and none of this notices.
"""

from __future__ import annotations

import pytest

from nibbles import app as nibbles
from nibbles import queue_screens as qs
from nibbles import shell
from nibbles import ytq
from nibbles import yt_screens as ys
from conftest import search_info, video_info

MiB = 1024**2

WIDTHS = [32, 33, 36, 40, 41, 48, 60, 80]
HEIGHTS = list(range(11, 31))

#: Targets that hold others, rather than being something to press.
CONTAINERS = {"outside", "sheet", "sheet-bar"}
#: Targets that are not three-row buttons by design.
NOT_BUTTONS = ("close", "stop", "row", "dest:", "pick", "field", "pull")


def containers(hit) -> bool:
    return hit.id in CONTAINERS or hit.id.endswith("-bar")


def is_button(hit) -> bool:
    return not containers(hit) and not hit.id.startswith(NOT_BUTTONS) and hit.id != "tab"


def check(app, label) -> None:
    W, H = app.width, app.height
    block = app.compose()
    assert block.width == W and block.height == H, label
    lines = block.plain().split("\n")
    assert len(lines) == H, label
    leaves = [hit for hit in app.hits.hits if not containers(hit)]
    for hit in app.hits.hits:
        assert hit.x >= 0 and hit.x + hit.w <= W and hit.y >= 0 and hit.y + hit.h <= H, (
            label, hit)
    # Nothing overlaps (the dimmed screen and the sheet's own back excepted).
    for i, a in enumerate(leaves):
        for b in leaves[i + 1:]:
            apart = (a.x + a.w <= b.x or b.x + b.w <= a.x
                     or a.y + a.h <= b.y or b.y + b.h <= a.y)
            assert apart, (label, a, b)
    sheet = app.sheets[-1] if app.sheets else None
    body = None
    if sheet is not None and sheet.layout is not None and sheet.layout.scrolls:
        body = (sheet.layout.body_y, sheet.layout.body_y + sheet.layout.room)
    for hit in leaves:
        if is_button(hit):
            cut = body is not None and (hit.y == body[0] or hit.y + hit.h == body[1])
            assert hit.h == 3 or cut, (label, hit)
    if sheet is not None:
        assert app.hits.find("close") is not None, label
    elif not getattr(app.tabs[app.tab], "fullscreen", False):
        assert [h.data for h in app.hits.hits if h.id == "tab"] == list(range(5)), label


def sweep(app, label, pinned: tuple[str, ...] = ()) -> None:
    for width in WIDTHS:
        for height in HEIGHTS:
            app.width, app.height = width, height
            check(app, f"{label} {width}x{height}")
            for id in pinned:
                assert any(h.id == id or h.id.startswith(id) for h in app.hits.hits), (
                    label, width, height, id)


@pytest.fixture
def app(queued):
    """The app, headless, with something in every list."""
    for n, name in enumerate(("ubuntu-24.04-desktop-amd64.iso", "Some Talk About Rust",
                              "big.iso")):
        queued(f"{(n + 1) * 10:02d}-{name}.py",
               body=f'"""x"""\n# EXPECT_BYTES: {(n + 1) * 300 * MiB}\n')
    made = nibbles.App(None, 0, size=(40, 24))
    yt = made.yt
    hits = ytq.entries(search_info([f"Video number {n} with a long enough title" for n in
                                    range(25)]))
    yt.landed("crust of rust", hits)
    yt.landed(ytq.SUBS_KEY, hits)
    made.tabs[0].show("crust of rust")
    for tab in (1, 2):
        made.tabs[tab].read_once = True
    info = video_info()
    yt.probed[info["webpage_url"]] = (info, *ytq.choices(info))
    made.url = info["webpage_url"]
    return made


@pytest.mark.parametrize("tab", range(5))
def test_every_tab_fits_every_size(app, tab):
    app.switch(tab)
    sweep(app, f"tab {tab}")


def test_the_search_tab_with_nothing_searched_fits(app):
    app.tabs[0].key_shown = None
    sweep(app, "search home")


def test_moving_a_download_fits_every_size(app):
    app.switch(3)
    app.tabs[3].hold(app, app.queue.rows[2]["name"])
    sweep(app, "moving", pinned=("put", "cancel"))


def video(app, **state):
    sheet = ys.VideoSheet(app, app.url, "Crust of Rust: Lifetime Annotations", "Jon Gjengset")
    app.sheets[:] = [sheet]
    sheet.shown(app)
    assert sheet.tier is not None, "the sheet is ready on a kept probe"
    for key, value in state.items():
        setattr(sheet, key, value)
    return sheet


def test_the_video_sheet_fits_and_keeps_its_button(app):
    video(app)
    sweep(app, "video", pinned=("go",))


def test_the_video_sheet_on_now_fits_and_keeps_its_button(app):
    video(app, when=1)
    sweep(app, "video now", pinned=("go",))


def test_the_video_sheet_on_audio_fits(app):
    sheet = video(app)
    sheet.to_mode("audio")
    sweep(app, "video audio", pinned=("go",))


@pytest.mark.parametrize("chips", [
    [240, 480, 720], [360, 720, 1080],  # More's presets
    [240, 360, 480, 720], [144, 240, 360, 480, 720, 1080, 1440, 2160],
])
def test_hand_set_quality_chips_never_squeeze_a_tier_button(app, chips):
    """Heights set by hand are every one of them, so they can outnumber the
    row: it holds fewer buttons rather than narrower ones. At every width,
    every tier button's label is whole, and the tier the sheet is on and
    ``audio`` are always among them; the heights left out live under Formats."""
    assert ytq.save_prefs({"chips": chips}) is None
    for tier in (("video", 360), ("video", 1080)):
        video(app, tier=tier)
        for width in range(32, 81):
            for height in (14, 24):
                app.width, app.height = width, height
                lines = app.compose().plain().split("\n")
                row = [h for h in app.hits.hits if h.id.startswith("tier")]
                ids = {h.id for h in row}
                label = f"{chips} on {tier} at {width}x{height}"
                assert f"tier:{tier[1]}" in ids and "tier-audio" in ids, (label, ids)
                for hit in row:
                    assert "…" not in lines[hit.y + 1][hit.x:hit.x + hit.w], (label, hit)


def test_the_duplicate_line_is_pinned_with_its_answer(app):
    clash = ytq.Duplicate(ytq.DONE / "2026-08-11" / "10-x.py", "done", "source")
    video(app, clash=clash)
    sweep(app, "video dup", pinned=("again",))


def test_the_loading_sheet_fits(app):
    sheet = ys.VideoSheet(app, "https://youtu.be/not-probed", "Not probed yet", "someone")
    app.sheets[:] = [sheet]
    sweep(app, "video loading", pinned=("go",))


def test_every_format_fits(app):
    sheet = video(app)
    app.sheets.append(ys.FormatsSheet(sheet))
    sweep(app, "formats")


def test_a_downloads_sheets_fit(app):
    row = app.queue.rows[1]
    for sheet, pinned in (
        (qs.ItemSheet(row), ()),
        (qs.DownloadSheet(row["name"]), ()),
        (qs.remove_sheet(app, row, qs.ItemSheet(row)), ("answer:",)),
        (qs.now_sheet(app, row, qs.ItemSheet(row)), ("answer:",)),
        (qs.RenameSheet(row), ("set", "cancel")),
    ):
        app.sheets[:] = [sheet]
        sweep(app, type(sheet).__name__, pinned=pinned)


def test_run_now_fits_blind_and_counted(app):
    for blind in (True, False):
        offer = {"spendable": 1200 * MiB, "blind": blind, "items": [{}, {}],
                 "verdict": "blind" if blind else "go"}
        app.sheets[:] = [qs.run_sheet(app, offer)]
        sweep(app, f"run blind={blind}", pinned=("answer:",))


def test_the_settings_sheets_fit(app):
    app.switch(4)
    for sheet in (qs.SettingSheet("window"), qs.SettingSheet("reserve"), qs.SkipSheet(),
                  qs.ChipsSheet(), qs.DestSheet(), qs.PathSheet("video")):
        app.sheets[:] = [sheet]
        pinned = ("set", "cancel") if isinstance(sheet, qs.FieldSheet) else ()
        sweep(app, type(sheet).__name__, pinned=pinned)


def test_a_long_notice_keeps_its_way_out(app):
    """A notice never loses its own way out: its body scrolls, its OK stays."""
    lines = ["the first line says what happened"] + [
        f"line {n}: /data/data/com.termux/files/home/.config/yt-dlp/cookies.txt"
        for n in range(30)]
    app.sheets[:] = [shell.Notice("A long one", lines)]
    sweep(app, "notice", pinned=("ok",))
