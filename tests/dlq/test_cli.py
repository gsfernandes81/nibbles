"""The one command: what a bare ``dlq`` does, and where each word goes.

Two decisions here are worth more than they look. **A bare ``dlq`` opens the
screen, and off a terminal it prints the status** — a pipe, a script, an ssh
command with no tty all used to print status, and curses in any of them is a
usage error where there used to be an answer. And **the default may never be an
action that does something**: the failure would be a bare command that arms the
job or spends data.

The other is that ``dlq <url>`` is routed before the verbs. No verb contains
``://``, so a URL can never be shadowed by one — and the queuer keeps its own
module and its own flags, with the dispatcher only the door.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from _pty import ZWANA, make_root

MiB = 1024**2


@pytest.fixture
def offline(dlq, monkeypatch):
    """Nothing that would reach the network, the scheduler or a real screen."""
    monkeypatch.setattr(dlq.runner, "portal_now", lambda: (None, "no credentials"))
    monkeypatch.setattr(dlq.sched, "api", lambda *a, **kw: (_ for _ in ()).throw(
        FileNotFoundError("termux-job-scheduler")
    ))
    return dlq


# --------------------------------------------------------------------------- #
# What a bare dlq does
# --------------------------------------------------------------------------- #


def test_a_bare_dlq_opens_the_screen_and_prints_status_off_a_terminal(dlq):
    assert dlq.sched.default_action(interactive=True) == "ui"
    assert dlq.sched.default_action(interactive=False) == "status"


def test_the_default_never_does_anything(dlq):
    """Both halves of it, whatever they come to be.

    A bare command that armed the job or spent data is the failure this exists
    to prevent, so it is the *set* of read-only actions that is pinned rather
    than the two names.
    """
    reads_only = {"status", "list", "ui", "names", "queue", "logs", "dump", "path"}
    for interactive in (True, False):
        assert dlq.sched.default_action(interactive) in reads_only


def test_every_action_is_reachable_and_every_reachable_one_is_named(dlq):
    """The usage block and the dispatcher are one list.

    An action in the usage that the dispatcher does not know falls through to
    the usage again; one the dispatcher knows and the usage does not is a
    feature nobody can find.
    """
    for name in dlq.sched.ACTIONS:
        assert dlq.sched._action([name]) == name
    for name in dlq.sched.HIDDEN:
        assert dlq.sched._action([name]) == name
    assert dlq.sched._action(["not-a-verb"]) is None
    assert not set(dlq.sched.ACTIONS) & set(dlq.sched.HIDDEN)
    assert [entry[0].split()[0] for entry in dlq.sched.HELP] == list(dlq.sched.ACTIONS)
    for _name, blurb in dlq.sched.HELP:
        assert blurb.strip()


def test_the_options_that_are_really_actions(dlq):
    """``--now`` was asked for as an option and reads as one; ``dlq`` has none."""
    for spelled, means in dlq.sched.ALIASES.items():
        assert dlq.sched._action([spelled]) == means
        assert means in dlq.sched.ACTIONS or means in dlq.sched.HIDDEN


def test_no_verb_could_ever_shadow_a_url(dlq):
    """Which is why a URL is routed before them and needs no flag."""
    for name in (*dlq.sched.ACTIONS, *dlq.sched.HIDDEN, *dlq.sched.ALIASES):
        assert "://" not in name


def test_a_url_goes_to_the_queuer_with_everything_after_it(dlq, monkeypatch):
    """The dispatch is only the door: the flags belong to ``dlq.py``."""
    seen = []
    monkeypatch.setattr(dlq.queuer, "main", lambda argv: seen.append(argv) or 0)
    argv = ["https://example.invalid/big.iso", "--name", "big.iso"]
    assert dlq.sched.main(list(argv)) == 0
    assert seen == [argv]


def test_an_unknown_word_prints_the_usage_and_fails(dlq, capsys):
    assert dlq.sched.main(["frobnicate"]) == 2
    said = capsys.readouterr().err
    assert "usage" in said
    for name in ("status", "list", "ui"):
        assert name in said


def test_an_action_that_takes_a_name_asks_for_one(dlq, capsys):
    for action in dlq.sched.NAMED:
        assert dlq.sched.main([action]) == 2
        assert "NAME" in capsys.readouterr().err


def test_a_name_that_matches_nothing_is_an_error_rather_than_a_guess(dlq, capsys):
    dlq.item("10-thing.py")
    assert dlq.sched.main(["path", "nothing-like-it"]) == 1
    assert "no download matches" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Running the queue on purpose
# --------------------------------------------------------------------------- #


def test_run_now_is_the_runner_forced_and_nothing_else(dlq):
    """``--force`` is what makes now mean now.

    Without it the runner answers "not yet: window opens 23:00Z", which is the
    right answer to a *firing* and no answer at all to somebody who has just
    typed run-now. It overrides the clock gate and nothing else.
    """
    argv = dlq.sched.queue_run_argv(blind=False)
    assert argv[1] == str(dlq.root / "expire_runner.py")
    assert "--force" in argv
    assert "--blind" not in argv
    blind = dlq.sched.queue_run_argv(blind=True)
    assert "--force" in blind and "--blind" in blind
    # One spelling, three callers: the difference is the question they ask.
    assert blind[:-1] == argv


def test_run_now_blind_says_the_number_and_asks_before_it_spends(
    dlq, monkeypatch, capsys
):
    """The figure is the runner's own :func:`blind_budget`, called rather than
    re-derived, so the number agreed to and the number spent are the same."""
    dlq.item("10-one.py", cap=200 * MiB)
    dlq.item("20-two.py", cap=50 * MiB)
    spawned = []
    monkeypatch.setattr(
        dlq.sched.subprocess, "run", lambda argv, **kw: spawned.append(argv)
    )
    monkeypatch.setattr(dlq.sched.sys.stdin, "isatty", lambda: False)

    assert dlq.sched.run_blind(assume_yes=False) == 2
    said = capsys.readouterr()
    assert dlq.ytq.human(250 * MiB) in said.out
    assert "mobile data" in said.out
    # Nobody was asked, so nothing was started — and that is an error rather
    # than a silence an unattended caller could read as a refusal.
    assert spawned == []
    assert "pass --yes" in said.err


def test_run_now_blind_on_an_empty_queue_starts_nothing(dlq, capsys):
    assert dlq.sched.run_blind(assume_yes=True) == 0
    assert "nothing queued" in capsys.readouterr().out


def test_downloading_one_item_now_asks_before_it_spends(dlq, monkeypatch, capsys):
    """Same bargain, one item: the remainder of its own declared cap."""
    dlq.item("10-one.py", cap=200 * MiB)
    monkeypatch.setattr(dlq.sched.sys.stdin, "isatty", lambda: False)
    row = dlq.sched.items()[0]
    assert dlq.sched.run_one(row, assume_yes=False) == 2
    said = capsys.readouterr()
    assert dlq.ytq.human(200 * MiB) in said.out
    assert "mobile data" in said.out


def test_nothing_spends_without_a_yes(dlq, monkeypatch, capsys):
    """The confirmation is the whole guard on this path.

    ``dlq now`` and ``run-now --blind`` are the two ways to spend metered data
    on purpose, so every guard the runner carries is off and the only thing
    between the question and the bytes is the answer. A "no" must start
    nothing, and a "yes" must start exactly what was described.
    """
    dlq.item("10-one.py", cap=200 * MiB)
    monkeypatch.setattr(dlq.sched.sys.stdin, "isatty", lambda: True)
    spawned = []

    def spawn(argv, **kw):
        spawned.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dlq.sched.subprocess, "run", spawn)
    ran = []
    monkeypatch.setattr(
        dlq.sched, "_run_item", lambda runner, row, cap: ran.append(cap) or 0
    )

    monkeypatch.setattr(dlq.sched, "_confirm", lambda question: False)
    assert dlq.sched.run_one(dlq.sched.items()[0], assume_yes=False) == 0
    assert dlq.sched.run_blind(assume_yes=False) == 0
    assert ran == [] and spawned == []

    monkeypatch.setattr(dlq.sched, "_confirm", lambda question: True)
    assert dlq.sched.run_one(dlq.sched.items()[0], assume_yes=False) == 0
    assert ran == [200 * MiB]
    dlq.sched.run_blind(assume_yes=False)
    assert spawned == [dlq.sched.queue_run_argv(blind=True)]


def test_what_it_says_it_will_spend_is_what_is_left_to_fetch(dlq, monkeypatch, capsys):
    """A resumable download half done costs the half that is missing.

    The figure is the whole point of asking, so quoting the declaration of an
    item that already has 150 MiB of it on the disk would be asking for
    agreement to four times what it is about to spend — and the slice the item
    is then given is this same number.
    """
    dlq.item("10-one.py", cap=200 * MiB)
    work = dlq.root / "work" / "10-one.py"
    work.mkdir(parents=True)
    (work / "part.iso").write_bytes(b"x" * (150 * MiB))
    monkeypatch.setattr(dlq.sched.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(dlq.sched, "_confirm", lambda question: True)
    ran = []
    monkeypatch.setattr(
        dlq.sched, "_run_item", lambda runner, row, cap: ran.append(cap) or 0
    )

    assert dlq.sched.run_one(dlq.sched.items()[0], assume_yes=False) == 0
    assert ran == [50 * MiB]
    assert dlq.ytq.human(50 * MiB) in capsys.readouterr().out


def test_an_item_that_has_already_taken_its_declaration_is_refused(dlq, capsys):
    """Nothing is left to fetch, so there is nothing to agree to spend."""
    dlq.item("10-one.py", cap=200 * MiB)
    work = dlq.root / "work" / "10-one.py"
    work.mkdir(parents=True)
    (work / "part.iso").write_bytes(b"x" * (200 * MiB))
    assert dlq.sched.run_one(dlq.sched.items()[0], assume_yes=True) == 1
    assert "EXPECT_BYTES" in capsys.readouterr().err


def test_an_item_that_cannot_run_is_refused_with_the_reason(dlq, capsys):
    (dlq.root / "queue" / "10-broken.py").write_text("# nothing declared\n")
    dlq.item("20-done.py", where="done/2026-09-01")
    rows = {row["name"]: row for row in dlq.sched.items()}
    assert dlq.sched.run_one(rows["10-broken.py"], assume_yes=True) == 1
    assert dlq.sched.run_one(rows["20-done.py"], assume_yes=True) == 1
    said = capsys.readouterr().err
    assert "not a runnable item" in said
    assert "not the queue" in said


def test_run_now_will_not_start_on_a_broken_checkout(dlq, capsys):
    (dlq.root / "queue" / "README.md").unlink()
    assert dlq.sched.main(["run-now"]) == 1
    assert "EXPIRE_HOME" in capsys.readouterr().err


def test_a_runner_the_scheduler_could_not_exec_is_reported_rather_than_fired(
    offline, capsys
):
    """The specific trap is ``#!/usr/bin/env python3``.

    It is the portable form everywhere else and it is wrong on Android, which
    has no ``/usr/bin`` at all: the job fires and dies with exit 126 before
    Python starts, so there is no heartbeat, no log and not even a lock file to
    say why. The queue then goes quiet for days.
    """
    runner = offline.root / "expire_runner.py"
    lines = runner.read_text().splitlines(keepends=True)
    # ``#!/usr/bin/env python3`` is the specific trap and it exists on this
    # machine, which is the whole point of it: it is portable everywhere except
    # the one platform this runs on. What the check actually asks is whether
    # the interpreter is on disk, so this is one that is not.
    lines[0] = "#!/no/such/prefix/bin/python3\n"
    runner.write_text("".join(lines))

    problem = offline.sched.shebang_problem()
    assert problem and "126" in problem
    assert offline.sched.main(["status"]) == 1
    assert "BROKEN" in capsys.readouterr().out
    # And the job is not armed over it either.
    worked, said = offline.sched.do_arm()
    assert not worked and said


# --------------------------------------------------------------------------- #
# The read-only answers
# --------------------------------------------------------------------------- #


@pytest.fixture
def zwana_beside(dlq):
    """zwana-quota where the nightly job finds it: beside the queue root.

    The suite finds its checkout through ``ZWANA_HOME``, which is exactly the
    arrangement the job cannot see — so a test that wants a job that works has
    to lay out the phone's arrangement. Taken away afterwards, because the
    root's parent outlives the test.
    """
    link = dlq.root.parent / "zwana-quota"
    link.symlink_to(ZWANA, target_is_directory=True)
    yield link
    link.unlink()


@pytest.fixture
def scheduler(offline, monkeypatch):
    """termux-job-scheduler, answering: every call it was asked, in order.

    ``pending`` is what ``--pending`` prints; ``fail``, when set, is raised by
    every call after it, which is the scheduler answering one question and
    then not the next.
    """
    asked = SimpleNamespace(calls=[], pending="", fail=None)

    def api(*args, timeout=30):
        asked.calls.append(args)
        if args[0] != "--pending" and asked.fail is not None:
            raise asked.fail
        out = asked.pending if args[0] == "--pending" else ""
        return subprocess.CompletedProcess(["termux-job-scheduler", *args], 0, out, "")

    monkeypatch.setattr(offline.sched, "api", api)
    return asked


def test_the_status_screen_prints_and_says_whether_anything_is_broken(
    offline, capsys, zwana_beside
):
    offline.item("10-thing.py")
    assert offline.sched.main(["status"]) == 0
    said = capsys.readouterr().out
    assert "DOWNLOAD QUEUE" in said
    assert "10-thing" in said


def test_a_broken_checkout_stops_the_status_screen_rather_than_filling_it(
    offline, capsys
):
    """Nothing below it would be about the queue anybody means."""
    (offline.root / "queue" / "README.md").unlink()
    assert offline.sched.main(["status"]) == 1
    said = capsys.readouterr().out
    assert "BROKEN" in said
    assert "DOWNLOAD QUEUE" not in said


def test_arm_and_status_agree_about_a_checkout_only_this_shell_can_find(
    offline, scheduler, capsys, request
):
    """The nightly job is not started from a shell, so it never has
    ``ZWANA_HOME``: a checkout only that finds is one every screen here reads
    figures through and the job never imports. Arming refuses and the status
    screen says so — both by one function — until the checkout is where the
    job looks."""
    sched = offline.sched
    # The suite's own arrangement: ZWANA_HOME, and nothing beside the root.
    assert sched.job_problem()
    worked, said = sched.do_arm()
    assert not worked and said.strip()
    assert not [call for call in scheduler.calls if "--script" in call]
    assert sched.main(["status"]) == 1
    assert "BROKEN" in capsys.readouterr().out

    link = offline.root.parent / "zwana-quota"
    link.symlink_to(ZWANA, target_is_directory=True)
    request.addfinalizer(link.unlink)
    assert sched.job_problem() is None
    worked, said = sched.do_arm()
    assert worked
    assert [call for call in scheduler.calls if "--script" in call]
    assert sched.main(["status"]) == 0


def test_a_manual_budget_needs_no_checkout_the_job_can_see(offline, scheduler):
    """Nothing is read through zwana-quota, so where it is cannot matter."""
    offline.config({"budget": "manual", "allowance_mb": 1000})
    assert offline.sched.job_problem() is None
    assert offline.sched.do_arm()[0]


@given(
    body=st.one_of(
        st.sampled_from([b"", b"#!", b"#!   \n", b"#!\nimport x\n", b"\n#!/x\n", b"\xff\xfe"]),
        st.binary(max_size=64),
        st.binary(max_size=32).map(lambda tail: b"#!" + tail),
    )
)
def test_whatever_the_launcher_holds_arm_and_status_answer_in_sentences(
    offline, scheduler, body
):
    """An empty launcher is what a write cut short leaves, and a bare ``#!``
    is one keystroke from a real one. Either is a launcher the scheduler
    cannot exec, which is the question these exist to answer — not an
    exception to raise from the screen that asked it."""
    offline.sched.RUNNER.write_bytes(body)
    problem = offline.sched.shebang_problem()
    assert problem is None or problem.strip()
    worked, said = offline.sched.do_arm()
    assert isinstance(worked, bool) and said.strip()
    assert offline.sched.main(["status"]) in (0, 1)


def test_a_scheduler_that_stops_answering_part_way_is_a_sentence(
    offline, scheduler, zwana_beside
):
    """``--pending`` answering is no promise that the next call does."""
    for fault in (subprocess.TimeoutExpired("termux-job-scheduler", 30), OSError("gone")):
        scheduler.fail = fault
        for verb in (offline.sched.do_arm, offline.sched.do_cancel):
            worked, said = verb()
            assert not worked and said.strip()


#: Other ids a substring "2400" also finds, and other runners job 2400 might
#: start: an old root's, a throwaway one's, and a path with the digits in it.
DECOY_IDS = [2400, 12400, 24000, 24001, 240, 1]
ELSEWHERE = [
    "/data/data/com.termux/files/home/dlq/expire_runner.py",
    "/tmp/throwaway/expire_runner.py",
    "/x/2400/sync.sh",
]


@given(
    jobs=st.lists(
        st.tuples(
            st.sampled_from(DECOY_IDS),
            st.integers(0, len(ELSEWHERE)),
            st.sampled_from([900_000, 2_400_000, 86_400_000]),
        ),
        max_size=4,
        unique_by=lambda job: job[0],
    )
)
def test_the_job_is_armed_only_when_our_id_starts_this_roots_runner(
    offline, scheduler, jobs
):
    """Whatever else is registered. A job left at ~/dlq after the move, or by
    a throwaway root, fires faithfully every night onto a queue that is not
    this one, and a screen calling that armed hides the one button that
    fixes it."""
    runners = [str(offline.sched.RUNNER), *ELSEWHERE]
    scheduler.pending = "\n".join(
        f"Pending Job {job}: {runners[which]}    (periodic: {ms}ms) (persisted)"
        for job, which, ms in jobs
    ) or "No jobs found"
    ours = any(job == offline.sched.JOB_ID and which == 0 for job, which, _ in jobs)
    assert offline.ui.armed(offline.sched.job_rows()) is ours


def test_a_job_that_starts_another_roots_runner_is_armed_again_from_more(
    offline, scheduler, monkeypatch
):
    """Not the confirm that stops it: Arm, which registers the id again at
    this root's runner."""
    scheduler.pending = (
        f"Pending Job {offline.sched.JOB_ID}: {ELSEWHERE[0]}    (periodic: 900000ms)"
    )

    def stub():
        return True, "job registered"

    monkeypatch.setattr(offline.sched, "do_arm", stub)
    app = offline.app.App(None, 4, size=(40, 24))
    tab = app.tabs[4]
    tab.job_rows = offline.sched.job_rows()
    tab.act(app, ("job",))
    assert not app.sheets
    assert tab.arming is not None and tab.arming.work is stub


