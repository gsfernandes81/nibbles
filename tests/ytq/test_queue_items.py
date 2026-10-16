"""Writing the item, which is the moment ytq commits somebody's data.

``write_item`` is the one door — the search, a pasted URL, ``--now``,
``--from-json`` and ``dlq`` all end on that line — so the duplicate refusal is
pinned there and not at any of the five places that could otherwise be written
around it. The rest of this file is the contract with dlq: the name, the
number, the header the runner parses, and the place the picker asks for.
"""

from __future__ import annotations

import ast
import errno
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nibbles import ytq
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


#: What a title is: any text at all. TikTok's is its caption, line breaks
#: kept, and a page's ``og:title`` decodes ``&#10;`` and ``&#27;`` — so the
#: line breaks, the controls and the separators are drawn on purpose, beside
#: the quotes and backslashes that end a docstring.
TITLES = st.text(
    alphabet=st.one_of(
        st.characters(blacklist_categories=("Cs",)),
        st.sampled_from('\n\r\x00\x0b\x0c\x1b\x85\u2028\u2029"\\#'),
    ),
    max_size=120,
)


@given(title=TITLES)
def test_any_title_at_all_still_writes_an_item_that_parses(title):
    """A title can hold quotes, backslashes and triple quotes; an item that
    does not compile is a night lost with no sign anything went wrong."""
    source = an_item(title=title)
    compile(source, "<item>", "exec")
    assert ytq.source_of(source) == "youtube:abc123"


def statements(source):
    """What an item runs, by kind: its docstring, then the five lines of code
    that hand it to ``ytdl_item``."""
    return [type(node).__name__ for node in ast.parse(source).body]


@given(title=TITLES, ident=TITLES.filter(str.strip), url=TITLES)
def test_no_title_ever_reaches_the_item_as_code(title, ident, url):
    """A line break in the title ended the ``# DESC:`` comment, and whatever
    followed it was Python: an item that never compiled, or one whose second
    line ran at the firing. Whatever the title, the id and the link, the item
    is its docstring and its own five lines, and its header reads back the
    key it was written with."""
    key = ytq.source_key({"id": ident, "ie_key": "Generic"})
    source = ytq.render(url, ytq.title_name(title), a_choice(), title,
                        "2026-09-02", "video", key)
    assert statements(source) == ["Expr", "Import", "Expr", "ImportFrom", "Expr"]
    assert ytq.source_of(source) == key
    head = [line for line in source.splitlines() if line.startswith("# DESC:")]
    assert len(head) == 1
    # The words are kept: on one line, not lost.
    assert re.sub(r"\W", "", ytq.one_line(title))[:20] in re.sub(r"\W", "", head[0])


def test_a_caption_that_spells_code_is_still_only_a_caption(queued):
    """The runner reads headers and never compiles, so an item like this was
    queued without a word and then ran its second line every night."""
    caption = "dance\nprint('ran')\n#"
    path = ytq.write_item(10, ytq.title_name(caption), an_item(title=caption))
    source = path.read_text(encoding="utf-8")
    assert statements(source) == ["Expr", "Import", "Expr", "ImportFrom", "Expr"]
    assert "\nprint(" not in source


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
    from nibbles import expire_runner

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
    """At the cap the queue is dealt fresh keys first, so the new item still
    goes last, and still in two digits."""
    queued(f"{ytq.MAX_PRIORITY}-talk.py")
    number = ytq.next_number()
    assert 0 <= number <= ytq.MAX_PRIORITY
    [held] = ytq.queued_names()
    assert ytq.item_slug(held) == "talk"
    assert ytq.item_name(number, "a") > held


def test_a_day_directory_is_not_an_item(queued):
    """``done/2026-08-08/`` matches an item's number-and-dash exactly as well
    as an item does, and counting one took the next number to 2036."""
    day = ytq.DONE / "2026-08-08"
    day.mkdir(parents=True)
    (day / "10-talk.py").write_text("# EXPIRE: v1\n")
    assert [where for where, _ in ytq.items()] == ["done"]
    # And the number is counted from what is waiting, which is nothing.
    assert ytq.next_number() == 10


