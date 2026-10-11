"""The Queue and More tabs, driven on a real terminal.

The app *is* its screens: a sheet that will not close, a tap that lands on
nothing, a move that says it happened and renames nothing — none of those
show in a return value. So these open the real ``dlq ui`` on a pty, answer
blessed's startup queries the way Termux does (``termux_pty``), read it back
through a terminal emulator, and tap and press what somebody would.

Everything asserted is *structure*: which tab is up, according to the header;
that a row for a download exists; that the tab bar is on its row; that after a
move the file on disk has a smaller number than its neighbour. Nothing here
knows what any sentence says, because the wording is the part that improves.

They are marked ``tui`` and are most of the suite's wall clock.
"""

from __future__ import annotations

import sys

import pytest

from _pty import env, make_root
from termux_pty import DOWN, ENTER, ESC, Termux

pytestmark = pytest.mark.tui

#: Three downloads, headers only, ten apart. The slugs are distinct at their
#: first letter so a row can be found on a 40-column screen.
ITEMS = {
    "10-alpha.py": "# EXPIRE: v1\n# EXPECT_BYTES: 6023000000\n# PARTIAL: yes\n",
    "20-bravo.py": "# EXPIRE: v1\n# EXPECT_BYTES: 529530000\n# PARTIAL: yes\n",
    "30-charlie.py": "# EXPIRE: v1\n# EXPECT_BYTES: 100000000\n# PARTIAL: yes\n",
}


def order_on_disk(root):
    """The queue as the runner would work it: file names, sorted."""
    return [
        path.name.split("-", 1)[1].removesuffix(".py")
        for path in sorted((root / "queue").glob("*.py"))
    ]


@pytest.fixture
def opened(pty_root):
    """``dlq ui`` on a 40x24 pty, opened on its Queue tab."""
    started = []

    def start(cols=40, rows=24, items=ITEMS, config=None):
        root = make_root(pty_root.root.parent, items)
        if config:
            (root / "config.json").write_text(config, encoding="utf-8")
        app = Termux([sys.executable, "-m", "nibbles", "queue"], cols, rows,
                     env(root, pty_root.home, cols, rows), cwd=str(root))
        started.append(app)
        app.wait_for(lambda lines: "queue" in lines[0] and "alpha" in "\n".join(lines))
        app.settle()
        app.root = root
        return app

    yield start
    for app in started:
        app.close()


def test_dlq_opens_on_the_queue_tab_with_the_tabs_under_it(opened):
    """A bare ``dlq`` lands on Queue, and the other four tabs are a tap away."""
    app = opened()
    assert "queue" in app.header
    for tab in ("Search", "Feed", "Later", "Queue", "More"):
        assert tab in app.tab_row
    # The window card's spend button, and every download on the list.
    assert "Run now" in app.text
    for name in ("alpha", "bravo", "charlie"):
        assert name in app.text
    # The status bar is the last row, a word at its left.
    assert app.lines[-1].split()


def test_the_cut_line_is_drawn_through_the_queued_group(opened):
    """With no portal there is nothing to spend, so the line goes to the top of
    the group and says why — which is the only place that answer can be."""
    app = opened()
    def ruled(line):
        return "── " in line and any(ch.isalpha() for ch in line)

    app.wait_for(lambda lines: any(ruled(line) for line in lines[9:-4]))
    rule = next(i for i, line in enumerate(app.lines) if i > 8 and ruled(line))
    first = next(i for i, line in enumerate(app.lines) if "alpha" in line)
    assert rule < first


def test_a_tap_on_a_row_opens_its_sheet_and_esc_closes_it(opened):
    """One tap opens a row; the sheet names it and has its way out."""
    app = opened()
    app.tap_on("bravo")
    assert "esc ×" in app.text
    assert "Remove" in app.text and "Move" in app.text
    app.send(ESC)
    assert "esc ×" not in app.text
    assert "queue" in app.header


