"""Which budget source answers is a setting, and manual needs no zwana-quota.

Two sources, one seam. ``nibbles settings budget`` chooses between the zwana
portal and a manual allowance, the runner's :data:`SETTINGS` is the one spec
for it and for the two figures the manual source is described by, and
:func:`expire_runner.snapshot` says which of them answered — in keys added
beside the ones the screens already read, never in place of them.

The last half of this file is the promise that makes the manual source worth
having on a phone with no portal: the runner, ``nibbles status``, ``nibbles settings``
and ``nibbles dump`` all run on a checkout with no zwana-quota beside it, and
``quota_widget`` is never imported on the way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from _pty import make_root

MiB = 1024**2
MB = 1_000_000

#: The keys a snapshot carried before there was a budget source. The screens
#: being rebuilt read these, so none may be renamed, removed or change meaning.
OLD_KEYS = {
    "root", "now", "forced", "blind", "verdict", "detail", "deadline",
    "window_open", "stop_by", "portal", "portal_problem", "spendable",
    "floor_bytes", "reserve_waived", "settings", "bps", "max_attempts",
    "night_seconds", "free_disk", "items", "rejected",
}  # fmt: skip

#: Zones either side of UTC, including the two half-hour and quarter-hour
#: offsets a plan's local midnight is most often sold in.
ZONES = ["UTC", "Asia/Kolkata", "Asia/Kathmandu", "America/St_Johns", "Pacific/Auckland"]


@pytest.fixture
def zone(monkeypatch):
    """Move the phone to another timezone, and put it back afterwards."""

    def move(name: str) -> None:
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield move
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


# --------------------------------------------------------------------------- #
# The settings
# --------------------------------------------------------------------------- #


def test_zwana_is_the_default_wherever_it_can_be_imported(dlq):
    """This suite runs beside a zwana-quota checkout, so zwana is the default."""
    assert dlq.runner.ZWANA_IMPORTABLE
    assert dlq.runner.SETTINGS["budget"]["default"] == "zwana"
    assert dlq.runner.budget_source() == "zwana"
    dlq.config({"budget": "manual"})
    assert dlq.runner.budget_source() == "manual"
    dlq.config({"budget": "the moon"})
    assert dlq.runner.budget_source() == "zwana"


def test_a_choice_is_one_of_its_words(dlq):
    assert dlq.runner.parse_setting("budget", " Manual ") == "manual"
    with pytest.raises(ValueError):
        dlq.runner.parse_setting("budget", "portal")


def test_an_allowance_is_typed_as_a_plan_is_sold(dlq):
    """In MB or GB, decimal like the reserve; nought is "not set", not nothing."""
    assert dlq.runner.parse_setting("allowance", "1500") == 1500
    assert dlq.runner.parse_setting("allowance", "2 GB") == 2000
    assert dlq.runner.parse_setting("allowance", "750mb") == 750
    assert dlq.runner.spell_setting("allowance", 0) != dlq.runner.spell_setting(
        "allowance", 1
    )
    dlq.config({"allowance_mb": 1500})
    assert dlq.runner.allowance_bytes() == 1500 * MB


@pytest.mark.parametrize("where", ZONES)
def test_the_reset_is_typed_and_shown_on_the_phones_clock(dlq, zone, where):
    """Typed in local time, stored in UTC, and shown in local time again.

    And the instant it names is that local time: midnight typed on a phone in
    India is the next local midnight there, wherever UTC's own midnight is.
    """
    zone(where)
    stored = dlq.runner.parse_setting("reset", "00:00")
    assert dlq.runner.setting_problem("reset", stored) is None
    assert dlq.runner.spell_setting("reset", stored) == "00:00"
    dlq.config({"reset_utc": stored})
    _, upcoming = dlq.runner.manual_resets(time.time())
    assert time.strftime("%H:%M", time.localtime(upcoming)) == "00:00"
    assert 0 < upcoming - time.time() <= 86_400


def test_a_reset_marked_utc_is_stored_as_it_is_typed(dlq, zone):
    zone("Asia/Kolkata")
    assert dlq.runner.parse_setting("reset", "18:30Z") == "18:30"
    assert dlq.runner.parse_setting("reset", "18:30 utc") == "18:30"
    assert dlq.runner.spell_setting("reset", "18:30") == "00:00"
    for nonsense in ("25:00", "noon", "12:75"):
        with pytest.raises(ValueError):
            dlq.runner.parse_setting("reset", nonsense)


def test_choosing_manual_with_no_allowance_says_what_is_missing(dlq):
    worked, said = dlq.sched.set_setting("budget", "manual")
    assert worked
    assert "allowance" in said[-1]
    assert json.loads((dlq.root / "config.json").read_text())["budget"] == "manual"


def test_run_now_blind_on_a_manual_budget_is_the_ordinary_run(dlq, monkeypatch):
    """There is no portal to do without, so nothing is run uncounted."""
    dlq.config({"budget": "manual", "allowance_mb": 1000})
    dlq.item("10-a.py")
    ran = []
    monkeypatch.setattr(
        dlq.sched.subprocess,
        "run",
        lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    assert dlq.sched.run_blind(assume_yes=True) == 0
    assert ran and "--blind" not in ran[0]


# --------------------------------------------------------------------------- #
# What a snapshot says about it
# --------------------------------------------------------------------------- #


def test_a_zwana_snapshot_keeps_every_key_and_says_it_was_zwana(dlq):
    dlq.item("10-a.py")
    doc = dlq.reading(free=400 * MiB)
    facts = dlq.facts(portal=doc)
    assert set(facts) >= OLD_KEYS
    assert facts["source"] == "zwana"
    assert facts["portal"] is doc
    assert facts["allowance"] is None
    assert facts["expiring"] == doc["free"]["left_bytes"]
    assert facts["spendable"] == dlq.runner.spendable_bytes(doc)


def test_a_manual_snapshot_has_no_portal_and_invents_no_expiring_figure(
    dlq, monkeypatch
):
    """What a manual source cannot know is ``None``, never a figure made up.

    And the portal is not asked at all: a manual snapshot is the disk alone.
    """
    def no_portal():
        raise AssertionError("a manual snapshot asked the portal")

    monkeypatch.setattr(dlq.runner, "portal_now", no_portal)
    dlq.config({"budget": "manual", "allowance_mb": 1000})
    dlq.state(spent=[[time.time(), 200 * MB]])
    dlq.item("10-a.py")
    facts = dlq.runner.snapshot(force=True)

    assert set(facts) >= OLD_KEYS
    assert facts["source"] == "manual"
    assert facts["portal"] is None and facts["portal_problem"] == ""
    assert facts["expiring"] is None
    assert facts["reserve_waived"] is False
    reading = facts["allowance"]
    assert reading["allowance_bytes"] == 1000 * MB
    assert reading["spent_bytes"] == 200 * MB
    assert facts["spendable"] == dlq.runner.manual_spendable(reading)
    assert facts["deadline"] == reading["resets"]
    assert facts["verdict"] == "go"


# --------------------------------------------------------------------------- #
# With no zwana-quota anywhere
# --------------------------------------------------------------------------- #


@pytest.fixture
def bare(tmp_path):
    """A queue root with no zwana-quota beside it, under it, or on the path."""
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "EXPIRE_HOME": str(root),
        "COLUMNS": "40",
        "TERM": "dumb",
    }

    def run(*argv: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *argv],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=120,
        )

    run.root = root
    return run


def _clean(said: subprocess.CompletedProcess) -> str:
    out = said.stdout + said.stderr
    assert "Traceback" not in out, out
    return out


def test_the_runner_and_its_commands_run_with_no_zwana_quota(bare):
    """Manual by default there, and every command a person needs still answers."""
    status = bare("expire_sched.py", "status")
    assert "allowance" in _clean(status)
    assert status.returncode == 0

    shown = bare("expire_sched.py", "settings")
    assert "manual" in _clean(shown) and shown.returncode == 0

    set_to = bare("expire_sched.py", "settings", "allowance", "2 GB")
    _clean(set_to)
    assert set_to.returncode == 0
    config = json.loads((bare.root / "config.json").read_text())
    assert config["allowance_mb"] == 2000

    dumped = bare("expire_sched.py", "dump")
    out = _clean(dumped)
    assert "manual" in out and "(unreadable" not in out


def test_a_manual_firing_never_imports_quota_widget(bare):
    """The firing itself, with an item queued and an allowance to spend."""
    (bare.root / "config.json").write_text(json.dumps({"allowance_mb": 2000}))
    (bare.root / "queue" / "10-a.py").write_text(
        "# EXPIRE: v1\n# EXPECT_BYTES: 1000\n", encoding="utf-8"
    )
    fired = bare(
        "-c",
        "import sys, expire_runner as r\n"
        "code = r.fire(force=True)\n"
        "print('imported' if 'quota_widget' in sys.modules else 'not imported', code)\n",
    )
    out = _clean(fired)
    assert "not imported 0" in out
    # It ran: the item finished and left the queue.
    assert not (bare.root / "queue" / "10-a.py").exists()


def test_zwana_chosen_with_no_checkout_is_a_broken_root_not_a_traceback(bare):
    """Asked for by name, a missing checkout is said, and nothing is spent."""
    (bare.root / "config.json").write_text(json.dumps({"budget": "zwana"}))
    status = bare("expire_sched.py", "status")
    assert "zwana-quota" in _clean(status)
    assert status.returncode == 1

    (bare.root / "queue" / "10-a.py").write_text(
        "# EXPIRE: v1\n# EXPECT_BYTES: 1000\n", encoding="utf-8"
    )
    fired = bare("expire_runner.py", "--force")
    _clean(fired)
    assert fired.returncode == 1
    assert (bare.root / "queue" / "10-a.py").exists()