def wipe_queue_root():
    for folder in (ytq.QUEUE, ytq.DONE, ytq.FAILED, ytq.HERE / "work", ytq.HERE / "out"):
        shutil.rmtree(folder, ignore_errors=True)
    (ytq.HERE / "state.json").unlink(missing_ok=True)


@settings(max_examples=25)
@given(
    history=st.lists(
        st.tuples(st.sampled_from(["done", "failed"]),
                  st.integers(min_value=0, max_value=ytq.MAX_PRIORITY),
                  st.sampled_from(["Talk", "talk", "Talk: Two", "東京 散歩"])),
        max_size=30,
    ),
    titles=st.lists(st.sampled_from(["Talk", "talk", "Talk: Two", "Talk/Two", "東京 散歩"]),
                    min_size=1, max_size=40),
)
def test_downloads_run_in_the_order_they_were_queued(history, titles):
    """ytq queues last, whatever ``done/`` and ``failed/`` already hold.
    Counting them put every item from the tenth download ever at ``99``, and
    the runner, which sorts names, ran those by title. And nothing written is
    written over: the titles here collide on purpose, with each other and
    with the history, and every write is still its own item."""
    wipe_queue_root()
    for where, number, title in history:
        folder = ytq.DONE / "2026-10-01" if where == "done" else ytq.FAILED
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ytq.item_name(number, ytq.title_name(title))).write_text("# EXPIRE: v1\n")
    written = []
    for index, title in enumerate(titles):
        path = ytq.write_item(ytq.next_number(), ytq.title_name(title),
                              an_item(title=title, key=f"test:{index}"), again=True)
        written.append(ytq.item_slug(path.name))
    names = ytq.queued_names()
    assert [ytq.item_slug(name) for name in names] == written
    assert all(re.match(r"^\d{2}-", name) for name in names)
    sources = {ytq.source_of((ytq.QUEUE / name).read_text()) for name in names}
    assert sources == {f"test:{index}" for index in range(len(titles))}
    wipe_queue_root()


def test_a_queue_a_download_holds_is_not_renamed_underneath_it(queued, clean_queue):
    """A firing or a ``nibbles now`` renames its item into ``done/`` when it
    finishes; the new item shares the last key rather than move anything."""
    held = queued(f"{ytq.MAX_PRIORITY}-talk.py")
    with (clean_queue / "runner.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = ytq.write_item(ytq.next_number(), "another",
                              an_item(title="another", key="youtube:other"))
    assert held.exists() and path.exists()
    assert sorted(ytq.queued_names()) == sorted([held.name, path.name])


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


def test_a_title_named_item_still_answers_to_its_name(queued):
    """Items are named after their titles now, and the name fallback looked
    for a slug: it matched nothing, and the second "Official Trailer" was
    written over the first."""
    first = ytq.write_item(99, ytq.title_name("Official Trailer"),
                           an_item(title="Official Trailer", key="youtube:one"))
    with pytest.raises(ytq.Duplicate) as raised:
        ytq.write_item(99, ytq.title_name("Official Trailer"),
                       an_item(title="Official Trailer", key="youtube:two"))
    assert raised.value.how == "name" and raised.value.path == first
    # Meant anyway: both are queued, each still the video it was.
    second = ytq.write_item(99, ytq.title_name("Official Trailer"),
                            an_item(title="Official Trailer", key="youtube:two"), again=True)
    assert first != second and first.exists() and second.exists()
    assert ytq.source_of(first.read_text()) == "youtube:one"
    assert ytq.source_of(second.read_text()) == "youtube:two"


