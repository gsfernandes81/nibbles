"""``dlq dump`` finishes, especially on the trees it exists for.

It is the bug report: the thing somebody pastes when a download failed on the
phone and the fix is being worked out somewhere else entirely. So the property
that matters is not what any section says but that **every section is reached**
— a dump that tracebacks in the middle is a bug report with the evidence
missing, on the one tree where the evidence is the point.

Each test below therefore breaks something real and asks for the whole dump
back: no state file, a config that will not parse, an item that is not text, a
sibling checkout that is not there, a logs directory that is not there.
"""

from __future__ import annotations

import pytest

MiB = 1024**2


def dumped(dlq, capsys, target=None) -> tuple[str, list[str]]:
    """``(everything it printed, the sections it got through)``."""
    assert dlq.sched.dump(target) == 0
    said = capsys.readouterr().out
    sections = [
        line[3:].strip() for line in said.splitlines() if line.startswith("== ")
    ]
    return said, sections


@pytest.fixture
def whole(dlq, capsys):
    """A dump of a healthy tree, to compare a broken one's sections against."""
    _, sections = dumped(dlq, capsys)
    assert sections
    return sections


def test_a_dump_of_a_working_queue_carries_the_evidence(dlq, capsys, whole):
    """The environment, how each checkout resolved, the gate, and the items."""
    dlq.item("10-thing.py", cap=MiB, desc="a thing", body="import expire_dl\n")
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert str(dlq.root) in said
    assert "expire_runner.py" in said
    assert "quota_widget.py" in said
    # An item's head is where the evidence usually is: its sys.path lines.
    assert "10-thing.py" in said
    assert "import expire_dl" in said


def test_it_finishes_with_no_state_file(dlq, capsys, whole):
    assert not (dlq.root / "state.json").exists()
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "no state.json" in said


def test_it_finishes_on_a_state_file_that_will_not_parse(dlq, capsys, whole):
    (dlq.root / "state.json").write_text("{ this is not json")
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "unreadable" in said


def test_it_names_the_config_it_could_not_read(dlq, capsys, whole):
    """Which is why every setting below it reads as its default, and why the
    person filing the report could not change any of them."""
    dlq.config("{ not json either")
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert dlq.runner.config_problem() in said
    for name in dlq.runner.SETTINGS:
        assert name in said


def test_it_names_a_stored_value_it_is_ignoring(dlq, capsys, whole):
    """The value, not just the fact that there is one: a hand-edited file is
    the reason a phone is spending by a figure nobody recognises."""
    dlq.config({"window_minutes": 7})
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "7" in said
    assert "config.json" in said


def test_it_finishes_on_an_item_that_is_not_a_text_file(dlq, capsys, whole):
    """A photo called ``20-holiday.png`` matches the item naming and is not
    UTF-8, and this runs over every file in the queue."""
    (dlq.root / "queue" / "20-holiday.py").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "20-holiday.py" in said


