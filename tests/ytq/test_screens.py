"""The app's YouTube tabs, driven on a pty and read back off a terminal emulator.

These are about *structure* — which tab is up, that the row for a video is
there, that the sheet has its way out and the price on its button — and never
about wording. The fetches cannot reach YouTube: what is driven is the search
field, the cookie refusal, a listing from a saved search, the video sheet from
a saved dump, and the whole road from that to a written item. Where a fetch
has to happen (Watch Later, a deeper look) a stand-in ``yt_dlp`` module goes
first on ``PYTHONPATH`` — ``ytdl_argv`` prefers ``-m yt_dlp`` — and records
what it was asked.

The pty answers blessed's startup queries the way Termux does
(``termux_pty``), and taps and drags are sent the way Termux sends them.
"""

from __future__ import annotations

import json
import time

import pytest

from nibbles import ytq
from conftest import search_info, video_info
from termux_pty import DOWN, ENTER, ESC

pytestmark = pytest.mark.tui

TABS = ("Search", "Feed", "Later", "Queue", "More")


def joined(lines) -> str:
    return "\n".join(lines)


def home_screen(session):
    return session.wait_for(lambda lines: "a search is" in joined(lines))


def fake_ytdlp(tmp_path, answer: dict, cookies: bool = True) -> dict:
    """A cookie jar, a yt-dlp config naming it, and a stand-in yt-dlp that
    answers *answer* and appends every argv it is given to ``asked.jsonl``."""
    home = tmp_path / "home"
    config = home / ".config" / "yt-dlp"
    config.mkdir(parents=True)
    if cookies:
        jar = config / "cookies.txt"
        jar.write_text("# Netscape HTTP Cookie File\n")
        (config / "config").write_text(f"--cookies {jar}\n")
    fake = tmp_path / "fake" / "yt_dlp"
    fake.mkdir(parents=True)
    asked = tmp_path / "asked.jsonl"
    (fake / "__init__.py").write_text("")
    (fake / "__main__.py").write_text(
        "import json, sys\n"
        f"open({str(asked)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"print(json.dumps({answer!r}))\n"
    )
    return {
        "env": {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "PYTHONPATH": str(fake.parent)},
        "asked": asked,
    }


