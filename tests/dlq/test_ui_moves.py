"""Changing the queue: the order, the names, and taking something off the list.

Done here on a real temporary queue and read back through the real reader,
because both failures this guards against are silent. **Bytes losing their
item** — a rename that moves the queue file and leaves a paid-for partial under
a name nothing will look for again — leaves a queue that looks fine and starts
from zero the next night. **A download missing from the screen it is removed
from** looks exactly like a download that was never there.

Two rules hold everywhere below. Everything an item owns moves with it, which
is :func:`expire_ui.belongings` and every mutation spelled from it. And nothing
outside the queue's own root is ever deleted: a delivered file sits in
Downloads among the phone's other files and belongs to whoever asked for it.
"""

from __future__ import annotations

import time

import fcntl
import json
import shutil

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

MiB = 1024**2


def queued(dlq):
    """The queued downloads in the order the runner would work them.

    Read off the file names, because that is what the runner sorts: this is the
    order, not a view of it.
    """
    return sorted(path.name for path in (dlq.root / "queue").glob("*.py"))


def slugs(dlq):
    return [dlq.ui.parse_name(name)[1] for name in queued(dlq)]


def stock(dlq, *names, bytes_each=1024):
    """A queue of *names*, ten apart, each with a partial download of its own."""
    for number, name in enumerate(names, start=1):
        item = f"{number * 10:02d}-{name}.py"
        dlq.item(item, cap=100 * MiB)
        work = dlq.root / "work" / item
        work.mkdir(parents=True)
        # The bytes carry the slug, so a partial that ends up under the wrong
        # item can be recognised rather than merely counted.
        (work / "file.part").write_bytes(name.encode() * bytes_each)
    dlq.state({f"{n * 10:02d}-{name}.py": {"attempts": 0} for n, name in
               enumerate(names, start=1)})


def move(dlq, slug, pos):
    """Move the download whose slug is *slug* to queued position *pos*."""
    rows = dlq.sched.items()
    name = next(row["name"] for row in rows if slug in row["name"])
    return dlq.ui.do_reorder(rows, name, pos)


def clear(dlq):
    """An empty queue again: a property's examples all share one fixture."""
    for sub in ("queue", "done", "failed", "work", "out"):
        for path in (dlq.root / sub).iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            elif path.name != "README.md":
                path.unlink()
    (dlq.root / "state.json").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# The order
# --------------------------------------------------------------------------- #


def test_the_one_keypress_example(dlq):
    """``one, two, three`` with ``three`` moved up once is ``one, three, two``.

    The user's own example, and the whole of what a move means: the order
    changes and nothing else does.
    """
    stock(dlq, "one", "two", "three")
    said, moved = move(dlq, "three", 1)
    assert moved and said
    assert slugs(dlq) == ["one", "three", "two"]
    # Every download still has its own bytes under its own name.
    for slug, name in zip(slugs(dlq), queued(dlq), strict=True):
        assert (dlq.root / "work" / name / "file.part").read_bytes().startswith(
            slug.encode()
        )


def test_a_move_that_changes_nothing_says_so_and_renames_nothing(dlq):
    stock(dlq, "one", "two", "three")
    before = queued(dlq)
    said, moved = move(dlq, "one", 0)
    assert not moved and said
    assert queued(dlq) == before


def test_only_a_queued_download_has_a_place_in_the_order(dlq):
    dlq.item("10-done.py", where="done/2026-09-01")
    rows = dlq.sched.items()
    said, moved = dlq.ui.do_reorder(rows, "10-done.py", 0)
    assert not moved and said


def test_a_number_is_always_two_digits(dlq):
    """The runner sorts file *names*, so ``100`` would sort before ``20``.

    An item moved to the back would arrive at the front, and the only symptom
    would be things running in the wrong order.
    """
    for number in (0, 5, 99):
        name = dlq.ui.renumber("10-thing.py", number)
        digits = name.split("-", 1)[0]
        assert len(digits) == 2 and digits.isdigit()
    # Nothing ever hands it a bigger one: every key the queue gives out comes
    # from ``slot`` or ``spread``, and both stop at two digits.
    assert all(key <= dlq.ytq.MAX_PRIORITY for key in dlq.ui.spread(90))
    assert dlq.ui.slot([dlq.ytq.MAX_PRIORITY], 1) is None
    # And the slug is untouched: it is what everything else names the item by.
    assert dlq.ui.renumber("10-a-very-long-slug-indeed.py", 20) == (
        "20-a-very-long-slug-indeed.py"
    )


def test_a_place_with_no_room_left_renumbers_the_whole_queue(dlq):
    """Two neighbours one apart, and the move still happens.

    A plain swap of two adjacent items is already a cycle: one of them has to
    be parked on a key nobody wants while the other moves. What is parked on is
    a **real priority**, so a firing that starts in the middle reads a queue
    that is complete and legal, just possibly in an order nobody asked for.
    """
    dlq.item("10-one.py")
    dlq.item("11-two.py")
    said, moved = move(dlq, "two", 0)
    assert moved and said
    assert slugs(dlq) == ["two", "one"]
    assert len(queued(dlq)) == 2


