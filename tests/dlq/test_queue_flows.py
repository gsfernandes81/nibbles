"""The Queue and More tabs' flows, headless: what a tap leads to on disk.

The real app with no terminal, driven with the taps and keys the terminal
would hand it, asserted on what changed on disk (the bytes, the names, the
config) and on which sheet is up — the things a screen could get wrong while
looking right.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import types

import pytest
from hypothesis import given
from hypothesis import strategies as st

MiB = 1024**2
GiB = 1024 * MiB


def headless(dlq, tab=3, size=(40, 24)):
    app = dlq.app.App(None, tab, size=size)
    app.guard.opened = -10.0
    return app


def heard(app, timeout=5.0):
    """Every job the app started, waited out and its answer delivered, as the
    loop would deliver it."""
    from nibbles import tui

    for job, _ in list(app.jobs):
        end = time.monotonic() + timeout
        while not job.finished and time.monotonic() < end:
            time.sleep(0.01)
        app.handle(tui.Done(job))


def finished(dlq, name="10-film.py", where="landing", file="film.mp4"):
    """A done download and the file the runner delivered and recorded."""
    dlq.item(name, where=f"done/{time.strftime('%Y-%m-%d')}")
    folder = dlq.root / where
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file
    path.write_bytes(b"x")
    dlq.state({name: {"delivered": [str(path)]}})
    return path


def reported(dlq, name, pid, part=10, **rest):
    """A fresh progress report for *name*, written by the run whose pid is *pid*."""
    work = dlq.root / "work" / name
    work.mkdir(parents=True, exist_ok=True)
    report = {"v": 1, "state": "progress", "run_id": f"{int(time.time())}-{pid}",
              "part_bytes": part, "total_bytes": 100 * MiB, **rest}
    (work / ".status.json").write_text(json.dumps(report))
    return work / ".status.json"


def counting(dlq, monkeypatch, reading, fail=False):
    """Every reading the queue asks for, counted; each answers *reading*."""
    asked = []

    def ask(force=False, blind=False):
        asked.append(time.time())
        if fail:
            raise OSError("no route to the portal")
        return dict(reading, now=time.time())

    monkeypatch.setattr(dlq.ui, "tonight_facts", ask)
    return asked


def tap(app, id, nth=0):
    """A tap on the middle of the *nth* target called *id*."""
    from nibbles import tui

    app.compose()
    hits = [h for h in app.hits.hits if h.id == id]
    assert len(hits) > nth, (id, app.hits.ids())
    hit = hits[nth]
    app.guard.opened = -10.0
    app.handle(tui.Tap(hit.x + hit.w // 2, hit.y + hit.h // 2))


def key(app, name):
    from nibbles import tui

    app.handle(tui.Key(name))


def open_row(app, name):
    tab = app.tabs[3]
    app.compose()
    index = next(i for i, e in enumerate(tab.lists["queued"].entries) if e.key == name)
    hit = next(h for h in app.hits.hits if h.id == "row" and h.data == index)
    from nibbles import tui

    app.guard.opened = -10.0
    app.handle(tui.Tap(hit.x + 1, hit.y))


def test_remove_keeps_what_was_paid_for_unless_told(dlq):
    """Both answers are buttons; the one that deletes bytes is never the
    first, and keeping them leaves work/ where it was."""
    dlq.item("10-keep.py")
    dlq.item("20-drop.py")
    for name in ("10-keep.py", "20-drop.py"):
        work = dlq.root / "work" / name
        work.mkdir(parents=True)
        (work / "part.bin").write_bytes(b"x" * 4096)
    app = headless(dlq)

    open_row(app, "10-keep.py")
    key(app, "d")
    sheet = app.sheets[-1]
    assert sheet.answers[0].kind != "danger" and sheet.answers[-1].key == "esc"
    tap(app, "answer:0")
    assert not (dlq.root / "queue" / "10-keep.py").exists()
    assert (dlq.root / "work" / "10-keep.py" / "part.bin").exists()

    open_row(app, "20-drop.py")
    key(app, "d")
    deleting = next(i for i, a in enumerate(app.sheets[-1].answers) if a.kind == "danger")
    tap(app, f"answer:{deleting}")
    assert not (dlq.root / "work" / "20-drop.py").exists()


def test_remove_keeps_what_a_firing_bought_while_it_was_asking(dlq):
    """Asked with nothing on the disk, so the one answer is "remove it"; a
    firing buys part of it and exits before the tap. The tap takes the item
    off the list and leaves the bytes it never asked about."""
    dlq.item("10-film.py", cap=600 * MiB)
    app = headless(dlq)
    open_row(app, "10-film.py")
    key(app, "d")
    assert not [a for a in app.sheets[-1].answers if a.kind == "danger"]
    work = dlq.root / "work" / "10-film.py"
    work.mkdir(parents=True)
    (work / "film.f137.mp4.part").write_bytes(b"x" * MiB)
    app.queue.read()  # the app's own poll: the list knows, the question does not
    tap(app, "answer:0")
    assert not (dlq.root / "queue" / "10-film.py").exists()
    assert (work / "film.f137.mp4.part").stat().st_size == MiB


def test_no_on_remove_removes_nothing(dlq):
    dlq.item("10-stay.py")
    app = headless(dlq)
    open_row(app, "10-stay.py")
    key(app, "d")
    key(app, "esc")
    assert (dlq.root / "queue" / "10-stay.py").exists()


def test_rename_moves_everything_the_download_owns(dlq):
    dlq.item("10-old-name.py")
    work = dlq.root / "work" / "10-old-name.py"
    work.mkdir(parents=True)
    (work / "part.bin").write_bytes(b"x" * 10)
    app = headless(dlq)
    open_row(app, "10-old-name.py")
    key(app, "r")
    key(app, "ctrl-u")
    for ch in "A Better: Name":
        key(app, ch)
    key(app, "enter")
    new = "10-A Better - Name.py"
    assert (dlq.root / "queue" / new).exists()
    assert (dlq.root / "work" / new / "part.bin").exists()
    assert not (dlq.root / "queue" / "10-old-name.py").exists()


def test_a_stray_file_in_the_queue_does_not_stop_a_move(dlq):
    """``20-holiday.png`` is listed among the queued; Move, ↑, ↑, Put here on
    the download below it still puts that download first, and the app is
    still there to say so."""
    dlq.item("10-A.py")
    dlq.item("30-B.py")
    (dlq.root / "queue" / "20-holiday.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    app = headless(dlq)
    open_row(app, "30-B.py")
    key(app, "m")
    for name in ("up", "up", "enter"):
        key(app, name)
    assert app.tabs[3].holding is None
    names = sorted(p.name for p in (dlq.root / "queue").glob("*.py"))
    assert [n.split("-", 1)[1] for n in names] == ["B.py", "A.py"]
    assert (dlq.root / "queue" / "20-holiday.png").exists()
    app.compose()


#: Titles as YouTube writes them: brackets, the characters a glob reads as
#: patterns, and the scripts and emoji a phone's titles are full of.
TITLES = st.text(st.sampled_from(list("ab [](){}*?!#%^&-_.' 日本🎵")), min_size=1, max_size=30)


@given(title=TITLES, now_first=st.booleans(), number=st.integers(0, 99))
def test_its_log_is_the_log_written_last_whatever_the_title(dlq, title, now_first, number):
    """A title keeps its brackets, and a bracket is not a pattern: the log an
    item wrote is found under the name ``title_name`` gave it. Of the night's
    log and a Download now's on the same day, the one written last is the one
    opened, whichever sorts last; and another item's log is never this one's,
    even where its name ends in this one's."""
    logs = dlq.root / "logs"
    shutil.rmtree(logs, ignore_errors=True)
    logs.mkdir()
    name = dlq.ytq.item_name(number, dlq.ytq.title_name(title))
    night = logs / f"2026-10-15-{name}.log"
    morning = logs / f"2026-10-15-now-{name}.log"
    other = logs / f"2026-10-16-41-x-{name}.log"
    for path in (night, morning, other):
        path.write_text(path.name)
    older, newer = (morning, night) if now_first else (night, morning)
    stamp = time.time()
    os.utime(older, (stamp - 13 * 3600, stamp - 13 * 3600))
    os.utime(newer, (stamp, stamp))
    os.utime(other, (stamp + 60, stamp + 60))
    assert dlq.ui.item_log(name) == newer


