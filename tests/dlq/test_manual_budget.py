"""A manual budget never spends past the allowance, and never into the reserve.

The manual source is a plan with no portal: a daily allowance and the time it
resets, set by the person, spent down from the runner's own count of what it
has moved since the reset. There is no reading to check against, so the whole
guarantee rests on three things this file pins — the arithmetic
(:func:`expire_runner.manual_spendable`), the ledger it is taken from
(:func:`expire_runner.note_spent`), and the guards that act on it: ``plan()``
and ``fire()`` before a download, ``watch()`` while one runs.

As in ``test_tonight_budget.py``, the projection's promise is proved by
permutation and over random nights, never by one queue that happens to fit.
"""

from __future__ import annotations

import datetime as dt
import json
import itertools
import os
import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st

from test_in_flight import ROOMY, supervised

MiB = 1024**2
GiB = 1024**3
MB = 1_000_000

#: A rate nothing is refused for being too slow at.
FAST = 50 * MiB


def manual(dlq, allowance_mb, reserve_mb=100, **rest):
    """Choose the manual source, with *allowance_mb* a day and *reserve_mb* kept."""
    dlq.config(
        {"budget": "manual", "allowance_mb": allowance_mb, "reserve_mb": reserve_mb}
        | rest
    )


def headroom(dlq, reading):
    """The most a manual reading may ever let go: what is left above the reserve."""
    return max(0, reading["allowance_bytes"] - reading["spent_bytes"]) - (
        dlq.runner.floor_bytes(reading)
    )


# --------------------------------------------------------------------------- #
# The arithmetic
# --------------------------------------------------------------------------- #


@given(
    allowance_mb=st.integers(0, 50_000),
    reserve_mb=st.integers(0, 5_000),
    spends=st.lists(st.integers(0, 4 * GiB), max_size=6),
)
def test_what_may_be_spent_fits_inside_the_allowance_above_the_reserve(
    dlq, allowance_mb, reserve_mb, spends
):
    """Spendable, plus the reserve, plus what is spent, is never past the allowance.

    Random days rather than one, and with the reserve set at or above the
    allowance as readily as below it: the case that has to come out as nought
    rather than as a negative figure somebody then adds to.
    """
    manual(dlq, allowance_mb, reserve_mb)
    state: dict = {}
    for spent in spends:
        dlq.runner.note_spent(state, spent)
    reading = dlq.runner.manual_reading(state)
    spendable = dlq.runner.spendable_bytes(reading)

    assert spendable >= 0
    assert reading["spent_bytes"] == sum(spends)
    if spendable:
        assert spendable + reserve_mb * MB + reading["spent_bytes"] <= allowance_mb * MB
        assert spendable <= headroom(dlq, reading)


def test_the_reserve_is_never_waived_without_a_paid_figure(dlq):
    """``reserve-when-paid no`` waives it on paid data, and a manual budget has none."""
    manual(dlq, 1000, reserve_when_paid=False)
    reading = dlq.runner.manual_reading({})
    assert not dlq.runner.reserve_waived(reading)
    assert dlq.runner.floor_bytes(reading) == 100 * MB


def test_only_what_was_spent_since_the_reset_counts(dlq, monkeypatch):
    """The ledger is asked "since the last reset", and the reset is the setting.

    Pinned at a reset that is not midnight UTC, a minute either side of it,
    because the bug this guards against is a day boundary drawn at the wrong
    place: a minute before the reset yesterday's spending still counts, and a
    minute after it nothing before the reset does.
    """
    manual(dlq, 1000, reset_utc="18:30")
    reset = dt.datetime(2026, 10, 10, 18, 30, tzinfo=dt.UTC).timestamp()
    # One spend the day before yesterday's reset, one in the day ending now.
    state = {"spent": [[reset - 90_000, 200 * MB], [reset - 3600, 300 * MB]]}

    before = dlq.runner.manual_reading(state, current=reset - 60)
    assert before["since"] == reset - 86_400 and before["resets"] == reset
    assert before["spent_bytes"] == 300 * MB

    dlq.runner.note_spent(state, 50 * MB, when=reset + 30)
    after = dlq.runner.manual_reading(state, current=reset + 60)
    assert after["since"] == reset and after["resets"] == reset + 86_400
    assert after["spent_bytes"] == 50 * MB


