"""Writing the item, which is the moment ytq commits somebody's data.

``write_item`` is the one door — the search, a pasted URL, ``--now``,
``--from-json`` and ``dlq`` all end on that line — so the duplicate refusal is
pinned there and not at any of the five places that could otherwise be written
around it. The rest of this file is the contract with dlq: the name, the
number, the header the runner parses, and the place the picker asks for.
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
import sys
import types

import pytest
from hypothesis import given
from hypothesis import strategies as st

import ytq
from conftest import video_info

MiB = 1024 * 1024


def a_choice(kind="merge", size=100 * MiB, exact=True, merge_ext="mp4"):
    return ytq.Choice(
        kind, "137+140", size, exact, "mp4", "1080p mp4",
        "avc1 + mp4a 129k, merged", merge_ext=merge_ext,
    )


def an_item(title="Crust of Rust", key="youtube:abc123", choice=None):
    return ytq.render(
        "https://www.youtube.com/watch?v=abc123",
        ytq.slugify(title),
        choice or a_choice(),
        title,
        "2026-09-02",
        "video",
        key,
    )


# --------------------------------------------------------------------------- #
# The file the runner has to be able to read
# --------------------------------------------------------------------------- #


def test_the_item_the_runner_gets_is_the_item_ytq_meant_to_write():
    choice = a_choice(size=487 * MiB, exact=False)
    source = an_item(choice=choice)
    compile(source, "<item>", "exec")
    assert source.startswith(ytq.SHEBANG)
    assert f"# EXPECT_BYTES: {choice.expect_bytes}" in source
    assert "# SOURCE: youtube:abc123" in source
    assert ytq.source_of(source) == "youtube:abc123"


def test_a_json_spelling_of_nothing_never_reaches_the_item():
    """``null`` parses as a *name*, so the item compiles and dies with a
    NameError on the night it was finally due to run."""
    single = an_item(choice=a_choice(kind="single", merge_ext=None))
    assert "merge_ext=None" in single
    # Every one of these is valid Python as a *name*, so an item holding one
    # compiles and every check that stops at "does this file parse" passes it.
    assert not re.search(r"\b(null|true|false)\b", single)
    assert ytq.literal(None) == "None"
    assert json.loads(ytq.literal('a "quoted" title')) == 'a "quoted" title'


#: What a yt-dlp title is: any text on one line. Line breaks are excluded
#: deliberately and not idly — a title carrying one ends up in the ``DESC``
#: comment and takes the item's syntax with it. Nothing observed produces one,
#: so this pins the domain that exists rather than asserting a behaviour the
#: code does not have.
TITLES = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")), max_size=120
)


@given(title=TITLES)
def test_any_title_at_all_still_writes_an_item_that_parses(title):
    """A title can hold quotes, backslashes and triple quotes; an item that
    does not compile is a night lost with no sign anything went wrong."""
    source = an_item(title=title)
    compile(source, "<item>", "exec")
    assert ytq.source_of(source) == "youtube:abc123"


def test_a_title_full_of_quotes_cannot_write_a_broken_item():
    source = an_item(title='he said """hello""" \\ and "goodbye"')
    compile(source, "<item>", "exec")


def test_the_source_header_is_read_from_the_header_and_nowhere_else():
    """Everything below the first non-comment line is the item's docstring and
    its code, and a URL quoted in either is not a claim about what it is."""
    assert ytq.source_of(
        f'{ytq.SHEBANG}\n# EXPIRE: v1\n# SOURCE: youtube:real\n'
        '"""\n# SOURCE: youtube:fake\n"""\n'
    ) == "youtube:real"
    assert ytq.source_of("import sys\n# SOURCE: youtube:late\n") == ""


def test_a_download_is_keyed_by_what_it_is_and_not_by_its_url():
    """``youtu.be/x``, ``watch?v=x`` and ``watch?v=x&list=…`` are one video."""
    assert ytq.source_key({"id": "x", "ie_key": "Youtube"}) == "youtube:x"
    assert ytq.source_key({"id": "x", "extractor": "YouTube"}) == "youtube:x"
    assert ytq.source_key({"title": "no id"}) == ""