@pytest.mark.parametrize("spelled", ["default", "Default", " default ", "DEFAULT\t", "", " "])
def test_every_spelling_of_default_puts_a_destination_back_and_makes_nothing(
    dlq, monkeypatch, tmp_path, spelled
):
    """As ``settings`` reads "default", and nothing left over: a capital or a
    stray space typed on the phone was a folder made wherever nibbles had been
    started, with every video delivered into it under a line saying it
    worked."""
    monkeypatch.chdir(tmp_path)
    assert dlq.sched.set_dest("video", str(dlq.root / "films"))[0]
    assert dlq.sched.main(["dest", "video", spelled]) == 0
    assert "video_dir" not in dlq.runner.load_config()
    assert dlq.runner.dests()["video"] == dlq.runner.default_dests()["video"]
    assert list(tmp_path.iterdir()) == []


def test_a_destination_typed_with_spaces_round_it_is_that_destination(dlq):
    films = dlq.root / "films"
    worked, _ = dlq.sched.set_dest("video", f"  {films}\t")
    assert worked
    assert dlq.runner.dests()["video"] == films


def test_the_listing_and_the_completions_show_the_same_downloads(dlq, capsys):
    dlq.item("10-thing.py", desc="a thing")
    dlq.item("20-other.py", where="failed")
    assert dlq.sched.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert dlq.sched.main(["names"]) == 0
    names = capsys.readouterr().out
    for name in ("10-thing", "20-other"):
        assert name in listed and name in names
    # fish's own completion format: name, a tab, what it is.
    for line in names.strip().splitlines():
        assert line.count("\t") == 1