def test_the_ledger_forgets_what_no_day_can_ask_about(dlq, monkeypatch):
    """Kept two days and no longer, so ``state.json`` does not grow for ever."""
    state: dict = {}
    dlq.runner.note_spent(state, 10 * MB, when=1_000_000.0)
    dlq.runner.note_spent(state, 20 * MB, when=1_000_000.0 + 3 * 86_400)
    assert [spent for _, spent in state["spent"]] == [20 * MB]
    # And nothing is written for a run that moved nothing.
    dlq.runner.note_spent(state, 0)
    assert len(state["spent"]) == 1


@pytest.mark.parametrize(
    "broken",
    [
        "{not json",  # a state.json that will not parse
        {"spent": "lots"},  # a ledger that is not a list of spends
    ],
)
def test_a_ledger_that_cannot_be_read_reads_as_spent(dlq, broken):
    """Forgetting a day's spending would read as an allowance nobody touched.

    So it fails the other way: nothing to spend, and a sentence saying why.
    """
    manual(dlq, 1000)
    if isinstance(broken, str):
        (dlq.root / "state.json").write_text(broken, encoding="utf-8")
    else:
        dlq.state(**broken)
    reading = dlq.runner.manual_reading()
    assert reading["problem"]
    assert dlq.runner.spendable_bytes(reading) == 0


def spent_today(dlq, spent: int) -> float:
    """A ledger with *spent* bytes moved since the last reset; the next reset."""
    current = time.time()
    since, resets = dlq.runner.manual_resets(current)
    dlq.state(spent=[[(since + current) / 2, spent]])
    return resets


def nothing_to_spend(dlq, current=None) -> bool:
    reading = dlq.runner.manual_reading(current=current)
    return dlq.runner.spendable_bytes(reading) == 0 and bool(reading["problem"])


def writes(dlq, writer: str) -> None:
    """What a firing, ``nibbles now`` and every screen do to ``state.json``."""
    state = dlq.runner.load_state()
    if writer == "spent":
        dlq.runner.note_spent(state, 30 * MB)
    dlq.runner.save_state(state)


@given(cut=st.integers(0, 10_000), writer=st.sampled_from(["saved", "spent"]))
def test_a_day_that_could_not_be_read_stays_spent_through_the_next_write(
    dlq, cut, writer
):
    """Until the reset, whoever writes over the file first.

    The rule that a ledger nobody can read reads as spent held only while the
    bad file was still there, and every writer here loads, changes and saves:
    the first save after a torn write put a good file over it with an empty
    ledger in it, and the next firing spent the allowance a second time. Any
    cut of a real ``state.json`` short of its end, then each kind of write,
    and the day is still spent — and the next one is not.
    """
    manual(dlq, 1000)
    resets = spent_today(dlq, 800 * MB)
    whole = (dlq.root / "state.json").read_bytes()
    (dlq.root / "state.json").write_bytes(whole[: cut % len(whole)])
    assert nothing_to_spend(dlq)

    writes(dlq, writer)
    assert nothing_to_spend(dlq)
    assert nothing_to_spend(dlq, current=resets - 1)
    after = dlq.runner.manual_reading(current=resets + 1)
    assert dlq.runner.spendable_bytes(after) > 0


@pytest.mark.parametrize(
    "broken",
    [b"", b"[]", b"null", b'"a string"', b'{"spent": [[1, 2]], "x": "\xff"}'],
)
def test_every_state_file_that_is_not_the_runners_record_reads_as_spent(dlq, broken):
    """Blank, valid JSON that is not a record, and not UTF-8 at all.

    A blank file is the write that never reached the disk, never a fresh
    queue — the runner writes ``{}`` at the least — and the others used to
    raise out of every caller that asked the state for anything. The file is
    kept beside the one written over it, which is all that is left of it.
    """
    manual(dlq, 1000)
    (dlq.root / "state.json").write_bytes(broken)
    assert isinstance(dlq.runner.load_state(), dict)
    assert nothing_to_spend(dlq)
    writes(dlq, "spent")
    assert nothing_to_spend(dlq)
    assert (dlq.root / "state.json.unreadable").read_bytes() == broken


