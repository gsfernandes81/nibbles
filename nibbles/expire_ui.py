#!/data/data/com.termux/files/usr/bin/python3
"""What changes the queue, and what the Queue tab works out before it draws.

``nibbles queue`` opens the app on its Queue tab, and ``queue_screens`` draws
it; this module is what those screens call. The handful of things that come up
once an item is *in* the queue and wrong — it should go first, it is called the
wrong thing, it should not run at all, it failed three nights and deserves
another one — were a rename in ``queue/`` and an edit of ``state.json`` by
hand, and doing them by hand is how the bytes get lost. Each is one verb here:
:func:`do_reorder`, :func:`do_rename`, :func:`do_remove`, :func:`do_requeue`
and :func:`do_clear_tries`, called alike by a button and its key, and each
answers ``(what to say, whether it worked)``: a screen branches on the flag,
never on the wording, which is free to change.

Two rules run through all of them, and both are about the bytes.

**Everything an item owns moves with it.** An item is not only the file in
``queue/``: it is also ``work/<name>/``, where a half-finished download of
several gigabytes sits, ``out/<name>/``, where a finished one waits to be
delivered, and its record in ``state.json``, which holds the attempts and where
the files went. Renaming the queue file alone leaves a paid-for partial under a
name nothing will ever look for again, and the item starts from zero on the
next night without a word. :func:`belongings` is the one place that decides
what an item owns, and every move and every removal is spelled from it. And a
name something still answers to is never handed to another item:
:func:`_occupied` is the rule ``ytq.write_item`` writes by
(:func:`ytq.names_in_use`), so a move and a write cannot disagree about one.

**Nothing outside the queue's own root is ever deleted.** A delivered file sits
in Downloads among the phone's other files and belongs to whoever asked for it,
not to the queue. Removing an item deletes the item and the scratch it was
downloading into; anything finished in ``out/`` is kept, and the screen says
where it stayed.

A third rule is about *when*: **while the queue is busy nothing may be
changed.** A firing or a ``nibbles now`` writes into ``work/<name>/`` and hands
the item to ``done/`` when it completes, so moving either underneath it loses
the download or breaks the archive. Every mutating function starts at
:func:`busy_problem`, which is checked rather than assumed — the guard lives
with the mutation and not with the screen, so it cannot be skipped by a caller.

**The cut line is computed and is never an item.** It has no name, no record
and no place in the order, and it is worked out afresh on every draw from
whatever order the items are in — including one that exists nowhere but under
a held item (:func:`preview`). :func:`tonight_plan` is
:func:`expire_runner.plan` over :func:`expire_runner.admit`, the rule
``fire()`` admits items by, so the screen cannot promise bytes the night then
refuses; :func:`cut_index` says where the line falls and, where nothing gets
anything, why. Moving an item across the line moves the line; it never moves
the budget.

:class:`Firing` is the whole-queue run that Run now hands to a detached
runner.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

from nibbles import expire_dl
from nibbles import expire_sched as sched
from nibbles import ytq
import contextlib

#: A name with its extension dropped, as ``nibbles list`` says it: called rather
#: than respelled, so the two cannot come out different.
_display_name = sched._display_name


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


def _key_of(name: str) -> int:
    """The number at the front of anything ``queue/`` lists, download or not.

    By the runner's own rule (:data:`ytq.ITEM_RE`) and not :data:`NAME_RE`,
    because the listing is: a stray such as ``20-holiday.png`` fails the
    stricter rule, is listed as a queued row all the same, and sits at 20 in
    the order the runner sorts by — which is the place its neighbours have to
    be put around. Nought only for a name nothing lists.
    """
    found = ytq.ITEM_RE.match(name)
    return int(found.group(1)) if found else 0


def _slug_of(name: str) -> str:
    """An item's name as this screen shows it: the slug, with no number on it.

    The number *is* the run order, and the list already shows the order by
    being a list. Printing it as well asks someone to read the same fact twice,
    in the harder of the two spellings — and it invites thinking in numbers,
    which is the thing this screen exists to stop: you move a download by
    picking it up and putting it where you want it, not by working out what
    integer lives between two others.

    Nothing needs it typed back either: ``nibbles path`` takes any unambiguous
    part of a name, which a slug is.
    """
    parsed = parse_name(name)
    return parsed[1] if parsed else _display_name(name)


def renumber(name: str, number: int) -> str:
    """The same item at a different priority — **the slug untouched**.

    Not spelled through :func:`ytq.slugify`, which is right for something a
    person typed and wrong here: it truncates at 42 characters, so putting a
    long-titled item first would silently shorten its name as well as move it,
    and the name is what ``nibbles now`` is given.
    """
    _, slug = parse_name(name) or (0, name)
    return f"{max(0, min(99999, number)):02d}-{slug}.py"


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

    Whether the scratch holds anything is asked of the disk, now, and never of
    ``row["have"]``: the row is what the confirm was built from, and a confirm
    can stay up across a firing that bought part of this download and exited.
    Read off the row, a partial that was empty when the question was asked is
    deleted when it is answered, by the answer that keeps the bytes.
    """
    goes = [row["path"]]
    kept: list[Path] = []
    work = sched.WORK / row["name"]
    if work.exists():
        # Scratch holding no payload was never paid for — an item that failed
        # before moving a byte still leaves the status file the runner writes —
        # so there is nothing there to keep and it goes either way. Keeping it
        # would leave a directory nothing lists and nothing will ever resume.
        (goes if bytes_too or not sched._payload_bytes(work) else kept).append(work)
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