def test_the_log_says_so_when_there_is_none_yet(dlq, capsys):
    assert dlq.sched.main(["logs"]) == 0
    assert "not written yet" in capsys.readouterr().out


def test_the_command_names_itself_the_way_it_was_invoked(dlq, monkeypatch):
    """``nibbles`` on PATH and ``expire_sched.py`` in the checkout — printing
    the other one sends people to the wrong place. (``dlq`` until nibbles
    became the one command.)"""
    monkeypatch.setattr(dlq.sched.sys, "argv", ["nibbles", "status"])
    assert dlq.sched._me() == "nibbles"
    monkeypatch.setattr(dlq.sched.sys, "argv", ["expire_sched.py"])
    assert dlq.sched._me() == "expire_sched.py"
    # A front end drawing this module's screens still names this module's
    # commands, because that is whose commands they are.
    monkeypatch.setattr(dlq.sched.sys, "argv", ["expire_runner.py", "--status"])
    assert dlq.sched._me() in ("nibbles", "expire_sched.py")


# --------------------------------------------------------------------------- #
# dlq <url>
# --------------------------------------------------------------------------- #


def test_a_server_that_answers_head_settles_both_questions_at_once(dlq, serving):
    """HEAD first: a length and an Accept-Ranges verdict is the whole answer,
    and it costs no payload at all."""
    serving.payload = b"x" * 4096
    assert dlq.queuer.probe(serving.url)[:2] == (4096, True)
    assert serving.state_of_the_world["head"]
    assert "asked" not in serving.state_of_the_world  # no GET was needed


def test_a_server_that_will_not_say_is_asked_for_one_byte(dlq, serving):
    """A GET for ``bytes=0-0``, closed unread, settles both at the cost of
    headers plus at most one byte of payload.

    Which is what makes the probe free enough to do before queueing: this runs
    on a phone whose whole point is not spending data it did not mean to.
    """
    serving.payload = b"y" * 8192
    serving.state_ranges = False
    serving.state_length = False
    assert dlq.queuer.probe(serving.url)[:2] == (8192, True)
    assert serving.state_of_the_world["asked"] == ["bytes=0-0"]


def test_a_server_that_refuses_head_is_still_sized(dlq, serving):
    """Plenty of them do; the ranged GET settles it."""
    serving.payload = b"z" * 2048
    serving.head_code = 405
    assert dlq.queuer.probe(serving.url)[:2] == (2048, True)


def test_a_server_that_ignores_range_says_so_in_the_answer(dlq, serving):
    """The whole file has to fit one night's slice or the item will fail, and
    that is a warning somebody has to be given at queue time."""
    serving.payload = b"w" * 3000
    serving.honour_range = False
    serving.state_ranges = False
    assert dlq.queuer.probe(serving.url)[:2] == (3000, False)


def test_what_head_said_stands_when_the_ranged_get_will_not_answer(dlq, serving):
    """Half an answer is still an answer.

    HEAD gave a length; the ranged GET was only ever there to settle the rest.
    Throwing the length away because the second request failed would send
    somebody to ``--expect-bytes`` for a file the server has already sized.
    """
    serving.payload = b"q" * 5000
    serving.state_ranges = False  # so the ranged GET is asked for at all
    serving.get_code = 500
    size, resumable = dlq.queuer.probe(serving.url)[:2]
    assert size == 5000
    assert resumable is None  # nothing was settled about resuming


def test_a_server_that_cannot_be_reached_is_an_error_and_not_a_guess(dlq):
    with pytest.raises(dlq.queuer.ProbeError):
        dlq.queuer.probe("http://127.0.0.1:1/nothing", timeout=2)


def test_a_probe_that_fails_is_survivable_with_a_declared_cap(dlq, monkeypatch, capsys):
    """The cap is a spending limit rather than a measurement, so a probe that
    could not run does not have to stop the queueing — but it is said."""
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    assert dlq.queuer.main(
        ["http://127.0.0.1:1/x.iso", "--expect-bytes", "1000000", "--name", "x.iso"]
    ) == 0
    assert "probe failed" in capsys.readouterr().err
    item = dlq.runner.parse_item(next((dlq.root / "queue").glob("*.py")))
    assert item["cap"] == 1_000_000

    # Without a cap there is nothing to queue against, and nothing is written.
    for path in (dlq.root / "queue").glob("*.py"):
        path.unlink()
    assert dlq.queuer.main(["http://127.0.0.1:1/x.iso"]) == 1
    assert list((dlq.root / "queue").glob("*.py")) == []

    # And --probe is a question rather than an ask, so it fails rather than
    # queueing something nobody sized.
    assert dlq.queuer.main(
        ["http://127.0.0.1:1/x.iso", "--expect-bytes", "1000000", "--probe"]
    ) == 1


@pytest.mark.parametrize("resumable", [True, False, None])
def test_a_probe_says_what_it_found_about_resuming(dlq, monkeypatch, capsys, resumable):
    """Three different answers, and "unknown" is not "no": the first means the
    item can be fetched in slices, the second that it cannot, and the third
    that the server did not say and the first firing will find out."""
    monkeypatch.setattr(
        dlq.queuer, "probe", lambda url, timeout=30: dlq.queuer.Probe(100 * MiB, resumable)
    )
    assert dlq.queuer.main(["https://example.invalid/x.iso", "--probe"]) == 0
    said = capsys.readouterr().out
    assert "resume" in said.lower()
    assert dlq.ytq.human(100 * MiB) in said
    # The cap it *would* declare, since that is what the question is asked for.
    assert f"{dlq.queuer.expect_bytes(100 * MiB):,}" in said