def test_an_item_that_is_not_text_never_hides_a_failed_one_after_it(dlq, capsys):
    """Queued rows come before failed ones, and the contract's own stray —
    ``20-holiday.png`` — is a queued row. Its head not being text has to end
    its own head and not the section, or every failed item after it is left
    out of the paste that was made for them."""
    (dlq.root / "queue" / "20-holiday.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    )
    dlq.item("30-broken.py", where="failed", body="sys.path.insert(0, '/the/evidence')\n")
    said, _ = dumped(dlq, capsys)
    lines = said.splitlines()
    start = lines.index("== items")
    end = next(at for at in range(start + 1, len(lines)) if lines[at].startswith("== "))
    items = "\n".join(lines[start:end])
    assert "20-holiday.png" in items
    assert "30-broken.py" in items
    assert "/the/evidence" in items
    assert items.index("20-holiday.png") < items.index("30-broken.py")


def test_it_finishes_with_a_sibling_checkout_missing(dlq, capsys, monkeypatch, whole):
    """The runner imports ``quota_widget`` from the zwana-quota checkout, and a
    dump written because that checkout is missing is the one that must arrive.
    """

    def gone():
        raise ImportError("No module named 'quota_widget'")

    monkeypatch.setattr(dlq.sched, "_runner", gone)
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "unreadable" in said


def test_it_says_where_the_nightly_job_looks_when_that_is_not_here(dlq, capsys):
    """The suite's own arrangement, ZWANA_HOME and nothing beside the root, is
    the one the job cannot see; the dump is where both answers are side by
    side."""
    job = dlq.sched._zwana_root(job=True)
    assert job != dlq.sched._zwana_root()
    said, _ = dumped(dlq, capsys)
    assert str(dlq.sched._zwana_root()) in said
    assert str(job) in said


def test_it_finishes_with_no_logs_directory(dlq, capsys, whole):
    for path in (dlq.root / "logs").iterdir():
        path.unlink()
    (dlq.root / "logs").rmdir()
    said, sections = dumped(dlq, capsys)
    assert sections == whole
    assert "no logs" in said


def test_it_finishes_on_a_tree_that_is_barely_a_queue_at_all(dlq, capsys, whole):
    """Everything wrong at once, which is what a bug report looks like."""
    (dlq.root / "queue" / "README.md").unlink()
    dlq.config("}{")
    (dlq.root / "state.json").write_text("nope")
    for path in (dlq.root / "logs").iterdir():
        path.unlink()
    (dlq.root / "logs").rmdir()
    _, sections = dumped(dlq, capsys)
    assert sections == whole


def test_a_named_item_is_the_one_it_shows(dlq, capsys):
    """``dlq dump NAME`` is the item somebody is asking about."""
    dlq.item("10-wanted.py", desc="the one in the report")
    dlq.item("20-other.py", desc="not this one")
    said, _ = dumped(dlq, capsys, target="wanted")
    assert "10-wanted.py" in said
    assert "20-other.py" not in said


def test_with_nothing_failing_it_still_shows_how_items_import(dlq, capsys):
    """The queue's own heads say how an item reaches its downloader, which is
    what a pre-split item gets wrong."""
    dlq.item("10-thing.py", body="import sys\nsys.path.insert(0, '/somewhere')\n")
    said, _ = dumped(dlq, capsys)
    assert "sys.path.insert" in said


def test_a_failed_item_is_what_it_shows_by_default(dlq, capsys):
    dlq.item("10-queued.py")
    dlq.item("20-failed.py", where="failed")
    said, _ = dumped(dlq, capsys)
    assert "20-failed.py" in said


def section(said: str, title: str) -> list[str]:
    """The lines of the dump's *title* section, its heading left off."""
    lines = said.splitlines()
    start = lines.index(f"== {title}") + 1
    end = next(
        (at for at in range(start, len(lines)) if lines[at].startswith("== ")),
        len(lines),
    )
    return lines[start:end]


def test_every_items_record_is_in_the_dump_whole_and_on_a_line_of_its_own(dlq, capsys):
    """Whatever the runner wrote about an item is the evidence, and which field
    matters is what the reader did not know to ask: the dump once kept a
    brief of keys the runner has never written. One line an item, so a queue
    of forty is forty lines rather than one."""
    records = {
        "10-done.py": {
            "attempts": 1,
            "last_exit": 0,
            "retired": "done",
            "bytes": 52_428_800,
            "part_bytes": 52_428_800,
            "delivered": ["/storage/emulated/0/Download/A talk.mp4"],
        },
        "20-failed.py": {
            "attempts": 3,
            "stalls": 2,
            "last": "2026-10-15 23:41:07Z",
            "last_exit": 75,
            "retired": "failed",
        },
    }
    dlq.state(records, spent=[[1_700_000_000, 1000]], ewma_bps=250_000.0)
    said, _ = dumped(dlq, capsys)
    lines = section(said, "state.json")
    for name, record in records.items():
        mine = [line for line in lines if name in line]
        assert len(mine) == 1, mine
        (line,) = mine
        assert not any(other in line for other in records if other != name)
        for key, value in record.items():
            assert key in line
            for leaf in value if isinstance(value, list) else [value]:
                assert str(leaf) in line


def kind_line(lines: list[str], kind: str) -> str:
    """The destinations section's line for *kind*: the one led by its name."""
    (line,) = [line for line in lines if line.split() and line.split()[0].startswith(kind)]
    return line


@pytest.mark.parametrize(
    "stored", [5, ["/sdcard/Movies"], True, "", "~nobody-on-this-phone/Movies"]
)
def test_a_destination_it_declines_is_said_and_reads_as_the_default(
    dlq, capsys, stored
):
    """The rule ``nibbles dest`` keeps (:func:`expire_runner.dest_state`): a
    stored value that cannot be a folder is not the one in force, so it reads
    exactly as nothing set would, and the line under it says what was
    declined."""
    unset = section(dumped(dlq, capsys)[0], "destinations")
    dlq.config({"video_dir": stored})
    declined = section(dumped(dlq, capsys)[0], "destinations")
    _, why = dlq.runner.dest_state("video")
    extra = [line for line in declined if line not in unset]
    assert len(extra) == 1 and why in extra[0]
    assert [line for line in declined if line not in extra] == unset


def test_a_destination_in_force_reads_otherwise_than_the_default(dlq, capsys):
    """Beside the folder it names, something says it was chosen."""
    unset = section(dumped(dlq, capsys)[0], "destinations")
    films = dlq.root / "films"
    films.mkdir()
    dlq.config({"video_dir": str(films)})
    chosen = section(dumped(dlq, capsys)[0], "destinations")
    default = str(dlq.runner.default_dests()["video"])
    assert kind_line(chosen, "video").replace(str(films), "") != kind_line(
        unset, "video"
    ).replace(default, "")
