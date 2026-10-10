"""The curses screens, driven under a pty and read back off a terminal emulator.

These are about *structure* — which screen is up, that the row for a video is
there, that the hint line still names a way out — and never about wording:
every sentence on these screens is meant to be rewritten without a test
standing in the way. The screens that spend data cannot be driven at all
(nothing here reaches youtube), so what is exercised is the entry field, the
cookie refusal, a listing from a saved search, the format list and the
confirmation from a saved dump, and the whole road from that to a written item.
"""

from __future__ import annotations

import contextlib
import json
import time

import pytest

import ytq
from conftest import DOWN, ENTER, ESC, search_info, video_info

pytestmark = pytest.mark.tui


def settled(session, seconds: float = 1.0) -> None:
    """Let the app finish drawing before anything is asserted about it."""
    while session.pump(seconds):
        pass


def test_the_field_takes_three_things_and_says_what_each_costs(tui):
    """Written on the screen or it does not exist: ``subs`` is a word typed
    into a field with nothing anywhere to discover it from."""
    session = tui()
    session.wait_for(lambda text: "paste a URL" in text)
    assert "subs" in session.text
    assert "wl" in session.text
    # Every cost stands there before anything is spent.
    assert session.text.count("MB") >= 3


def test_esc_leaves_without_queueing_anything(tui):
    session = tui()
    session.wait_for(lambda text: "paste a URL" in text)
    session.send(ESC)
    assert session.wait_exit() == 0
    assert "nothing queued" in session.raw.decode(errors="replace")
    assert ytq.items() == []


def test_the_feed_is_refused_before_a_byte_is_spent_on_it(tui):
    """A feed request with no session behind it does not fail — it comes back
    empty, so the page is bought and buys no explanation with it."""
    session = tui()
    session.wait_for(lambda text: "paste a URL" in text)
    session.send("subs" + ENTER)
    said = session.wait_for(lambda text: "cookie" in text.lower())
    assert "any key" in said
    # And the way back is a keypress, not a dead end.
    session.send(" ")
    session.wait_for(lambda text: "paste a URL" in text)
    # Watch Later is the same signed-in page, refused by the same question.
    session.send("wl" + ENTER)
    said = session.wait_for(lambda text: "cookie" in text.lower())
    assert "any key" in said
    session.send(" ")
    session.wait_for(lambda text: "paste a URL" in text)


def test_watch_later_is_the_same_listing_by_the_same_road(tui, tmp_path):
    """``wl`` in the field reads the playlist page and lands on the results
    screen under its own banner. The yt-dlp here is a stand-in module put
    first on the path — ``ytdl_argv`` prefers ``-m yt_dlp`` — so a real one
    installed beside the suite is never the one asked."""
    home = tmp_path / "home"
    config = home / ".config" / "yt-dlp"
    config.mkdir(parents=True)
    jar = config / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    (config / "config").write_text(f"--cookies {jar}\n")
    fake = tmp_path / "fake" / "yt_dlp"
    fake.mkdir(parents=True)
    asked = tmp_path / "asked.json"
    answer = search_info(["Saved For Tonight", "Also Saved"])
    (fake / "__init__.py").write_text("")
    (fake / "__main__.py").write_text(
        "import json, sys\n"
        f"open({str(asked)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"print(json.dumps({answer!r}))\n"
    )
    session = tui(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        PYTHONPATH=str(fake.parent),
    )
    session.wait_for(lambda text: "paste a URL" in text)
    session.send("wl" + ENTER)
    session.wait_for(lambda text: "Saved For Tonight" in text)
    assert "watch later" in session.screen.display[0]
    assert "Also Saved" in session.text
    assert ytq.WL_URL in json.loads(asked.read_text())
    # And the way out is still named.
    assert "q" in session.hints


