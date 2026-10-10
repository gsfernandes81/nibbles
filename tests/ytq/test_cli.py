"""The paths with no terminal: what ``--list`` prints and what the flags refuse.

``--list`` exists so the screens can be worked on, and the feed read, without
spending anything — so what is pinned here is that it writes nothing, that a
saved dump stands in for whichever request would have fetched it, and that
every combination of flags that cannot mean anything is refused rather than
half-done.
"""

from __future__ import annotations

import pytest

import ytq
from conftest import search_info, video_info


def refuses(argv):
    with pytest.raises(SystemExit) as raised:
        ytq.main(argv)
    assert raised.value.code == 2


def test_flags_that_contradict_each_other_are_refused():
    refuses(["--subs", "crust of rust"])       # the feed is the whole request
    refuses(["--list", "--now", "https://youtu.be/x"])  # --list writes nothing
    refuses(["--list"])                        # nothing to print
    refuses(["--list", "crust of rust"])       # one video's formats needs a URL
    refuses(["--list", "--subs", "--from-json", "dump.json"])
    refuses(["--wl", "crust of rust"])         # so is watch later
    refuses(["--list", "--wl", "--from-json", "dump.json"])
    refuses(["--subs", "--wl"])                # one list at a time


def test_a_saved_dump_prints_the_same_table_and_writes_nothing(
    capsys, make_dump, clean_queue
):
    dump = make_dump(video_info())
    assert ytq.main(["--list", "--from-json", str(dump)]) == 0
    printed = capsys.readouterr().out
    options, _ = ytq.choices(video_info())
    for option in options:
        assert ytq.human(option.size).split()[0] in printed
    # The hidden count explains a short list; there is one mhtml row in there.
    assert ytq.items() == []


def test_a_saved_search_prints_its_rows_rather_than_formats(capsys, make_dump):
    dump = make_dump(search_info(["First Video", "Second Video"]))
    assert ytq.main(["--list", "--from-json", str(dump)]) == 0
    printed = capsys.readouterr().out
    assert "First Video" in printed and "Second Video" in printed


def test_a_dump_that_is_not_there_is_an_error_and_not_a_traceback(capsys):
    assert ytq.main(["--list", "--from-json", "/nowhere/at/all.json"]) == 1
    assert "error" in capsys.readouterr().err


def test_a_dump_that_is_not_a_metadata_object_is_refused(capsys, tmp_path):
    path = tmp_path / "dump.json"
    path.write_text("[1, 2, 3]")
    assert ytq.main(["--list", "--from-json", str(path)]) == 1
    assert "error" in capsys.readouterr().err


def test_the_verdict_on_a_withheld_answer_goes_to_stderr(capsys, make_dump):
    """So a pipe reading the table is not handed a row that is not one, and
    so it survives being redirected away from."""
    from conftest import fmt

    dump = make_dump(video_info(formats=[
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", height=360,
            filesize=38 * 1024 * 1024),
    ]))
    assert ytq.main(["--list", "--from-json", str(dump)]) == 0
    out, err = capsys.readouterr()
    assert "bot check" in err or "one format" in err
    assert "360p" in out


def test_the_feed_refuses_before_spending_when_there_is_no_cookie(capsys):
    """The refusal is the same words the screen uses, one to a line, with the
    verdict first and the working under it."""
    assert ytq.list_feed() == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "cookie" in err.lower()


def test_watch_later_refuses_before_spending_when_there_is_no_cookie(
    capsys, monkeypatch
):
    monkeypatch.setattr(ytq, "ask", lambda *args: pytest.fail("spent data"))
    assert ytq.main(["--list", "--wl"]) == 1
    assert "cookie" in capsys.readouterr().err.lower()


def test_watch_later_prints_its_rows_when_it_can(capsys, monkeypatch):
    monkeypatch.setattr(ytq, "cookie_state", lambda: ("file", "a jar"))
    asked = []
    monkeypatch.setattr(
        ytq, "ask",
        lambda argv, timeout: asked.append(argv) or search_info(["Saved For Later"]),
    )
    assert ytq.main(["--list", "--watch-later"]) == 0
    assert "Saved For Later" in capsys.readouterr().out
    assert ytq.WL_URL in asked[0]


def test_an_empty_watch_later_is_not_called_the_feed(capsys, monkeypatch):
    monkeypatch.setattr(ytq, "cookie_state", lambda: ("file", "a jar"))
    monkeypatch.setattr(ytq, "ask", lambda argv, timeout: {"entries": []})
    assert ytq.list_feed(feed=ytq.WATCH_LATER) == 1
    err = capsys.readouterr().err
    assert "watch later" in err
    assert "feed" not in err


def test_the_picker_needs_a_terminal_and_says_which_flag_does_not(capsys):
    """Captured output is not a tty, which is exactly the case this is for."""
    assert ytq.main(["https://youtu.be/x"]) == 2
    assert "--list" in capsys.readouterr().err


def test_the_flag_and_the_typed_word_are_the_same_road(monkeypatch, capsys):
    """``--subs`` is the flag spelling of the word the entry field already
    takes, handed to the app down that one road rather than as a second way in."""
    seen = {}

    def wrapper(app, first, preloaded, now, dest):
        seen["first"] = first
        return []

    monkeypatch.setattr(ytq.curses, "wrapper", wrapper)
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True, raising=False)
    assert ytq.main(["--subs"]) == 0
    assert ytq.which_feed(seen["first"]) is ytq.SUBS
    assert ytq.main(["--wl"]) == 0
    assert ytq.which_feed(seen["first"]) is ytq.WATCH_LATER


def test_a_session_that_queued_nothing_says_so(monkeypatch, capsys):
    monkeypatch.setattr(ytq.curses, "wrapper", lambda *args: [])
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True, raising=False)
    assert ytq.main([]) == 0
    assert "nothing queued" in capsys.readouterr().out


def test_the_receipts_are_printed_after_the_screen_is_gone(monkeypatch, capsys):
    """A list, because a session can queue several items rather than ending
    at the first one."""
    monkeypatch.setattr(ytq.curses, "wrapper", lambda *args: ["queued one",
                                                             "queued two"])
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True, raising=False)
    assert ytq.main([]) == 0
    assert capsys.readouterr().out.splitlines() == ["queued one", "queued two"]


def test_a_dest_given_once_is_a_directory_and_not_a_kind(monkeypatch):
    seen = {}

    monkeypatch.setattr(ytq.curses, "wrapper",
                        lambda app, first, preloaded, now, dest:
                        seen.update(dest=dest, now=now) or [])
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True, raising=False)
    ytq.main(["--now", "--dest", "~/movies", "https://youtu.be/x"])
    assert seen["now"] is True
    assert seen["dest"].endswith("movies") and not seen["dest"].startswith("~")