def test_the_runner_admits_what_ytq_writes(queued, tmp_path):
    """dlq's own parser, asked rather than second-guessed. Off Termux the one
    objection it may have is the shebang, whose interpreter is not on disk
    here — anything else is this side getting the header wrong."""
    path = ytq.write_item(30, "crust-of-rust", an_item())
    problem = ytq.validate(path)
    if ytq.Path(ytq.SHEBANG[2:]).exists():
        assert problem is None
    else:
        assert problem is not None and "shebang" in problem


def test_the_declared_cap_is_the_one_the_runner_reads(queued, tmp_path):
    choice = a_choice(size=333 * MiB, exact=False)
    written = ytq.write_item(30, "talk", an_item(choice=choice)).read_text()
    # Read back through dlq's parser from a copy that is not executable, so
    # the shebang objection off Termux is the other test's business and not
    # this one's.
    plain = tmp_path / "30-talk.py"
    plain.write_text(written)
    sys.path.insert(0, str(ytq.HERE))
    import expire_runner

    parsed = expire_runner.parse_item(plain)
    assert parsed["cap"] == choice.expect_bytes
    assert parsed["partial"] is True
    assert parsed["slice_min"] == ytq.SLICE_MIN_BYTES
    assert parsed["dest"] == "video"


# --------------------------------------------------------------------------- #
# The name and the number
# --------------------------------------------------------------------------- #


@given(
    number=st.integers(min_value=0, max_value=99),
    slug=st.from_regex(r"[a-z0-9][a-z0-9-]{0,30}", fullmatch=True),
)
def test_a_name_reads_back_as_the_slug_it_was_made_from(number, slug):
    name = ytq.item_name(number, slug)
    assert ytq.item_slug(name) == slug
    assert ytq.ITEM_RE.match(name)


@given(number=st.integers(min_value=0, max_value=99))
def test_the_order_is_always_two_digits(number):
    """The runner sorts *file names*: ``100`` sorts before ``20``, so a third
    digit puts an item at the front of the queue rather than the back."""
    name = ytq.item_name(number, "talk")
    assert len(name.split("-")[0]) == 2


def test_the_number_leaves_room_to_insert_ahead(queued):
    assert ytq.next_number() == 10
    queued("10-talk.py")
    assert ytq.next_number() == 20


def test_the_number_never_grows_a_third_digit(queued):
    queued(f"{ytq.MAX_PRIORITY}-talk.py")
    assert ytq.next_number() == ytq.MAX_PRIORITY


def test_a_day_directory_is_not_an_item(queued):
    """``done/2026-08-08/`` matches an item's number-and-dash exactly as well
    as an item does, and counting one takes the next number to 2036."""
    day = ytq.DONE / "2026-08-08"
    day.mkdir(parents=True)
    (day / "10-talk.py").write_text("# EXPIRE: v1\n")
    assert ytq.next_number() == 20
    assert [where for where, _ in ytq.items()] == ["done"]


def test_a_slug_is_safe_to_be_a_file_name():
    assert ytq.slugify("Crust of Rust: Lifetimes!") == "crust-of-rust-lifetimes"
    assert ytq.slugify("") == "video"
    assert ytq.slugify("///") == "video"
    assert len(ytq.slugify("x" * 200)) <= 42


# --------------------------------------------------------------------------- #
# The one door
# --------------------------------------------------------------------------- #


def test_the_same_video_is_refused_however_it_was_queued(queued):
    ytq.write_item(10, "crust-of-rust", an_item())
    with pytest.raises(ytq.Duplicate) as raised:
        # A different title and a different number: the id is what matches.
        ytq.write_item(20, "a-completely-different-name", an_item(title="Other"))
    assert raised.value.how == "source"


def test_meaning_it_writes_it_anyway(queued):
    ytq.write_item(10, "crust-of-rust", an_item())
    second = ytq.write_item(20, "crust-of-rust-again", an_item(), again=True)
    assert second.is_file()
    assert len(ytq.items()) == 2


def test_an_item_with_no_id_is_matched_on_its_name_and_said_to_be(queued):
    """Items queued before SOURCE existed have no id: the same title is
    usually the same video and occasionally is not."""
    queued("10-crust-of-rust.py")
    found = ytq.find_duplicate("", "Crust of Rust")
    assert found is not None and found.how == "name"
    assert "name" in found.says()