def test_its_log_on_a_bracketed_title_opens_that_log(dlq):
    """The button on the sheet is that function's answer: a failed
    ``[Official Video]`` opens the log it wrote, not "no log yet"."""
    from nibbles import tui

    name = "40-Song [Official Video].py"
    dlq.item(name, where="failed")
    log = dlq.root / "logs" / f"2026-10-15-{name}.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text("night\n")
    app = headless(dlq)
    app.tabs[3].group = 1
    app.compose()
    hit = next(h for h in app.hits.hits if h.id == "row")
    app.handle(tui.Tap(hit.x + 1, hit.y))
    key(app, "l")
    assert isinstance(app.sheets[-1], dlq.qs.LogSheet)
    assert app.sheets[-1].path == log


def slugs_queued(dlq):
    return [dlq.qs.display(p.name) for p in sorted((dlq.root / "queue").glob("*.py"))]


def test_a_tap_on_a_row_puts_the_held_download_exactly_there(dlq):
    """Move's "a tap on another row puts it there", as a round trip between
    the row tapped in the list as drawn and the order on disk: above the held
    row or below it, the row next to it or the last, after a step or not —
    and every other download keeps its order."""
    from nibbles import tui

    letters = "abcd"
    for n in (2, 3, 4):
        for held in range(n):
            for tapped in range(n):
                for steps in (0, 1):
                    for path in (dlq.root / "queue").glob("*.py"):
                        path.unlink()
                    for i in range(n):
                        dlq.item(f"{10 * (i + 1)}-{letters[i]}.py")
                    app = headless(dlq)
                    open_row(app, f"{10 * (held + 1)}-{letters[held]}.py")
                    key(app, "m")
                    for _ in range(steps):
                        key(app, "down")
                    app.compose()
                    view = app.tabs[3]._place_view
                    drawn = [dlq.qs.display(e.key) for e in view.entries if e.key]
                    index = next(i for i, e in enumerate(view.entries)
                                 if e.key and dlq.qs.display(e.key) == drawn[tapped])
                    hit = next(h for h in app.hits.hits
                               if h.id == "row-place" and h.data == index)
                    app.guard.opened = -10.0
                    app.handle(tui.Tap(hit.x + 1, hit.y))
                    case = (n, held, tapped, steps)
                    order = slugs_queued(dlq)
                    assert app.tabs[3].holding is None, case
                    assert order.index(letters[held]) == tapped, (case, drawn, order)
                    rest = [s for s in drawn if s != letters[held]]
                    assert [s for s in order if s != letters[held]] == rest, case


