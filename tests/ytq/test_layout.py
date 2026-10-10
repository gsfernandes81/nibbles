"""Every line these screens draw has to fit the terminal it is drawn on.

The floor is 32 columns, and a line that does not fit is never a cosmetic
problem here: what gets clipped off the end of a hint line is the way out of
the screen, what gets clipped off a notice is the fix, and what gets clipped
off a feed line is the price of the key above it. So the widths are a property
and not a spot check — every layout is measured across the whole range, with
the content a phone actually gets.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

import ytq

#: The narrowest terminal these screens promise to work on, and a comfortable
#: desk-sized one. Everything below is measured across the lot.
WIDTHS = range(32, 121)

LONG_TITLE = (
    "Crust of Rust: Subtyping and Variance, and Why Your Lifetimes Are Wrong"
)


def a_result(title=LONG_TITLE, channel="Jon Gjengset", duration=5434,
             views=312_456):
    return ytq.Result(
        title=title, channel=channel, url="https://youtu.be/x",
        duration=duration, timestamp=1_700_000_000, key="youtube:x",
        views=views,
    )


# --------------------------------------------------------------------------- #
# The hints, which is where the way out lives
# --------------------------------------------------------------------------- #


def test_every_hint_set_fits_the_room_it_is_written_for():
    for keys in ytq.HINTS.values():
        assert len(keys) <= ytq.HINT_WIDTH
    for keys in ytq.TIGHT_HINTS.values():
        assert len(keys) <= ytq.TIGHT_WIDTH


def test_the_two_sets_answer_for_the_same_screens():
    """A screen with no tight set would be a screen clipped at the floor."""
    assert set(ytq.HINTS) == set(ytq.TIGHT_HINTS)


def test_every_screen_still_says_how_to_leave_it():
    for name in ytq.HINTS:
        for width in (ytq.TIGHT_WIDTH + 2, ytq.HINT_WIDTH + 2, 100):
            keys = ytq.hint(name, width)
            assert "back" in keys or "quit" in keys


def test_the_narrow_set_is_the_one_a_phone_gets():
    assert ytq.hint("results", ytq.TIGHT - 1) == ytq.TIGHT_HINTS["results"]
    assert ytq.hint("results", ytq.TIGHT) == ytq.HINTS["results"]


def test_the_confirmation_chooses_its_list_by_what_fits():
    """The pair a clipped list loses is the last one, and the last one is the
    way out — so this is decided by room and not by the layout's threshold."""
    for width in WIDTHS:
        for now in (True, False):
            assert len(ytq.confirm_hints(now, width)) <= width - 2


def test_the_spot_is_offered_only_while_this_is_not_a_paid_download():
    """What starts on enter is the file just written, under the name it was
    written with; renaming it underneath that is a download of a name nothing
    has."""
    for width in WIDTHS:
        assert " p " not in ytq.confirm_hints(True, width)
    assert any("p spot" in ytq.confirm_hints(False, width)
               or "p spot it" in ytq.confirm_hints(False, width)
               for width in WIDTHS)


# --------------------------------------------------------------------------- #
# The rows
# --------------------------------------------------------------------------- #


@given(
    width=st.integers(min_value=32, max_value=120),
    size=st.integers(min_value=1, max_value=20 * 1024**3),
    exact=st.booleans(),
    label=st.sampled_from(["1080p mp4", "2160p60 webm", "audio 129k m4a"]),
)
def test_a_format_row_fits_and_keeps_its_size(width, size, exact, label):
    """The size is kept at every width, because on a metered link it is the
    whole question — the format id and the codec detail go first."""
    option = ytq.Choice("merge", "137+140", size, exact, "mp4", label,
                        "avc1 + mp4a 129k, merged")
    line = ytq.format_row(option, width)
    assert len(line) <= width
    assert ytq.human(size).split()[0] in line


def test_a_row_that_will_take_a_week_says_so_even_when_clipped():
    """The nights note is appended before the clip, so what goes is the codec
    detail and not the warning."""
    option = ytq.Choice("merge", "137+140", 8 * 1024**3, True, "mp4",
                        "2160p mp4", "avc1 + mp4a 129k, merged")
    for width in WIDTHS:
        assert "nights" in ytq.format_row(option, width)