def _occupied(moving: set[str]) -> set[str]:
    """Every name something other than the queued items *moving* answers to.

    The rename's collision rule (:func:`_taken`) over a whole set of items at
    once, because a move is a rename too. A name is not free because
    ``queue/`` has no file by it: a finished or failed item may answer to it —
    and easily, since the keys :func:`slot` and :func:`spread` hand out are
    the keys :func:`ytq.next_number` handed out before, so a title queued
    again lands on its own old name — and so may a ``work/`` or ``out/``
    directory an item left behind, or a record in ``state.json`` that outlived
    its item. Moving onto any of them makes two items one: the record is
    overwritten or inherited, the finished one drops out of the listing, and
    the queued one adopts bytes it never downloaded and may never run again.

    **The rule is :func:`ytq.names_in_use`**, the one :func:`ytq.write_item`
    writes by, and not a second walk of the same folders: two copies were two
    answers, and a name one of them missed was a name a move took and a write
    stepped round, or the other way about.

    What *moving* own goes with them — their queue files, scratch, outboxes
    and records — so their names are taken out of it. Never a name a finished
    or failed item answers to, which no queued item owns.
    """
    held = {path.name for where, path in ytq.items() if where != "queued"}
    return (ytq.names_in_use() - moving) | held


def _fresh_keys(names: list[str], occupied: set[str]) -> list[int] | None:
    """Keys for *names* in this order, none of them making a name in *occupied*.

    :func:`spread`'s, each bumped past any key that would land its item on a
    name something else holds, and kept strictly rising so that the order the
    runner sorts is the order asked for. Where bumping runs off the end of the
    two digits the keys are packed from the bottom instead; ``None`` only when
    even that does not fit.
    """
    for bases in (spread(len(names)), [0] * len(names)):
        keys: list[int] = []
        for name, base in zip(names, bases, strict=True):
            key = max(base, keys[-1] + 1 if keys else 0)
            while key <= ytq.MAX_PRIORITY and renumber(name, key) in occupied:
                key += 1
            if key > ytq.MAX_PRIORITY:
                break
            keys.append(key)
        else:
            return keys
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

    No new name, parked or final, is one something outside the move answers
    to (:func:`_occupied`). And a stray in *order* — a file listed as queued
    whose name is not a download's — keeps the name it has: it is not this
    screen's to renumber, and nothing here can be spelled onto it.
    """
    names = [name for name in order if parse_name(name)]
    if len(names) > ytq.MAX_PRIORITY:
        return f"more than {ytq.MAX_PRIORITY} downloads is more than there is room for"
    occupied = _occupied(set(names))
    keys = _fresh_keys(names, occupied)
    if keys is None:
        return "no room to reorder; remove something first"
    wanted = {name: renumber(name, key) for name, key in zip(names, keys, strict=True)}
    pending = {old: new for old, new in wanted.items() if old != new}
    # Every key that must not be parked on: one an item already answers to, and
    # one something is about to.
    spoken = {parse_name(name)[0] for name in wanted} | set(keys)
    guard = 2 * len(wanted) + 4
    while pending:
        guard -= 1
        if guard < 0:  # pragma: no cover - the loop is finite by construction
            return "the order would not settle; nothing else was changed"
        free = [old for old, new in pending.items() if not (sched.QUEUE / new).exists()]
        if not free:
            old = next(iter(pending))
            # Nor on a key that would make it a name something else holds.
            key = _free_key(spoken | {
                k for k in range(ytq.MAX_PRIORITY + 1) if renumber(old, k) in occupied
            })
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
    if parse_name(name) is None:
        # A stray — ``20-holiday.png`` — is listed so that it can be explained,
        # not because it is a download: a new number spelled onto it would
        # make the photo a ``.py`` file as well as move it.
        return "only an NN-name.py download can be moved", False
    others = [item for item in queued if item != name]
    pos = max(0, min(pos, len(others)))
    if others[:pos] + [name] + others[pos:] == queued:
        return "left where it was", False
    key = slot([_key_of(item) for item in others], pos)
    target = renumber(name, key) if key is not None else ""
    # The runner sorts file names, so that is what has to put it between its
    # new neighbours — not the arithmetic, which a neighbour numbered past two
    # digits defeats — and a name something else holds is no room at all.
    between = (pos == 0 or others[pos - 1] < target) and (
        pos == len(others) or target < others[pos]
    )
    if target and between and target not in _occupied({name}):
        failure = _rename_bare(name, target)
    else:
        failure = _reindex(others[:pos] + [name] + others[pos:])
    if failure:
        return failure, False
    _note(f"moved {name} to {pos + 1} of {len(queued)}")
    return f"{_slug_of(name)} is {ytq.ordinal(pos + 1)} of {len(queued)}", True


# --------------------------------------------------------------------------- #
# Changing something
# --------------------------------------------------------------------------- #


def busy_problem() -> str | None:
    """Why nothing may be changed at this moment, or ``None``.

    Called first by every mutating function in this module rather than by the
    screens that call them, so that the guard cannot be skipped by a caller who
    did not know it was needed. What it guards is not subtle: a firing or a
    ``nibbles now`` is writing into ``work/<name>/`` and will rename the item into
    ``done/`` when it finishes, and moving either underneath it loses the
    download or leaves the archive step renaming a file that is not there.

    :func:`ytq.queue_busy` and not the freshness of a progress file, because
    this is the question the *runner* answers with the lock, and a mutation is
    one of the two things (the other is ``nibbles now``) that is entitled to take
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
    deliver a file it never downloaded. A record in ``state.json`` that
    outlived its item is the third: the renamed item would inherit its
    attempts, or overwrite where another download's file was delivered.

    Decided by :func:`_occupied`, the rule a move answers to as well; the walk
    below only finds the words.
    """
    if new_name not in _occupied(set()):
        return None
    for where, path in sched._paths():
        if path.name == new_name:
            return f"{where} already has a {_display_name(new_name)}"
    for root in (sched.WORK, sched.OUT):
        if (root / new_name).exists():
            return f"{root.name}/{_display_name(new_name)} still has bytes in it"
    return f"state.json still has a record of {_display_name(new_name)}"


def refuse_rename(row: dict, new_name: str) -> str | None:
    """Why this rename must not happen, or ``None``. Says it in one line."""
    problem = busy_problem()
    if problem:
        return problem
    if new_name == row["name"]:
        return "that is the name it has"
    if not NAME_RE.match(row["name"]):
        # A stray's own name says what kind of file it is; a download's name
        # spelled onto ``20-holiday.png`` would make the photo a ``.py``.
        return "only an NN-name.py download can be renamed"
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
    files were delivered to. Dropping it would cost ``nibbles path`` the only
    answer it has: once a file is in a folder shared with every other app on
    the phone, nothing can work out which one was ours by looking.
    """
    runner, state, _ = _record(old)
    items = state.get("items") or {}
    if old not in items:
        return
    if new in items:
        # Never over another item's history: both callers refuse such a name
        # first (:func:`_taken`, :func:`_occupied`), and should one get here
        # anyway, this item's attempts are the cheaper loss — the other record
        # may be the only one of where a delivered file went.
        _note(f"kept the record of {old} under that name: {new} already has one")
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