@pytest.mark.parametrize("writer", ["put it back", "a zwana firing"])
def test_nothing_that_writes_the_state_forgets_a_day_it_could_not_read(
    dlq, monkeypatch, writer
):
    """The two writers that are not the runner's own load-and-save.

    Put it back on a failed download, and a firing under the portal — which
    spends against its own reading and writes the state all the same — and
    afterwards a manual budget is still told the day is spent.
    """
    manual(dlq, 1000)
    spent_today(dlq, 800 * MB)
    (dlq.root / "state.json").write_text('{"spent": [[1', encoding="utf-8")

    if writer == "put it back":
        dlq.item("10-b.py", where="failed")
        row = next(row for row in dlq.sched.items() if row["name"] == "10-b.py")
        dlq.ui.do_requeue(row)
        assert (dlq.root / "queue" / "10-b.py").is_file()
    else:
        dlq.config({"budget": "zwana", "allowance_mb": 1000})
        dlq.item("10-b.py")
        monkeypatch.setattr(dlq.runner, "read_portal", lambda: dlq.reading())
        monkeypatch.setattr(dlq.runner, "notify", lambda *args: None)
        monkeypatch.setattr(dlq.runner, "admit", lambda *a, **kw: (MiB, ""))
        monkeypatch.setattr(
            dlq.runner, "run_item", lambda *a: (dlq.runner.EX_TEMPFAIL, MiB, None)
        )
        assert dlq.runner.fire(force=True) == 0
        manual(dlq, 1000)

    assert dlq.runner.load_state().get("items", {}).get("10-b.py") is not None
    assert nothing_to_spend(dlq)


def test_a_ledger_written_over_by_a_spend_is_not_forgotten(dlq):
    """``spent`` that is not a list is replaced by the next spend's list.

    It reads as spent while it is there, and has to go on reading that way
    once the next run's ledger entry is written in its place.
    """
    manual(dlq, 1000)
    dlq.state(spent="lots")
    writes(dlq, "spent")
    assert isinstance(dlq.runner.load_state()["spent"], list)
    assert nothing_to_spend(dlq)


# --------------------------------------------------------------------------- #
# Before a download: the projection and the firing
# --------------------------------------------------------------------------- #


@given(
    caps=st.lists(st.integers(1, 2 * GiB), min_size=1, max_size=5),
    partial=st.lists(st.booleans(), min_size=5, max_size=5),
    allowance_mb=st.integers(0, 5_000),
    reserve_mb=st.integers(0, 500),
    spent=st.integers(0, 3 * GiB),
    rate=st.floats(50_000, 20 * MiB),
    seconds=st.integers(0, 6 * 3600),
)
def test_a_night_never_promises_more_than_the_allowance_leaves(
    dlq, caps, partial, allowance_mb, reserve_mb, spent, rate, seconds
):
    """``plan()`` over a manual budget, in every order, over random nights.

    The budget is the manual source's own figure, taken from a ledger with
    *spent* already in it, and what the night promises is never more than it —
    nor, therefore, more than the allowance leaves above the reserve.
    """
    manual(dlq, allowance_mb, reserve_mb)
    state: dict = {}
    dlq.runner.note_spent(state, spent)
    reading = dlq.runner.manual_reading(state)
    budget = dlq.runner.spendable_bytes(reading)
    items = [
        {"name": f"{10 + n:02d}-item-{n}.py", "cap": cap, "partial": partial[n]}
        for n, cap in enumerate(caps)
    ]
    for order in itertools.permutations(items):
        planned = dlq.runner.plan(list(order), {}, budget, rate, seconds, False)
        promised = sum(entry["bytes"] for entry in planned)
        assert promised <= budget
        assert promised <= max(0, headroom(dlq, reading))


@pytest.fixture
def spawning(dlq, monkeypatch):
    """Firings that spawn nothing real: each admitted item 'moves' *factor* × its cap.

    The portal is made to fail loudly, because a manual firing must never ask it.
    """
    spawned = SimpleNamespace(factor=1.0, calls=[])

    def run_item(item, cap, stop_by, doc, state):
        moved = int(cap * spawned.factor)
        spawned.calls.append(moved)
        return dlq.runner.EX_TEMPFAIL if item["partial"] else 0, moved, None

    def no_portal(*args, **kwargs):
        raise AssertionError("a manual firing asked the portal")

    monkeypatch.setattr(dlq.runner, "run_item", run_item)
    monkeypatch.setattr(dlq.runner, "read_portal", no_portal)
    monkeypatch.setattr(dlq.runner, "portal_now", no_portal)
    monkeypatch.setattr(dlq.runner, "notify", lambda *args: None)
    return spawned