def test_the_id_is_stronger_evidence_than_the_name(queued):
    queued("10-crust-of-rust.py", source="youtube:abc123")
    found = ytq.find_duplicate("youtube:abc123", "something else entirely")
    assert found.how == "source"


def test_a_download_already_made_is_told_apart_from_one_still_waiting(queued):
    queued("10-talk.py", source="youtube:one", where="queued")
    queued("11-talk.py", source="youtube:two", where="done")
    queued("12-talk.py", source="youtube:three", where="failed")
    assert ytq.find_duplicate("youtube:one", "")\
        .where == "queued"
    assert ytq.find_duplicate("youtube:two", "").where == "done"
    assert ytq.find_duplicate("youtube:three", "").where == "failed"


def test_a_new_video_is_not_a_duplicate_of_anything(queued):
    queued("10-talk.py", source="youtube:one")
    assert ytq.find_duplicate("youtube:other", "another talk") is None


def test_the_verdict_fits_the_narrowest_screen(queued):
    day = ytq.DONE / "2026-08-11"
    day.mkdir(parents=True)
    (day / "10-samsung-galaxy-z-flip8-review.py").write_text("# SOURCE: youtube:z\n")
    for how in ("source", "name"):
        for where in ("queued", "done", "failed"):
            said = ytq.Duplicate(day / "10-x.py", where, how).says()
            assert 0 < len(said) <= ytq.TIGHT_WIDTH


def test_the_list_marks_what_the_queue_already_holds(queued):
    """Noticed here it has cost nothing; noticed after the probe it has cost
    an extraction, which on this connection is the whole point."""
    queued("10-talk.py", source="youtube:vid01")
    hits = ytq.entries({"entries": [
        {"id": "vid00", "ie_key": "Youtube", "title": "one"},
        {"id": "vid01", "ie_key": "Youtube", "title": "two"},
    ]})
    assert ytq.already_queued(hits) == {1}


# --------------------------------------------------------------------------- #
# The spot picked on dlq's listing
# --------------------------------------------------------------------------- #


def stub_expire_ui(monkeypatch, place):
    """dlq's side of the picker, replaced by a note-taking stand-in."""
    module = types.ModuleType("expire_ui")
    module.place = place
    module.pick_place = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "expire_ui", module)
    return module


def test_the_file_exists_before_dlq_is_asked_to_move_it(queued, monkeypatch):
    """The video is written last and moved afterwards, by dlq and with dlq's
    own rule — there is no file to move until write_item has returned."""
    seen = {}

    def place(name, pos):
        seen["name"], seen["pos"] = name, pos
        seen["on disk"] = (ytq.QUEUE / name).is_file()
        return f"{ytq.item_slug(name)} is 2nd of 4", True

    stub_expire_ui(monkeypatch, place)
    path = ytq.write_item(40, "crust-of-rust", an_item())
    said = ytq.take_spot(path.name, 1)
    assert seen["on disk"] is True
    # The one spelling of the name: a picker handed a second f-string is a
    # picker holding a file nobody writes.
    assert seen["name"] == ytq.item_name(40, "crust-of-rust") == path.name
    assert seen["pos"] == 1
    assert "2nd of 4" in said


def test_no_spot_picked_is_nothing_to_say(queued, monkeypatch):
    stub_expire_ui(monkeypatch, lambda name, pos: (_ for _ in ()).throw(
        AssertionError("dlq was asked to move an item nobody placed")
    ))
    assert ytq.take_spot("40-talk.py", None) is None


def test_a_busy_queue_is_a_receipt_line_and_never_a_traceback(
    queued, monkeypatch
):
    """A firing or another download holds the queue; the item is queued either
    way and the listing can still move it tomorrow."""
    stub_expire_ui(monkeypatch, lambda name, pos: ("the queue is busy", False))
    said = ytq.take_spot("40-talk.py", 2)
    assert "busy" in said and "last" in said

    def explode(name, pos):
        raise RuntimeError("the checkout is not there")

    stub_expire_ui(monkeypatch, explode)
    said = ytq.take_spot("40-talk.py", 2)
    assert "40-talk.py" in said