#: What a direct download's ``.part.meta.json`` counts *in a row*
#: (``expire_dl``): answers that were not the file (``refused``, a strike from
#: the :data:`expire_dl.MAX_REFUSALS`-th on) and 200s to a ranged request
#: (``range_200s``, the part kept once and the server doubted only the second
#: time). Streaks, like the attempts in ``state.json``: what the meta knows
#: about the file and its server — its size, its validators, ``no_range``,
#: ``at_least``, ``restarts`` — is not one, and stays.
STREAKS = ("refused", "range_200s")


def _fresh_streaks(name: str) -> None:
    """Start the item's :data:`STREAKS` again, with its attempts.

    A download given its nights back with a streak still counted was given
    none: its third answer that was not the file had made every answer after
    it a strike, so the first page the server sent the item put back was a
    strike again, with no grace of "not tonight" before it.
    """
    for meta in sorted((sched.WORK / name).glob("*.part.meta.json")):
        part = meta.with_name(meta.name.removesuffix(".meta.json"))
        found = expire_dl._load_meta(part)
        if isinstance(found, dict) and any(key in found for key in STREAKS):
            for key in STREAKS:
                found.pop(key, None)
            expire_dl._save_meta(part, found)


def do_rename(row: dict, new_name: str) -> tuple[str, bool]:
    """Rename the item and everything it owns: ``(what to say, renamed)``."""
    problem = refuse_rename(row, new_name)
    if problem:
        return problem, False
    failure = _apply(rename_moves(row, new_name))
    if failure:
        return failure, False
    _move_record(row["name"], new_name)
    _note(f"renamed {row['name']} -> {new_name}")
    return f"now {_display_name(new_name)}", True