@pytest.mark.parametrize("went", ["done", "failed", "deleted"])
def test_a_held_download_that_leaves_the_queue_is_let_go(dlq, went):
    """A firing finishing or giving up on the download being moved, or
    something else removing it, while Move holds it: the hold is let go, the
    tab comes back with its tabs under it, and nothing else is touched."""
    for name in ("10-a.py", "20-b.py", "30-c.py"):
        dlq.item(name)
    app = headless(dlq)
    open_row(app, "20-b.py")
    key(app, "m")
    tab = app.tabs[3]
    app.compose()
    assert tab.holding is not None and "tab" not in app.hits.ids()

    held = dlq.root / "queue" / "20-b.py"
    if went == "deleted":
        held.unlink()
    else:
        folder = dlq.root / ("failed" if went == "failed" else
                             f"done/{time.strftime('%Y-%m-%d')}")
        folder.mkdir(parents=True, exist_ok=True)
        held.rename(folder / held.name)
    app.queue.read_at = 0.0
    app.queue.tick()
    app.compose()
    assert tab.holding is None
    assert "tab" in app.hits.ids()
    assert app.said
    assert slugs_queued(dlq) == ["a", "c"]
    # And with no frame between (the hold let go by the draw itself).
    dlq.item("40-d.py")
    app.queue.read()
    tab.hold(app, "40-d.py")
    (dlq.root / "queue" / "40-d.py").unlink()
    app.queue.read()
    from nibbles import widgets as w

    assert not tab.draw_moving(app, w.Surface(40, 24, None), 24)
    assert tab.holding is None