def test_moving_never_loses_or_duplicates_a_download(dlq):
    """Whatever the queue is, and however many times it is rearranged."""
    stock(dlq, "one", "two", "three", "four")
    for slug, pos in [("four", 0), ("one", 3), ("three", 1), ("two", 0)]:
        move(dlq, slug, pos)
        assert sorted(slugs(dlq)) == ["four", "one", "three", "two"]


@given(
    moves=st.lists(
        st.tuples(st.sampled_from(["one", "two", "three"]), st.integers(0, 2)),
        max_size=6,
    )
)
def test_the_screen_order_and_the_runner_order_are_the_same_order(dlq, moves):
    """The property under the cut line: a move changes the order and nothing
    else.

    After any sequence of moves, the order the runner would work — file names,
    sorted — is the order the last move asked for, every download is still
    there exactly once, and every download's bytes are still under its own
    name.
    """
    for path in (dlq.root / "queue").glob("*.py"):
        path.unlink()
    for path in (dlq.root / "work").iterdir():
        for inner in path.iterdir():
            inner.unlink()
        path.rmdir()
    stock(dlq, "one", "two", "three")

    wanted = ["one", "two", "three"]
    for slug, pos in moves:
        rest = [other for other in wanted if other != slug]
        pos = max(0, min(pos, len(rest)))
        said, moved = move(dlq, slug, pos)
        assert said
        if moved:
            wanted = rest[:pos] + [slug] + rest[pos:]
        assert slugs(dlq) == wanted
        for name in queued(dlq):
            assert len(name.split("-", 1)[0]) == 2
            slug_of = dlq.ui.parse_name(name)[1]
            kept = (dlq.root / "work" / name / "file.part").read_bytes()
            assert kept.startswith(slug_of.encode())


#: The keys a move is most likely to hand out over a queue at 10, 20 and 30 —
#: halves, midpoints, the next ten, and :func:`spread`'s — so that a name
#: something else holds is one a move actually reaches for.
LIKELY = st.one_of(
    st.sampled_from([5, 10, 15, 20, 22, 25, 30, 35, 40, 44, 66]), st.integers(0, 99)
)


def _held(dlq, names):
    """Every byte and every record that answers to one of *names*."""
    found = {}
    for sub in ("done", "failed", "work", "out"):
        for path in sorted((dlq.root / sub).rglob("*")):
            relative = path.relative_to(dlq.root)
            mine = relative.parts[1] in names if sub in ("work", "out") else True
            if mine and path.is_file():
                found[str(relative)] = path.read_bytes()
    records = json.loads((dlq.root / "state.json").read_text())["items"]
    found.update({f"record {name}": records.get(name) for name in names})
    return found


@given(
    moves=st.lists(
        st.tuples(st.sampled_from(["one", "two", "three", "holiday"]), st.integers(0, 3)),
        max_size=6,
    ),
    held=st.lists(
        st.tuples(
            st.sampled_from(["done", "failed", "work", "out", "record"]),
            st.sampled_from(["one", "two", "three"]),
            LIKELY,
        ),
        max_size=8,
    ),
    stray=st.none() | st.integers(0, 120),
)
def test_a_move_never_lands_on_a_name_something_else_holds(dlq, moves, held, stray):
    """A move is a rename, and answers to the rename's collision rule.

    ``queue/`` having no file by a name does not make it free: a finished or
    failed download may answer to it, and so may a ``work/`` or ``out/`` left
    behind or a record that outlived its item — and the keys a move hands out
    are the keys :func:`ytq.next_number` handed out before, so a title queued
    again lands on its own old name easily. Landing there makes two items one.
    And a stray (``20-holiday.png``) sits among the queued rows: moving around
    it must not raise, and moving it must not make the photo a ``.py``.

    After every move: nothing held by another name has changed, every queued
    download still has its own bytes and its own record, the listing has a row
    for every item file on disk, and the downloads are in the order asked for.
    """
    clear(dlq)
    stock(dlq, "one", "two", "three")
    records = {name: {"marker": dlq.ui.parse_name(name)[1]} for name in queued(dlq)}
    names: set[str] = set()
    for kind, slug, key in held:
        name = f"{key:02d}-{slug}.py"
        if name in records and name not in names:
            continue  # a queued download's own name: that is its own
        if kind in ("done", "failed"):
            if any(next((dlq.root / sub).rglob(name), None) for sub in ("done", "failed")):
                continue  # one finished or failed item to a name, as on a phone
            dlq.item(name, where="done/2026-10-01" if kind == "done" else "failed")
        elif kind in ("work", "out"):
            (dlq.root / kind / name).mkdir(parents=True, exist_ok=True)
            (dlq.root / kind / name / "left.bin").write_bytes(f"held {name}".encode())
        records[name] = {"marker": f"held {name}", "part_bytes": 300 * MiB}
        names.add(name)
    dlq.state(records)
    picture = b"\x89PNG\r\n\x1a\n" + b"holiday"
    if stray is not None:
        (dlq.root / "queue" / f"{stray:02d}-holiday.png").write_bytes(picture)
    before = _held(dlq, names)

    def files():
        return sum(
            1
            for sub in ("queue", "done", "failed")
            for path in (dlq.root / sub).rglob("*")
            if path.is_file() and dlq.ytq.ITEM_RE.match(path.name)
        )

    for slug, pos in moves:
        rows = dlq.sched.items()
        listed = [row["name"] for row in rows if row["where"] == "queued"]
        name = next((item for item in listed if slug in item), None)
        if name is None:
            continue  # the stray is not there this time
        asked = [row["name"] for row in dlq.ui.preview(rows, name, pos)
                 if row["where"] == "queued"]
        said, moved = dlq.ui.do_reorder(rows, name, pos)
        assert said
        if dlq.ui.parse_name(name) is None:
            assert not moved
        else:
            assert moved or asked == listed, said
        order = asked if moved else listed
        assert slugs(dlq) == [dlq.ui.parse_name(item)[1] for item in order
                              if dlq.ui.parse_name(item)]
        assert all(len(item.split("-", 1)[0]) == 2 for item in queued(dlq))
        assert _held(dlq, names) == before
        state = json.loads((dlq.root / "state.json").read_text())["items"]
        for item in queued(dlq):
            mine = dlq.ui.parse_name(item)[1]
            assert state[item]["marker"] == mine
            assert (dlq.root / "work" / item / "file.part").read_bytes().startswith(
                mine.encode()
            )
        assert len(dlq.sched.items()) == files()
        if stray is not None:
            assert (dlq.root / "queue" / f"{stray:02d}-holiday.png").read_bytes() == picture