@given(
    width=st.integers(min_value=32, max_value=120),
    title=st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
                  min_size=1, max_size=90),
    channel=st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
                    max_size=40),
    queued=st.booleans(),
)
def test_a_result_row_fits_the_terminal(width, title, channel, queued):
    for line in ytq.result_row(a_result(title, channel), width, queued):
        assert len(line) < width


def test_the_length_and_the_age_are_never_the_columns_that_go():
    """A 90-minute video and a 3-minute one are not the same choice."""
    result = a_result(channel="A Channel With A Very Long Name Indeed")
    for width in WIDTHS:
        drawn = " ".join(ytq.result_row(result, width))
        assert ytq.clock(result.duration) in drawn
        assert ytq.age(result.timestamp) in drawn
        assert ytq.views(result.views) in drawn


def test_the_views_sit_to_the_right_of_the_length():
    result = a_result()
    for width in WIDTHS:
        drawn = " ".join(ytq.result_row(result, width))
        assert drawn.index(ytq.views(result.views)) > drawn.index(
            ytq.clock(result.duration)
        )


def test_a_view_count_is_dropped_whole_and_never_clipped():
    """At the floor a long length leaves no room for the count beside the
    narrowest channel, and the clip at the line's end would take its unit
    letter — ``34M`` read as ``34``. Whole or not at all."""
    for duration in (59, 5434, 7200, 60_000, 600_000):
        for count in (7, 1_234, 34_567_890, 15_000_000_000):
            result = a_result(duration=duration, views=count)
            shown = ytq.views(count)
            for width in range(30, ytq.WIDE):
                line = ytq.result_row(result, width)[1]
                tail = line.rsplit(" · ", 1)[-1]
                assert tail in (shown, ytq.clock(duration)), (width, line)


def test_a_row_with_no_count_says_nothing_about_it():
    """Narrow, the tail is a sentence and loses its last clause; wide, it is a
    column and keeps its width, so the rows above and below still line up."""
    counted, bare = a_result(), a_result(views=None)
    narrow = ytq.result_row(bare, 40)[1]
    assert narrow.endswith(ytq.clock(bare.duration))
    assert "?" not in narrow
    assert ytq.title_room(counted, 100) == ytq.title_room(bare, 100)
    assert len(ytq.result_row(counted, 100)[0]) == len(ytq.result_row(bare, 100)[0])


def test_a_phone_gives_the_title_a_line_of_its_own():
    assert len(ytq.result_row(a_result(), ytq.WIDE - 1)) == 2
    assert len(ytq.result_row(a_result(), ytq.WIDE)) == 1


def test_queueing_a_row_does_not_shift_its_title_sideways():
    plain = ytq.result_row(a_result(), 40, False)[0]
    marked = ytq.result_row(a_result(), 40, True)[0]
    assert len(plain) == len(marked)
    assert plain[2:] == marked[2:]


def test_the_bot_check_notice_fits_and_carries_no_ambiguous_glyph():
    """``⚠`` is ambiguous-width and routinely drawn double, which would put
    the clip this line exists to avoid straight back."""
    for width in WIDTHS:
        note = ytq.withheld_note(width)
        assert len(note) <= width - 2
        assert "⚠" not in note
        assert "bot check" in note


def test_a_running_download_reports_itself_inside_the_line():
    for width in WIDTHS:
        assert len(ytq.progress_line("40-crust-of-rust.py", (5, 10), width)) < width


# --------------------------------------------------------------------------- #
# Keeping your place
# --------------------------------------------------------------------------- #


@given(
    cursor=st.integers(min_value=-50, max_value=400),
    top=st.integers(min_value=-50, max_value=400),
    listed=st.integers(min_value=1, max_value=40),
    count=st.integers(min_value=0, max_value=200),
)
def test_a_restored_place_is_always_one_the_screen_draws(cursor, top, listed, count):
    """A place restored from a previous visit arrives with a ``top`` that may
    be nonsense — the list grew under it, or shrank, or the terminal was
    resized. Handing back a cursor the screen does not draw is worse than
    forgetting the place: every key still works and nothing appears to move."""
    got_cursor, got_top = ytq.viewport(cursor, top, listed, count)
    assert got_top >= 0
    if count == 0:
        assert (got_cursor, got_top) == (0, 0)
        return
    assert 0 <= got_cursor <= count - 1
    # On screen: at or after the top of the window, and inside it.
    assert got_top <= got_cursor < got_top + listed
    # And the window itself is held inside the list, so a place restored onto
    # a list that has shrunk does not leave one row alone on an empty screen.
    assert got_top <= max(0, count - listed)


