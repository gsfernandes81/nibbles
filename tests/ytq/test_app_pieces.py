"""The app's pieces, without a terminal: events, guards, hits, words, lists.

What each of these pins is a rule from ``design/design.md``: a mouse report is
never a key; a tap is ignored for 100 ms after a sheet appears and on the same
cell for the rest of Android's double-tap window; a row of buttons fills its
width exactly and never more; time left is one unit; the selection rides one
item in from the edge (Helix's scrolloff); a drag on the bar moves the thumb
a row per row; the quality buttons pass a skipped codec over but never empty a
tier; a download is named after its title.
"""

from __future__ import annotations

import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nibbles import shell
from nibbles import tui
from nibbles import widgets as w
from nibbles import ytq

MiB = 1024**2


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


class FakeKey(str):
    """The parts of a blessed keystroke ``tui.event_of`` reads."""

    def __new__(cls, text="", name=None, xy=(-1, -1), sequence=False):
        made = super().__new__(cls, text)
        made.name, made.mouse_xy, made.is_sequence = name, xy, sequence
        return made


def test_a_tap_is_a_press_and_a_release_is_nothing():
    """Termux sends both on lift; the press is the tap, the release is not a
    second one."""
    assert tui.event_of(FakeKey("x", "MOUSE_LEFT", (3, 7))) == tui.Tap(3, 7)
    assert tui.event_of(FakeKey("x", "MOUSE_LEFT_RELEASED", (3, 7))) is None
    assert tui.event_of(FakeKey("x", "MOUSE_RELEASED", (3, 7))) is None


def test_a_wheel_is_a_signed_step_stamped_with_where_the_drag_began():
    assert tui.event_of(FakeKey("x", "MOUSE_SCROLL_DOWN", (5, 9))) == tui.Scroll(1, 5, 9)
    assert tui.event_of(FakeKey("x", "MOUSE_SCROLL_UP", (5, 9))) == tui.Scroll(-1, 5, 9)


def test_a_mouse_report_is_never_a_key():
    for name in ("MOUSE_MOTION", "MOUSE_RIGHT", "MOUSE_MIDDLE", "MOUSE_LEFT_MOTION"):
        assert tui.event_of(FakeKey("\x1b[<35;1;1M", name, (0, 0), True)) is None


def test_an_escape_sequence_nobody_named_is_dropped_whole():
    """Never a byte of it through as a letter that presses something."""
    assert tui.event_of(FakeKey("\x1b[99~", None, sequence=True)) is None
    assert tui.event_of(FakeKey("", None)) is None


def test_keys_have_one_short_spelling():
    assert tui.event_of(FakeKey("\x1b[A", "KEY_UP", sequence=True)) == tui.Key("up")
    assert tui.event_of(FakeKey("\r", "KEY_ENTER")) == tui.Key("enter")
    assert tui.event_of(FakeKey("\x1b", "KEY_ESCAPE")) == tui.Key("esc")
    assert tui.event_of(FakeKey("\x15")) == tui.Key("ctrl-u")
    assert tui.event_of(FakeKey("q")) == tui.Key("q")


def test_a_paste_is_one_event_and_never_a_key():
    """What blessed hands over for a bracketed paste — built the way blessed
    builds it — is one :class:`tui.Paste`, its line breaks spaces: never
    a ⏎ or a letter that acts."""
    from blessed.dec_modes import DecPrivateMode
    from blessed.keyboard import RE_PATTERN_BRACKETED_PASTE, Keystroke

    sent = "\x1b[200~crust of rust\rsubtyping\r\x1b[201~"
    ks = Keystroke(ucs=sent, mode=DecPrivateMode.BRACKETED_PASTE,
                   match=RE_PATTERN_BRACKETED_PASTE.match(sent))
    assert ks.name == "BRACKETED_PASTE"
    assert tui.event_of(ks) == tui.Paste("crust of rust subtyping")
    empty = "\x1b[200~\r\n\x1b[201~"
    ks = Keystroke(ucs=empty, mode=DecPrivateMode.BRACKETED_PASTE,
                   match=RE_PATTERN_BRACKETED_PASTE.match(empty))
    assert tui.event_of(ks) is None


