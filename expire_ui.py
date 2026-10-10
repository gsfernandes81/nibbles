#!/data/data/com.termux/files/usr/bin/python3
"""The queue's management screen: reorder, rename, remove, retry, run now.

``dlq ui``. The queue already had two screens and neither of them changes
anything: ``dlq status`` says what happens next, ``dlq list`` says where
everything is. What neither could do is the handful of things that come up once
an item is *in* the queue and wrong — it should go first, it is called the
wrong thing, it should not run at all, it failed three nights and deserves
another one. Those were a rename in ``queue/`` and an edit of ``state.json`` by
hand, and doing them by hand is how the bytes get lost.

Two rules run through this whole file, and both are about the bytes.

**Everything an item owns moves with it.** An item is not only the file in
``queue/``: it is also ``work/<name>/``, where a half-finished download of
several gigabytes sits, ``out/<name>/``, where a finished one waits to be
delivered, and its record in ``state.json``, which holds the attempts and where
the files went. Renaming the queue file alone leaves a paid-for partial under a
name nothing will ever look for again, and the item starts from zero on the
next night without a word. :func:`belongings` is the one place that decides
what an item owns, and every move and every removal is spelled from it.

**Nothing outside the queue's own root is ever deleted.** A delivered file sits
in Downloads among the phone's other files and belongs to whoever asked for it,
not to the queue. Removing an item deletes the item and the scratch it was
downloading into; anything finished in ``out/`` is kept, and the screen says
where it stayed.

A third rule is about *when*: **while the queue is busy nothing may be
changed.** A firing or a ``dlq now`` writes into ``work/<name>/`` and hands
the item to ``done/`` when it completes, so moving either underneath it loses
the download or breaks the archive. Every mutating function starts at
:func:`busy_problem`, which is checked rather than assumed — the guard lives
with the mutation and not with the screen, so it cannot be skipped by a caller.

Where the actions live is itself a safety rule: **the list picks and the item
screen acts.** Every key that changes something is on a screen showing one item
and nothing else, so the item being removed is the one that is on the screen.
It also buys the room to spell each action out in words, which is what makes
this readable at 32 columns where a row of hint keys would not be.

**The listing is the whole queue.** There was a second screen above it — the
status, the job, the destinations, the settings and the key that ran the lot —
and it is gone: what tonight would do is two header lines on the listing
itself, ``n``, ``s`` and ``l`` are on the listing, and the destinations and the
nightly job are rows on the settings page. What replaces the paragraph of
figures is one line drawn *through the queued group*, after the last download
tonight's budget reaches. **That line is computed and is never an item**: it
has no name, no record and no place in the order, the cursor steps over it, and
it is worked out afresh on every draw from whatever order the items are in —
including an order that exists nowhere but under a held item. It is
:func:`expire_runner.plan` over :func:`expire_runner.admit`, which is the same
rule ``fire()`` admits items by, so the screen cannot promise bytes the night
then refuses. Moving an item across the line moves the line; it never moves the
budget.

Layout follows the rest of the queue: Termux in portrait is about 40 columns,
every line of every screen must fit down to 32, and the key hints
are the line that must never be the one clipped — they are the way out.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import expire_sched as sched  # noqa: E402  (sibling module, path fixed up above)
import ytq  # noqa: E402  (beside this file, path fixed up above)
import contextlib

#: What a row says is said the same way ``dlq list`` says it, by calling the
#: same functions rather than by respelling them: the state, the progress, the
#: colour it is worth and the name with its extension dropped. This screen owns
#: only the *arrangement*, which differs because a cursor needs rows of a fixed
#: height that can be reversed whole — ``compose_list``'s tight shape separates
#: downloads with blank lines, and a blank line cannot be highlighted.
_display_name = sched._display_name
_state_of = sched._state_of
_progress_of = sched._progress_of
_tone = sched._tone
_fit = ytq.fit
_wrap = sched._wrap

#: The width at which the description column and the long labels fit. Shared
#: with the other two screens so that one terminal does not get two answers
#: about whether it is wide.
WIDE = sched.WIDE


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #

#: An item's file name in full: the priority, a dash, a slug, ``.py``. Stricter
#: than the runner's :data:`expire_runner.ITEM_RE`, which only has to recognise
#: an item; this one has to *make* one, and a name this does not match is a
#: file the runner would ignore for ever without saying so.
NAME_RE = re.compile(r"^(\d{2,})-([^/\\]+)\.py$")


def parse_name(name: str) -> tuple[int, str] | None:
    """``(priority, slug)``, or ``None`` if that is not an item's name."""
    found = NAME_RE.match(name)
    if not found:
        return None
    return int(found.group(1)), found.group(2)


def _slug_of(name: str) -> str:
    """An item's name as this screen shows it: the slug, with no number on it.

    The number *is* the run order, and the list already shows the order by
    being a list. Printing it as well asks someone to read the same fact twice,
    in the harder of the two spellings — and it invites thinking in numbers,
    which is the thing this screen exists to stop: you move a download by
    picking it up and putting it where you want it, not by working out what
    integer lives between two others.

    Nothing needs it typed back any more either. ``dlq now`` and ``dlq open``
    are gone from the command line, and ``dlq path`` takes any unambiguous
    part of a name, which a slug is.
    """
    parsed = parse_name(name)
    return parsed[1] if parsed else _display_name(name)