@pytest.mark.parametrize("fired", [False, True])
def test_a_title_queued_again_does_not_take_the_finished_ones_name(dlq, fired):
    """The case the property stands for, as it happens on the phone.

    ``Song`` finished as ``20-Song.py`` (its record says where the file went;
    its ``work/`` was left holding the bookkeeping), then was queued again as
    ``50-Song.py`` behind ``40-A.py``. Moved to the top, it halves onto ``20``
    — the finished one's name. Not yet started, it would inherit the finished
    one's record, and the runner would count it fetched and never start it;
    with a partial of its own, the move would fail on the ``work/`` in the way.
    """
    dlq.item("20-Song.py", where="done/2026-10-01")
    leftover = dlq.root / "work" / "20-Song.py"
    leftover.mkdir(parents=True)
    (leftover / ".status.json").write_text('{"state": "complete"}')
    done = {"attempts": 1, "retired": "done", "part_bytes": 300 * MiB,
            "delivered": ["/storage/emulated/0/Download/Song.mp4"]}
    dlq.state({"20-Song.py": done})
    dlq.item("40-A.py")
    dlq.item("50-Song.py", cap=60 * MiB)
    if fired:
        (dlq.root / "work" / "50-Song.py").mkdir(parents=True)
        (dlq.root / "work" / "50-Song.py" / "file.part").write_bytes(b"s" * 1000)

    said, moved = dlq.ui.do_reorder(dlq.sched.items(), "50-Song.py", 0)
    assert moved, said
    assert slugs(dlq) == ["Song", "A"]
    song = queued(dlq)[0]
    assert song != "20-Song.py"
    # The finished one is still listed, still its own, still where it was.
    assert len(dlq.sched.items()) == 3
    state = json.loads((dlq.root / "state.json").read_text())["items"]
    assert state["20-Song.py"] == done and "retired" not in state.get(song, {})
    assert (leftover / ".status.json").read_text() == '{"state": "complete"}'
    if fired:
        assert (dlq.root / "work" / song / "file.part").stat().st_size == 1000
    # And the new download is one the night would still start.
    item = dlq.runner.parse_item(dlq.root / "queue" / song)
    granted, _ = dlq.runner.admit(item, state.get(song, {}), 500 * MiB, 1e6, 3600, False)
    assert granted > 0


def test_a_stray_in_the_queue_neither_moves_nor_stops_a_move(dlq):
    """``20-holiday.png`` is listed as a queued row so that it can be
    explained. Moving its neighbours past it must work, and nothing may spell
    a download's name onto it."""
    dlq.item("10-A.py")
    dlq.item("30-B.py")
    picture = dlq.root / "queue" / "20-holiday.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    rows = dlq.sched.items()
    stray = next(row for row in rows if row["name"] == picture.name)
    assert not {"m", "r"} & {key for key, _ in dlq.ui.actions_for(stray)}
    said, moved = dlq.ui.do_reorder(rows, picture.name, 0)
    assert not moved and said
    assert dlq.ui.refuse_rename(stray, "20-holiday.py")
    assert picture.read_bytes() == b"\x89PNG\r\n\x1a\n"
    said, moved = dlq.ui.do_reorder(dlq.sched.items(), "30-B.py", 0)
    assert moved, said
    assert slugs(dlq) == ["B", "A"] and picture.exists()