def test_a_saved_search_opens_on_the_listing(tui, make_dump):
    dump = make_dump(search_info(["Lifetime Annotations", "Subtyping and Variance"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "Lifetime Annotations" in text)
    assert "Subtyping and Variance" in session.text
    # Two results, and the header says so.
    assert "2 results" in session.text
    session.row_with("Lifetime Annotations")


def test_the_cursor_moves_down_the_listing(tui, make_dump):
    dump = make_dump(search_info(["First One", "Second One", "Third One"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "Third One" in text)

    def reversed_rows():
        return {
            row for row in range(session.screen.lines)
            for cell in session.screen.buffer[row].values()
            if cell.reverse and cell.data.strip()
        }

    settled(session)
    first = reversed_rows()
    session.send(DOWN)
    settled(session)
    assert reversed_rows() != first


def test_backing_out_of_the_listing_reaches_the_field(tui, make_dump):
    dump = make_dump(search_info(["Only One"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "Only One" in text)
    session.send("q")
    session.wait_for(lambda text: "paste a URL" in text)


def test_a_screen_with_nothing_to_scroll_costs_no_wakeups(tui, make_dump):
    """The property the results loop was written for: an idle screen blocks on
    the keyboard rather than redrawing on a timer."""
    dump = make_dump(search_info(["Short One", "Short Two"]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "Short One" in text)
    settled(session, 1.0)
    assert session.pump(2.0) == 0


def test_a_title_too_long_for_its_room_is_the_thing_that_moves(tui, make_dump):
    dump = make_dump(search_info([
        "Crust of Rust: Subtyping and Variance and Everything Else Besides"
    ]))
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "Crust of Rust" in text)
    settled(session, 1.0)
    # Only because it does not fit: the same screen with short titles above
    # emits nothing at all over the same wait.
    assert session.pump(2.0) > 0


def test_a_saved_video_opens_on_the_format_list(tui, make_dump):
    dump = make_dump(video_info())
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "1080p" in text)
    options, _ = ytq.choices(video_info())
    biggest = ytq.human(options[0].size).split()[0]
    session.row_with(biggest)
    # The keys that spend are named on the screen that spends them.
    assert "n" in session.hints and "q" in session.hints


def test_the_confirmation_says_the_cap_and_goes_back_to_the_list(tui, make_dump):
    dump = make_dump(video_info())
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "1080p" in text)
    session.send(ENTER)
    said = session.wait_for(lambda text: "cap" in text)
    # Free unless it says otherwise, and the two are spelled out rather than
    # colour-coded.
    assert "free" in said.lower()
    session.send("q")
    session.wait_for(lambda text: "format" in text.lower() or "1080p" in text)


def test_now_says_it_is_paid_and_t_puts_it_back(tui, make_dump):
    dump = make_dump(video_info())
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "1080p" in text)
    session.send(ENTER)
    session.wait_for(lambda text: "cap" in text)
    session.send("n")
    session.wait_for(lambda text: "PAID" in text)
    session.send("t")
    session.wait_for(lambda text: "PAID" not in text)


def test_the_whole_road_from_a_dump_to_a_queued_item(tui, make_dump, clean_queue):
    """Enter on the confirmation writes the item, and the receipt names the
    file it wrote — printed after curses is torn down, not on the screen."""
    dump = make_dump(video_info(title="Crust of Rust Lifetimes"))
    session = tui("--from-json", str(dump), cols=80)
    session.wait_for(lambda text: "1080p" in text)
    session.send(ENTER)
    session.wait_for(lambda text: "cap" in text)
    session.send(ENTER)

    end = time.monotonic() + 8
    while time.monotonic() < end and not list(ytq.QUEUE.glob("*.py")):
        session.pump(0.2)
    written = list(ytq.QUEUE.glob("*.py"))
    assert len(written) == 1
    assert written[0].name == ytq.item_name(10, "crust-of-rust-lifetimes")
    assert ytq.source_of(written[0].read_text()) == ytq.source_key(video_info())

    # Off Termux the runner's parser objects to the item's shebang, which is a
    # notice with a key to dismiss; on the phone there is nothing to dismiss.
    with contextlib.suppress(OSError):
        session.send(" ")
    session.wait_exit()
    printed = session.raw.decode(errors="replace")
    assert "queued" in printed and written[0].name in printed


def test_the_same_video_twice_gets_a_screen_of_its_own(tui, make_dump, queued):
    """A warning sharing a screen with nine other facts is a warning that gets
    skimmed past — and this is a moment where data is about to be spent twice."""
    info = video_info(title="Crust of Rust Lifetimes")
    queued("10-crust-of-rust-lifetimes.py", source=ytq.source_key(info))
    session = tui("--from-json", str(make_dump(info)))
    said = session.wait_for(lambda text: "again" in text)
    assert "queue" in said.lower()
    # Any other key backs out, and the override is written on the screen.
    session.send("z")
    session.wait_for(lambda text: "paste a URL" in text)


def test_nothing_is_written_by_backing_out_of_the_confirmation(
    tui, make_dump, clean_queue
):
    dump = make_dump(video_info())
    session = tui("--from-json", str(dump))
    session.wait_for(lambda text: "1080p" in text)
    session.send(ENTER)
    session.wait_for(lambda text: "cap" in text)
    session.send(ESC)
    session.wait_for(lambda text: "1080p" in text)
    session.send("q")
    session.wait_for(lambda text: "paste a URL" in text)
    session.send(ESC)
    assert session.wait_exit() == 0
    assert ytq.items() == []


def test_the_screens_fit_the_narrowest_terminal(tui, make_dump):
    """32 columns is the floor, and what a clipped line loses there is the way
    out of the screen."""
    dump = make_dump(search_info(["A Video With Quite A Long Title Indeed"]))
    session = tui("--from-json", str(dump), cols=32)
    session.wait_for(lambda text: "A Video" in text)
    lines = session.screen.display
    assert all(len(line.rstrip()) <= 32 for line in lines)
    # The hints sit on the second-to-last row; nothing has spilled past them.
    assert session.hints.strip()
    assert not lines[-1].strip()
    assert "q" in session.hints