def _ordinal(number: int) -> str:
    """``1st``, ``2nd``, ``3rd``… — a position said the way a person says it."""
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def renumber(name: str, number: int) -> str:
    """The same item at a different priority — **the slug untouched**.

    Not spelled through :func:`ytq.slugify`, which is right for something a
    person typed and wrong here: it truncates at 42 characters, so putting a
    long-titled item first would silently shorten its name as well as move it,
    and the name is what ``dlq now`` is given.
    """
    _, slug = parse_name(name) or (0, name)
    return f"{max(0, min(99999, number)):02d}-{slug}.py"


def reslug(name: str, text: str) -> str:
    """The same item under a new name, at the priority it already has.

    Through :func:`ytq.slugify`, because this half *was* typed by a person and
    the rule for what an item may be called is ytq's — one spelling of it, or
    the two front ends produce names that sort against each other differently.
    """
    number, _ = parse_name(name) or (0, "")
    return f"{number:02d}-{ytq.slugify(text)}.py"


# --------------------------------------------------------------------------- #
# What an item owns
# --------------------------------------------------------------------------- #


def belongings(row: dict) -> list[tuple[str, Path]]:
    """Every path this item owns, as ``(what it is, where it is)``.

    The one place that decides what an item is on disk, because every mutation
    below is spelled from it and the failure it prevents is silent: bytes
    already paid for, left under a name nothing will look for again.

    Three of the four things an item owns are here — the item file itself, the
    scratch directory it downloads into, and the outbox it delivers into. The
    fourth is its record in ``state.json``, which is not a path; it is keyed by
    the item's name and is moved by :func:`_move_record` alongside these.

    Its logs are deliberately *not* here. ``logs/<date>-<name>.log`` is the
    record of what happened on a particular night, and the runner's own log
    names the item in prose that cannot be rewritten anyway — so a rename is
    noted in that log instead, and the trail stays readable from both ends.
    """
    found = [("item", row["path"])]
    for what, root in (("work", sched.WORK), ("out", sched.OUT)):
        path = root / row["name"]
        if path.exists():
            found.append((what, path))
    return found


def rename_moves(row: dict, new_name: str) -> list[tuple[Path, Path]]:
    """Where each of the item's belongings goes when it is called *new_name*.

    One line, and that is the point of :func:`belongings`: everything an item
    owns is named after it and stays where it is, so a rename is the same
    rename applied to each. The item file keeps its directory too, which is
    what makes this safe to run on a failed or an archived item — a rename
    never changes which state something is in.
    """
    return [(path, path.with_name(new_name)) for _, path in belongings(row)]


def removal(row: dict, bytes_too: bool = False) -> tuple[list[Path], list[Path]]:
    """``(what a removal deletes, what it leaves behind)``.

    Removing a download from the list is a decision about the *list*. By
    default it costs nothing that was paid for: the item file goes, and the
    bytes stay exactly where they are — the partial in ``work/<name>/`` and
    anything finished in ``out/<name>/``, which the runner could not hand over
    because the destination was unreachable or the item declared none.

    *bytes_too* is the second, explicit answer, offered on the same screen and
    never the default: it also deletes the partial, which is the only thing
    here it is safe to delete, because nothing but this item could ever have
    resumed it. **A finished file in** ``out/`` **is never deleted either
    way** — it is complete and already bought, and deciding to throw one away
    is not a tool's call.

    Nothing outside the queue root is ever in the first list, which a test
    must pin: an item's delivered file is in Downloads, and it is the
    property of whoever asked for it rather than of the queue.
    """
    goes = [row["path"]]
    kept: list[Path] = []
    work = sched.WORK / row["name"]
    if work.exists():
        # Scratch holding no payload was never paid for — an item that failed
        # before moving a byte still leaves the status file the runner writes —
        # so there is nothing there to keep and it goes either way. Keeping it
        # would leave a directory nothing lists and nothing will ever resume.
        (goes if bytes_too or not row["have"] else kept).append(work)
    out = sched.OUT / row["name"]
    with contextlib.suppress(OSError):
        kept += sorted(path for path in out.iterdir() if path.is_file())
    return goes, kept


# --------------------------------------------------------------------------- #
# The order
# --------------------------------------------------------------------------- #


def slot(others: list[int], pos: int) -> int | None:
    """A priority that puts an item at *pos* among items keyed *others*.

    ``None`` when there is no room — two neighbours one apart, or a queue that
    has run out of two-digit keys at the end. That is not a failure, it is the
    signal to hand out fresh keys to everything (:func:`spread`), and it is
    rare: items arrive ten apart and each insertion only halves one gap.

    Every answer stays inside ``00``–``99`` on purpose. The runner sorts by
    file name, so a three-digit key sorts *before* a two-digit one and an item
    moved to the back would arrive at the front — see :data:`ytq.MAX_PRIORITY`.
    """
    before = others[pos - 1] if pos > 0 else None
    after = others[pos] if pos < len(others) else None
    if before is None and after is None:
        return 10
    if before is None:
        # Half of whatever is at the top rather than ten below it: this is the
        # end of the queue that runs out first, and halving leaves room on both
        # sides of the new head instead of all of it above.
        return after // 2 if after >= 1 else None
    if after is None:
        return before + 10 if before + 10 <= ytq.MAX_PRIORITY else None
    return (before + after) // 2 if after - before >= 2 else None