def test_a_place_is_a_position_and_never_a_number(dlq):
    """``slot`` answers with room to insert, or ``None`` to renumber the lot."""
    slot = dlq.ui.slot
    assert slot([], 0) == 10
    assert slot([10, 30], 1) == 20
    assert slot([10, 20], 2) == 30
    assert slot([10, 11], 1) is None  # no room between them
    assert slot([dlq.ytq.MAX_PRIORITY], 1) is None  # no room at the back
    assert slot([1], 0) == 0
    assert slot([0], 0) is None
    for others, pos in (([10, 30], 1), ([10, 20], 2), ([], 0), ([40], 0)):
        answer = slot(others, pos)
        assert answer is None or 0 <= answer <= dlq.ytq.MAX_PRIORITY


@given(count=st.integers(1, 90))
def test_fresh_keys_are_spread_and_always_fit_two_digits(dlq, count):
    keys = dlq.ui.spread(count)
    assert len(keys) == count == len(set(keys))
    assert keys == sorted(keys)
    assert all(0 <= key <= dlq.ytq.MAX_PRIORITY for key in keys)


# --------------------------------------------------------------------------- #
# What an item owns
# --------------------------------------------------------------------------- #


def test_everything_an_item_owns_moves_with_it(dlq):
    """The queue file, the partial, the outbox and the record in state.json."""
    stock(dlq, "thing")
    out = dlq.root / "out" / "10-thing.py"
    out.mkdir(parents=True)
    (out / "thing.iso").write_bytes(b"finished")
    dlq.state({"10-thing.py": {"attempts": 2, "part_bytes": 1234}})

    row = dlq.sched.items()[0]
    assert dlq.ui.do_rename(row, "10-other.py") == "now 10-other"

    assert queued(dlq) == ["10-other.py"]
    assert (dlq.root / "work" / "10-other.py" / "file.part").is_file()
    assert (dlq.root / "out" / "10-other.py" / "thing.iso").read_bytes() == b"finished"
    state = json.loads((dlq.root / "state.json").read_text())["items"]
    assert state["10-other.py"]["attempts"] == 2
    assert "10-thing.py" not in state
    # And nothing of the old name is left behind to be found again.
    assert not (dlq.root / "work" / "10-thing.py").exists()


def test_a_rename_is_refused_before_it_can_mix_two_downloads(dlq):
    """A ``work/`` directory left by a removed item still has bytes in it."""
    stock(dlq, "one", "two")
    rows = dlq.sched.items()
    row = rows[0]
    assert dlq.ui.refuse_rename(row, row["name"]) == "that is the name it has"
    assert dlq.ui.refuse_rename(row, "not-an-item-name")
    assert dlq.ui.refuse_rename(row, "20-two.py")  # another item answers to it
    (dlq.root / "work" / "40-orphan.py").mkdir(parents=True)
    assert dlq.ui.refuse_rename(row, "40-orphan.py")
    assert dlq.ui.refuse_rename(row, "40-free.py") is None


def test_a_rename_that_cannot_finish_puts_back_what_it_moved(dlq, monkeypatch):
    """An item whose scratch moved and whose file did not downloads itself again."""
    stock(dlq, "thing")
    row = dlq.sched.items()[0]
    moves = dlq.ui.rename_moves(row, "20-thing.py")
    assert [source.name for source in (pair[0] for pair in moves)] == [
        "10-thing.py",
        "10-thing.py",
    ]

    # The scratch directory refuses to move; the queue file has already gone.
    real = type(moves[0][0]).rename

    def rename(self, target):
        if self.parent.name == "work":
            raise OSError(13, "Permission denied")
        return real(self, target)

    monkeypatch.setattr(type(moves[0][0]), "rename", rename)
    assert dlq.ui._apply(moves)
    monkeypatch.undo()
    # Back where it started, whole.
    assert queued(dlq) == ["10-thing.py"]
    assert (dlq.root / "work" / "10-thing.py" / "file.part").is_file()


# --------------------------------------------------------------------------- #
# Taking one off the list
# --------------------------------------------------------------------------- #


def test_removing_keeps_what_was_paid_for(dlq):
    """The item goes; the partial stays, and so does anything finished."""
    stock(dlq, "thing")
    out = dlq.root / "out" / "10-thing.py"
    out.mkdir(parents=True)
    (out / "thing.iso").write_bytes(b"finished")

    row = dlq.sched.items()[0]
    said = dlq.ui.do_remove(row)
    assert said.startswith("removed")
    assert dlq.sched.items() == []
    assert (dlq.root / "work" / "10-thing.py" / "file.part").is_file()
    assert (out / "thing.iso").is_file()
    assert "10-thing.py" not in json.loads((dlq.root / "state.json").read_text())["items"]