def test_the_cap_is_the_measurement_plus_the_margin_ytq_uses(dlq):
    """Payload bytes are not wire bytes, and the item pays for retries."""
    size = 100 * MiB
    cap = dlq.queuer.expect_bytes(size)
    assert cap > size
    assert cap == int(-(-size * dlq.ytq.OVERHEAD_EXACT // 1)) + dlq.ytq.OVERHEAD_FIXED
    # It never shrinks with the file: a bigger file has a bigger margin.
    assert dlq.queuer.expect_bytes(2 * size) > cap


@pytest.mark.parametrize(
    ("headers", "answer"),
    [
        ({"Content-Length": "50", "Accept-Ranges": "bytes"}, (50, True)),
        ({"Content-Length": "50", "Accept-Ranges": "none"}, (50, False)),
        ({"Content-Length": "50"}, (50, None)),  # the server has not said
        ({"Accept-Ranges": "bytes"}, (0, True)),
        ({"Content-Length": "about fifty"}, (0, None)),
        ({}, (0, None)),
    ],
)
def test_what_a_head_response_is_read_as(dlq, headers, answer):
    """``None`` is "the server has not said", which is not "no"."""
    assert dlq.queuer._from_head(headers) == answer


@pytest.mark.parametrize(
    ("code", "headers", "answer"),
    [
        (206, {"Content-Range": "bytes 0-0/900"}, (900, True)),
        (206, {"Content-Range": "bytes 0-0/*"}, (0, True)),
        (206, {}, (0, True)),
        (200, {"Content-Length": "900"}, (900, False)),
        (200, {}, (0, False)),
        (416, {}, (0, None)),
    ],
)
def test_what_a_ranged_response_is_read_as(dlq, code, headers, answer):
    """A 206 proves the server honours Range and names the total after the
    slash; a 200 proves it does not, and its length is the whole file."""
    assert dlq.queuer._from_ranged(code, headers) == answer


@pytest.fixture
def probed(dlq, monkeypatch):
    """A server that states a size and honours Range, without a server."""

    def probe(url, timeout=30):
        return dlq.queuer.Probe(100 * MiB, True)

    monkeypatch.setattr(dlq.queuer, "probe", probe)
    # The shebang an item is written with is Termux's absolute python, spelled
    # literally so a run under some other interpreter cannot emit an item that
    # will not start on the phone. Which means it does not start *here*, and
    # the runner would rightly refuse it — so for the checks below it is the
    # interpreter this machine has.
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    return dlq


def test_a_url_becomes_an_item_the_runner_would_admit(probed, capsys):
    """Written through ``ytq.write_item``, which is the one door, and checked
    with the runner's own parser rather than by eye."""
    assert probed.queuer.main(["https://example.invalid/big.iso"]) == 0
    queued = list((probed.root / "queue").glob("*.py"))
    assert len(queued) == 1
    assert probed.ytq.validate(queued[0]) is None
    item = probed.runner.parse_item(queued[0])
    assert "error" not in item
    # The cap is the measurement plus a margin, never below it.
    assert item["cap"] > 100 * MiB
    assert item["partial"] is True
    assert item["dest"] == "file"
    said = capsys.readouterr().out
    assert queued[0].name.removesuffix(".py") in said
    assert "lands in" in said
    # This server resumes, so there is nothing to warn about — the warning is
    # for the server that cannot be fetched in slices at all.
    assert "warning" not in said


def test_nothing_is_queued_twice(probed, capsys):
    """Items record ``# SOURCE:`` and ``write_item`` is the one door that
    refuses a duplicate; ``dlq`` goes through it too."""
    url = "https://example.invalid/big.iso"
    assert probed.queuer.main([url]) == 0
    assert probed.queuer.main([url]) == 1
    assert len(list((probed.root / "queue").glob("*.py"))) == 1
    said = capsys.readouterr().err
    assert "--again" in said
    # Matched by its URL, which is the same file — so nothing is said about it
    # possibly being another one.
    assert "another file" not in said
    # And meaning it anyway is one flag.
    assert probed.queuer.main([url, "--again"]) == 0
    assert len(list((probed.root / "queue").glob("*.py"))) == 2


def test_a_dry_run_writes_nothing(probed, capsys):
    assert probed.queuer.main(["https://example.invalid/x.iso", "--dry-run"]) == 0
    assert list((probed.root / "queue").glob("*.py")) == []
    assert "EXPECT_BYTES" in capsys.readouterr().out


def test_a_server_that_states_no_size_needs_a_cap_to_be_given(dlq, monkeypatch, capsys):
    """"unknown" is not a valid ``EXPECT_BYTES``: the cap is the most you are
    willing to let it cost."""
    monkeypatch.setattr(dlq.queuer, "probe", lambda url, timeout=30: dlq.queuer.Probe(0, None))
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    assert dlq.queuer.main(["https://example.invalid/feed"]) == 1
    assert "--expect-bytes" in capsys.readouterr().err
    assert list((dlq.root / "queue").glob("*.py")) == []

    assert dlq.queuer.main(["https://example.invalid/feed", "--expect-bytes",
                            str(50 * MiB)]) == 0
    item = dlq.runner.parse_item(next((dlq.root / "queue").glob("*.py")))
    assert item["cap"] == 50 * MiB


def test_a_cap_below_the_measured_size_is_refused(probed, capsys):
    assert probed.queuer.main(
        ["https://example.invalid/big.iso", "--expect-bytes", "1000"]
    ) == 1
    assert "below the measured" in capsys.readouterr().err


def test_a_name_is_taken_from_the_url_and_made_safe(dlq):
    name_from_url = dlq.queuer.name_from_url
    assert name_from_url("https://x.invalid/a/b/big.iso") == "big.iso"
    spaced = name_from_url("https://x.invalid/a/b/%20big%20file.iso")
    assert spaced.endswith(".iso") and "big" in spaced and "file" in spaced
    assert name_from_url("https://x.invalid/") == "download"
    assert "/" not in name_from_url("https://x.invalid/a/../b")
    # A name that is not ASCII is still its name, not its bare suffix.
    assert name_from_url("https://x.invalid/%D0%94%D0%BE%D0%BA.pdf") == "Док.pdf"
    # A link that names no file says less than the address it led to.
    assert name_from_url(
        "https://x.invalid/latest/download", "https://cdn.invalid/v2/app-2.apk"
    ) == "app-2.apk"


#: Every character Android's shared storage refuses in a name.
REFUSED = set('/\\:*?"<>|')


@given(raw=st.text(), kind=st.sampled_from(["", "application/pdf", "text/html"]))
def test_every_name_a_file_is_given_is_one_shared_storage_takes(dlq, raw, kind):
    """``--name``, a server's name and a URL's all go through one rule: only
    what Android refuses is taken out, it fits well under 255 bytes with
    ``.part.meta.json`` on the end, and a suffix that was there is kept —
    since the suffix is all Android's opener reads a file's type from."""
    name = dlq.queuer.file_name(raw, kind)
    assert name
    assert not REFUSED & set(name)
    assert name.isprintable()
    assert len(f"{name}.part.meta.json".encode()) <= 255
    suffix = dlq.queuer._suffix(raw.strip())
    if suffix:
        assert name.endswith(f".{suffix}")


@given(stem=st.text(alphabet=st.characters(categories=["L", "N"]), min_size=1, max_size=40))
def test_a_name_that_is_already_clean_is_kept_as_it_is(dlq, stem):
    assert dlq.queuer.file_name(f"{stem}.pdf") == f"{stem}.pdf"


def _run_args(source: str) -> tuple[list, dict]:
    """What an item hands ``expire_dl.run``, read back as Python reads it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run":
            return (
                [ast.literal_eval(arg) for arg in node.args],
                {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords},
            )
    raise AssertionError("no expire_dl.run call in the item")


def _dry_run(dlq, capsys, argv: list[str]) -> str:
    capsys.readouterr()
    assert dlq.queuer.main([*argv, "--dry-run"]) == 0
    return capsys.readouterr().out


def test_a_file_is_named_by_what_its_server_says(dlq, serving, capsys):
    """The name a server gives a file (Content-Disposition, ``filename*``
    first) beats a link that says ``download?id=``; with none, its type gives
    a nameless file a suffix, which is what Android opens it by."""
    serving.payload = b"%PDF" * 100
    url = serving.url.replace("file.bin", "download?id=123")
    serving.content_type = "application/pdf"
    serving.disposition = (
        "attachment; filename=\"Report Q3.pdf\"; "
        "filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82%20Q3.pdf"
    )
    (_, name), _ = _run_args(_dry_run(dlq, capsys, [url]))
    assert name == "Отчёт Q3.pdf"

    serving.disposition = None
    (_, name), _ = _run_args(_dry_run(dlq, capsys, [url]))
    assert name.endswith(".pdf")


def test_two_files_behind_one_unhelpful_link_are_not_one_file(dlq, serving, monkeypatch):
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    serving.payload = b"x" * 1000
    for ident, called in ((1, "Report A.pdf"), (2, "Report B.pdf")):
        serving.disposition = f'attachment; filename="{called}"'
        url = serving.url.replace("file.bin", f"download?id={ident}")
        assert dlq.queuer.main([url]) == 0
    assert len(list((dlq.root / "queue").glob("*.py"))) == 2


@pytest.mark.parametrize(
    "asked", ["sub/x.iso", "Report: Q3?.pdf", 'a"""b.bin', "my\\Nfile.iso", "a" * 300 + ".iso"]
)
def test_a_name_asked_for_is_cleaned_like_any_other(probed, capsys, asked):
    """A ``/`` failed every firing after the request was paid for; a ``:``
    downloaded and could not be handed to shared storage; a name too long for
    its sidecar was downloaded, delivered, struck and downloaded again."""
    source = _dry_run(probed, capsys, ["https://example.invalid/x", "--name", asked])
    compile(source, "item", "exec")
    (_, name), _ = _run_args(source)
    assert name == probed.queuer.file_name(asked)
    assert Path_suffix(name) == Path_suffix(asked)


def Path_suffix(name: str) -> str:  # noqa: N802 - reads as what it stands for
    return name.rpartition(".")[2]


def test_a_page_is_not_queued_as_a_file(dlq, serving, monkeypatch, capsys):
    """A flag that only a file takes skips asking what the link is; the probe
    then finds a web page — a sign-in page, or a page and not a file — which
    the download would refuse at every firing. Said now, and nothing written."""
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    serving.payload = b"<html></html>"
    serving.content_type = "text/html; charset=utf-8"
    assert dlq.queuer.main([serving.url, "--name", "page.html"]) == 1
    assert "page" in capsys.readouterr().err
    assert list((dlq.root / "queue").glob("*.py")) == []
    # An HTML file sent as an attachment is a file, and is queued.
    serving.disposition = 'attachment; filename="page.html"'
    assert dlq.queuer.main([serving.url]) == 0


@pytest.mark.parametrize(
    ("kind", "disposition", "answer"),
    [
        ("text/html; charset=utf-8", None, "page"),
        ("application/xhtml+xml", None, "page"),
        ("text/html", "attachment; filename=a.html", "file"),
        ("application/zip", None, "file"),
        (None, None, "file"),
    ],
)
def test_what_a_link_is_is_what_its_server_says(dlq, serving, kind, disposition, answer):
    serving.payload = b"x" * 100
    serving.content_type, serving.disposition = kind, disposition
    assert dlq.queuer.kind_of(serving.url) == answer
    # A server that refuses HEAD is asked once more, by a ranged GET.
    serving.head_code = 405
    assert dlq.queuer.kind_of(serving.url) == answer
    assert serving.state_of_the_world["asked"] == ["bytes=0-0"]


def test_a_link_that_cannot_be_asked_is_an_error_and_not_a_guess(dlq, serving):
    with pytest.raises(dlq.queuer.ProbeError):
        dlq.queuer.kind_of("http://127.0.0.1:1/nothing", timeout=2)
    serving.head_code, serving.get_code = 405, 404
    with pytest.raises(dlq.queuer.ProbeError):
        dlq.queuer.kind_of(serving.url)


@pytest.mark.parametrize("resumable", [True, None, False])
def test_an_item_is_partial_unless_its_server_was_seen_not_to_resume(
    dlq, monkeypatch, capsys, resumable
):
    """``PARTIAL: yes`` for a server the probe saw ignore Range was a promise
    the first slice broke: downloaded, thrown away at the next request, then a
    strike. ``no`` gets it a firing that can take all of it. Unknown is not
    "no": the first firing finds out."""
    monkeypatch.setattr(
        dlq.queuer, "probe", lambda url, timeout=30: dlq.queuer.Probe(100 * MiB, resumable)
    )
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    assert dlq.queuer.main(["https://example.invalid/big.iso"]) == 0
    item = dlq.runner.parse_item(next((dlq.root / "queue").glob("*.py")))
    assert item["partial"] is (resumable is not False)


SPELLED = {
    "upper": str.upper,
    "prefixed": lambda hexed: f"SHA256:{hexed}",
    "sha256sum line": lambda hexed: f"{hexed}  big.iso",
}


@pytest.mark.parametrize("spell", SPELLED.values(), ids=SPELLED.keys())
def test_a_digest_is_written_as_hashlib_spells_it(probed, capsys, spell):
    digest = hashlib.sha256(b"big").hexdigest()
    source = _dry_run(probed, capsys, ["https://example.invalid/big.iso", "--sha256", spell(digest)])
    assert _run_args(source)[1]["expect_sha256"] == digest


@pytest.mark.parametrize(
    "wrong", [hashlib.md5(b"x").hexdigest(), "sha256:abc", "not a digest"]  # noqa: S324
)
def test_a_digest_that_is_not_one_is_refused_and_nothing_is_written(probed, wrong):
    with pytest.raises(SystemExit) as refused:
        probed.queuer.main(["https://example.invalid/big.iso", "--sha256", wrong])
    assert refused.value.code != 0
    assert list((probed.root / "queue").glob("*.py")) == []


@given(number=st.integers(-1000, 1000))
def test_anything_reported_as_queued_is_listed_and_runs(probed, number):
    """``--number`` is a place in a queue the runner sorts by *name*: 100
    would run before 20, and -1 wrote an item nothing lists or runs, reported
    as queued. Either it is a place, or it is refused and nothing is written."""
    for path in (probed.root / "queue").glob("*.py"):
        path.unlink()
    try:
        code = probed.queuer.main(["https://example.invalid/x.iso", "--number", str(number)])
    except SystemExit as refused:
        code = refused.code
    written = list((probed.root / "queue").glob("*.py"))
    if code != 0:
        assert written == []
        return
    assert len(written) == 1
    runs = [item["name"] for item in probed.runner.queued_items()[0]]
    listed = [path.name for _, path in probed.ytq.items()]
    assert runs.count(written[0].name) == 1
    assert listed.count(written[0].name) == 1


text = st.text(alphabet=st.characters(exclude_categories=["Cs"]))


@given(tail=text, name=text)
def test_any_url_and_any_name_at_all_still_write_an_item_that_parses(dlq, tail, name):
    """The docstring is a person's copy of the URL and the name, and a
    backslash in either (``\\N``, ``\\U``, ``\\x``) or a ``\"\"\"`` wrote an
    item that never compiled — reported as queued. What it runs with is
    exactly what it was given."""
    url = f"https://x.invalid/{tail}"
    source = dlq.queuer.render(url, name, 100, 10, None, "2026-10-16")
    compile(source, "item", "exec")
    assert _run_args(source)[0] == [url, name]
    if url.isprintable():
        # As the duplicate check reads it, which strips the line's end.
        assert dlq.ytq.source_of(source) == f"url:{url}".rstrip()


def test_the_item_it_writes_is_valid_python_that_names_its_source(probed):
    probed.queuer.main(["https://example.invalid/big.iso"])
    source = next((probed.root / "queue").glob("*.py")).read_text()
    compile(source, "item", "exec")
    assert "# SOURCE: url:https://example.invalid/big.iso" in source
    assert "expire_dl" in source


def test_a_probe_prints_what_it_found_and_writes_nothing(probed, capsys):
    assert probed.queuer.main(["https://example.invalid/big.iso", "--probe"]) == 0
    said = capsys.readouterr().out
    assert "resume" in said
    assert list((probed.root / "queue").glob("*.py")) == []


def test_the_number_a_new_item_gets_leaves_room_in_front_of_it(probed):
    """Ten past the highest, and never past the two digits the runner sorts by."""
    for number in range(1, 4):
        probed.queuer.main([f"https://example.invalid/file{number}.iso"])
    numbers = sorted(
        int(path.name.split("-", 1)[0]) for path in (probed.root / "queue").glob("*.py")
    )
    assert numbers == [10, 20, 30]
    assert all(number <= probed.ytq.MAX_PRIORITY for number in numbers)


def test_what_each_flag_puts_in_the_item(probed):
    """The four that change the item rather than the asking.

    Checked by reading the item back with the runner's own parser, because the
    item is the only thing that outlives the command.
    """
    assert probed.queuer.main(
        [
            "https://example.invalid/x",
            "--name",
            "chosen.iso",
            "--number",
            "42",
            "--sha256",
            "a" * 64,
            "--dest",
            str(probed.root / "elsewhere"),
        ]
    ) == 0
    path = next((probed.root / "queue").glob("*.py"))
    assert path.name.startswith("42-")
    item = probed.runner.parse_item(path)
    assert item["dest"] == str(probed.root / "elsewhere")
    source = path.read_text()
    assert "chosen.iso" in source
    assert "a" * 64 in source
    # And it is the runner that resolves where that goes, at delivery.
    assert probed.runner.dest_of(item) == probed.root / "elsewhere"


def test_a_server_that_ignores_range_is_a_warning_at_queue_time(dlq, monkeypatch, capsys):
    """The whole file has to fit one night's slice or the item fails every
    night — and the night it fails is not the night to find out."""
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    monkeypatch.setattr(
        dlq.queuer, "probe", lambda url, timeout=30: dlq.queuer.Probe(500 * MiB, False)
    )
    assert dlq.queuer.main(["https://example.invalid/big.iso"]) == 0
    said = capsys.readouterr().out
    assert "warning" in said
    assert "Range" in said


def test_an_item_the_runner_would_refuse_is_written_and_said(probed, monkeypatch, capsys):
    """Written anyway, because the bytes of a queue item are cheap and the
    fault may be one line — but the exit code and the line say so, rather than
    leaving somebody to find it out on the night it does not run."""
    monkeypatch.setattr(probed.ytq, "validate", lambda path: "no 'EXPIRE: v1' header")
    assert probed.queuer.main(["https://example.invalid/x.iso"]) == 1
    said = capsys.readouterr().out
    assert "would reject" in said
    assert "written anyway" in said
    assert list((probed.root / "queue").glob("*.py"))


def test_a_duplicate_matched_by_name_says_it_may_be_another_file(probed, capsys):
    """The two matches are not the same fact: a URL already queued is the same
    file, and a slug already queued may be a different one."""
    assert probed.queuer.main(["https://example.invalid/big.iso"]) == 0
    capsys.readouterr()
    # The same name from a different URL: matched by the slug, not the source.
    assert probed.queuer.main(["https://elsewhere.invalid/big.iso"]) == 1
    said = capsys.readouterr().err
    assert "another file" in said
    assert "--again" in said


@given(asked=st.text(alphabet=st.characters(exclude_categories=["Cs"]), min_size=1,
                     max_size=60))
def test_a_file_s_item_is_named_after_its_file_as_a_video_s_is_after_its_title(
    probed, asked
):
    """One name everywhere (design §6): the Queue tab's row is the file's own
    name, behind its number, in whatever script it is in — a slug made every
    name that is not ASCII ``video``. The item runs, is listed once, and
    downloads a file whose name begins with the row's."""
    for path in (probed.root / "queue").glob("*.py"):
        path.unlink()
    assert probed.queuer.main(["https://example.invalid/x", f"--name={asked}", "--again"]) == 0
    [path] = (probed.root / "queue").glob("*.py")
    (_, name), _ = _run_args(path.read_text(encoding="utf-8"))
    row = probed.ytq.item_slug(path.name)
    assert name.startswith(row)
    assert probed.ytq.same_name(row) == probed.ytq.same_name(probed.ytq.title_name(row))
    assert [item["name"] for item in probed.runner.queued_items()[0]] == [path.name]


def test_files_in_another_script_are_told_apart_by_name_and_not_all_video(probed, capsys):
    """Two files whose names are not ASCII were both ``NN-video.py``: the
    second was refused as the first ``by name``. By their own names they are
    two files, and the same name from another link is still caught."""
    for called in ("Отчёт.pdf", "報告.pdf"):
        assert probed.queuer.main([f"https://a.invalid/{called}"]) == 0
    rows = sorted(probed.ytq.item_slug(p.name) for p in (probed.root / "queue").glob("*.py"))
    assert rows == sorted(["Отчёт", "報告"])
    capsys.readouterr()
    assert probed.queuer.main(["https://b.invalid/%D0%9E%D1%82%D1%87%D1%91%D1%82.pdf"]) == 1
    assert "another file" in capsys.readouterr().err


def test_the_queuer_hands_on_one_spelling_of_the_link_however_it_was_called(
    dlq, monkeypatch
):
    """Run directly, or by ``expire_sched``, the queuer asks and writes the
    link as the door would: its scheme added, what is not ASCII escaped."""
    asked = []
    monkeypatch.setattr(dlq.queuer, "probe", lambda url, timeout=30:
                        asked.append(url) or dlq.queuer.Probe(100 * MiB, True))
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    assert dlq.queuer.main(["www.example.invalid/Док.iso"]) == 0
    spelled = dlq.queuer.normal_url("www.example.invalid/Док.iso")
    assert asked == [spelled] and spelled.isascii()
    source = next((dlq.root / "queue").glob("*.py")).read_text(encoding="utf-8")
    assert dlq.ytq.source_of(source) == f"url:{spelled}"
    assert _run_args(source)[0][0] == spelled


#: Text urllib refuses to read as a link at all: a port that is not a number,
#: an unclosed bracket, a bracketed host that is no address.
NOT_LINKS = ["http://127.0.0.1:abc/x.iso", "http://[::1/x.iso", "http://[abc]/x.iso"]


@pytest.mark.parametrize("url", NOT_LINKS)
def test_a_link_urllib_cannot_read_is_a_sentence_and_never_a_traceback(
    dlq, monkeypatch, capsys, url
):
    """``nibbles <url>`` says why, writes nothing and spends nothing, whichever
    door and whatever the flags — ``--expect-bytes`` included, which trusts a
    look that failed but never a link nothing could fetch."""
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    for ask in (dlq.queuer.kind_of, dlq.queuer.probe):
        with pytest.raises(dlq.queuer.ProbeError):
            ask(url, timeout=2)
    for argv in ([url], [url, "--expect-bytes", "1000000"], [url, "--name", "x.iso"]):
        capsys.readouterr()
        assert dlq.queuer.main(argv) == 1
        assert dlq.app.main(argv) == 1
        assert "error" in capsys.readouterr().err
    assert list((dlq.root / "queue").glob("*.py")) == []


def test_a_server_that_does_not_talk_http_is_a_sentence(dlq):
    """A port that answers, but not in HTTP: http.client's own exception,
    which is neither an OSError nor a URLError, is the probe's sentence."""
    import socket
    import threading

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def answer():
        for _ in range(4):
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"not http at all\r\n\r\n")

    threading.Thread(target=answer, daemon=True).start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/x.iso"
    try:
        with pytest.raises(dlq.queuer.ProbeError):
            dlq.queuer.kind_of(url, timeout=5)
        with pytest.raises(dlq.queuer.ProbeError):
            dlq.queuer.probe(url, timeout=5)
    finally:
        listener.close()