def test_a_number_setting_is_set_from_its_presets_without_typing(dlq):
    app = headless(dlq, tab=4)
    key(app, "w")
    preset = next(i for i, (_, value) in enumerate(app.sheets[-1].presets) if value == "45")
    tap(app, f"preset:{preset}")
    tap(app, "set")
    assert json.loads((dlq.root / "config.json").read_text())["window_minutes"] == 45
    assert not app.sheets
    assert "45" in app.said


def test_a_refused_value_is_said_in_the_sheet_and_nothing_is_written(dlq):
    app = headless(dlq, tab=4)
    key(app, "w")
    key(app, "ctrl-u")
    for ch in "7":
        key(app, ch)
    key(app, "enter")
    assert app.sheets and app.sheets[-1].problem
    assert not (dlq.root / "config.json").exists()


def test_a_switch_flips_where_it_sits_and_says_so(dlq):
    app = headless(dlq, tab=4)
    key(app, "a")
    assert json.loads((dlq.root / "config.json").read_text())["auto"] is False
    assert not app.sheets and "auto" in app.said
    assert app.receipts


def test_a_broken_config_is_never_written_over(dlq):
    dlq.config("{not json")
    app = headless(dlq, tab=4)
    key(app, "a")
    assert (dlq.root / "config.json").read_text() == "{not json"
    assert "config.json" in app.said or "parse" in app.said


def test_b_removes_too_when_there_are_no_bytes_to_choose_about(dlq):
    """One answer wearing two keys: the keys never vary with the item."""
    dlq.item("10-empty.py")
    app = headless(dlq)
    open_row(app, "10-empty.py")
    key(app, "d")
    assert len(app.sheets[-1].answers) == 2  # the one answer, then No
    key(app, "b")
    assert not (dlq.root / "queue" / "10-empty.py").exists()


def test_download_now_waits_for_whether_zwana_answers(dlq):
    """Its words depend on where the phone is, asked fresh as it opens; until
    the answer lands its yes does nothing."""
    import time

    dlq.item("10-thing.py", cap=200 * MiB)
    app = headless(dlq)
    app.queue.reach_job = object.__new__(type("Pending", (), {"finished": False}))
    open_row(app, "10-thing.py")
    key(app, "n")
    sheet = app.sheets[-1]
    app.compose()
    assert sheet.answers[0].kind == "off"
    key(app, "y")
    assert app.sheets[-1] is sheet, "an unknown answer is not a yes"
    app.queue.reach_job = None
    app.queue.reached, app.queue.reached_at = False, time.monotonic()
    app.compose()
    assert sheet.answers[0].kind == "danger" and sheet.border is not None


def test_a_manual_budget_is_always_counted(dlq):
    app = headless(dlq)
    app.queue.facts = dict(dlq.facts(), source="manual")
    app.queue.reached = False
    assert app.queue.counted() is True


def test_a_reading_that_failed_says_so_on_the_card(dlq):
    app = headless(dlq)
    app.queue.facts, app.queue.note = None, "no route"
    drawn = app.compose().plain()
    assert drawn.count("no route") == 2  # on the card, and in the status bar


def test_a_manual_budget_card_spends_against_what_is_left_of_the_allowance(dlq):
    """The spec's own shape, spendable/left, and never "expires" (the
    budget-source entry approved 2026-10-10)."""
    app = headless(dlq)
    allowance = {"allowance_bytes": 1200 * MiB, "left_bytes": 1144 * MiB,
                 "spent_bytes": 56 * MiB, "problem": ""}
    app.queue.facts = dict(dlq.facts(), source="manual", allowance=allowance,
                           spendable=1017 * MiB, verdict="early")
    card = app.tabs[3].card(app, 40, True).block.plain()
    pair = dlq.qs.pair_of(1017 * MiB, 1144 * MiB, 22)
    assert pair.endswith("to spend") and len(pair) <= 22
    assert pair in card and "expire" not in card
    strip = app.tabs[3].strip(app, 40, True).block.plain()
    assert pair.removesuffix(" to spend") in strip


def test_no_allowance_set_says_where_to_set_it_and_runs_nothing(dlq):
    app = headless(dlq)
    app.queue.facts = dict(dlq.facts(), source="manual", verdict="unset", spendable=0,
                           allowance={"allowance_bytes": 0, "left_bytes": 0})
    drawn = app.compose().plain()
    assert "no daily allowance set" in drawn and "set it under More" in drawn
    assert app.queue.status(40)[:3] == ("WAITING", "primary", "no allowance set")
    app.compose()
    run = next(h for h in app.hits.hits if h.id == "run")
    assert "Run now" in drawn
    tap(app, "run")
    assert not app.sheets and "allowance" in app.said
    del run