@given(st.text())
def test_a_paste_reaches_a_field_as_one_printable_line(text):
    """Every character a field can show is kept, in order; everything else —
    a line break, a tab, an escape — is a space."""
    line = tui.one_line(text)
    assert line.isprintable()
    kept = [ch for ch in text.strip("\r\n") if ch.isprintable() and ch != " "]
    assert [ch for ch in line if ch != " "] == kept


# --------------------------------------------------------------------------- #
# The guards
# --------------------------------------------------------------------------- #


def test_every_tap_is_ignored_for_a_tenth_of_a_second_after_a_sheet_appears():
    guard = tui.Guard()
    guard.opened_by(tui.Tap(4, 4), at=100.0)
    assert not guard.allows(tui.Tap(20, 20), at=100.05)
    assert guard.allows(tui.Tap(20, 20), at=100.11)


def test_only_the_same_cell_is_dropped_for_the_rest_of_the_double_tap_window():
    guard = tui.Guard()
    guard.opened_by(tui.Tap(4, 4), at=100.0)
    assert not guard.allows(tui.Tap(4, 4), at=100.2)
    assert guard.allows(tui.Tap(5, 4), at=100.2)
    assert guard.allows(tui.Tap(4, 4), at=100.31)


def test_a_sheet_opened_by_a_key_guards_no_cell():
    guard = tui.Guard()
    guard.opened_by(None, at=100.0)
    assert guard.allows(tui.Tap(4, 4), at=100.2)


# --------------------------------------------------------------------------- #
# Hits
# --------------------------------------------------------------------------- #


def test_the_last_thing_composed_wins_a_cell():
    hits = w.HitMap()
    hits.add(w.Hit(0, 0, 10, 10, "under"))
    hits.add(w.Hit(2, 2, 3, 3, "over"))
    assert hits.at(3, 3).id == "over"
    assert hits.at(0, 0).id == "under"
    assert hits.at(10, 10) is None


def test_a_target_is_only_where_it_was_drawn():
    s = w.Surface(10, 5)
    s.put(w.button("Go", "", 6, id="go"), 7, 3)
    hit = s.hits.find("go")
    assert hit.x + hit.w <= 10 and hit.y + hit.h <= 5


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #

words = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF,
                                       blacklist_categories=("Cs", "Cc", "Mn", "Me")),
                min_size=1, max_size=14)


@given(labels=st.lists(words, min_size=1, max_size=4), width=st.integers(24, 120))
def test_a_row_of_buttons_fills_its_width_exactly(labels, width):
    """Spare columns shared out; too tight and the widest gives, never wider."""
    if len(labels) * 5 > width:
        return
    row = w.dock([w.Btn(label, id=f"b{i}") for i, label in enumerate(labels)], width)
    assert row.width == width and row.height == 3
    assert sorted(h.id for h in row.hits) == sorted(f"b{i}" for i in range(len(labels)))
    edges = sorted((h.x, h.x + h.w) for h in row.hits)
    assert edges[0][0] == 0 and edges[-1][1] == width
    assert all(a[1] == b[0] for a, b in zip(edges, edges[1:], strict=False))


@given(width=st.integers(10, 80), n=st.integers(2, 4))
def test_one_of_choices_are_equal_boxes(width, n):
    row = w.segmented([f"opt{i}" for i in range(n)], 0, width, "pick")
    sizes = [h.w for h in row.hits]
    assert row.width == width and max(sizes) - min(sizes) <= 1


def test_a_pressed_button_is_drawn_filled():
    plain = w.button("Go", "⏎", 10, "primary", id="go")
    pressed = w.button("Go", "⏎", 10, "primary", id="go", pressed="go")
    assert plain.block.plain() == pressed.block.plain()
    assert plain.block != pressed.block