def test_the_second_answer_deletes_the_partial_and_never_the_finished_file(dlq):
    """The partial is the only thing here it is safe to delete: nothing but
    this item could ever have resumed it."""
    stock(dlq, "thing")
    out = dlq.root / "out" / "10-thing.py"
    out.mkdir(parents=True)
    (out / "thing.iso").write_bytes(b"finished")

    row = dlq.sched.items()[0]
    dlq.ui.do_remove(row, bytes_too=True)
    assert not (dlq.root / "work" / "10-thing.py").exists()
    assert (out / "thing.iso").is_file()


def test_nothing_outside_the_queue_root_is_ever_deleted(dlq):
    """A delivered file is the property of whoever asked for it."""
    landing = dlq.root.parent / "elsewhere"
    landing.mkdir()
    (landing / "thing.iso").write_bytes(b"theirs")
    dlq.item("10-thing.py", where="done/2026-09-01")
    dlq.state({"10-thing.py": {"delivered": [str(landing / "thing.iso")]}})

    row = dlq.sched.items()[0]
    for bytes_too in (False, True):
        goes, _ = dlq.ui.removal(row, bytes_too)
        for path in goes:
            assert dlq.root in path.parents or path == dlq.root
    dlq.ui.do_remove(row, bytes_too=True)
    assert (landing / "thing.iso").read_bytes() == b"theirs"


def test_scratch_that_holds_nothing_paid_for_goes_either_way(dlq):
    """An item that failed before moving a byte still leaves a status file.

    Keeping that would leave a directory nothing lists and nothing will resume.
    """
    dlq.item("10-thing.py")
    work = dlq.root / "work" / "10-thing.py"
    work.mkdir(parents=True)
    (work / ".status.json").write_text("{}")
    row = dlq.sched.items()[0]
    assert row["have"] == 0
    dlq.ui.do_remove(row)
    assert not work.exists()


@given(
    then=st.sampled_from([0, 4096]),
    grown=st.sampled_from([0, 1, 300 * 1024]),
    bytes_too=st.booleans(),
)
def test_a_removal_never_deletes_bytes_its_question_did_not_name(
    dlq, then, grown, bytes_too
):
    """The question is asked about the row, and answered after a firing.

    A remove confirm stays up for as long as nobody answers it, and a firing
    (or a ``nibbles now``) can buy part of the download and exit in between —
    the lock is free again by the time the answer comes. Whatever the disk did
    meanwhile, the answer that keeps the bytes keeps every one of them, and
    the answer that deletes them deletes no more than it named.
    """
    clear(dlq)
    dlq.item("10-film.py", cap=600 * MiB)
    work = dlq.root / "work" / "10-film.py"
    work.mkdir(parents=True)
    (work / ".status.json").write_text("{}")
    if then:
        (work / "film.part").write_bytes(b"x" * then)
    row = dlq.sched.items()[0]
    assert row["have"] == then
    if grown:  # a firing bought this much and exited while the question was up
        with (work / "film.part").open("ab") as handle:
            handle.write(b"y" * grown)
    there = dlq.sched._payload_bytes(work)

    said = dlq.ui.do_remove(row, bytes_too=bytes_too)
    assert said
    lost = there - dlq.sched._payload_bytes(work)
    assert lost <= (then if bytes_too else 0)
    gone = not (dlq.root / "queue" / "10-film.py").exists()
    # Refused only where deleting would have taken more than it named.
    assert gone == (not bytes_too or not grown)


def test_the_keys_the_remove_screen_answers_to_never_vary(dlq):
    """A key live on one download and meaning "no" on the next is worse than
    one that is not there at all.

    That is how the removal bug hid: on an item that had downloaded nothing,
    ``b`` fell through to "any other key: no" and the download stayed, quietly,
    exactly as it would have if you had meant it.
    """
    stock(dlq, "with-bytes")
    dlq.item("20-without.py")
    rows = dlq.sched.items()
    with_bytes = next(row for row in rows if row["have"])
    without = next(row for row in rows if not row["have"])

    def letters(answers):
        return {key for keys, _ in answers for key in keys}

    assert letters(dlq.ui.removal_answers(with_bytes)) == {"y", "b"}
    assert letters(dlq.ui.removal_answers(without)) == {"y", "b"}
    # What differs is only whether they are worth offering separately.
    assert len(dlq.ui.removal_answers(with_bytes)) == 2
    assert len(dlq.ui.removal_answers(without)) == 1
    assert all(label.strip() for _, label in dlq.ui.removal_answers(without))


def test_a_done_download_whose_file_was_deleted_removes_itself(dlq):
    """It answered "where did it go", and nothing can ask that any more."""
    landing = dlq.root / "landing"
    landing.mkdir()
    dlq.item("10-thing.py", where="done/2026-09-01")
    dlq.state({"10-thing.py": {"delivered": [str(landing / "thing.iso")]}})

    rows = dlq.sched.items()
    assert rows[0]["lost"] == "gone"
    assert dlq.ui.forget_gone(rows) == ["thing"]
    assert dlq.sched.items() == []