def test_open_it_never_holds_the_app(dlq, monkeypatch):
    """Open it hands the file to Android in the background, through the one
    opener: an opener that does not answer must not freeze every screen for
    its timeout, and what it answers is what the line says."""
    import threading

    release = threading.Event()
    opened = []
    answer = "what the opener said about it"

    def slow(target):
        release.wait(5)
        opened.append(target)
        return answer

    monkeypatch.setattr(dlq.ytq, "open_file", slow)
    film = finished(dlq)
    app = headless(dlq)
    row = next(r for r in app.queue.rows if r["name"] == "10-film.py")
    sheet = dlq.qs.ItemSheet(row)
    app.open(sheet)
    began = time.monotonic()
    sheet.act(app, "o")
    assert time.monotonic() - began < 1
    release.set()
    heard(app)
    assert opened == [film]
    assert app.said == answer


def test_open_it_opens_the_file_as_it_is_now_and_not_as_last_read(dlq, monkeypatch):
    """The row is a poll up to a quarter of a minute old: a file delivered
    somewhere else since is the one opened, and one deleted since is never
    handed to Android at all."""
    opened = []
    monkeypatch.setattr(dlq.ytq, "open_file", lambda target: opened.append(target) or "")
    film = finished(dlq)
    app = headless(dlq)
    row = next(r for r in app.queue.rows if r["name"] == "10-film.py")
    assert row["files"] == [film]
    sheet = dlq.qs.ItemSheet(row)
    app.open(sheet)

    moved = dlq.root / "elsewhere" / film.name
    moved.parent.mkdir()
    film.rename(moved)
    dlq.state({"10-film.py": {"delivered": [str(moved)]}})
    sheet.act(app, "o")
    heard(app)
    assert opened == [moved]

    moved.unlink()
    sheet.act(app, "o")
    heard(app)
    assert opened == [moved], "a file that is not there is never handed over"


def test_an_opener_that_raises_is_said_and_never_called_opened(dlq, monkeypatch):
    film = finished(dlq)

    def broken(target):
        raise OSError("no such opener")

    monkeypatch.setattr(dlq.ytq, "open_file", broken)
    app = headless(dlq)
    sheet = dlq.qs.ItemSheet(next(r for r in app.queue.rows if r["name"] == "10-film.py"))
    app.open(sheet)
    sheet.act(app, "o")
    heard(app)
    worked = "the opener's own sentence"
    assert film.name in app.said and app.said != worked
    monkeypatch.setattr(dlq.ytq, "open_file", lambda target: worked)
    sheet.act(app, "o")
    heard(app)
    assert app.said == worked


def test_a_download_started_now_ends_on_its_sheet_and_opens_as_asked(dlq, monkeypatch):
    """Open it when done: once the download finishes, its sheet stops saying
    it is downloading within a poll, says where it went, and says what
    opening it came to — the answer the open itself gave."""
    import time

    opened = []
    monkeypatch.setattr(dlq.ytq, "open_file", lambda path: opened.append(path) or "opened it")
    body = (
        "import json, os, pathlib, time\n"
        "work = pathlib.Path(os.environ['EXPIRE_WORK'])\n"
        "out = pathlib.Path(os.environ['EXPIRE_OUT'])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "for i in range(4):\n"
        "    (work / '.status.json').write_text(json.dumps({'v': 1, 'state': 'progress',\n"
        "        'run_id': os.environ['EXPIRE_RUN_ID'], 'part_bytes': i * 100,\n"
        "        'total_bytes': 400, 'payload_bytes_this_slice': i * 100}))\n"
        "    time.sleep(0.3)\n"
        "(out / 'film.mp4').write_bytes(b'x' * 400)\n"
    )
    dlq.script("10-film.py", body)
    app = headless(dlq)
    assert app.queue.start_now("10-film.py") is None
    sheet = dlq.qs.DownloadSheet("10-film.py")
    app.open(sheet)
    app.queue.running.toggle_open()
    end = time.monotonic() + 30
    while app.queue.running.alive and time.monotonic() < end:
        app.queue.tick()
        app.compose()
        time.sleep(0.1)
    assert not app.queue.running.alive
    # Well inside the idle poll: the end of a download is read at once.
    end = time.monotonic() + dlq.qs.IDLE_POLL / 3
    while (sheet.where(app) != "done" or app.queue.downloading_name()) \
            and time.monotonic() < end:
        time.sleep(0.1)
        app.queue.tick()
    assert app.queue.downloading_name() == ""
    assert sheet.where(app) == "done"
    end = time.monotonic() + 15
    while not app.queue.running.settled and time.monotonic() < end:
        time.sleep(0.1)
    assert [p.name for p in opened] == ["film.mp4"]
    screen = app.compose().plain()
    assert app.queue.running.opened in screen
    # Nothing left to watch: the sheet stops waking the loop.
    assert sheet.wake(app) is None


