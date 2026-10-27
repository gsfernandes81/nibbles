#!/usr/bin/env bash
# nibbles-dev's own start-up, baked into the image at /home/dev/child-init.sh and RUN by
# gsrpi-dev-base's entrypoint (its child-init seam) after it has cloned or pulled
# /workspace and before it starts sshd — bounded by the entrypoint's timeout, and
# non-fatal: a non-zero exit is printed as a warning and the container still comes up,
# because a container you can ssh into and fix beats one that refused to start. So this
# says what failed rather than swallowing it. infra's `make login C=nibbles-dev` runs it
# too, after a clone start-up could not make.
#
# Three things, each safe to repeat: the venv, the sibling checkouts beside /workspace,
# and the pre-push hook. No secrets and no ssh identities: nibbles needs neither here.
set -u

rc=0

# ── the venv ────────────────────────────────────────────────────────────────
# The locked dependencies are baked into /home/dev/venv at build time with
# --no-install-project; this adds the editable project, which needs the clone. It runs
# on every start because the venv is in the image, not on a volume.
#
# THE FLAGS MUST MATCH Dockerfile.dev's build sync, less --no-install-project. uv sync
# makes the environment exactly what it is asked for, so a start that asked for fewer
# groups would uninstall what the build put there. --frozen: exactly uv.lock, never a
# resolve, so the environment is not a function of when the container last restarted.
# bewitch stays out of it: the checkout at /bewitch is what draws, as on the phone.
if [ -f /workspace/pyproject.toml ]; then
    if (cd /workspace && uv sync --frozen --no-install-package bewitch \
            --group lint --group mutants); then
        echo "venv synced from uv.lock (dev, lint, mutants; bewitch is /bewitch)"
    else
        rc=1
        echo "uv sync FAILED — /home/dev/venv is stale or incomplete."
        echo "    The container is still up: ssh in and run the same command to see why."
    fi
else
    echo "no clone in /workspace yet — venv left as built."
    echo "    The clone needs the hub's token; 'make login C=nibbles-dev' on zero makes it."
fi

# ── the sibling checkouts ───────────────────────────────────────────────────
# The checks need bewitch (it draws every screen) and zwana-quota (the portal client the
# zwana budget is tested through) as clones beside the checkout, which here is beside
# /workspace: /bewitch and /zwana-quota, made empty and dev's in the image
# (Dockerfile.dev says why there and not under ~). They are on the container's own
# filesystem, so they survive a stop and start and are cloned afresh after a rebuild.
#
# ANONYMOUSLY, and that is the constraint: the hub's token reaches gsfernandes81/nibbles
# and nothing else, so a sibling can be cloned only while it is public. Both are, as of
# 2026-10-27. credential.helper is emptied so the token is never offered for a repo it
# does not cover, and a repo that went private fails here with a sentence instead of a
# prompt nobody can answer.
#
# Pulled --ff-only on every later start, like /workspace; a sibling with local work that
# will not fast-forward is left as it is and said so.
for name in bewitch zwana-quota; do
    dir="/$name"
    url="https://github.com/gsfernandes81/$name.git"
    if [ -d "$dir/.git" ]; then
        if out=$(GIT_TERMINAL_PROMPT=0 timeout 120 \
                git -c credential.helper= -C "$dir" pull --ff-only --quiet 2>&1); then
            echo "$dir: pulled ($(git -C "$dir" log --oneline -1 2>/dev/null))"
        else
            echo "$dir: pull skipped (not fast-forward, or offline) — left as it was"
            [ -z "$out" ] || printf '%s\n' "$out" | sed 's/^/    /'
        fi
    elif [ ! -d "$dir" ] || [ ! -w "$dir" ]; then
        rc=1
        echo "$dir is missing or not dev's — the image makes it; was this built from"
        echo "    nibbles' Dockerfile.dev? The checks will fail without $name."
    elif [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
        rc=1
        echo "$dir holds files but no checkout — not cloning $name over them."
    elif out=$(GIT_TERMINAL_PROMPT=0 timeout 120 \
            git -c credential.helper= clone --quiet "$url" "$dir" 2>&1); then
        echo "$dir: cloned $url"
    else
        rc=1
        echo "$dir: could not clone $url anonymously — the checks will fail without it."
        echo "    If $name has gone private, the hub's token (nibbles only) cannot reach it."
        [ -z "$out" ] || printf '%s\n' "$out" | sed 's/^/    /'
        # A failed clone into an existing directory can leave a partial tree behind it.
        find "$dir" -mindepth 1 -delete 2>/dev/null
    fi
done

# ── the pre-push hook ───────────────────────────────────────────────────────
# A push here is a deploy (the phone pulls main, and a version bump on main is a PyPI
# release), so pushes go through .githooks/pre-push, which runs the checks. It is armed
# once per clone; this is that, for the clone the entrypoint made.
if [ -d /workspace/.git ]; then
    if [ "$(git -C /workspace config core.hooksPath)" != .githooks ]; then
        git -C /workspace config core.hooksPath .githooks \
            && echo "pre-push hook armed (core.hooksPath .githooks)"
    fi
fi

exit "$rc"
