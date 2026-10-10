#!/bin/bash
# The checks: both pytest suites, one runner, one copy.
#
#     .githooks/checks.sh        run everything
#     make check                 the same thing
#
# The pre-push hook runs this and refuses the push on a failure — a push is a
# deploy here: the phone pulls it and the nightly runner runs what landed.
#
# Offline: no network, no scheduler, no portal. Needs the zwana-quota checkout
# (beside this one or under ~), because the runner imports quota_widget from
# it the same way a real run does. Each suite builds its own queue root under a
# temporary directory and points EXPIRE_HOME and HOME at it, so nothing here
# reads or writes the queue this checkout is managing.
#
# Two suites, two pytest processes: tests/ytq and tests/dlq came from the two
# repos merged into this one on 2026-10-10, and each conftest owns the
# environment and sys.modules for its whole session.
#
# The front ends lay out to the terminal and check every line fits it down to
# 32 columns, so these fail on a long checkout path — that is the path, not a
# regression: run them from a shallow clone (~/nibbles is what they are built
# for).
#
# An empty collection is a failure, not a pass: pytest exits 5 when it finds
# no tests at all, which is what a suite deleted or broken at import looks like.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

if [ -d .venv ] && command -v uv >/dev/null 2>&1; then
    run() { uv run pytest -q "$@"; }
else
    run() { python3 -m pytest -q "$@"; }
fi

status=0
for suite in tests/ytq tests/dlq; do
    run "$suite" "$@"
    rc=$?
    if [ "$rc" -eq 5 ]; then
        echo "checks: $suite collected no tests at all — that is the failure." >&2
    fi
    [ "$rc" -ne 0 ] && status=$rc
done
exit $status