@pytest.mark.parametrize("typed", ["Movies", "./Movies", "sub/../Movies", "~/Movies"])
def test_a_destination_means_one_folder_wherever_it_was_typed(
    probed, monkeypatch, tmp_path, typed
):
    """A relative ``--dest`` was written as typed and resolved against the
    directory of whichever runner delivered it — the queue root for Run now,
    Termux's home for the nightly job — so one item landed in a different
    folder by who fetched it, and the app, looking from its own directory,
    found it gone and forgot it. Both doors and ``nibbles dest`` now write
    the one folder it meant, from where it was typed; a kind stays a kind."""
    typed_in = tmp_path / "typed-in"
    typed_in.mkdir()
    monkeypatch.chdir(typed_in)
    meant = str(Path(typed).expanduser() if typed.startswith("~")
                else (typed_in / "Movies").resolve())

    assert probed.queuer.main(["https://example.invalid/x.iso", "--dest", typed]) == 0
    item = probed.runner.parse_item(next((probed.root / "queue").glob("*.py")))
    seen = {}
    monkeypatch.setattr(probed.app, "run", lambda start, first, preloaded, now, dest:
                        seen.update(dest=dest) or [])
    monkeypatch.setattr(probed.ytq.sys.stdout, "isatty", lambda: True, raising=False)
    assert probed.ytq.main(["--dest", typed, "https://youtu.be/x"]) == 0
    ok, _ = probed.sched.set_dest("video", typed)
    assert ok
    assert item["dest"] == seen["dest"] == probed.runner.load_config()["video_dir"] == meant

    # Delivered from anywhere, it is the same folder.
    monkeypatch.chdir(tmp_path)
    assert probed.runner.dest_of(item) == Path(meant)

    for kind in probed.runner.DEST_KINDS:
        assert probed.runner.typed_dest(kind) == kind
        assert probed.ytq.main(["--dest", kind, "https://youtu.be/x"]) == 0
        assert seen["dest"] == kind