@hsettings(max_examples=25)
@given(
    caps=st.lists(st.integers(1, 600 * MiB), min_size=1, max_size=5),
    partial=st.lists(st.booleans(), min_size=5, max_size=5),
    allowance_mb=st.integers(0, 1_500),
)
def test_firings_never_spend_past_the_allowance_or_into_the_reserve(
    dlq, spawning, caps, partial, allowance_mb
):
    """Three firings in a row, the ledger carried between them, sum to the headroom.

    The firing admits out of the manual figure, records what each item moved
    into the ledger, and asks the ledger again before the next item — so a
    night of several firings, each starting from what the last one left, can
    never add up to more than the allowance less the reserve. Forced, because
    the clock is not what this is about; ``--force`` is a *when*, and the
    figure answers to nobody's.
    """
    for path in (dlq.root / "queue").glob("[0-9]*"):
        path.unlink()
    (dlq.root / "state.json").unlink(missing_ok=True)
    spawning.calls.clear()
    manual(dlq, allowance_mb)
    for n, cap in enumerate(caps):
        dlq.item(f"{10 + n:02d}-item-{n}.py", cap=cap, partial=partial[n])

    for _ in range(3):
        dlq.runner.fire(force=True)

    ceiling = max(0, allowance_mb * MB - dlq.runner.reserve_bytes())
    assert sum(spawning.calls) <= ceiling
    assert dlq.runner.manual_reading()["spent_bytes"] == sum(spawning.calls)


def test_an_item_that_overspends_its_slice_is_charged_and_the_rest_wait(
    dlq, spawning
):
    """What the ledger records is what moved, not what was asked for.

    An item allowed 100 MiB that moves 150 has spent 150, and the next item is
    admitted out of what is left after *that* — the half of "never past the
    allowance" that is the runner's own count, not the item's promise.
    """
    manual(dlq, 400)
    dlq.item("10-a.py", cap=100 * MiB, partial=False)
    dlq.item("20-b.py", cap=200 * MiB, partial=False)
    spawning.factor = 1.5
    dlq.runner.fire(force=True)
    # 400 MB less 100 MB of reserve, less the margin, is ~254 MiB: a's 150 MiB
    # leaves too little for b's 200.
    assert spawning.calls == [150 * MiB]
    assert dlq.runner.manual_reading()["spent_bytes"] == 150 * MiB


def test_a_spent_allowance_spends_nothing_even_when_forced(dlq, spawning):
    """The source's figure answers to nobody's ``--force``."""
    manual(dlq, 500)
    dlq.state(spent=[[dlq.runner.now(), 450 * MB]])
    dlq.item("10-a.py", cap=MiB, partial=False)
    assert dlq.runner.fire(force=True) == 0
    assert spawning.calls == []


def test_a_firing_with_no_allowance_set_spends_nothing_and_is_not_a_fault(
    dlq, spawning
):
    """``unset`` is a heartbeat, not a blocked firing: no notification every 15 min."""
    manual(dlq, 0)
    dlq.item("10-a.py", cap=MiB, partial=False)
    assert dlq.runner.fire(force=True) == 0
    assert spawning.calls == []
    assert "allowance" in (dlq.root / "heartbeat").read_text()


# --------------------------------------------------------------------------- #
# While a download runs
# --------------------------------------------------------------------------- #


def test_a_running_download_is_stopped_before_it_reaches_the_reserve(
    dlq, monkeypatch
):
    """``watch()`` projects the allowance down by the interface counter.

    There is no portal to poll, so the projection is the whole of the in-flight
    guard: the remainder the reading started from, less what the counter says
    has moved. It must stop the download before the floor, however large the
    slice the download was handed.
    """
    manual(dlq, 500)
    reading = dlq.runner.manual_reading({})
    run = supervised(dlq, monkeypatch, moved=[n * 40 * MiB for n in range(1, 30)])
    spent = run.run(cap=ROOMY, doc=reading)

    assert run.stopped
    assert run.polled == 0  # nothing is ever asked of the portal
    floor = dlq.runner.floor_bytes(reading) + dlq.runner.FLOOR_MARGIN
    # Stopped on the first look that projected the floor, one tick past it at
    # most: everything before that look was above it.
    assert reading["left_bytes"] - (spent - 40 * MiB) > floor


