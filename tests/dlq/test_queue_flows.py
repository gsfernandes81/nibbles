"""The Queue and More tabs' flows, headless: what a tap leads to on disk.

The real app with no terminal, driven with the taps and keys the terminal
would hand it, asserted on what changed on disk (the bytes, the names, the
config) and on which sheet is up — the things a screen could get wrong while
looking right.
"""

from __future__ import annotations

import json

MiB = 1024**2


def headless(dlq, tab=3, size=(40, 24)):
    app = dlq.app.App(None, tab, size=size)
    app.guard.opened = -10.0
    return app


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
