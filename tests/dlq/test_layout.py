"""Every line fits the terminal it was laid out for.

Termux in portrait is about 40 columns and the queue's rule is that every line
of every screen fits down to 32. That is not cosmetic: a line wider than the
screen wraps, and the wrapping is what pushes the answer off the top of it.

So this is a *property* rather than a set of expected strings — nothing here
knows what any line says, only that it fits, that it is there, and that what
must never be given up has not been. The three widths are the phone, a small
terminal window and a desktop; between them are swept rather than sampled,
because the failures are at the width where a layout changes shape.

A long checkout path makes some of these fail, and that is the path rather than
a regression: the root is on the wide status screen, spelled with ``~``.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

MiB = 1024**2

#: The phone, a small window, a desktop.
WIDTHS = [32, 40, 80]

#: A long name, a long description and a long destination — the three cells a
#: layout gives up room in, each one longer than any width tested.
LONG = "a-really-quite-long-name-for-a-download-that-somebody-queued"


def plain(pairs):
    return [text for text, _ in pairs]


def fits(line: str, width: int) -> bool:
    """Whether *line* is inside *width*, by the rule the wrapping works to.

    A single word longer than the terminal — which on a phone is most absolute
    paths — is left to overhang rather than broken, deliberately: a terminal
    wrapping a path is visibly a wrapped path, whereas a break inserted into
    one reads as a path with a space in it, and these are the lines somebody is
    about to retype.
    """
    return len(line) <= width or " " not in line.strip()


def paint(text, code):
    """``quota_widget.Paint`` with colour off: what a pipe would get."""
    return text


def stocked(dlq):
    """One of everything: queued, failed, done, rejected, and one downloading."""
    dlq.item(f"10-{LONG}.py", cap=6 * 1024 * MiB, desc=f"{LONG} {LONG}")
    dlq.item("20-small.py", cap=MiB, desc="a short one")
    dlq.item("30-failed.py", where="failed", desc="this one failed")
    dlq.item("40-done.py", where="done/2026-09-01", desc="this one finished")
    (dlq.root / "queue" / "50-broken.py").write_text("# nothing declared here\n")
    work = dlq.root / "work" / f"10-{LONG}.py"
    work.mkdir(parents=True, exist_ok=True)
    (work / "part.bin").write_bytes(b"x" * 4096)
    dlq.state({"30-failed.py": {"attempts": 2}, "20-small.py": {"attempts": 1}})
    return dlq.sched.items()


def facts_for(dlq, **rest):
    return dlq.facts(portal=dlq.reading(free=400 * MiB), force=True, **rest)


# --------------------------------------------------------------------------- #
# The two printed screens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width", WIDTHS)
def test_the_listing_fits(dlq, width):
    rows = stocked(dlq)
    lines = plain(dlq.sched.compose_list(rows, width, paint))
    assert lines
    for line in lines:
        assert fits(line, width), line
    # Every download is on it, under a heading that counts it.
    drawn = "\n".join(lines)
    for row in rows:
        assert dlq.ui._slug_of(row["name"])[:12] in drawn


@pytest.mark.parametrize("width", WIDTHS)
def test_the_status_screen_fits(dlq, width):
    stocked(dlq)
    job = [("job", "armed, fires every 15m", "32")]
    lines = plain(dlq.sched.compose_status(facts_for(dlq), width, paint, job=job))
    for line in lines:
        assert fits(line, width), line


@pytest.mark.parametrize("width", WIDTHS)
def test_the_status_screen_leads_with_the_verdict(dlq, width):
    """The first line is the title bar; the second is what happens next.

    Everything under it is the working — the money, the queue, the machinery —
    and this is the whole answer to the question the screen was opened to ask.
    """
    stocked(dlq)
    facts = facts_for(dlq)
    lines = plain(dlq.sched.compose_status(facts, width, paint))
    headline = dlq.sched.VERDICTS[facts["verdict"]][0]
    assert lines[1].strip() == headline.strip()[: len(lines[1].strip())]


MB = 1_000_000


@pytest.mark.parametrize("width", WIDTHS)
def test_the_money_block_is_the_reserve_that_applies_tonight(dlq, width):
    """Not the reserve as it is *set*, which is not always the same figure.

    With ``reserve-when-paid`` off and paid data behind the grant, nothing is
    being kept back — and a screen still showing the setting would be
    describing a different night from the one the runner is about to work.
    """
    stocked(dlq)
    dlq.sched.set_setting("reserve", "250")
    kept = plain(
        dlq.sched.compose_status(
            dlq.facts(portal=dlq.reading(free=400 * MiB, paid=0), force=True),
            width,
            paint,
        )
    )
    assert any("250" in line for line in kept)

    dlq.config({**dlq.runner.load_config(), "reserve_when_paid": False})
    waived = dlq.facts(
        portal=dlq.reading(free=400 * MiB, paid=500 * MB), force=True
    )
    assert waived["reserve_waived"] is True
    stood_aside = plain(dlq.sched.compose_status(waived, width, paint))
    assert not any("250" in line for line in stood_aside)
    assert any("0 MB" in line for line in stood_aside)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_reserve_that_stood_aside_does_not_read_as_a_reserve_of_nothing(
    dlq, width
):
    """Both are nought tonight, and they are not the same fact.

    "0 MB is always kept back" is a figure and a lie on one line: it is not
    always kept back, it was waived a moment ago because paid data turned up,
    and it comes back the moment that data is spent. The two screens below are
    drawn from the *same* portal reading and differ only in the config, so
    anything that separates them is the screen saying which of the two it is.
    """
    stocked(dlq)
    doc = dlq.reading(free=400 * MiB, paid=500 * MB)

    dlq.sched.set_setting("reserve", "0")
    nothing_kept = dlq.facts(portal=doc, force=True)
    assert nothing_kept["floor_bytes"] == 0
    assert nothing_kept["reserve_waived"] is False

    dlq.sched.set_setting("reserve", "250")
    dlq.config({**dlq.runner.load_config(), "reserve_when_paid": False})
    stood_aside = dlq.facts(portal=doc, force=True)
    assert stood_aside["floor_bytes"] == 0
    assert stood_aside["reserve_waived"] is True

    drawn = [
        "\n".join(plain(dlq.sched.compose_status(facts, width, paint)))
        for facts in (nothing_kept, stood_aside)
    ]
    assert drawn[0] != drawn[1]


@pytest.mark.parametrize("width", WIDTHS)
def test_what_the_screen_says_is_spendable_is_what_the_runner_decided(dlq, width):
    """Spelled from ``facts``, never worked out a second time on the way past.

    Two answers to "what may tonight spend" is the failure the facts/layout
    split exists to prevent, and it is the figure the cut line on the other
    screen is drawn from.
    """
    stocked(dlq)
    facts = facts_for(dlq)
    lines = plain(dlq.sched.compose_status(facts, width, paint))
    assert facts["spendable"] > 0
    said = dlq.runner.human(facts["spendable"])
    assert any(said in line for line in lines), said


@pytest.mark.parametrize("verdict", ["go", "early", "late", "empty", "off", "spent",
                                     "blind", "no-portal", "stale"])
def test_every_verdict_has_words_on_both_screens(dlq, verdict):
    """A verdict the gate grew and a table did not would draw a blank where the
    answer goes."""
    assert verdict in dlq.sched.VERDICTS
    assert verdict in dlq.ui.VERDICT_WORDS
    assert verdict in dlq.qs.STATUS
    assert dlq.sched.VERDICTS[verdict][0].strip()
    assert dlq.ui.VERDICT_WORDS[verdict].strip()
    # The status bar's label is a word, never only a colour.
    assert dlq.qs.STATUS[verdict][0].strip()
    assert "tonight" not in dlq.ui.VERDICT_WORDS[verdict]
    # Short enough for the narrowest phone unwrapped: this line is the answer.
    assert len(dlq.sched.VERDICTS[verdict][0]) <= 32
    assert set(dlq.sched.VERDICTS) - {"downloading"} == set(dlq.runner.GATE_STATES)


# --------------------------------------------------------------------------- #
# The app's Queue and More tabs
# --------------------------------------------------------------------------- #


def app_at(dlq, width, height=24, tab=3, facts=None):
    """The real app, headless, on *tab*, with *facts* as its reading."""
    app = dlq.app.App(None, tab, size=(width, height))
    app.queue.facts = facts
    return app


def lines_of(block):
    return block.plain().split("\n")


@pytest.mark.parametrize("width", WIDTHS)
def test_the_queue_rows_are_exactly_the_screen_wide(dlq, width):
    """Every row is drawn the width it is given, whatever it holds."""
    rows = stocked(dlq)
    facts = facts_for(dlq)
    for entry in dlq.qs.queue_entries(rows, facts, "03:00"):
        for selected in (False, True):
            block = entry.draw(width, selected)
            assert block.width == width
            assert block.height == entry.height


@pytest.mark.parametrize("width", WIDTHS)
def test_the_window_card_fits(dlq, width):
    """The card's lines (the verdict, the bar, the figures) fit at every
    width, before a reading, on an ordinary night and on a blind one."""
    stocked(dlq)
    for facts in (None, facts_for(dlq), facts_for(dlq, blind=True)):
        app = app_at(dlq, width, facts=facts)
        tab = app.tabs[3]
        for piece in (tab.card(app, width, True), tab.strip(app, width, True),
                      tab.card(app, width, False)):
            assert piece.width == width


@pytest.mark.parametrize("width", WIDTHS)
def test_a_download_in_flight_outranks_every_verdict(dlq, width):
    """What is being spent now is the answer to "what is happening"; the
    window it is being spent inside is not. The status bar says it."""
    stocked(dlq)
    for verdict in dlq.runner.GATE_STATES:
        app = app_at(dlq, width, facts=dict(facts_for(dlq), verdict=verdict))
        app.queue.live = "20-small.py"
        label, _, detail, _ = app.queue.status(width)
        assert label.startswith("↓"), verdict
        assert "small" in detail


@pytest.mark.parametrize("width", WIDTHS)
def test_one_item_and_its_actions_fit(dlq, width):
    """Every action ``actions_for`` offers is a button on the item's sheet,
    at every width and both heights: the grid never drops one."""
    rows = stocked(dlq)
    for height in (24, 14, 11):
        app = app_at(dlq, width, height, facts=facts_for(dlq))
        for row in rows:
            app.sheets[:] = [dlq.qs.ItemSheet(row)]
            app.compose()
            offered = {key for key, _ in dlq.ui.actions_for(row)}
            shown = {hit.data for hit in app.hits.hits if hit.id.startswith("act:")}
            assert shown == offered, (row["name"], height)


@pytest.mark.parametrize("width", WIDTHS)
def test_every_setting_has_a_row_at_every_height(dlq, width):
    """A row nobody knows is there is a setting nobody knows is there. The
    More tab scrolls rather than giving any row up; ``paid-min`` is there only
    while the waiver is on, which is the one row that comes and goes."""
    for waived in (False, True):
        dlq.config({"reserve_when_paid": not waived})
        for height in range(11, 31):
            app = app_at(dlq, width, height, tab=4)
            app.compose()
            names = [entry.key[1] for entry in app.tabs[4].view.entries
                     if entry.key[0] == "setting"]
            values = dlq.runner.settings()
            assert names == dlq.qs.shown_settings(values), height
            assert ("paid-min" in names) == waived
            hidden = set(dlq.runner.SETTINGS) - set(names)
            # Only the rows that come and go are ever missing.
            assert hidden <= {"paid-min", "allowance", "reset"}, hidden


@pytest.mark.parametrize("width", WIDTHS)
def test_every_sheet_keeps_its_way_out(dlq, width):
    """Every sheet has ``esc ×`` on its title row, and its pinned answers
    stay on the screen however short it gets."""
    rows = stocked(dlq)
    for height in (24, 14, 11):
        app = app_at(dlq, width, height, facts=facts_for(dlq))
        for sheet in (dlq.qs.ItemSheet(rows[0]), dlq.qs.DestSheet(),
                      dlq.qs.SettingSheet("window"),
                      dlq.qs.remove_sheet(app, rows[0], dlq.qs.ItemSheet(rows[0]))):
            app.sheets[:] = [sheet]
            app.compose()
            assert app.hits.find("close") is not None, (type(sheet), height)
            for hit in app.hits.hits:
                assert hit.y + hit.h <= height


# --------------------------------------------------------------------------- #
# Swept rather than sampled
# --------------------------------------------------------------------------- #


@given(width=st.integers(32, 120))
def test_nothing_is_laid_out_wider_than_the_terminal_at_any_width(dlq, width):
    """Between the three shapes are the widths where a layout changes shape.

    From 32 up, because that is the rule: below it even the title bar and the
    clock beside it do not fit together, and nothing can help a line that is
    one word wider than the terminal.
    """
    rows = stocked(dlq)
    facts = facts_for(dlq)
    for line in plain(dlq.sched.compose_list(rows, width, paint)):
        assert fits(line, width)
    for line in plain(dlq.sched.compose_status(facts, width, paint)):
        assert fits(line, width)


@given(
    text=st.text(min_size=0, max_size=200),
    width=st.integers(1, 100),
)
def test_wrapping_always_gives_back_at_least_one_line(dlq, text, width):
    """The lines this draws are reasons and paths, and a reason with its tail
    cut off is usually the half that said what to do about it."""
    lines = dlq.sched._wrap(text, width)
    assert lines
    # Long words are left whole on purpose: a break inserted into a path reads
    # as a path with a space in it, and these are lines someone retypes.
    for line in lines:
        assert len(line) <= max(8, width) or " " not in line.strip()


def test_a_bar_is_drawn_in_characters_a_phone_draws_one_column_wide(dlq):
    """bewitch's ``█`` against ``░``: both one column on the phone (checked
    2026-10-10, design §10), and the bar is exactly the width it is given."""
    from nibbles import widgets
    from bewitch.lipgloss._cells import char_width

    for width in range(12, 60):
        for fraction in (0, 0.18, 0.5, 1):
            for bar in (widgets.bar(fraction, width), widgets.progress_bar(fraction, width)):
                assert bar.width == width
                assert all(char_width(ch) == 1 for ch in bar.plain() if ch.strip())


def test_a_download_with_no_stated_total_never_draws_a_full_bar(dlq):
    """No total means no fraction: a full-looking bar over an unknown size is
    the one reading worse than none."""
    dlq.item("10-x.py", cap=100 * MiB)
    app = app_at(dlq, 40)
    app.queue.live = "10-x.py"
    app.sheets[:] = [dlq.qs.DownloadSheet("10-x.py")]
    drawn = app.compose().plain()
    assert "█" not in drawn


def test_a_size_nobody_has_stated_is_marked_as_the_bound_it_is(dlq):
    """Until a server states one the only figure is the declared cap, which is
    deliberately larger than the file: printed as a size it makes a finished
    download look 70% done. The same on the Queue tab's rows."""
    assert "≤" in dlq.qs.amount({"have": 1, "stated": 0, "cap": 100})
    assert "≤" not in dlq.qs.amount({"have": 1, "stated": 100, "cap": 200})
    assert "≤" in dlq.sched._of(1, 0, 100)
    assert "≤" not in dlq.sched._of(1, 100, 200)
    assert dlq.sched._of(1, 100, 200, compact=True).count("/") == 1