def test_titles_in_another_script_are_not_all_one_name(queued):
    """A slug keeps ``a-z0-9`` and nothing else, so every Japanese title was
    the slug ``video`` and the same name as every other."""
    queued("10-東京散歩.py", source="youtube:one")
    assert ytq.find_duplicate("youtube:two", "大阪散歩") is None
    assert ytq.find_duplicate("youtube:two", "東京散歩").how == "name"


@pytest.mark.parametrize("left", ["queued", "done", "failed", "work", "out", "record"])
def test_a_name_something_still_answers_to_is_never_reused(queued, clean_queue, left):
    """Whatever answers to a name next inherits what is kept under it: another
    download's partial in ``work/`` resumed into this one, a file left in
    ``out/`` delivered as this one, or a finished record's "nothing left to
    fetch" every night for ever."""
    name = ytq.item_name(10, "Talk")
    if left in ("queued", "done", "failed"):
        queued(name, where=left, source="youtube:old")
    elif left == "record":
        (clean_queue / "state.json").write_text(json.dumps(
            {"items": {name: {"retired": "done", "part_bytes": 600 * MiB}}}))
    else:
        (clean_queue / left / name).mkdir(parents=True)
    path = ytq.write_item(10, "Talk", an_item(title="Talk", key="youtube:new"), again=True)
    assert path.exists() and path.name != name
    assert ytq.ITEM_RE.match(path.name).group(1) == "10"
    assert ytq.item_slug(path.name).startswith("Talk")
    for folder in ("work", "out"):
        assert not (clean_queue / folder / path.name).exists()
    if left == "queued":
        assert ytq.source_of((ytq.QUEUE / name).read_text()) == "youtube:old"


def test_a_write_that_fails_leaves_nothing_half_written(queued, monkeypatch):
    """A full disk mid-write: the item is not queued, and nothing is left in
    ``.staging`` to be mistaken for one."""
    real = ytq.Path.write_text

    def full(self, *args, **kwargs):
        if self.parent == ytq.STAGING:
            real(self, "#!/half", encoding="utf-8")
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(ytq.Path, "write_text", full)
    with pytest.raises(OSError):
        ytq.write_item(10, "talk", an_item())
    monkeypatch.undo()
    assert ytq.queued_names() == []
    assert [p.name for p in ytq.STAGING.iterdir() if not p.name.startswith(".")] == []


def test_the_verdict_fits_the_narrowest_screen(queued):
    day = ytq.DONE / "2026-08-11"
    day.mkdir(parents=True)
    (day / "10-samsung-galaxy-z-flip8-review.py").write_text("# SOURCE: youtube:z\n")
    for how in ("source", "name"):
        for where in ("queued", "done", "failed"):
            said = ytq.Duplicate(day / "10-x.py", where, how).says()
            # "✓ " and the verdict, inside the narrowest sheet: 32 - 4 - 2.
            assert 0 < len(said) <= 26


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


# --------------------------------------------------------------------------- #
# Handing a download to dlq, and watching it
# --------------------------------------------------------------------------- #


def test_the_download_is_run_by_this_package_under_this_interpreter():
    """``nibbles now`` from the copy that is running, not whatever is on PATH;
    the child finds the package even when nothing installed it."""
    argv = ytq.now_argv("40-talk.py")
    assert argv[:3] == [sys.executable, "-m", "nibbles"]
    assert argv[3:] == ["now", "40-talk.py", "--yes"]
    path = ytq.home.child_env()["PYTHONPATH"].split(os.pathsep)
    assert path[0] == str(ytq.home.SOURCE)


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
# The answers that are for a person
# --------------------------------------------------------------------------- #


def test_the_clipboard_says_what_happened_either_way(monkeypatch):
    """The fix IS the message: a command clipped at the edge of a phone is a
    command retyped wrong, so the absence of the tool gets the install line."""
    monkeypatch.setattr(ytq.shutil, "which", lambda name: None)
    absent = ytq.to_clipboard("https://youtu.be/x")
    assert "termux-api" in absent
    # Said on the line above the tabs, which is the whole width at the floor.
    assert len(absent) <= 32

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
