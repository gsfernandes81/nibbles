"""How ``make mutants`` runs poodle over this repo.

Mutation testing is the suite's own check. poodle changes one operator, literal
or comparison at a time and runs the tests against it; a mutant that *survives*
is a line no test was actually asserting anything about — which is the question
coverage cannot answer, since coverage says only that a line ran.

It is a **ratchet and never a gate**. Some mutants are equivalent — the same
behaviour spelled differently — and can never be killed, and a large share of
the rest are a message reworded, which this suite declines to pin on purpose.
So ``--fail_under`` is set under the score already reached rather than at 100,
and it goes up when the score does. ``make mutants`` is deliberately outside
``make test`` and ``make check``: a push here is a deploy, and the pre-push hook
has to stay quick.

ytq and dlq were two repos until 2026-10-10, each with its own poodle setup;
this is the two merged. **It has not been run since the merge**: the scores in
CLAUDE.md are the two old repos', and the first whole run here sets the notch.

Things here that are load-bearing:

* ``source_folders = ["."]``, with ``only_files`` naming ``nibbles/…``. The
  package sits at the repo root, not under ``src/``, which is poodle's default
  and would find nothing to mutate; the doors beside it at the root are
  re-exports with nothing to mutate.
* ``file_copy_filters``. poodle copies the tree per worker; without this it
  drags in ``.venv``, ``.git``, the ``.hypothesis`` cache and — worse — the
  live ``queue/``, ``work/`` and ``state.json``, which is the runtime state of
  the real queue being handed to the run it is meant to be hidden from.
* ``ZWANA_HOME``. A worker runs the suite from inside ``.poodle-temp``, where
  there is no zwana-quota clone beside it. Set from this file's location.
* Two suites, two processes. ``tests/ytq`` and ``tests/dlq`` each own the
  environment and ``sys.modules`` for their whole session, so the command runs
  them one after the other through a shell, never as one pytest.

The curses event loops are fenced with ``# nomut: start`` / ``# nomut: end``: a
mutant inside one does not fail a test, it hangs a terminal until the timeout
kills it. What those loops do is checked under a pty instead, which is also why
the mutation run skips the ``tui`` mark — those tests are most of the suite's
wall clock and none of the code they drive is mutated.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

source_folders = ["."]

only_files = [
    "nibbles/app.py",
    "nibbles/dlq.py",
    "nibbles/expire_dl.py",
    "nibbles/expire_runner.py",
    "nibbles/expire_sched.py",
    "nibbles/expire_ui.py",
    "nibbles/home.py",
    "nibbles/queue_screens.py",
    "nibbles/shell.py",
    "nibbles/tui.py",
    "nibbles/widgets.py",
    "nibbles/ytdl_item.py",
    "nibbles/yt_screens.py",
    "nibbles/ytq.py",
]

file_filters = ["test_*.py", "*_test.py", "conftest.py", "poodle_config.py", "_pty.py",
                "termux_pty.py"]

file_copy_filters = [
    "__pycache__/**",
    "*.pyc",
    ".git/**",
    ".venv/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".hypothesis/**",
    ".poodle-temp/**",
    # The runtime state of the real queue. ``queue/README.md`` is deliberately
    # not excluded — it is the item contract, and the suites copy it into the
    # roots they build.
    "queue/*.py",
    "queue/.staging/**",
    "work/**",
    "out/**",
    "done/**",
    "failed/**",
    "logs/**",
    "state.json",
    "config.json",
    "heartbeat",
    "runner.lock",
    "*.log",
]

min_timeout = 120
timeout_multiplier = 10

#: Two workers, so the machine — and the phone this may run on — stays usable.
max_workers = 2

#: Which tests each mutant is put to: both suites minus the pty tests, unless
#: ``POODLE_TESTS`` narrows it (one module against the files that reach it is
#: the way to get an *answer*; it pairs with poodle's own ``--only``)::
#:
#:     POODLE_TESTS="tests/dlq/test_gate.py tests/dlq/test_tonight_budget.py" \
#:         uv run --group mutants poodle --only nibbles/expire_runner.py
_PYTEST = f"{sys.executable} -m pytest -x -q -p no:cacheprovider"
_NARROWED = os.environ.get("POODLE_TESTS")

runner_opts = {
    "command_line": (
        f"{_PYTEST} {_NARROWED}"
        if _NARROWED
        else (
            f"{_PYTEST} -m 'not tui' --hypothesis-profile=mutants tests/ytq && "
            f"{_PYTEST} -m 'not tui' tests/dlq"
        )
    ),
    "command_line_env": {
        "ZWANA_HOME": str(HERE.parent / "zwana-quota"),
        "BEWITCH_HOME": str(HERE.parent / "bewitch"),
    },
}