def spread(count: int) -> list[int]:
    """Fresh keys for *count* items, evenly spaced through the two digits.

    Wide gaps while the queue is short, so the next few moves are single
    renames again; narrowing as it grows, because the alternative to a tight
    gap is a key that does not fit in two digits, and that one is not a
    cosmetic problem.
    """
    step = max(1, (ytq.MAX_PRIORITY - 9) // (count + 1))
    return [step * (index + 1) for index in range(count)]


def _rename_bare(name: str, new_name: str) -> str | None:
    """Move a queued item and its belongings, with no log line and no verdict.

    The half of :func:`do_rename` that reordering needs: a reorder is one
    action however many files it has to touch, so the note and the sentence
    belong to the reorder rather than to each rename inside it.
    """
    row = {"name": name, "path": sched.QUEUE / name}
    failure = _apply(rename_moves(row, new_name))
    if failure:
        return failure
    _move_record(name, new_name)
    return None


def _free_key(taken: set[int]) -> int | None:
    """The lowest two-digit key nobody is using or about to use."""
    for key in range(ytq.MAX_PRIORITY + 1):
        if key not in taken:
            return key
    return None


def _reindex(order: list[str]) -> str | None:
    """Give every queued item a fresh key, in this order. A failure, or ``None``.

    The renames are done in whatever order does not collide, which is not
    necessarily the order asked for: an item whose new key is another item's
    current one has to wait for that one to move. When *every* remaining move
    is blocked — a cycle, which a plain swap of two neighbours already is — one
    item is parked on a key nobody wants and the rest unwind behind it.

    The parking key is a **real priority**, not a temporary name, so that at no
    instant does an item stop looking like an item. A firing that starts in the
    middle of this reads a queue that is complete and legal, possibly in an
    order nobody asked for; the alternative — parking on a dotfile — is a queue
    with downloads missing from it, which is the one thing that must never
    happen quietly.
    """
    if len(order) > ytq.MAX_PRIORITY:
        return f"more than {ytq.MAX_PRIORITY} downloads is more than there is room for"
    wanted = {
        name: renumber(name, key)
        for name, key in zip(order, spread(len(order)), strict=True)
    }
    pending = {old: new for old, new in wanted.items() if old != new}
    # Every key that must not be parked on: one an item already answers to, and
    # one something is about to.
    spoken = {parse_name(name)[0] for name in wanted} | {
        parse_name(name)[0] for name in wanted.values()
    }
    guard = 2 * len(wanted) + 4
    while pending:
        guard -= 1
        if guard < 0:  # pragma: no cover - the loop is finite by construction
            return "the order would not settle; nothing else was changed"
        free = [old for old, new in pending.items() if not (sched.QUEUE / new).exists()]
        if not free:
            old = next(iter(pending))
            key = _free_key(spoken)
            if key is None:
                return "no room to reorder; remove something first"
            spoken.add(key)
            parked = renumber(old, key)
            failure = _rename_bare(old, parked)
            if failure:
                return failure
            pending[parked] = pending.pop(old)
            continue
        for old in free:
            failure = _rename_bare(old, pending.pop(old))
            if failure:
                return failure
    return None


def landed_index(rows: list[dict], pos: int) -> int | None:
    """Where the cursor lands after a drop: the row at queued position *pos*.

    By position and never by name, because :func:`do_reorder` *renamed* the
    item — its number is its place — so the name that was picked up finds
    nothing in the re-read list. The drop's whole meaning is "put it at
    *pos* among the queued", so the row now at that position is the one that
    moved, whatever it is called now.
    """
    queued = [index for index, row in enumerate(rows) if row["where"] == "queued"]
    if not queued:
        return None
    return queued[max(0, min(pos, len(queued) - 1))]


def do_reorder(rows: list[dict], name: str, pos: int) -> tuple[str, bool]:
    """Put the queued item *name* at position *pos*: ``(what to say, moved)``.

    One rename when there is room between its new neighbours, and a fresh set
    of keys for the whole queue when there is not. Both are the same action to
    whoever asked for it, which is why neither of them says a number back.
    """
    problem = busy_problem()
    if problem:
        return problem, False
    queued = [row["name"] for row in rows if row["where"] == "queued"]
    if name not in queued:
        return "only a queued download has a place in the order", False
    others = [item for item in queued if item != name]
    pos = max(0, min(pos, len(others)))
    if others[:pos] + [name] + others[pos:] == queued:
        return "left where it was", False
    keys = [parse_name(item)[0] for item in others]
    key = slot(keys, pos)
    target = renumber(name, key) if key is not None else ""
    if target and not (sched.QUEUE / target).exists():
        failure = _rename_bare(name, target)
    else:
        failure = _reindex(others[:pos] + [name] + others[pos:])
    if failure:
        return failure, False
    _note(f"moved {name} to {pos + 1} of {len(queued)}")
    return f"{_slug_of(name)} is {_ordinal(pos + 1)} of {len(queued)}", True


# --------------------------------------------------------------------------- #
# Changing something
# --------------------------------------------------------------------------- #


def busy_problem() -> str | None:
    """Why nothing may be changed at this moment, or ``None``.

    Called first by every mutating function in this module rather than by the
    screens that call them, so that the guard cannot be skipped by a caller who
    did not know it was needed. What it guards is not subtle: a firing or a
    ``dlq now`` is writing into ``work/<name>/`` and will rename the item into
    ``done/`` when it finishes, and moving either underneath it loses the
    download or leaves the archive step renaming a file that is not there.

    :func:`ytq.queue_busy` and not the freshness of a progress file, because
    this is the question the *runner* answers with the lock, and a mutation is
    one of the two things (the other is ``dlq now``) that is entitled to take
    it. The read-only screens use the progress file precisely because they are
    not entitled to.
    """
    if ytq.queue_busy():
        return "the queue is busy — a firing or a download holds it"
    return None


def _taken(new_name: str) -> str | None:
    """Why *new_name* cannot be used, or ``None``.

    Both halves matter. Another item already answering to the name is the
    obvious one. The other is a ``work/`` or ``out/`` directory left behind by
    an item that was removed while its finished files were kept: renaming onto
    it would mix two downloads' bytes into one directory, and the item would
    deliver a file it never downloaded.
    """
    for where, path in sched._paths():
        if path.name == new_name:
            return f"{where} already has a {_display_name(new_name)}"
    for root in (sched.WORK, sched.OUT):
        if (root / new_name).exists():
            return f"{root.name}/{_display_name(new_name)} still has bytes in it"
    return None


def refuse_rename(row: dict, new_name: str) -> str | None:
    """Why this rename must not happen, or ``None``. Says it in one line."""
    problem = busy_problem()
    if problem:
        return problem
    if new_name == row["name"]:
        return "that is the name it has"
    if not NAME_RE.match(new_name):
        return "a name is a number, a dash, a slug and .py"
    return _taken(new_name)


def _apply(moves: list[tuple[Path, Path]]) -> str | None:
    """Do every move, or undo the ones already done and say what stopped it.

    Each move is a rename within the queue root, so each is atomic and none of
    them can half-copy a gigabyte. The set of them is not atomic, which is what
    the rollback is for: an item whose scratch moved and whose item file did
    not is an item that will silently download itself again.

    A rollback that itself fails is the one case nothing can fix, so it is
    written to the runner's log naming both paths — that log is then the only
    record of where the bytes went, and it is the file the next person reads.
    """
    done: list[tuple[Path, Path]] = []
    for source, target in moves:
        try:
            source.rename(target)
        except OSError as exc:
            for was, now in reversed(done):
                try:
                    now.rename(was)
                except OSError:
                    _note(f"ROLLBACK FAILED: {now} should be {was}")
            return f"could not move {source.name}: {exc.strerror or exc}"
        done.append((source, target))
    return None


def _note(message: str) -> None:
    """Append to the runner's own log, without printing it.

    :func:`expire_runner.log` echoes every line to stdout so that a manual run
    shows its reasoning; inside the app that is a line drawn onto a screen this
    module does not own, and one that no redraw will clear. Same file, same
    stamp, same reader.

    Management actions belong in that log and not in a second one: what
    happened to an item is one story, and "it failed twice and then somebody
    renamed it" only reads as a story if both halves are in the same file.
    """
    try:
        line = f"{sched._runner().stamp()}  ui: {message}"
        sched.LOGS.mkdir(parents=True, exist_ok=True)
        with (sched.LOGS / "runner.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - a record, never a blocker
        pass


def _record(name: str) -> tuple[object, dict, dict]:
    """``(runner, whole state, this item's record)``, creating neither."""
    runner = sched._runner()
    state = runner.load_state()
    items = state.get("items") or {}
    return runner, state, items.get(name) or {}


def _move_record(old: str, new: str) -> None:
    """Carry the item's history over to its new name.

    The attempts, the bytes spent and — for a finished item — the paths its
    files were delivered to. Dropping it would cost ``dlq path`` the only
    answer it has: once a file is in a folder shared with every other app on
    the phone, nothing can work out which one was ours by looking.
    """
    runner, state, _ = _record(old)
    items = state.get("items") or {}
    if old not in items:
        return
    items[new] = items.pop(old)
    state["items"] = items
    runner.save_state(state)


def _edit_record(name: str, changes: dict, drop: tuple[str, ...] = ()) -> None:
    """Set and unset fields of one item's record, leaving the rest alone."""
    runner, state, _ = _record(name)
    items = state.setdefault("items", {})
    record = items.setdefault(name, {})
    record.update(changes)
    for key in drop:
        record.pop(key, None)
    runner.save_state(state)


def do_rename(row: dict, new_name: str) -> str:
    """Rename the item and everything it owns. Returns what to say about it."""
    problem = refuse_rename(row, new_name)
    if problem:
        return problem
    failure = _apply(rename_moves(row, new_name))
    if failure:
        return failure
    _move_record(row["name"], new_name)
    _note(f"renamed {row['name']} -> {new_name}")
    return f"now {_display_name(new_name)}"


def do_remove(row: dict, bytes_too: bool = False, why: str = "removed") -> str:
    """Take the item off the list, keeping every byte unless told otherwise."""
    problem = busy_problem()
    if problem:
        return problem
    goes, kept = removal(row, bytes_too)
    for path in goes:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            return f"could not remove {path.name}: {exc.strerror or exc}"
    runner, state, _ = _record(row["name"])
    if (state.get("items") or {}).pop(row["name"], None) is not None:
        runner.save_state(state)
    if not kept:
        # Only when it is empty: an out/ directory with files in it is the
        # reason those files still exist.
        with contextlib.suppress(OSError):
            (sched.OUT / row["name"]).rmdir()
    bytes_said = (
        f"{ytq.human(row['have'])} {'deleted' if bytes_too else 'kept'}"
        if row["have"]
        else ""
    )
    _note(
        f"{why} {row['name']}"
        + (f" — {bytes_said}" if bytes_said else "")
        + (f", {len(kept)} left in out/" if kept else "")
    )
    # Short on purpose: the flash line is clipped rather than wrapped, so what
    # happened to the bytes goes first and is the half that survives it.
    left = [path for path in kept if path.is_file()]
    parts = ([bytes_said] if bytes_said else []) + (
        [f"{len(left)} kept in out/"] if left else []
    )
    said = f"removed {_slug_of(row['name'])}"
    return f"{said}; {', '.join(parts)}" if parts else said


def forget_gone(rows: list[dict]) -> list[str]:
    """Drop finished downloads whose delivered file has been deleted.

    The queue keeps a done item for one reason: it is the only record of where
    the file went, since a shared Downloads folder cannot be searched for
    "mine". Once the file is not there, the record answers a question nobody
    can ask any more, and leaving it costs a row in every listing that looks
    like work outstanding.

    Two conditions, and both are evidence rather than inference. The folder has
    to be *readable* — :func:`expire_sched._readable` lists it, so a permission
    that was never granted or a card that is out reads as ``away`` and is left
    alone, which is the whole reason this can be automatic at all. And the item
    has to have recorded where it was delivered: with no record there is
    nothing to have looked in, and absence of evidence is not the same fact.

    Never touches the file itself, and never runs while the queue is busy.
    """
    if busy_problem():
        return []
    forgotten = []
    for row in rows:
        if row["where"] != "done" or row.get("lost") != "gone" or not row["recorded"]:
            continue
        folder = row["recorded"][0].parent
        said = do_remove(row, why=f"forgot (nothing of it left in {folder})")
        if said.startswith("removed"):
            forgotten.append(_slug_of(row["name"]))
    return forgotten


def do_requeue(row: dict) -> str:
    """Put a failed item back in the queue, with its attempts wiped.

    The wipe is not a courtesy: an item is set aside once its attempts reach
    ``MAX_ATTEMPTS``, so one put back with them still on the clock is given up
    on again by the first firing that touches it — a retry that retries
    nothing. What is deliberately kept is ``work/<name>/``, so the retry
    resumes from whatever the three failed nights did manage to buy.
    """
    problem = busy_problem()
    if problem:
        return problem
    if row["where"] != "failed":
        return f"it is in {row['where']}, not failed"
    # Not :func:`_taken`, which would find this very item sitting in failed/.
    # The one collision that matters here is a queued item of the same name.
    if (sched.QUEUE / row["name"]).exists():
        return f"the queue already has a {_display_name(row['name'])}"
    failure = _apply([(row["path"], sched.QUEUE / row["name"])])
    if failure:
        return failure
    _edit_record(row["name"], {"attempts": 0, "stalls": 0}, drop=("retired",))
    _note(f"put {row['name']} back in the queue, attempts cleared")
    return f"{_display_name(row['name'])} is queued again"


def do_clear_tries(row: dict) -> str:
    """Give a queued item its three nights back."""
    problem = busy_problem()
    if problem:
        return problem
    if not row["attempts"]:
        return "it has no failed tries"
    _edit_record(row["name"], {"attempts": 0, "stalls": 0})
    _note(f"cleared {row['attempts']} failed tries on {row['name']}")
    return f"{row['attempts']} failed tries cleared"


# --------------------------------------------------------------------------- #
# What may be done to one item
# --------------------------------------------------------------------------- #


def actions_for(row: dict) -> list[tuple[str, str]]:
    """The keys this item offers, in the order they are worth offering.

    By state, and only the ones that mean something: an archived download has
    no priority to change and a rejected one cannot be told to run. What is
    *not* filtered here is anything that depends on the moment rather than on
    the item — the lock, mostly — because an action that quietly vanishes
    between one look and the next reads as a bug. Those are offered and then
    explained when they are pressed.
    """
    where = row["where"]
    offered: list[tuple[str, str]] = []
    if where == "queued" and not row["error"] and row["cap"] > row["have"]:
        offered.append(("n", "download it now"))
    if where == "failed":
        offered.append(("u", "put it back in the queue"))
    if where == "queued":
        offered.append(("m", "move it in the queue"))
    if where in ("queued", "failed"):
        offered.append(("r", "rename"))
    if where == "queued" and row["attempts"]:
        offered.append(("t", f"clear {row['attempts']} failed tries"))
    if row["files"]:
        offered.append(("o", "open the file"))
    offered.append(("l", "its log"))
    offered.append(("d", "remove from the list" if where == "done" else "remove"))
    return offered


# --------------------------------------------------------------------------- #
# What the next window would download
# --------------------------------------------------------------------------- #

#: The screens' word for each of :data:`expire_sched.VERDICTS` — **one word per
#: verdict, at every width**, and none of them "tonight": the window is named
#: by when it opens on the phone's clock (design §6). A test must pin an entry
#: for every verdict, because one the gate grew and this did not would draw a
#: blank where the answer goes.
VERDICT_WORDS = {
    "downloading": "downloading",
    "go": "window open",
    "early": "waiting",
    "late": "done",
    "empty": "nothing queued",
    "unset": "no allowance set",
    "off": "auto is off",
    "spent": "nothing to spend",
    "blind": "no portal",
    "no-portal": "zwana not answering",
    "stale": "stale reading",
}


def tonight_plan(order: list[str], facts: dict | None) -> list[dict]:
    """What each queued item would get tonight, in the order it is given.

    :func:`expire_runner.plan` and nothing else — **the runner's own
    projection, over the runner's own budget**. That is the whole safety of the
    cut line: the rule that decides which items the night reaches is
    :func:`expire_runner.admit`, the same function ``fire()`` calls at
    midnight, so a line drawn here cannot promise bytes the night then refuses.
    A second copy of the arithmetic would be a screen committing more than the
    queue will spend, which is the one thing this exists to prevent.

    The order is the screen's, which is the point: the items are handed over in
    whatever order they are on the screen — including an order that exists
    nowhere but under a held item — and what comes back is what *that* order
    would download. The budget is not the screen's to change.

    An item the reading does not know about — queued since it was taken — is
    not in the projection at all, and so gets nothing tonight until the next
    reading. Saying anything else would be inventing a cap for it.

    No ``state.json`` is passed: a snapshot's items carry their own
    ``part_bytes``, which is the only thing :func:`plan` reads a state for.
    """
    if not facts:
        return []
    known = {item["name"]: item for item in facts["items"]}
    return sched._runner().plan(
        [known[name] for name in order if name in known],
        {},
        facts["spendable"],
        facts["bps"],
        facts["night_seconds"],
        facts["blind"],
        facts["free_disk"],
    )


def _nothing_to_spend(facts: dict) -> str:
    """Why tonight has no budget at all — the answer above every item's own.

    Three ways for the budget to be nought with the night otherwise willing,
    and they are not the same thing to do something about: a portal that did
    not answer is the phone being off the vessel's wifi, a stale reading is
    one that answered with yesterday's figures, and a reading with nothing
    spendable in it is a night where the allowance is genuinely gone. Only the
    last of them is about the data.
    """
    if facts["portal"] is None:
        return "no portal reading"
    if not sched._runner().usable(facts["portal"]):
        return "reading is stale"
    return "no data to spend"


def cut_index(
    order: list[str],
    facts: dict | None,
    planned: list[dict] | None = None,
) -> tuple[int | None, str]:
    """``(how many queued items the window reaches, what the line says)``.

    The cut line, and it is **computed rather than an item**: it has no name,
    no record and no place in the order — it is worked out afresh from wherever
    the items are, every draw, including live from a preview order while one of
    them is being held. Nothing about it can be picked up, dropped, renamed or
    removed, which is why the cursor never stops on it.

    The count is the position after the last item that gets any bytes, so what
    the line means is exactly "nothing below this gets anything tonight". That
    is not always the same as counting the items that got something: an item
    can be passed over for a reason of its own — too big for what is left, no
    disk — while a smaller one behind it still runs, and drawing the line by
    the count would put an item that downloads below a line saying it does not.

    ``None`` when there is no reading yet: an honest listing with no line is
    better than a line drawn from figures nobody has.

    When nothing gets anything the line goes to the top of the queued group and
    says why, which is the only place the answer can be — and the answer is
    taken from as far up as it goes. A verdict that stops the whole night is
    quoted in the status screen's own words; a night with no budget at all says
    why there is none (:func:`_nothing_to_spend`), because with nothing to
    spend every item is refused and the first refusal would blame the item for
    it; only where there is a budget and the items still do not fit is an
    item's own refusal the answer, which is :func:`expire_runner.admit`
    explaining itself in the same sentence it would log.
    """
    if not facts or not order:
        return None, ""
    # *planned* is :func:`tonight_plan` on this same *order*, handed in by the
    # one caller that also needs it for the rows — the projection is asked for
    # once per draw and both the line and the rows are drawn from that one
    # answer, so a row cannot say a download gets bytes on a night the line
    # below it says it does not. Left out, it is asked for here.
    if planned is None:
        planned = tonight_plan(order, facts)
    got = {entry["name"]: entry["bytes"] for entry in planned}
    last = -1
    for position, name in enumerate(order):
        if got.get(name, 0):
            last = position
    if last >= 0:
        total = ytq.human(sum(got.values()))
        return last + 1, f"the window ends here · {total}"
    verdict = facts["verdict"]
    if verdict not in (*sched._runner().GATE_GO, "early"):
        why = VERDICT_WORDS.get(verdict, facts["detail"])
    elif facts["spendable"] <= 0 and not facts["blind"]:
        # Why there is nothing to spend comes *before* any item's own refusal.
        # With a budget of nought every item is turned down for being bigger
        # than nothing, and the first of those refusals reads as a fact about
        # that item — "slice 0 B below the useful minimum 32 MiB" — on a night
        # whose actual answer is that no reading arrived. The item is not the
        # reason; the missing budget is, and this says which kind it is.
        why = _nothing_to_spend(facts)
    else:
        # A night that downloads, with something to spend on it: the answer
        # really is about the items, so it is the runner's own first refusal,
        # word for word, less the working in brackets — "(budget 0 B, 3122s
        # left)" — which is the half worth losing on a phone.
        why = next(
            (entry["reason"] for entry in planned if entry["reason"]),
            "nothing fits",
        ).split(" (")[0]
    return 0, f"nothing in the window · {why}"


def _tonight_share(row: dict, planned: int, at: str = "the window") -> str:
    """``46 MiB at 03:00`` for a download the window reaches only part of.

    The one row where the cut line is not the whole answer: the item that
    straddles it. A resumable download is handed whatever is left of the budget
    when the projection reaches it — 46 MiB of a 210 MiB item — and it sits
    *above* the line, correctly, because it does get bytes tonight; but the row
    read exactly like the two above it, which finish. This is the figure that
    says how much of it tonight actually buys.

    Nothing for an item the night finishes, and nothing for one it never
    reaches: on most rows the figure would only be the progress cell's own
    number said twice, and the one row where it is news would be lost in them.
    """
    if planned <= 0:
        return ""
    need = max(0, row.get("cap", 0) - row.get("have", 0))
    if planned >= need:
        return ""
    return f"{ytq.human(planned)} at {at}"


def preview(rows: list[dict], name: str, pos: int) -> list[dict]:
    """*rows* with the queued download *name* shown at position *pos*.

    Nothing is renamed until it is dropped: moving is done on a copy of the
    list, so ↑ and ↓ cost nothing and a move that is thought better of costs
    nothing either. It is also the only honest way to show it — the row has to
    be where it is going to be, not where it is.
    """
    queued = [row for row in rows if row["where"] == "queued"]
    rest = [row for row in rows if row["where"] != "queued"]
    moved = [row for row in queued if row["name"] == name]
    others = [row for row in queued if row["name"] != name]
    pos = max(0, min(pos, len(others)))
    return others[:pos] + moved + others[pos:] + rest


# --------------------------------------------------------------------------- #
# An item's log
# --------------------------------------------------------------------------- #


def item_log(name: str) -> Path | None:
    """The newest log this item wrote, or ``None``.

    Both spellings are matched: the runner writes ``<date>-<item>.log`` and a
    ``dlq now`` writes ``<date>-now-<item>.log``.
    """
    try:
        found = sorted(sched.LOGS.glob(f"*-{name}.log"))
    except OSError:
        return None
    return found[-1] if found else None


# --------------------------------------------------------------------------- #
# The reading, the job, and the whole-queue run
# --------------------------------------------------------------------------- #


def tonight_facts(force: bool = False, blind: bool = False) -> dict:
    """What the runner says about tonight — its snapshot, straight across.

    One door, so that everything on this screen that talks about tonight — the
    two header lines, the cut line, the figure the run-now confirm names — is
    reading one set of figures taken at one moment. This screen decides nothing
    about the queue; it draws what the runner would do and offers the keys that
    change it.
    """
    return sched._runner().snapshot(force=force, blind=blind)


def armed(job: list[tuple[str, str, str]]) -> bool:
    """Whether the nightly job is registered, according to *job*.

    Read off :func:`expire_sched.job_rows`, which is what the status screen
    prints, so the screen and the key cannot disagree about it. The word is
    pinned at both ends by a test: spelled differently, this screen
    would offer "arm it" over a status line saying it is armed, and both would
    look right on their own.
    """
    return any(text.startswith(sched.ARMED) for _, text, _ in job)


class Firing:
    """The whole-queue run this screen started, if it started one.

    The item screen's ``n`` hands one download to a detached ``dlq now``; this
    hands the whole queue to a detached runner, which is the same process the
    nightly job fires and takes the same lock. Detached for the same reason:
    the download has to outlive the screen that started it, and the screen has
    to stay usable while it runs.
    """

    def __init__(self) -> None:
        self.child: subprocess.Popen | None = None
        self.blind = False

    @property
    def alive(self) -> bool:
        return self.child is not None and self.child.poll() is None

    def start(self, blind: bool) -> Path:
        """Spawn the runner and return the file its output is going to."""
        sched.LOGS.mkdir(parents=True, exist_ok=True)
        log = sched.LOGS / f"{time.strftime('%Y-%m-%d', time.gmtime())}-now-queue.log"
        handle = log.open("a", encoding="utf-8")
        try:
            self.child = subprocess.Popen(
                sched.queue_run_argv(blind),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(sched.ROOT),
            )
        finally:
            handle.close()
        self.blind = blind
        return log

    #: **SIGINT, not SIGTERM.** The download is not in the runner's process
    #: group — :func:`expire_runner.run_item` gives every item a session of its
    #: own so that the group can be killed without killing the runner — so a
    #: signal to the runner is not a signal to the download. What stops the
    #: download is the runner *unwinding*: ``run_item`` catches anything coming
    #: out of its supervisor and kills the item's tree on the way past. Only an
    #: interrupt does that. SIGTERM kills the runner where it stands and leaves
    #: yt-dlp running with nothing watching it and nothing left to stop it —
    #: spending data, on a blind run, until the phone is rebooted. This is the
    #: ctrl-c the runner is written for, sent from a screen instead of a
    #: terminal.
    SIGNAL = signal.SIGINT

    def stop(self) -> None:
        """Interrupt the run, which is what ctrl-c would have done.

        The part file stays on disk and the item stays in the queue, so the
        nightly window carries on from where this stopped — the same bargain
        the item-level stop makes, and the reason stopping one is cheap.
        """
        if self.child is None:
            return
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(self.child.pid), self.SIGNAL)


# --------------------------------------------------------------------------- #
# The actions themselves
# --------------------------------------------------------------------------- #


def removal_note(row: dict) -> list[str]:
    """What the remove screen has to say, in the order it has to say it.

    The bytes first, because that is the part that cost money and the part that
    cannot be got back without paying for it again.
    """
    _, kept = removal(row)
    files = [path for path in kept if path.is_file()]
    lines = [f"remove {_slug_of(row['name'])} from the list?"]
    if row["have"]:
        lines.append(f"the {ytq.human(row['have'])} already downloaded stays in work/")
    if files:
        lines.append(
            f"{len(files)} finished file{'s' if len(files) > 1 else ''} "
            f"stay{'' if len(files) > 1 else 's'} in out/"
        )
    if row["files"] and not files:
        lines.append("the file it delivered is not touched")
    return lines


def removal_answers(row: dict) -> list[tuple[str, str]]:
    """The keys the remove screen takes, as ``(keys, what they do)``.

    **The keys never change.** Which of them is worth offering separately does:
    a download with bytes on the disk has two different answers — keep them or
    delete them — and one with none has a single answer wearing two keys.

    That distinction used to be drawn by *withholding* ``b``, and it made the
    screen unusable in the way that is hardest to see: on an item that had
    downloaded nothing, ``b`` was not offered, so pressing it fell through to
    "any other key: no" and the download stayed. The item screen said nothing
    was removed, quietly, exactly as it would have if you had meant it — and it
    did the same thing on the next run, and the run after that. A key that is
    live on one download and means "no" on the next is worse than a key that is
    not there at all.
    """
    if row["have"]:
        size = ytq.human(row["have"])
        return [
            ("y", f"remove it, keep the {size}"),
            ("b", f"remove it and delete the {size}"),
        ]
    return [("yb", "remove it")]


def reachable() -> bool:
    """Whether the crew portal answers, within a couple of seconds.

    In a thread with a hard join, so a name lookup that hangs on a captive
    network cannot hang the screen: what does not answer in two seconds has not
    answered, which is the same conclusion by a shorter route. Erring towards
    "no" is erring towards the loud version of the question.
    """
    answer: list[bool] = []
    worker = threading.Thread(
        target=lambda: answer.append(sched._runner().portal_reachable()),
        daemon=True,
    )
    worker.start()
    worker.join(2.0)
    return bool(answer and answer[0])


def cancel_note() -> list[str]:
    """What the unregister confirm says — out here so it can be checked.

    The last line is the way back, and it names the row on the More tab that
    arms it again rather than a key: a confirm can be wrong about its own
    screen, and this is the one line where being wrong costs the nightly job.
    """
    return [
        "stop the nightly job?",
        "nothing downloads by itself after this",
        "nightly job on More arms it again; the queue is untouched either way",
    ]


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def run() -> int:
    """The app, opened on the Queue tab: what ``dlq`` with no words opens."""
    if not sys.stdout.isatty():
        print(
            "dlq ui needs a terminal; dlq list is the same queue, printed",
            file=sys.stderr,
        )
        return 2
    problem = sched.root_problem()
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    import nibbles

    for line in nibbles.run("queue"):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        print("       dlq ui is the same screen", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main())