def test_a_folder_that_cannot_be_read_is_never_acted_on(dlq, monkeypatch):
    """Unreadable is ``away``, and away is left alone.

    This is the whole reason forgetting can be automatic at all: a permissions
    blip must not write off every completed download on the phone.
    """
    landing = dlq.root / "landing"
    landing.mkdir()
    dlq.item("10-thing.py", where="done/2026-09-01")
    dlq.state({"10-thing.py": {"delivered": [str(landing / "thing.iso")]}})

    import os

    real = os.listdir
    monkeypatch.setattr(
        os,
        "listdir",
        lambda path=".": (_ for _ in ()).throw(PermissionError(13, "no"))
        if str(path) == str(landing)
        else real(path),
    )
    rows = dlq.sched.items()
    assert rows[0]["lost"] == "away"
    assert dlq.ui.forget_gone(rows) == []
    monkeypatch.undo()
    assert len(dlq.sched.items()) == 1


def test_an_item_with_no_record_of_where_it_went_is_left_alone(dlq):
    """With no record there is nothing to have looked in.

    Absence of evidence is not the same fact as evidence of absence.
    """
    dlq.item("10-thing.py", where="done/2026-09-01")
    rows = dlq.sched.items()
    assert dlq.ui.forget_gone(rows) == []
    assert len(dlq.sched.items()) == 1


# --------------------------------------------------------------------------- #
# Retrying, and the guard over all of it
# --------------------------------------------------------------------------- #


def test_a_failed_item_comes_back_with_its_nights_and_its_bytes(dlq):
    """The wipe is not a courtesy: an item put back with its attempts still on
    the clock is given up on again by the first firing that touches it."""
    dlq.item("10-thing.py", where="failed")
    work = dlq.root / "work" / "10-thing.py"
    work.mkdir(parents=True)
    (work / "file.part").write_bytes(b"x" * 2048)
    dlq.state({"10-thing.py": {"attempts": 3, "stalls": 2, "retired": "failed"}})

    row = dlq.sched.items()[0]
    assert dlq.ui.do_requeue(row).endswith("is queued again")
    assert queued(dlq) == ["10-thing.py"]
    record = json.loads((dlq.root / "state.json").read_text())["items"]["10-thing.py"]
    assert record["attempts"] == 0 and record["stalls"] == 0
    assert "retired" not in record
    assert (work / "file.part").stat().st_size == 2048


def test_clearing_the_tries_of_a_queued_item(dlq):
    dlq.item("10-thing.py")
    dlq.state({"10-thing.py": {"attempts": 2}})
    row = dlq.sched.items()[0]
    assert dlq.ui.do_clear_tries(row).endswith("cleared")
    assert json.loads((dlq.root / "state.json").read_text())["items"]["10-thing.py"][
        "attempts"
    ] == 0
    assert dlq.ui.do_clear_tries(dlq.sched.items()[0]) == "it has no failed tries"


def test_nothing_may_be_changed_while_the_queue_is_busy(dlq):
    """A firing is writing into ``work/<name>/`` and will rename the item into
    ``done/`` when it finishes; moving either underneath it loses the download.

    The guard lives with the mutation and not with the screen, so it cannot be
    skipped by a caller who did not know it was needed — which is why every one
    of them is asked here rather than one standing for the rest.
    """
    stock(dlq, "one", "two")
    rows = dlq.sched.items()
    before = queued(dlq)

    handle = (dlq.root / "runner.lock").open("w")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert dlq.ui.busy_problem()
        said = [
            dlq.ui.do_reorder(rows, rows[0]["name"], 1)[0],
            dlq.ui.do_rename(rows[0], "40-new.py"),
            dlq.ui.do_remove(rows[0]),
            dlq.ui.do_clear_tries(rows[0]),
            dlq.ui.do_requeue(rows[0]),
            dlq.ui.refuse_rename(rows[0], "40-new.py"),
        ]
        assert all(answer == dlq.ui.busy_problem() for answer in said)
        assert dlq.ui.forget_gone(rows) == []
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()

    assert queued(dlq) == before
    assert (dlq.root / "work" / before[0] / "file.part").is_file()
    assert dlq.ui.busy_problem() is None


@given(
    number=st.integers(0, 99),
    words=st.text(min_size=1, max_size=40),
)
def test_a_name_survives_being_taken_apart_and_put_back(dlq, number, words):
    """The number, the slug and the suffix, and back again.

    A rename goes through ytq's slugify because that half was typed by a
    person and the rule for what an item may be called is ytq's — one spelling
    of it, or the two front ends produce names that sort against each other
    differently. A move does not, because it must not silently shorten a long
    name as well as move it.
    """
    slug = dlq.ytq.slugify(words)
    assume(slug and dlq.ui.NAME_RE.match(f"{number:02d}-{slug}.py"))
    name = f"{number:02d}-{slug}.py"

    assert dlq.ui.parse_name(name) == (number, slug)
    assert dlq.ui.renumber(name, number) == name
    assert dlq.ui.reslug(name, slug) == name
    assert dlq.ui._slug_of(name) == slug
    # And moving it keeps the slug whatever the number becomes.
    assert dlq.ui.parse_name(dlq.ui.renumber(name, 99))[1] == slug