def test_a_state_file_that_will_not_parse_is_not_a_crash(dlq):
    """It is read on every listing, and a listing that raises is every screen."""
    (dlq.root / "state.json").write_text("{ not json")
    dlq.item("10-thing.py")
    assert [row["name"] for row in dlq.sched.items()] == ["10-thing.py"]
    assert dlq.runner.load_state().get("items", {}) == {}
    (dlq.root / "state.json").write_text(json.dumps(["a", "list"]))
    assert dlq.sched._state_items() == {}


# --------------------------------------------------------------------------- #
# nibbles: the one command
# --------------------------------------------------------------------------- #


def test_nibbles_is_the_only_executable_and_clashes_with_neither():
    """An old ``ytq`` or ``dlq`` install can stay on PATH beside this one."""
    import tomllib
    from pathlib import Path

    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    assert project["project"]["scripts"] == {"nibbles": "nibbles:main"}
    assert project["project"]["name"] not in ("ytq", "dlq")


def _routes(dlq, monkeypatch, kind="page", takes=None):
    """Every door ``nibbles`` can open, each answering with where it went.

    *kind* is what a server's headers would say a URL is, and *takes* what
    yt-dlp's extractors would say of a word — both asked of the network or of
    yt-dlp for real, so both stood in for here; ``dlq.kind_of`` and
    ``ytq.read_input`` have tests of their own."""
    import sys

    went = []
    monkeypatch.setattr(dlq.ytq, "main", lambda argv: went.append(("ytq", argv)) or 0)
    monkeypatch.setattr(dlq.queuer, "main", lambda argv: went.append(("file", argv)) or 0)
    monkeypatch.setattr(dlq.sched, "main", lambda argv: went.append(("queue", argv)) or 0)
    monkeypatch.setattr(dlq.app, "run", lambda tab, *a, **k: went.append(("app", tab)) or [])
    monkeypatch.setattr(dlq.queuer, "kind_of", lambda url, timeout=0: kind)
    monkeypatch.setattr(dlq.ytq, "yt_dlp_takes", lambda text, timeout=0: takes)
    monkeypatch.setitem(sys.modules, "ytq", dlq.ytq)
    monkeypatch.setitem(sys.modules, "dlq", dlq.queuer)
    monkeypatch.setitem(sys.modules, "expire_sched", dlq.sched)
    return went