def test_x_follows_the_run_it_was_opened_on(dlq):
    """``x`` on the Queue tab while Run now is starting: the sheet is never
    live over nothing, takes up each item the run starts, and once the run
    has ended stops waking the loop."""
    dlq.item("10-a.py")
    dlq.item("20-b.py")
    app = headless(dlq)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        app.queue.firing.child = child
        key(app, "x")
        sheet = app.sheets[-1]
        assert isinstance(sheet, dlq.qs.DownloadSheet)
        app.compose()
        assert app.queue.downloading_name() == "" and not sheet.live(app)
        assert any(h.id == "pause" for h in app.hits.hits)

        first = reported(dlq, "10-a.py", child.pid)
        os.utime(first, (time.time() - 5, time.time() - 5))
        app.queue.read()
        app.compose()
        assert sheet.name == app.queue.downloading_name() == "10-a.py"
        assert sheet.live(app)

        reported(dlq, "20-b.py", child.pid)
        app.queue.read()
        app.compose()
        assert sheet.name == app.queue.downloading_name() == "20-b.py"
    finally:
        child.kill()
        child.wait()
    app.queue.read()
    app.compose()
    assert sheet.name == "20-b.py"
    assert sheet.wake(app) is None


# --------------------------------------------------------------------------- #
# The reading, the countdown, and what wakes the loop
# --------------------------------------------------------------------------- #


def test_a_reading_whose_moment_has_come_is_asked_again_once(dlq, monkeypatch):
    """A "waiting" reading taken three hours ago, for a window that opened
    since: the next look asks for a fresh one — once, on the edge, never on
    every tick after — and never counts below nought meanwhile."""
    now = time.time()
    stale = dict(dlq.facts(), verdict="early", now=now - 3 * 3600,
                 window_open=now - 3 * 3600 + 600, stop_by=now + 3600)
    asked = counting(dlq, monkeypatch, dict(stale, verdict="go"))
    app = headless(dlq)
    heard(app)
    asked.clear()
    app.queue.facts, app.queue.taken = stale, time.monotonic() - 3 * 3600
    assert app.queue.countdown() is None
    assert app.queue.status(40)[3] == ""
    app.queue.tick()
    heard(app)
    assert len(asked) == 1
    assert app.queue.facts["now"] >= stale["window_open"]
    for _ in range(3):
        app.queue.tick()
        heard(app)
    assert len(asked) == 1


def test_a_portal_that_is_down_is_not_asked_on_every_tick(dlq, monkeypatch):
    """The fresh reading failing leaves the old one up; it is asked again
    after a minute, not on every keypress meanwhile."""
    now = time.time()
    stale = dict(dlq.facts(), verdict="early", now=now - 3 * 3600,
                 window_open=now - 600, stop_by=now + 3600)
    app = headless(dlq)
    heard(app)
    asked = counting(dlq, monkeypatch, stale, fail=True)
    app.queue.facts, app.queue.taken = stale, time.monotonic() - 3 * 3600
    for _ in range(5):
        app.queue.tick()
        heard(app)
    assert len(asked) == 1
    app.queue.taken -= app.queue.STALE
    app.queue.tick()
    heard(app)
    assert len(asked) == 2