def test_the_picker_leaves_the_place_alone_when_it_cannot_be_opened(
    monkeypatch,
):
    module = types.ModuleType("expire_ui")

    def explode(*args, **kwargs):
        raise RuntimeError("no terminal")

    module.pick_place = explode
    monkeypatch.setitem(sys.modules, "expire_ui", module)
    spot, why = ytq.pick_spot(None, "40-talk.py", 1, 3)
    assert spot == 3 and why


def test_leaving_the_listing_is_not_taking_the_last_place_in_it(monkeypatch):
    module = types.ModuleType("expire_ui")
    module.pick_place = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "expire_ui", module)
    assert ytq.pick_spot(None, "40-talk.py", 1, 2) == (2, "")
    module.pick_place = lambda *args, **kwargs: 5
    assert ytq.pick_spot(None, "40-talk.py", 1, 2) == (5, "")


# --------------------------------------------------------------------------- #
# Handing a download to dlq, and watching it
# --------------------------------------------------------------------------- #


def test_the_download_is_run_by_path_under_the_queue_root():
    """An installed copy in site-packages manages a queue that is not there."""
    argv = ytq.now_argv("40-talk.py")
    assert argv[0] == sys.executable
    assert argv[1] == str(ytq.HERE / "expire_sched.py")
    assert argv[2:] == ["now", "40-talk.py", "--yes"]