def test_every_word_nibbles_takes_reaches_what_answers_it(dlq, monkeypatch):
    went = _routes(dlq, monkeypatch)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    table = [
        (["search", "crust", "of", "rust"], ("ytq", ["crust", "of", "rust"])),
        (["--list", "subs"], ("ytq", ["--subs", "--list"])),
        (["--list", "wl"], ("ytq", ["--wl", "--list"])),
        ([url], ("ytq", [url])),
        (["--now", url], ("ytq", [url, "--now"])),
        (["--list", url], ("ytq", [url, "--list"])),
        (["--list", "--from-json", "x.json"], ("ytq", ["--list", "--from-json", "x.json"])),
        (["queue"], ("queue", ["ui"])),
        (["ui"], ("queue", ["ui"])),
        (["status"], ("queue", ["status"])),
        (["--list"], ("queue", ["--list"])),
        (["now", "10-thing", "--yes"], ("queue", ["now", "10-thing", "--yes"])),
        (["run-now", "--blind"], ("queue", ["run-now", "--blind"])),
        (["settings", "window", "45"], ("queue", ["settings", "window", "45"])),
        (["ytsearch5:crust of rust"], ("ytq", ["crust", "of", "rust"])),
    ]
    for argv, where in table:
        went.clear()
        assert dlq.app.main(argv) == 0, argv
        assert went == [where], (argv, went)
    # Every queue verb has its door.
    for action in dlq.sched.ACTIONS:
        if action in ("ui",):
            continue
        went.clear()
        dlq.app.main([action])
        assert went and went[0][0] == "queue", action


def test_the_words_the_owner_took_out_open_nothing(dlq, monkeypatch):
    """``subs``, ``wl``, ``feed``, ``later``, ``files`` and ``file`` were
    words once (2026-10-10): Feed and Later are a tap away, and a URL is one
    door for a page or a file."""
    went = _routes(dlq, monkeypatch, takes=False)
    for word in ("subs", "wl", "feed", "later", "files", "file", "--subs", "--wl"):
        went.clear()
        assert dlq.app.main([word]) == 2, word
        assert went == [], (word, went)


def test_a_url_is_a_page_or_a_file_by_what_its_server_says(dlq, monkeypatch):
    url = "https://releases.example/ubuntu.iso"
    went = _routes(dlq, monkeypatch, kind="file")
    assert dlq.app.main([url, "--dest", "/tmp/x"]) == 0
    assert went == [("file", [url, "--dest", "/tmp/x"])]
    went = _routes(dlq, monkeypatch, kind="page")
    assert dlq.app.main([url]) == 0
    assert went == [("ytq", [url])]


def test_what_a_flag_says_a_url_is_is_never_asked(dlq, monkeypatch):
    """A file's own flags make it a file, a video's make it a page, and
    neither asks the server."""
    def asked(url, timeout=0):
        raise AssertionError("the server was asked")

    went = _routes(dlq, monkeypatch)
    monkeypatch.setattr(dlq.queuer, "kind_of", asked)
    url = "https://x.example/thing"
    assert dlq.app.main([url, "--name", "a.bin"]) == 0
    assert went[-1] == ("file", [url, "--name", "a.bin"])
    assert dlq.app.main(["--now", url]) == 0
    assert went[-1][0] == "ytq"


def test_a_link_without_its_scheme_is_taken_as_yt_dlp_takes_it(dlq, monkeypatch):
    went = _routes(dlq, monkeypatch, kind="file")
    assert dlq.app.main(["releases.example/ubuntu.iso"]) == 0
    assert went == [("file", ["https://releases.example/ubuntu.iso"])]


def test_what_only_yt_dlp_knows_is_a_link_reaches_the_app_as_one(dlq, monkeypatch):
    """A bare video id: no link to the eye, taken by yt-dlp's YouTube
    extractor, and handed to the app marked, since the field would search."""
    went = _routes(dlq, monkeypatch, takes=True)
    assert dlq.app.main(["dQw4w9WgXcQ"]) == 0
    assert went == [("ytq", ["--link", "dQw4w9WgXcQ"])]


def test_a_server_that_cannot_be_asked_is_an_error_and_not_a_guess(dlq, monkeypatch, capsys):
    went = _routes(dlq, monkeypatch)

    def unreachable(url, timeout=0):
        raise dlq.queuer.ProbeError("cannot reach it")

    monkeypatch.setattr(dlq.queuer, "kind_of", unreachable)
    assert dlq.app.main(["https://x.example/a"]) == 1
    assert went == [] and "cannot reach" in capsys.readouterr().err


def test_a_word_that_is_no_command_is_refused_and_spends_nothing(dlq, monkeypatch, capsys):
    """A mistyped verb must not become a search: a search spends data."""
    went = _routes(dlq, monkeypatch, takes=False)
    assert dlq.app.main(["stauts"]) == 2
    assert went == []
    assert "nibbles search stauts" in capsys.readouterr().err


def test_a_word_shaped_like_a_video_id_is_refused_and_spends_nothing(dlq, monkeypatch):
    """YouTube's extractor takes any eleven ``[A-Za-z0-9_-]`` as an id, so
    yt-dlp says yes to ``programming``: a word is still refused, and only
    something shaped like an id is handed on to be probed."""
    went = _routes(dlq, monkeypatch, takes=True)
    for word in ("programming", "documentary", "lo-fi-beats", "Photography"):
        went.clear()
        assert dlq.app.main([word]) == 2, word
        assert went == [], (word, went)
    assert dlq.app.main(["dQw4w9WgXcQ"]) == 0
    assert went == [("ytq", ["--link", "dQw4w9WgXcQ"])]


def test_yt_dlps_own_word_for_a_list_is_the_fields_and_never_a_probe(dlq, monkeypatch):
    """``:ytsubs`` and ``:ytwatchlater`` are taken by yt-dlp, and the field
    takes them for the Feed and Later tabs: handed on as the field has them,
    never marked as a link for the video sheet to probe."""
    went = _routes(dlq, monkeypatch, takes=True)
    for word in (":ytsubs", ":ytwatchlater"):
        went.clear()
        assert dlq.app.main([word]) == 0
        assert went == [("ytq", [word])], word


def test_now_and_list_are_a_videos_flags_wherever_they_stand(dlq, monkeypatch):
    """At the door ``--now`` and ``--list`` are the video's, as the usage
    says, so the order they are typed in changes nothing; a bare ``--list``
    alone is the queue's listing (in the table above)."""
    went = _routes(dlq, monkeypatch, takes=True)
    for flag in ("--now", "--list"):
        went.clear()
        assert dlq.app.main([flag, "dQw4w9WgXcQ"]) == 0
        assert went == [("ytq", ["--link", "dQw4w9WgXcQ", flag])]
        for link in ("vimeo.com/76979871", "https://vimeo.com/76979871"):
            went.clear()
            assert dlq.app.main([flag, link]) == 0
            assert dlq.app.main([link, flag]) == 0
            assert went[0] == went[1], went
            assert went[0][0] == "ytq" and flag in went[0][1]