def test_a_tap_on_the_dimmed_screen_closes_the_sheet(opened):
    app = opened()
    app.tap_on("bravo")
    assert "esc ×" in app.text
    app.tap(5, 1)  # the dimmed window card, above the sheet
    assert "esc ×" not in app.text


def test_a_tap_outside_every_button_does_nothing(opened):
    """The header is not a target: tapping it changes nothing on the disk or
    on the screen."""
    app = opened()
    before, files = app.text, order_on_disk(app.root)
    app.tap(app.cols - 2, 0)
    app.settle()
    assert order_on_disk(app.root) == files
    assert "esc ×" not in app.text and "queue" in app.header
    assert app.text.split("\n")[1:-1] == before.split("\n")[1:-1]


def test_moving_a_download_renames_it_and_says_where_it_went(opened):
    """Move on its sheet, ↓, ⏎ — and the file on disk has a smaller number.

    The whole of what a move means is where the item is in the run order, and
    the run order is the file names: a screen that reordered its own list and
    renamed nothing would look exactly like this one and download in the order
    it always did.
    """
    app = opened()
    assert order_on_disk(app.root) == ["alpha", "bravo", "charlie"]
    app.tap_on("alpha")
    app.tap_on("Move")
    assert "moving alpha" in app.header
    app.send(DOWN)
    app.send(ENTER)
    assert "queue" in app.header
    assert order_on_disk(app.root) == ["bravo", "alpha", "charlie"]


def test_put_here_by_tapping_the_buttons(opened):
    """The dock under a held row: ↓ then Put here, by taps alone."""
    app = opened()
    app.tap_on("alpha")
    app.tap_on("Move")
    app.tap_on("↓")
    app.tap_on("Put here")
    assert order_on_disk(app.root) == ["bravo", "alpha", "charlie"]


def test_a_move_that_is_thought_better_of_costs_nothing(opened):
    """Cancel leaves it where it was, and nothing was renamed to find that out."""
    app = opened()
    before = order_on_disk(app.root)
    app.tap_on("alpha")
    app.tap_on("Move")
    app.send(DOWN)
    app.tap_on("Cancel")
    assert "queue" in app.header
    assert order_on_disk(app.root) == before


def test_more_is_a_tab_away_and_a_switch_flips_where_it_stands(opened):
    """``s`` (or the More tab) opens the settings; tapping a switch flips it
    on the page, which stays, and says what changed on the line above the
    tabs. The receipt survives the screen."""
    app = opened(config='{\n  "auto": false\n}\n')
    app.tap_on("More")
    assert "settings" in app.header
    auto = next(line for line in app.lines if " auto " in f" {line} ")
    app.tap_on(auto.strip().split()[1] if auto.strip().split()[0] == "a" else "auto")
    assert "settings" in app.header
    flipped = next(line for line in app.lines if " auto " in f" {line} ")
    assert flipped != auto
    # Said on the line directly above the rule over the tabs.
    assert "auto" in app.lines[-5]
    app.send(b"q")
    assert app.wait_exit() == 0
    assert b"auto" in bytes(app.raw)


def test_a_swipe_moves_the_list_and_never_opens_anything(opened):
    """A drag is wheel events; it never presses a row, however many."""
    items = {f"{n:02d}-item{n:02d}.py": "# EXPIRE: v1\n# EXPECT_BYTES: 1000000\n"
             for n in range(10, 60, 2)}
    app = opened(items={**ITEMS, **items})
    x, y = app.find("alpha")
    app.drag(6, x, y)
    assert "esc ×" not in app.text
    app.drag(-6, x, y)
    assert "esc ×" not in app.text
    assert "queue" in app.header


def test_mouse_reporting_asks_for_clicks_and_nothing_more(opened):
    """Termux sends a drag as wheel events whatever the mode; asking for drag
    or motion reports would only be bytes nobody reads."""
    app = opened()
    sent = bytes(app.raw)
    assert b"\x1b[?1006;1000h" in sent or (b"?1000h" in sent and b"?1006h" in sent)
    assert b"?1002h" not in sent and b"?1003h" not in sent