def test_the_checkbox_says_its_state_in_a_glyph_and_not_only_a_colour():
    assert "✓" in w.checkbox("Open it when done", True, 30).block.plain()
    assert "•" in w.checkbox("Open it when done", False, 30).block.plain()


@given(width=st.integers(32, 120))
def test_the_tab_bar_keeps_all_five_tabs_and_the_status_bar(width):
    bar = w.tab_bar(3, width, ("↓ 18%", "warn", "ubuntu-24.04-desktop-amd64.iso", "1h"))
    assert bar.width == width and bar.height == 4
    assert [h.data for h in bar.hits] == list(range(5))
    assert all(h.h == 3 for h in bar.hits)
    for tab in w.TABS:
        assert tab in bar.block.plain()


@given(detail=st.text(max_size=80), width=st.integers(20, 80))
def test_the_status_bar_keeps_its_label_and_a_clear_column(detail, width):
    bar = w.status_bar(("WAITING", "primary", detail, "19m"), width)
    line = bar.plain()
    assert bar.width == width
    assert line.startswith(" WAITING ")
    assert line.endswith(" 19m ")


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("seconds", "said"), [
    (35, "35s"), (59, "59s"), (60, "1m"), (5 * 60 + 20, "5m"), (59 * 60 + 40, "1h"),
    (71 * 60, "1h"), (100 * 60, "2h"),
])
def test_time_left_is_one_unit_never_two(seconds, said):
    assert shell.left(seconds) == said


def test_no_time_left_is_said_as_nothing_and_never_formatted():
    assert shell.left(None) == "" and shell.left(float("inf")) == ""
    assert shell.clock(float("inf")) == "no stop time"