@pytest.mark.parametrize("flag, value", [
    ("--dest", "/sdcard/Movies"),
    ("--dest", "videos.old/"),
    ("--name", "a.iso"),
    ("--number", "5"),
    ("--sha256", "ab12"),
    ("--expect-bytes", "1000"),
])
@pytest.mark.parametrize("url", ["https://x.example/thing",
                                 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
def test_a_flags_value_is_never_taken_for_the_link(dlq, monkeypatch, flag, value, url):
    """``nibbles --dest DIR URL`` (the docs' own example) goes where
    ``nibbles URL --dest DIR`` does, with the same words, in any order that
    keeps the value after its flag — and the value is never asked of yt-dlp
    or of a server as if it were the link."""
    import itertools

    went = _routes(dlq, monkeypatch, kind="file")
    asked = []
    monkeypatch.setattr(dlq.queuer, "kind_of",
                        lambda link, timeout=0: asked.append(link) or "file")
    monkeypatch.setattr(dlq.ytq, "yt_dlp_takes",
                        lambda text, timeout=0: asked.append(text) or False)
    for extra in ([], [["--now"]]):
        routes = []
        for order in itertools.permutations([[url], [flag, value], *extra]):
            went.clear()
            argv = [word for group in order for word in group]
            assert dlq.app.main(argv) == 0, argv
            assert len(went) == 1, (argv, went)
            where, handed = went[0]
            assert handed[0] == url, (argv, handed)
            routes.append((where, sorted(handed)))
        assert all(route == routes[0] for route in routes), routes
    assert not any(value in text for text in asked), asked


@settings(max_examples=40)
@given(words=st.lists(st.from_regex(r"[a-z]{1,8}", fullmatch=True), min_size=1, max_size=5),
       now=st.none() | st.integers(min_value=1, max_value=5))
def test_a_search_typed_unquoted_is_searched_in_the_order_typed(dlq, monkeypatch, words, now):
    """``nibbles ytsearch:crust of rust`` is three words to the shell; the
    field is handed them in that order, with ``--now`` wherever it fell."""
    seen = []
    monkeypatch.setattr(dlq.app, "run",
                        lambda start, first, preloaded, now, dest: seen.append((first, now))
                        or [])
    monkeypatch.setattr(dlq.app.sys.stdout, "isatty", lambda: True)
    argv = [f"ytsearch:{words[0]}", *words[1:]]
    if now is not None:
        argv.insert(min(now, len(argv)), "--now")
    assert dlq.app.main(argv) == 0
    assert seen[-1] == (" ".join(words), now is not None)


@pytest.mark.parametrize("path", ["/Документ.pdf", "/文件.iso", "/emoji-😀.bin",
                                  "/a%20b.bin", "/q.bin?name=café#part"])
def test_a_link_that_is_not_ascii_is_asked_and_queued_in_one_spelling(
    dlq, serving, monkeypatch, capsys, path
):
    """A file name in Cyrillic was a traceback from deep in http.client. The
    door hands on one spelling, escaped: the server is asked for the same
    path, and the item names its source in ASCII."""
    import urllib.parse

    serving.payload = b"x" * 1000
    url = serving.url.rsplit("/", 1)[0] + path
    monkeypatch.setattr(dlq.ytq, "SHEBANG", f"#!{sys.executable}")
    # Asked for its headers (no flag says what it is) and queued; then a
    # file's own flag, which asks the probe alone.
    assert dlq.app.main([url]) == 0
    assert len(list((dlq.root / "queue").glob("*.py"))) == 1
    assert dlq.app.main([url, "--dry-run"]) == 0
    printed = capsys.readouterr().out
    source = next(line for line in printed.splitlines() if line.startswith("# SOURCE:"))
    assert source.isascii(), source
    sent = serving.state_of_the_world["head"]
    assert sent and all(p.isascii() for p in sent), sent
    expected = urllib.parse.urlsplit(url)
    for p in sent:
        asked = urllib.parse.urlsplit(p)
        assert urllib.parse.unquote(asked.path) == urllib.parse.unquote(expected.path)


def test_a_link_without_its_scheme_has_one_whatever_its_flags_say(dlq, monkeypatch):
    """``www.`` is a link to the eye and to yt-dlp; handed to the file queue
    by its own flags it still goes on with its scheme."""
    went = _routes(dlq, monkeypatch, kind="file")
    assert dlq.app.main(["www.example.com/x.iso", "--name", "x.iso"]) == 0
    assert went == [("file", ["https://www.example.com/x.iso", "--name", "x.iso"])]
    went.clear()
    assert dlq.app.main(["youtu.be/dQw4w9WgXcQ", "--now"]) == 0
    assert went == [("ytq", ["https://youtu.be/dQw4w9WgXcQ", "--now"])]


_LINK_TEXT = st.text(
    st.characters(blacklist_categories=("Cs", "Cc", "Zs", "Zl", "Zp"),
                  blacklist_characters="%?#\\"),
    min_size=1,
)


@given(path=_LINK_TEXT, query=_LINK_TEXT)
def test_one_spelling_of_a_link_is_ascii_and_means_what_was_typed(dlq, path, query):
    import urllib.parse

    url = f"https://x.example/{path}?{query}"
    normal = dlq.queuer.normal_url(url)
    assert normal.isascii()
    assert dlq.queuer.normal_url(normal) == normal
    typed, spelled = urllib.parse.urlsplit(url), urllib.parse.urlsplit(normal)
    assert urllib.parse.unquote(spelled.path) == typed.path
    assert urllib.parse.unquote(spelled.query) == typed.query
    assert spelled.netloc == typed.netloc


@given(text=st.text(st.characters(blacklist_categories=("Cs",)), max_size=40))
def test_one_spelling_of_a_link_is_its_own_spelling(dlq, text):
    """Idempotent whatever it is handed, escapes included."""
    once = dlq.queuer.normal_url(f"https://x.example/{text}")
    assert dlq.queuer.normal_url(once) == once


def test_the_words_that_print_need_none_of_the_screens(tmp_path):
    """A stale bewitch checkout — one that predates what ``tui`` imports — is
    the app's problem, and the app's alone: every word that prints, the bug
    report among them, goes through the door without the screens' modules,
    so it answers rather than dying in an import."""
    import subprocess

    from _pty import ZWANA

    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stale = tmp_path / "stale"
    (stale / "bewitch").mkdir(parents=True)
    (stale / "bewitch" / "__init__.py").write_text("")
    program = (
        "import sys, nibbles\n"
        "for verb in sys.argv[1:]:\n"
        "    try:\n"
        "        nibbles.main([verb])\n"
        "    except SystemExit:\n"
        "        pass\n"
        "screens = ('nibbles.tui', 'nibbles.widgets', 'nibbles.shell', 'bewitch', 'blessed')\n"
        "print('LOADED', [m for m in screens if m in sys.modules], file=sys.stderr)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", program,
         "help", "status", "settings", "names", "logs", "list", "dump"],
        cwd=root, capture_output=True, text=True, timeout=120,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
             "EXPIRE_HOME": str(root), "ZWANA_HOME": str(ZWANA),
             "BEWITCH_HOME": str(stale), "COLUMNS": "40", "TERM": "dumb"},
    )
    said = done.stdout + done.stderr
    assert "Traceback" not in said, said
    assert "LOADED []" in done.stderr, done.stderr


def test_a_bare_nibbles_only_ever_opens_the_app(dlq, monkeypatch, capsys):
    """Never the status in its place (the owner, 2026-10-10): with no
    terminal there is no app, and it says so."""
    went = _routes(dlq, monkeypatch)
    monkeypatch.setattr(dlq.app.sys.stdout, "isatty", lambda: True)
    assert dlq.app.main([]) == 0
    assert went == [("app", "search")]
    went.clear()
    monkeypatch.setattr(dlq.app.sys.stdout, "isatty", lambda: False)
    assert dlq.app.main([]) == 2
    assert went == [] and "terminal" in capsys.readouterr().err


def test_help_names_every_command_it_routes(dlq, capsys):
    assert dlq.app.main(["help"]) == 0
    said = capsys.readouterr().out
    for word in ("search", "queue", "more", "URL", "status", "list", "path", "dest",
                 "settings", "run-now", "arm", "cancel", "logs", "dump", "--list"):
        assert word in said, word
    for gone in ("nibbles subs", "nibbles wl", "nibbles file", "nibbles files"):
        assert gone not in said, gone


def test_a_server_says_whether_a_url_is_a_page_or_a_file(dlq, serving):
    """``kind_of`` against a real server: HTML is a page, anything else a file,
    an attachment is a file whatever it calls itself, and a server that will
    not answer HEAD is asked by a ranged GET instead."""
    serving.payload = b"x" * 100
    for content_type, kind in (("text/html; charset=utf-8", "page"),
                               ("application/xhtml+xml", "page"),
                               ("application/octet-stream", "file"),
                               ("video/mp4", "file"),
                               (None, "file")):
        serving.content_type = content_type
        assert dlq.queuer.kind_of(serving.url) == kind, content_type
    serving.content_type, serving.disposition = "text/html", "attachment; filename=a.html"
    assert dlq.queuer.kind_of(serving.url) == "file"
    serving.disposition = None
    serving.head_code = 405
    assert dlq.queuer.kind_of(serving.url) == "page"
    assert serving.state_of_the_world["asked"] == ["bytes=0-0"]


def test_youtube_is_a_page_without_asking(dlq):
    for url in ("https://www.youtube.com/watch?v=x", "https://youtu.be/x",
                "https://m.youtube.com/shorts/x"):
        assert dlq.queuer.kind_of(url, timeout=0) == "page"