def test_the_end_of_a_run_of_ours_asks_for_a_fresh_reading(dlq, monkeypatch):
    """What a run spent is gone from the window card's figures as soon as it
    ends, not when somebody next opens the tab; its start asks nothing."""
    dlq.item("10-a.py")
    asked = counting(dlq, monkeypatch, dlq.facts())
    app = headless(dlq)
    heard(app)
    asked.clear()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        app.queue.firing.child = child
        app.queue.tick()
        heard(app)
        assert asked == []
    finally:
        child.kill()
        child.wait()
    app.queue.tick()
    heard(app)
    assert len(asked) == 1
    app.queue.tick()
    heard(app)
    assert len(asked) == 1


VERDICTS = ["early", "go", "late", "empty", "unset", "off", "spent", "no-portal", "stale"]


@given(verdict=st.sampled_from(VERDICTS),
       taken=st.floats(-86400, 0), opens=st.floats(-86400, 86400),
       window=st.floats(15 * 60, 86400))
def test_the_countdown_never_counts_a_moment_already_past(dlq, verdict, taken, opens,
                                                          window):
    """Whatever the verdict and wherever the reading sits against its window:
    the countdown is a moment still ahead or nothing, the status bar's right
    segment is never a countdown that is over, and the loop wakes each second
    only in the last two minutes of one that is running."""
    now = time.time()
    app = headless(dlq)
    app.queue.facts = dict(dlq.facts(), verdict=verdict, now=now + taken,
                           window_open=now + opens, stop_by=now + opens + window)
    app.queue.read_at = time.monotonic()
    seconds = app.queue.countdown()
    assert seconds is None or seconds > 0
    if app.queue.status(40)[3]:
        assert seconds is not None
    ticking = app.queue.wake() <= 1.0
    assert ticking == (seconds is not None and seconds < 120)


def test_nothing_to_spend_inside_the_window_names_the_next_one(dlq):
    """A window that has spent everything opens again tomorrow; it never
    "opens" at a moment already past."""
    now = time.time()
    app = headless(dlq)
    app.queue.facts = dict(dlq.facts(), verdict="spent", now=now,
                           window_open=now - 1800, stop_by=now + 1700)
    assert app.queue.next_open() > now
    assert app.queue.countdown() > 0
    # And a queue that is merely empty inside the window still names this one:
    # whatever is queued now goes in it.
    app.queue.facts = dict(app.queue.facts, verdict="empty")
    assert app.queue.next_open() == now - 1800
    assert app.queue.countdown() is None


@pytest.mark.parametrize("ours", ["running", "firing"])
def test_a_run_of_ours_that_has_exited_is_never_read_as_downloading(dlq, ours):
    """Pause on a Run now or a ``nibbles now``: its report, still fresh,
    says ``progress`` on its way out, and is not a download going on."""
    dlq.item("10-big.py")
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    reported(dlq, "10-big.py", child.pid)
    app = headless(dlq)
    assert app.queue.downloading_name() == "10-big.py"
    app.tabs[3].run_now(app)
    busy = app.said
    app.said = ""
    getattr(app.queue, ours).child = child
    app.queue.read()
    assert app.queue.downloading_name() == ""
    assert not app.queue.status(40)[0].startswith("↓")
    app.tabs[3].run_now(app)
    assert app.said != busy
    heard(app)


# --------------------------------------------------------------------------- #
# A download's figures
# --------------------------------------------------------------------------- #


def fake_clock(dlq, monkeypatch, start=1000.0):
    clock = [start]
    fake = types.SimpleNamespace(**{name: getattr(time, name) for name in dir(time)
                                    if not name.startswith("_")})
    fake.monotonic = lambda: clock[0]
    monkeypatch.setattr(dlq.qs, "time", fake)
    return clock