def test_a_download_inside_the_allowance_is_left_alone(dlq, monkeypatch):
    """A guard that stops everything is an outage, not a guard."""
    manual(dlq, 2_000)
    run = supervised(dlq, monkeypatch, moved=[10 * MiB, 20 * MiB, 30 * MiB])
    run.run(cap=100 * MiB, doc=dlq.runner.manual_reading({}))
    assert not run.stopped


def test_a_download_started_now_comes_out_of_the_same_allowance(dlq, monkeypatch):
    """``dlq now`` is spent from the day the nightly window spends from.

    It is a person's yes and keeps no reserve, but the bytes it moved are gone
    from the allowance all the same, and the window that night must know.
    """
    manual(dlq, 1000)
    dlq.script("10-now.py", "import sys\nsys.exit(0)\n")
    counter = iter([7 * GiB, 7 * GiB + 30 * MiB])
    monkeypatch.setattr(dlq.runner, "iface_bytes", lambda: next(counter))
    row = dlq.sched.items()[0]
    assert dlq.sched._run_item(dlq.runner, row, MiB) == 0
    assert dlq.runner.manual_reading()["spent_bytes"] == 30 * MiB


def test_a_download_stopped_partway_is_still_charged(dlq, monkeypatch):
    """Stopping is SIGINT, and an interrupt unwinds past ``fire()``'s count.

    So the run that is interrupted is charged on its way out: what it moved is
    gone from the allowance either way, and forgetting it would let the next
    run spend the same bytes a second time.
    """
    manual(dlq, 1000)
    path = dlq.script("10-a.py", "import sys\nsys.exit(0)\n", cap=100 * MiB)
    item = dlq.runner.parse_item(path)
    moved = [7 * GiB]

    def interrupted(*args):
        moved[0] += 40 * MiB
        raise KeyboardInterrupt

    monkeypatch.setattr(dlq.runner, "iface_bytes", lambda: moved[0])
    monkeypatch.setattr(dlq.runner, "watch", interrupted)
    monkeypatch.setattr(dlq.runner, "kill_tree", lambda pgid, why, child=None: None)
    state = dlq.runner.load_state()
    with pytest.raises(KeyboardInterrupt):
        dlq.runner.run_item(item, 100 * MiB, dlq.runner.NO_DEADLINE, None, state)
    assert dlq.runner.manual_reading()["spent_bytes"] == 40 * MiB


def _until(path: Path, limit: float = 8.0) -> str:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.02)
    return ""


def test_a_download_now_paused_twice_is_waited_for_and_charged(
    dlq, monkeypatch, tmp_path
):
    """Pause, and Pause again while it is closing its file: still charged.

    An item takes a moment to stop — yt-dlp's gentle stop takes seconds — and
    the second interrupt used to raise out of ``nibbles now``'s wait for it:
    nothing charged to the allowance, no record saved, and the lock let go
    with the download still writing. Now both are the item's to answer, and
    the run ends when the item has.
    """
    manual(dlq, 1000)
    monkeypatch.setattr(dlq.runner, "iface_readable", lambda: False)
    body = (
        "import os, signal, sys, time\n"
        f"here = {str(tmp_path)!r}\n"
        "def stopping(number, frame):\n"
        "    signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "    time.sleep(1.0)\n"
        "    open(os.path.join(here, 'closed'), 'w').write('yes')\n"
        "    sys.exit(75)\n"
        "signal.signal(signal.SIGINT, stopping)\n"
        "with open(os.path.join(os.environ['EXPIRE_WORK'], 'x.part'), 'wb') as f:\n"
        "    f.write(b'x' * 300000)\n"
        "open(os.path.join(here, 'up'), 'w').write(str(os.getpid()))\n"
        "for _ in range(400):\n"
        "    time.sleep(0.05)\n"
    )
    dlq.script("10-now.py", body, cap=10 * MiB)
    front = threading.main_thread().ident

    def pause_twice():
        # What Pause sends: an interrupt to the group `nibbles now` and its
        # item share.
        item = int(_until(tmp_path / "up"))
        for _ in range(2):
            os.kill(item, signal.SIGINT)
            signal.pthread_kill(front, signal.SIGINT)
            time.sleep(0.3)

    presser = threading.Thread(target=pause_twice, daemon=True)
    presser.start()
    try:
        dlq.sched._run_item(dlq.runner, dlq.sched.items()[0], 10 * MiB)
    except KeyboardInterrupt:
        pytest.fail("a second Pause cut the run short")
    presser.join(timeout=10)
    assert (tmp_path / "closed").read_text() == "yes"
    assert dlq.runner.manual_reading()["spent_bytes"] >= 300_000
    assert dlq.runner.load_state()["items"]["10-now.py"]["last_exit"] == 75