@pytest.mark.parametrize(
    ("name", "parsed"),
    [
        ("10-thing.py", (10, "thing")),
        ("00-a.py", (0, "a")),
        ("100-thing.py", (100, "thing")),
        ("thing.py", None),
        ("1-thing.py", None),
        ("10-thing.txt", None),
        ("10-a/b.py", None),
    ],
)
def test_what_an_item_may_be_called(dlq, name, parsed):
    """Stricter than the runner's own rule, because this one has to *make* one.

    A name this does not match is a file the runner would ignore for ever
    without saying so.
    """
    assert dlq.ui.parse_name(name) == parsed


# --------------------------------------------------------------------------- #
# Every key that is offered does something
# --------------------------------------------------------------------------- #


def test_every_action_an_item_offers_is_one_the_screen_can_carry_out(dlq):
    """An action that is offered and does nothing cannot ship.

    ``actions_for`` decides what a download is worth being asked, and
    ``ACTION_WORDS`` is the button each of those keys is on the download's
    sheet. A key in the first and not the second is a key with no button.
    """
    stock(dlq, "queued")
    dlq.item("20-failed.py", where="failed")
    dlq.item("30-done.py", where="done/2026-09-01")
    (dlq.root / "queue" / "40-broken.py").write_text("# nothing declared\n")
    landing = dlq.root / "landing"
    landing.mkdir()
    (landing / "film.mp4").write_bytes(b"x")
    dlq.state({"30-done.py": {"delivered": [str(landing / "film.mp4")]}})

    offered = set()
    for row in dlq.sched.items():
        keys = [key for key, _ in dlq.ui.actions_for(row)]
        assert len(keys) == len(set(keys)), row["name"]
        for key, label in dlq.ui.actions_for(row):
            assert label.strip()
            assert key in dlq.qs.ACTION_WORDS, key
        offered |= set(keys)
    # And the ones that only make sense somewhere are only offered there.
    assert offered >= {"n", "u", "m", "r", "o", "l", "d"}


def test_what_is_offered_depends_on_where_the_download_is(dlq):
    """An archived download has no priority to change and a rejected one
    cannot be told to run."""
    dlq.item("10-queued.py")
    dlq.item("20-failed.py", where="failed")
    dlq.item("30-done.py", where="done/2026-09-01")
    rows = {row["name"]: row for row in dlq.sched.items()}
    keys = lambda name: {key for key, _ in dlq.ui.actions_for(rows[name])}  # noqa: E731

    assert "n" in keys("10-queued.py") and "m" in keys("10-queued.py")
    assert "u" in keys("20-failed.py") and "n" not in keys("20-failed.py")
    assert "m" not in keys("30-done.py") and "u" not in keys("30-done.py")
    # Removing is offered everywhere: it is a decision about the *list*.
    for name in rows:
        assert "d" in keys(name)


def test_every_colour_a_row_can_be_worth_can_be_drawn(dlq):
    """A tone missing from the screen's table is a row that loses its colour
    with nothing saying so.

    ``expire_sched._tone`` is where "what colour is this row worth" is decided
    for the printed listing; on the Queue tab a failed and a finished download
    carry their state as a mark as well as a colour.
    """
    rows = [
        {"error": "no header", "files": [], "where": "queued", "have": 0},
        {"error": None, "files": [object()], "where": "done", "have": 1},
        {"error": None, "files": [], "where": "failed", "have": 0},
        {"error": None, "files": [], "where": "queued", "have": 10},
        {"error": None, "files": [], "where": "queued", "have": 0},
    ]
    # Different answers, so the palette is saying something.
    assert len({dlq.sched._tone(row) for row in rows}) == len(rows)
    dlq.item("20-failed.py", where="failed")
    dlq.item("30-done.py", where="done/2026-09-01")
    for row in dlq.sched.items():
        drawn = dlq.qs.row_entry(row, 0, "03:00").draw(40, False).plain()
        mark = {"failed": "×", "done": "✓"}[row["where"]]
        assert drawn.split("\n")[0][1] == mark, drawn


# --------------------------------------------------------------------------- #
# What a screen says before it spends, and before it stops the nightly job
# --------------------------------------------------------------------------- #


def test_the_word_the_job_row_uses_is_the_word_the_key_reads(dlq):
    """Spelled differently, the screen would offer "arm it" over a status line
    saying it is armed — and both would look right on their own."""
    armed_row = [("job", f"{dlq.sched.ARMED}, fires every 15m", "32")]
    assert dlq.ui.armed(armed_row) is True
    assert dlq.ui.armed([("job", "not armed - dlq arm", "1;31")]) is False
    assert dlq.ui.armed([]) is False