def test_a_held_lock_is_reported_as_busy(clean_queue):
    assert ytq.queue_busy() is False
    with (clean_queue / "runner.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert ytq.queue_busy() is True
    assert ytq.queue_busy() is False


def test_progress_is_read_off_the_download_s_own_report(clean_queue):
    work = clean_queue / "work" / "40-talk.py"
    work.mkdir(parents=True)
    report = work / ".status.json"
    assert ytq.now_progress("40-talk.py") is None
    report.write_text("{half written")
    assert ytq.now_progress("40-talk.py") is None
    report.write_text(json.dumps({"part_bytes": 500, "total_bytes": 1000}))
    assert ytq.now_progress("40-talk.py") == (500, 1000)
    report.write_text(json.dumps({"part_bytes": 500}))
    assert ytq.now_progress("40-talk.py") == (500, 0)


def test_a_download_with_no_report_yet_still_says_it_is_going():
    """Drawn on a timer: a screen must not die because it looked early."""
    line = ytq.progress_line("40-talk.py", None, 40)
    assert line and len(line) <= 40
    both = ytq.progress_line("40-talk.py", (500 * MiB, 1000 * MiB), 80)
    assert "500 MiB" in both and "40-talk" in both


# --------------------------------------------------------------------------- #
# What was chosen last time
# --------------------------------------------------------------------------- #


def test_the_format_chosen_is_remembered_beside_the_destinations(clean_queue):
    assert ytq.recalled_format() is None
    ytq.remember_format(a_choice())
    assert ytq.recalled_format() == {"label": "1080p mp4", "kind": "merge"}
    # In the queue's own config, not a second file of preferences.
    assert "ytq_last_format" in json.loads((clean_queue / "config.json").read_text())


def test_a_config_that_will_not_parse_is_never_a_blocker(clean_queue):
    (clean_queue / "config.json").write_text("{not json")
    assert ytq.recalled_format() is None
    ytq.remember_format(a_choice())  # says nothing, breaks nothing


def test_where_a_file_lands_is_asked_of_the_runner():
    """A line printed at queue time that disagrees with where the file turns
    up is worse than no line."""
    assert ytq.landing("video")
    assert ytq.landing("/somewhere/absolute").endswith("absolute")


def test_the_probe_and_the_written_item_agree_about_the_video(queued):
    info = video_info()
    path = ytq.write_item(
        10,
        ytq.slugify(info["title"]),
        ytq.render(info["webpage_url"], ytq.slugify(info["title"]), a_choice(),
                   info["title"], "2026-09-02", "video", ytq.source_key(info)),
    )
    assert ytq.already_queued(ytq.entries({"entries": [
        {"id": info["id"], "ie_key": "Youtube", "title": info["title"]}
    ]})) == {0}
    assert path.name == ytq.item_name(10, ytq.slugify(info["title"]))


# --------------------------------------------------------------------------- #
# A flick scrolls; only a keypress spends
# --------------------------------------------------------------------------- #


def test_a_wheel_event_is_a_signed_step_and_nothing_else():
    """The screens ask for wheels only: a tap must never press a key on a
    screen where some keys spend data."""
    assert ytq.wheel_step(ytq.WHEEL_UP) == -1
    assert ytq.wheel_step(ytq.WHEEL_DOWN) == 1
    assert ytq.wheel_step(0) == 0
    # Any other button — a tap, a drag start — moves nothing.
    assert ytq.wheel_step(ytq.curses.BUTTON1_PRESSED) == 0


def test_a_mouse_report_that_is_not_a_wheel_moves_nothing(monkeypatch):
    monkeypatch.setattr(ytq.curses, "getmouse",
                        lambda: (0, 0, 0, 0, ytq.WHEEL_DOWN))
    assert ytq.read_wheel() == 1

    def no_event():
        raise ytq.curses.error("no mouse event")

    monkeypatch.setattr(ytq.curses, "getmouse", no_event)
    assert ytq.read_wheel() == 0


def test_asking_for_wheels_asks_for_nothing_else(monkeypatch):
    asked = []
    monkeypatch.setattr(ytq.curses, "mousemask", lambda mask: asked.append(mask))
    ytq.enable_touch_scroll()
    assert asked == [ytq.WHEEL_UP | ytq.WHEEL_DOWN]
    # A terminal with no mouse support at all is not a crash.
    monkeypatch.setattr(
        ytq.curses, "mousemask",
        lambda mask: (_ for _ in ()).throw(ytq.curses.error("no mouse")),
    )
    ytq.enable_touch_scroll()


# --------------------------------------------------------------------------- #
# The answers that are for a person
# --------------------------------------------------------------------------- #


def test_the_clipboard_says_what_happened_either_way(monkeypatch):
    """The fix IS the message: a command clipped at the edge of a phone is a
    command retyped wrong, so the absence of the tool gets the install line."""
    monkeypatch.setattr(ytq.shutil, "which", lambda name: None)
    absent = ytq.to_clipboard("https://youtu.be/x")
    assert "termux-api" in absent
    assert len(absent) <= ytq.HINT_WIDTH

    monkeypatch.setattr(ytq.shutil, "which", lambda name: "/usr/bin/clip")
    monkeypatch.setattr(
        ytq.subprocess, "run",
        lambda argv, input, text, capture_output, timeout:
            subprocess.CompletedProcess(argv, 0),
    )
    assert "https://youtu.be/x" in ytq.to_clipboard("https://youtu.be/x")

    monkeypatch.setattr(
        ytq.subprocess, "run",
        lambda argv, input, text, capture_output, timeout:
            subprocess.CompletedProcess(argv, 1),
    )
    assert "failed" in ytq.to_clipboard("https://youtu.be/x")

    def missing(*args, **kwargs):
        raise OSError("gone")

    monkeypatch.setattr(ytq.subprocess, "run", missing)
    assert "failed" in ytq.to_clipboard("https://youtu.be/x")


def test_the_version_is_free_to_ask_for_and_says_nothing_when_absent(
    monkeypatch,
):
    monkeypatch.setattr(ytq.shutil, "which", lambda name: None)
    assert ytq.tool_version("yt-dlp") == ""

    monkeypatch.setattr(ytq.shutil, "which", lambda name: "/usr/bin/yt-dlp")
    monkeypatch.setattr(
        ytq.subprocess, "run",
        lambda argv, capture_output, text, timeout:
            subprocess.CompletedProcess(argv, 0, "2026.9.1\nmore\n", ""),
    )
    assert ytq.tool_version("yt-dlp") == "2026.9.1"

    def explode(*args, **kwargs):
        raise OSError("no such thing")

    monkeypatch.setattr(ytq.subprocess, "run", explode)
    assert ytq.tool_version("yt-dlp") == ""


# --------------------------------------------------------------------------- #
# Open when done: held in memory by the screen that started the download
# --------------------------------------------------------------------------- #


class _Exited:
    """A child that has already exited, however it went."""

    pid = 2**22 + 1  # no such process: stop()'s killpg is a quiet no-op

    def wait(self):
        return 0

    def poll(self):
        return 0


def _state(items):
    (ytq.HERE / "state.json").write_text(json.dumps({"items": items}))


def _settled(monkeypatch, asked=True, stop=False, replaced=False):
    opened = []
    monkeypatch.setattr(ytq, "open_file", lambda path: opened.append(path) or "opened")
    running = ytq.Running()
    child = _Exited()
    running.child, running.name = child, "10-talk.py"
    running.open_when_done = asked
    if stop:
        running.stop()
    if replaced:
        running.child = _Exited()
    running.settle(child, "10-talk.py")
    return running, opened


def test_the_file_a_finished_run_delivered_is_the_largest_one_there(tmp_path):
    small, large = tmp_path / "a.srt", tmp_path / "a.mp4"
    small.write_bytes(b"x")
    large.write_bytes(b"x" * 100)
    assert ytq.delivered_file("10-talk.py") is None  # no state at all
    _state({"10-talk.py": {"delivered": [str(large)]}})
    assert ytq.delivered_file("10-talk.py") is None  # not retired: not done
    _state({"10-talk.py": {"retired": "done",
                           "delivered": [str(small), str(large), str(tmp_path / "gone")]}})
    assert ytq.delivered_file("10-talk.py") == large
    # A record left by an earlier item of the same name, with this one still
    # queued: not this run's delivery.
    ytq.QUEUE.mkdir(parents=True, exist_ok=True)
    (ytq.QUEUE / "10-talk.py").write_text("# EXPIRE: v1\n")
    assert ytq.delivered_file("10-talk.py") is None


def test_a_run_that_delivers_opens_what_it_delivered_when_asked(monkeypatch, tmp_path):
    film = tmp_path / "talk.mp4"
    film.write_bytes(b"x")
    _state({"10-talk.py": {"retired": "done", "delivered": [str(film)]}})
    running, opened = _settled(monkeypatch)
    assert opened == [film] and running.opened and running.settled
    # Not asked, stopped (which is not done), or no longer the run on the
    # screen: nothing is opened.
    for kwargs in ({"asked": False}, {"stop": True}, {"replaced": True}):
        assert _settled(monkeypatch, **kwargs)[1] == []


def test_a_stopped_run_cannot_be_asked_again_on_its_way_down(monkeypatch):
    """``x`` then ``o`` while the child is still unwinding must not re-arm
    the ask: whatever it delivers as it goes, it was told to stop."""

    class Unwinding(_Exited):
        def poll(self):
            return None

    running = ytq.Running()
    running.child, running.name = Unwinding(), "10-talk.py"
    assert running.askable
    on, off = running.toggle_open(), running.toggle_open()
    assert on != off and not running.open_when_done
    running.stop()
    assert running.alive and not running.askable


def test_a_run_that_stops_short_opens_nothing_and_says_so(monkeypatch):
    """The item stays queued; the run that finishes it later is another run,
    and nothing it delivers is opened on this one's ask."""
    _state({"10-talk.py": {"attempts": 0, "part_bytes": 1234}})
    running, opened = _settled(monkeypatch)
    assert opened == [] and running.opened and running.settled


def test_a_new_download_starts_without_the_last_ones_ask(monkeypatch):
    monkeypatch.setattr(ytq, "start_now", lambda name: (_Exited(), None))
    running = ytq.Running()
    running.open_when_done = True
    running.start("20-next.py")
    assert running.open_when_done is False


def test_opening_never_raises(monkeypatch, tmp_path):
    target = tmp_path / "talk.mp4"
    monkeypatch.setattr(ytq.shutil, "which", lambda name: None)
    assert "talk.mp4" in ytq.open_file(target)
    monkeypatch.setattr(ytq.shutil, "which", lambda name: "/bin/false")
    monkeypatch.setattr(
        ytq.subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("no such opener")),
    )
    assert "talk.mp4" in ytq.open_file(target)