@given(
    listed=st.integers(min_value=1, max_value=20),
    count=st.integers(min_value=1, max_value=60),
)
def test_a_place_already_on_screen_is_left_exactly_where_it_was(listed, count):
    """Otherwise every redraw would scroll the list under the reader."""
    for top in range(0, max(0, count - listed) + 1):
        for cursor in range(top, min(top + listed, count)):
            assert ytq.viewport(cursor, top, listed, count) == (cursor, top)


def test_the_place_survives_a_list_that_grew_and_one_that_shrank():
    assert ytq.viewport(90, 80, 10, 60) == (59, 50)
    assert ytq.viewport(29, 20, 10, 150) == (29, 20)


# --------------------------------------------------------------------------- #
# The one title that moves
# --------------------------------------------------------------------------- #


def test_a_title_that_fits_never_moves():
    """The motion is a property of the title being too long, never of the row
    being selected — which is what makes it safe to call on every row."""
    for tick in range(40):
        assert ytq.marquee("short", 20, tick) == "short"


def test_a_scrolling_title_holds_at_the_start_of_each_lap():
    """The beginning of a title is the part a choice is usually made on."""
    first = ytq.marquee(LONG_TITLE, 20, 0)
    assert all(ytq.marquee(LONG_TITLE, 20, tick) == first
               for tick in range(ytq.MARQUEE_HOLD))
    assert ytq.marquee(LONG_TITLE, 20, ytq.MARQUEE_HOLD + 1) != first


@given(
    text=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126),
                 min_size=1, max_size=120),
    width=st.integers(min_value=1, max_value=60),
    tick=st.integers(min_value=-5, max_value=500),
)
def test_a_scrolling_title_always_fills_its_room_exactly(text, width, tick):
    """No ellipsis: a line that is visibly moving has already said something
    was lost, and a fixed width is what stops it disturbing its neighbours."""
    drawn = ytq.marquee(text, width, tick)
    assert len(drawn) == min(width, len(text))


def test_a_whole_lap_shows_the_whole_title():
    width = 20
    period = len(LONG_TITLE + ytq.MARQUEE_GAP) + ytq.MARQUEE_HOLD
    seen = "".join(ytq.marquee(LONG_TITLE, width, tick) for tick in range(period))
    assert LONG_TITLE[-width:] in seen


def test_drawing_and_waking_agree_about_which_titles_move():
    """Written twice they drift, and both failures are silent: a title that
    moves for no reason, or a wakeup every 300ms for ever on an idle screen."""
    for width in WIDTHS:
        for title in ("short", LONG_TITLE):
            result = a_result(title)
            room = ytq.title_room(result, width)
            assert ytq.scrolls(result, width) == (len(title) > room)
            # And what is drawn is exactly the room that decision was made on.
            assert len(ytq.marquee(title, room, 7)) == min(room, len(title))


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #


@given(
    lines=st.lists(st.text(alphabet=st.characters(min_codepoint=32,
                                                  max_codepoint=126),
                           min_size=1, max_size=200),
                   min_size=1, max_size=8),
    width=st.integers(min_value=20, max_value=100),
    rows=st.integers(min_value=1, max_value=30),
)
def test_a_notice_never_grows_past_its_own_way_out(lines, width, rows):
    """``message`` draws the key that leaves under the body; a body allowed to
    run past the bottom takes that line with it and leaves a full-screen
    notice with no visible way out."""
    body = ytq.message_body(lines, width, rows)
    assert len(body) <= rows
    assert all(len(row) <= width for row in body)


def test_a_notice_says_what_it_had_to_drop():
    """What goes first is the last line, and on these screens the last line is
    the fix."""
    lines = [f"sentence number {index}" for index in range(20)]
    body = ytq.message_body(lines, 40, 5)
    assert len(body) == 5
    assert "more" in body[-1]


def test_a_notice_that_fits_is_left_alone():
    body = ytq.message_body(["one", "two"], 40, 10)
    assert body == ["one", "", "two"]