def do_remove(
    row: dict, bytes_too: bool = False, why: str = "removed"
) -> tuple[str, bool]:
    """Take the item off the list, keeping every byte unless told otherwise:
    ``(what to say, removed)``.

    *row* is what the question was asked about, and the answer can come hours
    later — a confirm stays up across a firing, and one that bought part of
    this download and exited has left bytes the question never named. So what
    is on the disk is measured again here: keeping keeps whatever is there
    now (:func:`removal` decides from the disk too), what is said is the size
    there now, and deleting more than the yes named is refused, because the
    size on that answer was the consent to lose it.
    """
    problem = busy_problem()
    if problem:
        return problem, False
    have = sched._payload_bytes(sched.WORK / row["name"])
    if bytes_too and have > row["have"]:
        grown = ytq.human(have - row["have"])
        return f"it has downloaded {grown} more since you asked; nothing was removed", False
    row = {**row, "have": have}
    goes, kept = removal(row, bytes_too)
    for path in goes:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            return f"could not remove {path.name}: {exc.strerror or exc}", False
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
    return (f"{said}; {', '.join(parts)}" if parts else said), True


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
        _, removed = do_remove(row, why=f"forgot (nothing of it left in {folder})")
        if removed:
            forgotten.append(_slug_of(row["name"]))
    return forgotten


def do_requeue(row: dict) -> tuple[str, bool]:
    """Put a failed item back in the queue, with its attempts wiped:
    ``(what to say, put back)``.

    The wipe is not a courtesy: an item is set aside once its attempts reach
    ``MAX_ATTEMPTS``, so one put back with them still on the clock is given up
    on again by the first firing that touches it — a retry that retries
    nothing. A direct download's streaks go with them (:func:`_fresh_streaks`).
    What is deliberately kept is ``work/<name>/`` and what its meta knows of
    the file, so the retry resumes from whatever the three failed nights did
    manage to buy.
    """
    problem = busy_problem()
    if problem:
        return problem, False
    if row["where"] != "failed":
        return f"it is in {row['where']}, not failed", False
    # Not :func:`_taken`, which would find this very item sitting in failed/.
    # The one collision that matters here is a queued item of the same name.
    if (sched.QUEUE / row["name"]).exists():
        return f"the queue already has a {_display_name(row['name'])}", False
    failure = _apply([(row["path"], sched.QUEUE / row["name"])])
    if failure:
        return failure, False
    _edit_record(row["name"], {"attempts": 0, "stalls": 0}, drop=("retired",))
    _fresh_streaks(row["name"])
    _note(f"put {row['name']} back in the queue, attempts cleared")
    return f"{_display_name(row['name'])} is queued again", True