def test_a_clock_is_the_phones_own_and_never_utc():
    now = time.time()
    assert "Z" not in shell.clock(now + 3600, now)
    at = round((now + 3600) / 60) * 60
    assert shell.clock(now + 3600, now) == time.strftime("%H:%M", time.localtime(at))
    # To the nearest minute: seconds before the hour are the hour.
    hour = (int(now // 3600) + 2) * 3600
    assert shell.clock(hour - 2, now) == time.strftime("%H:%M", time.localtime(hour))


@pytest.mark.parametrize(("n", "said"), [(0, "0 B"), (92 * MiB, "92 MiB"),
                                         (int(10.2 * MiB), "10.2 MiB"),
                                         (int(1.02 * 1024 * MiB), "1.02 GiB")])
def test_a_size_is_three_figures_at_most(n, said):
    assert shell.size(n) == said


@pytest.mark.parametrize(("n", "said"), [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
                                         (11, "11th"), (12, "12th"), (13, "13th"),
                                         (21, "21st"), (22, "22nd")])
def test_a_position_is_said_the_way_a_person_says_it(n, said):
    assert shell.ordinal(n) == said


# --------------------------------------------------------------------------- #
# Names, tiers, preferences
# --------------------------------------------------------------------------- #


def test_a_download_is_named_after_its_title():
    """Cleaned only of what Android's shared storage refuses."""
    assert ytq.title_name("Crust of Rust: Subtyping and Variance") == \
        "Crust of Rust - Subtyping and Variance"
    assert ytq.title_name('a/b\\c*d?e"f<g>h|i') == "a - b - c - d - e - f - g - h - i"
    assert ytq.title_name("   ") == "video"


@given(title=st.text(max_size=400))
def test_a_name_is_never_refused_and_never_too_long(title):
    name = ytq.title_name(title)
    assert name and len(name.encode("utf-8")) <= ytq.NAME_BYTES
    assert not set(name) & set('/\\:*?"<>|')
    assert ytq.ITEM_RE.match(ytq.item_name(10, name))


def choice(label, size, codecs, kind="merge"):
    return ytq.Choice(kind, label, size, True, "mp4", label, "", codecs=codecs)


TIER = [
    choice("480p webm", 71 * MiB, "vp9 + opus"),
    choice("480p mp4", 92 * MiB, "avc1.4d401e + mp4a.40.2"),
    choice("480p mp4", 104 * MiB, "av01.0.04M.08 + mp4a.40.2"),
]


def test_smallest_passes_a_skipped_codec_over_and_says_which():
    got, passed = ytq.pick_in_tier(TIER, ("video", 480), "smallest", ["vp9", "av01"])
    assert got.size == 92 * MiB and passed == ["vp9"]
    got, passed = ytq.pick_in_tier(TIER, ("video", 480), "largest", ["vp9", "av01"])
    assert got.size == 92 * MiB and passed == ["av01"]


def test_nothing_skipped_is_nothing_said():
    got, passed = ytq.pick_in_tier(TIER, ("video", 480), "smallest", [])
    assert got.size == 71 * MiB and passed == []


def test_a_preference_never_empties_a_tier():
    only = [choice("480p webm", 71 * MiB, "vp9 + opus")]
    got, passed = ytq.pick_in_tier(only, ("video", 480), "smallest", ["vp9"])
    assert got is only[0] and passed == []


def test_the_quality_buttons_are_the_heights_you_use():
    assert ytq.chip_heights({}) == [240, 480, 720]
    learned = {"heights": {"1080": 9, "480": 7, "240": 1, "360": 3}}
    assert ytq.chip_heights(learned) == [360, 480, 1080]
    assert ytq.chip_heights({"chips": [720, 144]}) == [144, 720]


def test_smallest_is_the_video_default_and_largest_the_audio_one():
    assert ytq.rule_for("video", {}) == "smallest"
    assert ytq.rule_for("audio", {}) == "largest"
    assert ytq.rule_for("video", {"rule": {"video": "largest"}}) == "largest"


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


def rows(n):
    return [shell.Entry(2, lambda wd, sel: w.gap(wd, 2).block, key=i) for i in range(n)]


def test_the_selection_rides_one_item_in_from_the_edge():
    """Helix's scrolloff: a swipe moves the view, and the cursor stays on its
    row until it comes within one item of the edge."""
    view = shell.ListView(entries=rows(30), height=10)  # five items on screen
    view.cursor = 2
    for _ in range(2):  # one item's worth of rows
        view.view(1)
    assert view.top == 1 and view.cursor == 2  # still inside the margin
    for _ in range(4):
        view.view(1)
    assert view.top == 3 and view.cursor == 4  # riding one item in


def test_arrows_keep_the_same_margin():
    view = shell.ListView(entries=rows(30), height=10)
    view.cursor = 0
    for _ in range(4):
        view.move(1)
    assert view.cursor == 4 and view.top + view.visible() - 1 >= view.cursor + 1


def test_with_fewer_than_three_items_on_screen_there_is_no_margin():
    view = shell.ListView(entries=rows(30), height=4)
    assert view.margin() == 0


@given(n=st.integers(1, 60), height=st.integers(2, 40), cursor=st.integers(-1, 70),
       top=st.integers(0, 70), steps=st.lists(st.integers(-3, 3), max_size=30))
def test_the_view_always_hands_back_a_place_the_screen_draws(n, height, cursor, top, steps):
    """A restored place on a list that grew, shrank or was resized."""
    view = shell.ListView(entries=rows(n), height=height, cursor=min(cursor, n - 1), top=top)
    view.settle()
    for step in steps:
        view.view(step)
        view.settle()
        assert 0 <= view.top <= max(0, view.furthest())
        assert -1 <= view.cursor < n
        if view.cursor >= 0 and step:
            assert view.top <= view.cursor < view.top + max(1, view.visible())


def test_a_drag_that_starts_on_the_bar_moves_the_thumb_a_row_per_row():
    view = shell.ListView(entries=rows(100), height=20)
    view.width, view.y = 40, 0
    start, _ = w.thumb(20, view.total_rows(), 20, view.offset_rows())
    view.bar_drag(3)
    moved, _ = w.thumb(20, view.total_rows(), 20, view.offset_rows())
    assert moved == start + 3
    assert view.in_bar(39, 5) and view.in_bar(37, 5) and not view.in_bar(36, 5)