def test_a_path_is_never_broken_across_two_lines():
    """A path broken at a hyphen is a path retyped wrong, on the screens whose
    whole job is telling somebody what to type."""
    text = "export it to ~/.config/yt-dlp/cookies.txt named by --cookies there"
    for line in ytq.wrapped(text, 24):
        assert not line.endswith("-")
    assert ytq.wrapped("", 20) == [""]


@given(
    text=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126),
                 max_size=200),
    width=st.integers(min_value=8, max_value=80),
)
def test_wrapping_never_loses_a_word(text, width):
    """Whitespace may change; nothing else may. A word longer than the whole
    width is broken rather than dropped, which is the one case where a line
    ends mid-word."""
    lines = ytq.wrapped(text, width)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
    if all(len(word) <= width for word in text.split()):
        assert all(len(line) <= width for line in lines)


@given(
    text=st.text(max_size=80),
    # From two columns up: at one there is no room for both a character and
    # the ellipsis saying the rest went, and no screen here draws into one.
    width=st.integers(min_value=2, max_value=80),
)
def test_clipping_says_that_something_was_lost(text, width):
    clipped = ytq.fit(text, width)
    assert len(clipped) <= width
    if clipped != text:
        assert clipped.endswith("…")


def test_there_is_nothing_to_draw_in_no_room_at_all():
    assert ytq.fit("anything", 0) == ""
    assert ytq.fit("anything", -5) == ""


# --------------------------------------------------------------------------- #
# The place a spot picked on dlq's listing puts a video
# --------------------------------------------------------------------------- #


def test_a_place_is_said_as_a_position_among_what_is_there():
    """*queued* is what the position was picked among, so the total is one
    more than it: this video is not in it yet."""
    queue = ["10-one.py", "20-two.py", "30-three.py"]
    assert ytq.spot_said(0, queue, 60).startswith("1st of 4")
    assert ytq.spot_said(1, queue, 60).startswith("2nd of 4")
    assert "after one" in ytq.spot_said(1, queue, 60)
    assert ytq.spot_said(3, queue, 60).startswith("4th of 4")


@given(
    pos=st.integers(min_value=-10, max_value=30),
    size=st.integers(min_value=0, max_value=12),
    width=st.integers(min_value=8, max_value=60),
)
def test_a_place_always_fits_and_the_neighbour_goes_first(pos, size, width):
    """A name cut in half is a name read as another item; the position is the
    fact this row exists to carry, so what is dropped is the whole neighbour."""
    queue = [f"{index:02d}-item-with-a-long-name.py" for index in range(size)]
    said = ytq.spot_said(pos, queue, width)
    assert len(said) <= width
    if "(after" in said:
        assert said.endswith(")")


def test_a_position_is_said_the_way_a_person_says_it():
    assert [ytq._ordinal(n) for n in (1, 2, 3, 4)] == ["1st", "2nd", "3rd", "4th"]
    assert [ytq._ordinal(n) for n in (11, 12, 13)] == ["11th", "12th", "13th"]
    assert [ytq._ordinal(n) for n in (21, 22, 23)] == ["21st", "22nd", "23rd"]


def test_the_confirmation_s_labels_clear_their_own_column():
    """It was typed as 11, reasoned as "file name is nine columns", and the
    screen rendered ``file namecrust-of-rust``."""
    for label in ytq.CONFIRM_LABELS:
        assert len(label) + 2 < ytq.CONFIRM_GUTTER


def test_a_row_uses_every_column_it_has():
    """The title gets the room that is actually there. A row that comes back
    short is room given away — which on a phone is the difference between
    reading a title and guessing at it. Measured with content longer than any
    of these terminals, so what bounds the line is the terminal."""
    result = a_result(title="x" * 300, channel="y" * 300)
    for width in WIDTHS:
        lines = ytq.result_row(result, width)
        assert [len(line) for line in lines] == [width - 1] * len(lines)


def test_the_room_a_title_gets_is_what_the_row_gives_it():
    """One function decides it, and the row is drawn from that answer — the
    ellipsis included, which is what says the rest was lost."""
    # A short channel, so the one thing clipped on the line is the title.
    result = a_result(title="x" * 300, channel="ch")
    for width in WIDTHS:
        drawn = ytq.result_row(result, width)[0]
        assert drawn.count("x") + drawn.count("…") == ytq.title_room(result, width)