def test_the_confirm_that_stops_the_nightly_job_names_the_key_that_starts_it(dlq):
    """A confirm can be wrong about its own screen, and this is the one line
    where being wrong costs the nightly job.

    It said ``a`` for as long as the queue had a screen of its own with arming
    on it, and went on saying ``a`` after the key moved — by which time ``a``
    was the switch that stops the queue downloading at all.
    """
    lines = dlq.ui.cancel_note()
    assert lines and all(line.strip() for line in lines)
    # It names the row that arms it again, which is a row on More now.
    assert "nightly job" in lines[-1]
    sheet = None
    app = dlq.app.App(None, 4, size=(40, 24))
    app.tabs[4].job_rows = [("job", f"{dlq.sched.ARMED}, fires every 15m", "32")]
    app.tabs[4].act(app, ("job",))
    sheet = app.sheets[-1]
    # Confirmed, with the stop in the danger style and No last.
    assert sheet.answers[0].kind == "danger" and sheet.answers[-1].key == "esc"


def test_the_number_is_the_whole_point_of_asking(dlq):
    """Both confirms put what it costs on the yes, and both say who is
    counting it: the one yes for a spend nothing is counting."""
    dlq.item("10-thing.py", cap=200 * MiB)
    row = dlq.sched.items()[0]
    facts = dlq.facts(portal=dlq.reading(free=300 * MiB), force=True)
    app = dlq.app.App(None, 3, size=(40, 24))
    app.queue.facts = facts
    item = dlq.qs.ItemSheet(row)
    shell = dlq.qs.shell

    # Counted: zwana answered the fresh connect the sheet asks as it opens.
    app.queue.reached, app.queue.reached_at = True, time.monotonic()
    now = dlq.qs.now_sheet(app, row, item)
    run = dlq.qs.run_sheet(app, facts)
    assert shell.size(200 * MiB) in now.answers[0].note
    assert shell.size(facts["spendable"]) in run.answers[0].note
    for sheet in (now, run):
        assert sheet.answers[-1].key == "esc"
        assert sheet.question.strip() and sheet.grey.strip()

    # With no portal answering, nothing is counting it — and that is said as
    # well as the number, because mobile data and a portal that is down look
    # identical from here. The border turns warning-coloured.
    blind = dlq.facts(blind=True, force=True)
    app.queue.facts = blind
    app.queue.reached, app.queue.reached_at = False, time.monotonic()
    for sheet in (dlq.qs.now_sheet(app, row, item), dlq.qs.run_sheet(app, blind)):
        assert "not answering" in sheet.question
        assert sheet.border is not None
    assert "mobile data" in dlq.qs.now_sheet(app, row, item).grey
    assert "≤" in dlq.qs.run_sheet(app, blind).answers[0].note


def test_what_an_item_owns_is_decided_in_one_place(dlq):
    """Three of the four things: the item file, the scratch it downloads into
    and the outbox it delivers into. The fourth is its record in state.json,
    which is not a path and is moved alongside them.
    """
    stock(dlq, "thing")
    row = dlq.sched.items()[0]
    owned = dict(dlq.ui.belongings(row))
    assert owned["item"] == dlq.root / "queue" / "10-thing.py"
    assert owned["work"] == dlq.root / "work" / "10-thing.py"
    assert "out" not in owned  # there is none yet

    (dlq.root / "out" / "10-thing.py").mkdir(parents=True)
    assert "out" in dict(dlq.ui.belongings(dlq.sched.items()[0]))

    # Its logs are deliberately not owned: a night's log is the record of that
    # night, and the runner's own log names the item in prose anyway.
    for _, path in dlq.ui.belongings(row):
        assert path.parent != dlq.root / "logs"


# --------------------------------------------------------------------------- #
# Open when done
# --------------------------------------------------------------------------- #


def test_o_asks_for_the_file_only_on_a_download_this_screen_started(dlq):
    """The ask is held in memory by the ``ytq.Running`` watching the download,
    so "Open it when done" is offered only where there is one: this session's
    own download of this item, while it runs. A tap ticks it."""
    dlq.item("10-queued.py")
    app = dlq.app.App(None, 3, size=(40, 24))

    class Run:
        askable, alive, name, open_when_done = True, True, "10-queued.py", False
        stopped, opened, settled = False, "", False

        def toggle_open(self):
            self.open_when_done = not self.open_when_done

    app.queue.running = run = Run()
    app.sheets[:] = [dlq.qs.DownloadSheet("10-queued.py")]
    app.compose()
    box = app.hits.find("open")
    assert box is not None and "•" in app.compose().plain()
    app.sheets[-1].tap(app, box, None)
    assert run.open_when_done and "✓ Open it when done" in app.compose().plain()

    run.name = "20-other.py"  # ours, but another item
    app.compose()
    assert app.hits.find("open") is None
    run.name, run.askable = "10-queued.py", False  # ended, stopped, or not ours
    app.compose()
    assert app.hits.find("open") is None