# --------------------------------------------------------------------------- #
# On a phone, where the interface counters cannot be read
# --------------------------------------------------------------------------- #


def test_the_meter_takes_the_items_report_before_its_files(dlq, tmp_path):
    """The report, at wire cost; a stale report is no report; then the files."""
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    (work / "old.part").write_bytes(b"x" * 1000)  # there before the run
    meter = dlq.runner.Meter(work, out, "run-1")
    assert meter.moved() == 0

    (out / "new.bin").write_bytes(b"x" * 2000)
    assert meter.moved() == int(2000 * dlq.runner.WIRE_FACTOR)

    status = {"run_id": "run-0", "payload_bytes_this_slice": 50}
    (work / ".status.json").write_text(json.dumps(status))
    assert meter.moved() == int(2000 * dlq.runner.WIRE_FACTOR)  # not this run's

    status["run_id"] = "run-1"
    (work / ".status.json").write_text(json.dumps(status))
    assert meter.moved() == int(50 * dlq.runner.WIRE_FACTOR)


def test_on_a_phone_a_firing_charges_what_the_item_reported(dlq, monkeypatch):
    """A real item, ``/proc/net/dev`` denied: the ledger still hears of its bytes.

    The item writes the report ``expire_dl`` writes, and what the ledger is
    charged is that report at the wire's cost — not the nought the interface
    counters read on Android, which would let a manual budget spend for ever.
    """
    manual(dlq, 1000)
    monkeypatch.setattr(dlq.runner, "iface_readable", lambda: False)
    monkeypatch.setattr(dlq.runner, "iface_bytes", lambda: 0)
    monkeypatch.setattr(dlq.runner, "notify", lambda *args: None)
    body = (
        "import json, os\n"
        "report = {'run_id': os.environ['EXPIRE_RUN_ID'],\n"
        "          'payload_bytes_this_slice': 20 * 1024 * 1024, 'part_bytes': 0}\n"
        "with open(os.path.join(os.environ['EXPIRE_WORK'], '.status.json'), 'w') as f:\n"
        "    json.dump(report, f)\n"
    )
    dlq.script("10-a.py", body, cap=50 * MiB, partial=False)
    assert dlq.runner.fire(force=True) == 0
    charged = dlq.runner.manual_reading()["spent_bytes"]
    assert charged == int(20 * MiB * dlq.runner.WIRE_FACTOR)


def test_on_a_phone_a_download_started_now_is_charged_too(dlq, monkeypatch):
    """``dlq now`` charges the ledger by the same meter when the counters are dark."""
    manual(dlq, 1000)
    monkeypatch.setattr(dlq.runner, "iface_readable", lambda: False)
    monkeypatch.setattr(dlq.runner, "iface_bytes", lambda: 0)
    body = (
        "import os\n"
        "with open(os.path.join(os.environ['EXPIRE_OUT'], 'file.bin'), 'wb') as f:\n"
        "    f.write(b'x' * 300000)\n"
    )
    dlq.script("10-now.py", body)
    row = dlq.sched.items()[0]
    assert dlq.sched._run_item(dlq.runner, row, MiB) == 0
    assert dlq.runner.manual_reading()["spent_bytes"] == int(
        300_000 * dlq.runner.WIRE_FACTOR
    )