def asks(path) -> list[list[str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def selected_rows(session) -> set[int]:
    """Rows drawn on a filled background: the selection bar."""
    return {
        y for y in range(session.screen.lines - 4)
        for cell in session.screen.buffer[y].values()
        if cell.bg not in ("default", None) and cell.data.strip()
    }


# --------------------------------------------------------------------------- #
# The Search tab
# --------------------------------------------------------------------------- #


def test_search_says_what_it_costs_and_the_feeds_are_tabs(tui):
    """Every cost stands on the screen before anything is spent, and the two
    signed-in lists are tabs rather than words to discover."""
    session = tui()
    home_screen(session)
    assert "MB" in session.text
    for tab in TABS:
        assert tab in session.tab_row
    assert session.lines[-1].split(), "the status bar is the last row"


def test_q_leaves_without_queueing_anything(tui):
    session = tui()
    home_screen(session)
    session.send(b"q")
    assert session.wait_exit() == 0
    assert "nothing queued" in session.raw.decode(errors="replace")
    assert ytq.items() == []


def test_the_feeds_are_refused_before_a_byte_is_spent(tui, tmp_path):
    """A feed request with no session behind it does not fail — it comes back
    empty, so the page is bought and buys no explanation with it. The cookie
    is asked about first, on the tab, and yt-dlp is never run."""
    stand_in = fake_ytdlp(tmp_path, search_info(["x"]), cookies=False)
    session = tui(**stand_in["env"])
    home_screen(session)
    session.tap_on("Feed")
    session.wait_for(lambda lines: "cookie" in joined(lines).lower())
    assert "subscriptions" in session.header
    session.tap_on("Later")
    session.wait_for(lambda lines: "watch later" in lines[0]
                     and "cookie" in joined(lines).lower())
    assert asks(stand_in["asked"]) == []


def test_watch_later_is_a_word_in_the_field_and_a_tab(tui, tmp_path):
    """``wl`` typed and ⏎ lands on the Later tab, which reads the playlist."""
    stand_in = fake_ytdlp(tmp_path, search_info(["Saved For Tonight", "Also Saved"]))
    session = tui(**stand_in["env"])
    home_screen(session)
    session.send(b"wl")
    session.send(ENTER)
    session.wait_for(lambda lines: "Saved For Tonight" in joined(lines))
    assert "watch later" in session.header
    assert "Also Saved" in session.text
    assert ytq.WL_URL in asks(stand_in["asked"])[0]


def test_a_saved_search_opens_on_its_results(tui, make_dump):
    dump = make_dump(search_info(["Lifetime Annotations", "Subtyping and Variance"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Lifetime Annotations" in joined(lines))
    assert "Subtyping and Variance" in session.text
    assert "2 results" in session.text


def test_the_selection_moves_down_the_list(tui, make_dump):
    dump = make_dump(search_info(["First One", "Second One", "Third One"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Third One" in joined(lines))
    session.send(DOWN)
    first = selected_rows(session)
    assert first
    session.send(DOWN)
    assert selected_rows(session) != first


def test_esc_on_the_results_goes_back_to_the_recent_list(tui, make_dump):
    dump = make_dump(search_info(["Only One"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Only One" in joined(lines))
    session.send(ESC)
    session.wait_for(lambda lines: "Recent" in joined(lines))


def test_an_idle_screen_writes_nothing(tui, make_dump):
    """The property the loop was written for: an idle screen blocks on the
    keyboard rather than redrawing on a timer — with a row selected, too."""
    dump = make_dump(search_info(["Short One", "Short Two"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Short One" in joined(lines))
    session.settle(1.0)
    assert session.pump(2.0) == 0
    session.send(DOWN)
    session.settle(1.0)
    assert session.pump(2.0) == 0


def test_a_selected_title_too_long_for_its_row_is_the_thing_that_moves(tui, make_dump):
    dump = make_dump(search_info([
        "Crust of Rust: Subtyping and Variance and Everything Else Besides"
    ]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Crust of Rust" in joined(lines))
    session.settle(1.0)
    # Not selected: it does not move.
    assert session.pump(2.0) == 0
    session.send(DOWN)
    # Selected and too long: it does, and only because of that.
    assert session.pump(2.0) > 0


def test_a_drag_on_the_list_never_opens_anything(tui, make_dump):
    """A drag is wheel events, stamped with the cell it began on: whatever the
    list does, no row is pressed."""
    dump = make_dump(search_info([f"Video number {n}" for n in range(30)]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda lines: "Video number 0" in joined(lines))
    x, y = session.find("Video number 1")
    session.drag(8, x, y)
    assert "esc ×" not in session.text
    assert "Video number 0" not in session.text  # the view moved
    session.drag(-8, x, y)
    assert "esc ×" not in session.text


# --------------------------------------------------------------------------- #
# The video sheet
# --------------------------------------------------------------------------- #


def sheet_up(session):
    """The sheet, drawn and settled: for 100 ms after a sheet appears every
    tap is ignored (the double-tap guard), so nothing here taps sooner than a
    person could."""
    session.wait_for(lambda lines: "Queue for" in joined(lines))
    session.settle()
    return session.lines


def test_a_saved_video_opens_its_sheet_with_the_price_on_the_button(tui, make_dump):
    session = tui("--from-json", str(make_dump(video_info())))
    sheet_up(session)
    assert "esc ×" in session.text
    button = next(line for line in session.lines if "Queue for" in line)
    figure = next(line for line in session.lines if " · " in line and "MiB" in line
                  and "Queue for" not in line)
    size = figure.split("·")[0].strip(" │")
    assert size and size in button


def test_now_turns_the_button_into_the_one_yes_and_at_puts_it_back(tui, make_dump):
    session = tui("--from-json", str(make_dump(video_info())))
    sheet_up(session)
    session.tap_on("Now")
    session.wait_for(lambda lines: "Start now" in joined(lines))
    assert "Queue for" not in session.text
    session.tap_on("At ")
    sheet_up(session)
    assert ytq.items() == []


def test_the_whole_road_from_a_dump_to_a_queued_item(tui, make_dump, clean_queue):
    """One tap on the button writes the item under the video's own name, and
    the receipt names the file — printed after the app gives the terminal
    back, not on the screen."""
    info = video_info(title="Crust of Rust: Lifetimes")
    session = tui("--from-json", str(make_dump(info)), cols=80)
    sheet_up(session)
    session.tap_on("Queue for")
    end = time.monotonic() + 8
    while time.monotonic() < end and not list(ytq.QUEUE.glob("*.py")):
        session.pump(0.2)
    written = list(ytq.QUEUE.glob("*.py"))
    assert len(written) == 1
    assert written[0].name == ytq.item_name(10, "Crust of Rust - Lifetimes")
    assert ytq.source_of(written[0].read_text()) == ytq.source_key(info)
    # Off Termux the runner objects to the item's shebang, which is a notice
    # with its own way out; on the phone there is nothing to dismiss.
    session.settle()
    if "esc ×" in session.text:
        session.send(ESC)
    session.send(b"q")
    session.wait_exit()
    printed = session.raw.decode(errors="replace")
    assert "queued" in printed and written[0].name in printed


def test_the_same_video_twice_says_so_directly_above_its_answer(tui, make_dump, queued):
    """The notice and the button that answers it are pinned together."""
    info = video_info(title="Crust of Rust Lifetimes")
    queued("10-crust-of-rust-lifetimes.py", source=ytq.source_key(info))
    session = tui("--from-json", str(make_dump(info)))
    session.wait_for(lambda lines: "again" in joined(lines))
    lines = session.lines
    notice = next(i for i, line in enumerate(lines) if "already" in line)
    answer = next(i for i, line in enumerate(lines) if "again" in line)
    assert answer == notice + 2  # the line, then the button's top border
    session.send(ESC)
    session.settle()
    assert len(ytq.items()) == 1


def test_closing_the_sheet_writes_nothing(tui, make_dump, clean_queue):
    session = tui("--from-json", str(make_dump(video_info())))
    sheet_up(session)
    session.tap(1, 0)  # the dimmed header, outside the sheet
    session.settle()
    assert "esc ×" not in session.text
    session.send(b"q")
    assert session.wait_exit() == 0
    assert ytq.items() == []


def test_a_tap_on_the_sheet_outside_every_button_does_nothing(tui, make_dump, clean_queue):
    session = tui("--from-json", str(make_dump(video_info())))
    sheet_up(session)
    before = session.text
    x, y = session.find("esc ×")
    session.tap(2, y + 1)  # the byline: a line of text, not a target
    assert session.text == before
    assert ytq.items() == []


# --------------------------------------------------------------------------- #
# The deeper look, and momentum
# --------------------------------------------------------------------------- #


def test_momentum_never_fetches_and_a_rested_pull_does(tui, tmp_path):
    """A fling is an unbroken stream of wheel events, so it can scroll to the
    end and stop there, but it can never produce the rest and then more that
    a deliberate pull is."""
    answer = search_info([f"Saved {n}" for n in range(ytq.SUBS_RESULTS)])
    stand_in = fake_ytdlp(tmp_path, answer)
    session = tui(**stand_in["env"])
    home_screen(session)
    session.tap_on("Later")
    session.wait_for(lambda lines: "Saved 0" in joined(lines))
    assert len(asks(stand_in["asked"])) == 1
    x, y = session.find("Saved 1")
    # A fling: far past the end, no pause anywhere in it.
    session.drag(3 * ytq.SUBS_RESULTS, x, y, gap=0.01)
    session.settle(0.3)
    assert len(asks(stand_in["asked"])) == 1
    assert f"Saved {ytq.SUBS_RESULTS - 1}" in session.text
    # A rest, then a fresh pull: that is a deliberate ask.
    time.sleep(0.7)
    session.drag(1, x, y)
    session.wait_for(lambda lines: len(asks(stand_in["asked"])) == 2)


def test_the_screens_fit_the_narrowest_terminal(tui, make_dump):
    """32 columns is the floor: every line fits, and the five tabs and the
    status bar are still there."""
    dump = make_dump(search_info(["A Video With Quite A Long Title Indeed"]))
    session = tui("--from-json", str(dump), cols=32)
    session.wait_for(lambda lines: "A Video" in joined(lines))
    assert all(len(line) <= 32 for line in session.lines)
    for tab in TABS:
        assert tab in session.tab_row
    assert session.lines[-1].strip()