@given(steps=st.lists(st.tuples(st.floats(0.5, 40), st.booleans()), max_size=40))
def test_a_stalled_download_reads_as_not_moving(dlq, steps):
    """Whenever the figure has stood still for longer than a download stays
    quiet while it moves, there is no speed and no time left — whatever
    came before."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        app = headless(dlq)
        clock = fake_clock(dlq, monkeypatch)
        have = [0]
        monkeypatch.setattr(dlq.ytq, "now_progress", lambda name: (have[0], 100 * GiB))
        changed = clock[0]
        app.queue.progress("10-a.py")
        for gap, grows in steps:
            clock[0] += gap
            if grows:
                have[0] += MiB
                changed = clock[0]
            _, _, rate = app.queue.progress("10-a.py")
            assert rate >= 0
            if clock[0] - changed > dlq.qs.STILL:
                assert rate == 0 and app.queue.time_left("10-a.py") is None


def test_a_steady_download_keeps_its_speed_across_a_stall(dlq, monkeypatch):
    """Reports every five seconds read as the speed they are, before a stall
    of an hour and after it, never measured across it."""
    app = headless(dlq)
    clock = fake_clock(dlq, monkeypatch)
    have = [0]
    monkeypatch.setattr(dlq.ytq, "now_progress", lambda name: (have[0], 100 * GiB))
    speed = 2 * MiB

    def run(seconds, moving):
        rates = []
        for second in range(seconds):
            clock[0] += 1
            if moving and second % 5 == 0:
                have[0] += 5 * speed
            rates.append(app.queue.progress("x.py")[2])
        return rates

    assert abs(run(30, True)[-1] - speed) < speed / 100
    stalled = run(3600, False)
    assert stalled[-1] == 0 and app.queue.time_left("x.py") is None
    after = run(30, True)
    assert after[0] == 0
    assert abs(after[-1] - speed) < speed / 100


# --------------------------------------------------------------------------- #
# Words on the Queue tab
# --------------------------------------------------------------------------- #


def test_a_failed_row_never_draws_the_runners_utc_stamp(dlq):
    """The runner's ``last`` is its UTC log stamp; the row says it on no
    clock at all, in a zone four hours off UTC, and an item's own refusal
    is said ahead of it."""
    kept = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Dubai"
    time.tzset()
    try:
        when = time.time() - 3 * 3600
        stamp = dlq.runner.stamp(when)
        dlq.item("40-old.py", where="failed")
        (dlq.root / "failed" / "50-broken.py").write_text("# nothing declared here\n")
        dlq.state({name: {"attempts": 3, "last": stamp, "retired": "failed"}
                   for name in ("40-old.py", "50-broken.py")})
        app = headless(dlq, size=(40, 18))
        app.queue.read()
        app.tabs[3].group = 1
        drawn = app.compose().plain()
        assert "old" in drawn
        assert stamp not in drawn
        assert not re.search(r"\d\d:\d\d:\d\dZ", drawn)
        broken = next(r for r in app.queue.rows if r["name"] == "50-broken.py")
        assert broken["error"] and broken["error"][:20] in drawn
    finally:
        if kept is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = kept
        time.tzset()


@given(when=st.floats(1, 4e9))
def test_a_log_stamp_reads_back_as_the_instant_it_was(dlq, when):
    assert abs(dlq.runner.unstamp(dlq.runner.stamp(when)) - when) < 1
    assert dlq.runner.unstamp("yt-dlp: HTTP Error 403") is None


def test_the_tiny_header_says_the_figure_in_its_own_unit(dlq):
    """Below 13 rows at 32 columns the card folds into the header: the
    figure there reads back as what the window may spend, GiB or MiB, and a
    reading that failed is never dressed up as one."""
    base = dlq.facts(portal=dlq.reading())
    for width in (32, 34, 35):
        for spend, expiring in ((500 * MiB, 763 * MiB), (500 * MiB, 15 * GiB),
                                (int(14.5 * GiB), 15 * GiB), (9 * GiB, int(9.9 * GiB)),
                                (0, 12 * GiB)):
            app = headless(dlq, size=(width, 12))
            app.queue.facts = dict(base, verdict="early", spendable=spend,
                                   expiring=expiring)
            header = app.compose().plain().split("\n")[0]
            found = re.search(r"· ([\d.]+) (MiB|GiB)", header)
            assert found, (width, header)
            unit = MiB if found[2] == "MiB" else GiB
            half = 0.5 * MiB if unit == MiB else 0.05 * GiB
            assert abs(float(found[1]) * unit - spend) <= half, (width, header)
        app = headless(dlq, size=(width, 12))
        app.queue.facts, app.queue.note = None, "no /data/route/here"
        header = app.compose().plain().split("\n")[0]
        assert not re.search(r"(MiB|GiB)", header), header