def do_clear_tries(row: dict) -> tuple[str, bool]:
    """Give a queued item its three nights back: ``(what to say, cleared)``."""
    problem = busy_problem()
    if problem:
        return problem, False
    if not row["attempts"]:
        return "it has no failed tries", False
    _edit_record(row["name"], {"attempts": 0, "stalls": 0})
    _fresh_streaks(row["name"])
    _note(f"cleared {row['attempts']} failed tries on {row['name']}")
    return f"{row['attempts']} failed tries cleared", True


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

    A stray — a file listed because its name starts ``NN-`` but not named
    ``NN-name.py`` — is offered neither a move nor a rename: either would spell
    a download's name onto it, and ``20-holiday.png`` would become a ``.py``.
    """
    where = row["where"]
    named = parse_name(row["name"]) is not None
    offered: list[tuple[str, str]] = []
    if where == "queued" and not row["error"] and row["cap"] > row["have"]:
        offered.append(("n", "download it now"))
    if where == "failed":
        offered.append(("u", "put it back in the queue"))
    if where == "queued" and named:
        offered.append(("m", "move it in the queue"))
    if where in ("queued", "failed") and named:
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
    manual = facts.get("allowance")
    if manual is not None:
        return "no allowance set" if not manual["allowance_bytes"] else "allowance spent"
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


#: What comes before an item's name in its log's: the UTC day, and ``now-`` for
#: the log a ``nibbles now`` writes. Nothing else may, or ``41-foo-10-x.py``'s
#: log would be ``10-x.py``'s too.
_LOG_HEAD = re.compile(r"\d{4}-\d{2}-\d{2}-(?:now-)?")


def item_log(name: str) -> Path | None:
    """The log this item wrote last, or ``None``.

    Both spellings are matched: the runner writes ``<date>-<item>.log`` and a
    ``nibbles now`` writes ``<date>-now-<item>.log``. The name is read
    literally rather than as a glob — titles keep their brackets, and
    ``[Official Video]`` read as a character class matches nothing, so the
    failures a log is there to explain would say there is none.

    Last *written*, by the clock, and not last by name: on one day the ``now-``
    spelling sorts after the other whichever came second, so a morning's
    Download now would stand in for the night's failure.
    """
    tail = f"{name}.log"
    found = []
    try:
        entries = list(sched.LOGS.iterdir())
    except OSError:
        return None
    for path in entries:
        if not path.name.endswith(tail):
            continue
        if not _LOG_HEAD.fullmatch(path.name[: -len(tail)]):
            continue
        try:
            found.append((path.stat().st_mtime, path.name, path))
        except OSError:
            continue
    return max(found)[2] if found else None


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

    The item screen's ``n`` hands one download to a detached ``nibbles now``; this
    hands the whole queue to a detached runner, which is the same process the
    nightly job fires and takes the same lock. Detached for the same reason:
    the download has to outlive the screen that started it, and the screen has
    to stay usable while it runs.
    """

    def __init__(self) -> None:
        self.child: subprocess.Popen | None = None
        self.blind = False
        #: Set by :meth:`stop`, so a run is interrupted once (see there).
        self.stopped = False

    @property
    def alive(self) -> bool:
        return self.child is not None and self.child.poll() is None

    def start(self, blind: bool) -> Path:
        """Spawn the runner and return the file its output is going to.

        The log and the spawn are the runner's (``log_path``,
        ``spawn_logged``), which the item screen's Download now uses too.
        """
        runner = sched._runner()
        log = runner.log_path("queue", now=True)
        self.child = runner.spawn_logged(sched.queue_run_argv(blind), log)
        self.blind = blind
        self.stopped = False
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

        Once. The runner answers the first by unwinding — the item's tree
        killed, the ledger charged, the state saved — and a second is only
        that same stop asked for again while it is being carried out.
        """
        if self.child is None or self.stopped:
            return
        self.stopped = True
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


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def run() -> int:
    """The app, opened on the Queue tab: what ``dlq`` with no words opens."""
    if not sys.stdout.isatty():
        print(
            "nibbles queue needs a terminal; nibbles list is the same queue, printed",
            file=sys.stderr,
        )
        return 2
    problem = sched.root_problem()
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    from nibbles import app

    for line in app.run("queue"):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        print("       nibbles queue is the same screen", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main())
