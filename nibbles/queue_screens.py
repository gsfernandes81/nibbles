"""The queue half: the Queue and More tabs and the sheets they open.

``design/design.md`` §5 is the spec and ``design/mockups/k-queue``, ``k-item``,
``k-place``, ``k-download``, ``k-run``, ``k-more``, ``k-setting`` and
``k-narrow`` are how it looks. Every button calls the same function its key
did and its command does — ``do_reorder``, ``do_remove``, ``do_rename``,
``do_requeue``, ``do_clear_tries``, ``set_setting``, ``set_dest``,
``do_arm``, ``do_cancel``, ``queue_run_argv`` — so a screen and a command
cannot disagree about whether something worked.

Imported by the app when it starts and never at a module's top: ``expire_ui``
imports ``expire_sched``, which imports ``ytq``, and none of them may be
half-loaded when another asks for it.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path

from nibbles import expire_dl
from nibbles import expire_sched as sched
from nibbles import expire_ui as ui
from nibbles import shell
from nibbles import tui
from nibbles import widgets as w
from nibbles import ytq
from nibbles.shell import SHORT, Choice, Confirm, Entry, ListView, Notice, Screen, Sheet, spin
from nibbles.widgets import T, Btn, Piece, Surface

APP_NAME = "nibbles"

#: How often the queue is re-read off the disk: while something downloads,
#: and while nothing does (to notice a nightly firing starting).
LIVE_POLL = 1.0
IDLE_POLL = 15.0

#: How long a download's figure may stand still before it is read as not
#: moving: three of the reports it writes at least this often while it is.
STILL = 3 * expire_dl.STATUS_EVERY_SECONDS


def runner():
    return sched._runner()


def display(name: str) -> str:
    """An item's name as the screens show it: no number, no ``.py``."""
    return ui._slug_of(name)


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


#: The status bar's label for each of ``gate()``'s verdicts, and its kind.
#: A word every time, never only a colour; a test pins one per verdict.
STATUS = {
    "early": ("WAITING", "primary"),
    "go": ("OPEN", "success"),
    "late": ("DONE", "primary"),
    "empty": ("IDLE", "primary"),
    "unset": ("WAITING", "primary"),
    "off": ("OFF", "warn"),
    "spent": ("SPENT", "primary"),
    "blind": ("RUNNING", "warn"),
    "no-portal": ("BLOCKED", "error"),
    "stale": ("BLOCKED", "error"),
    "downloading": ("↓", "warn"),
}

#: The verdicts that count down to something, on the status bar and the card:
#: to the stop time while the window is open, else to when the next opens.
TIMED = ("early", "go", "late", "spent")


class QueueModel:
    """Every download, what the window would do, and what is downloading.

    The reading (``expire_runner.snapshot``) is a portal call and is taken in
    a :class:`tui.Job`, never on the screen's thread; the rows are a walk of
    the queue's own directories and are re-read on a timer while something
    downloads.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.running = ytq.Running()
        self.firing = ui.Firing()
        self.rows: list[dict] = []
        self.live = ""
        self.facts: dict | None = None
        self.note = ""
        self.job: tui.Job | None = None
        self.read_at = 0.0
        self.taken = 0.0
        #: Whether zwana answered a fresh 1.5 s connect, and when (``reached``
        #: is ``None`` until one has come back).
        self.reached: bool | None = None
        self.reached_at = 0.0
        self.reach_job: tui.Job | None = None
        self.samples: dict[str, list[tuple[float, int]]] = {}
        #: :meth:`_seeing` at the last tick.
        self.seen: tuple[bool, bool, str] = (False, False, "")
        self.read()
        self.refresh()

    # Reading ---------------------------------------------------------------

    def read(self) -> None:
        self.rows = sched.items()
        forgotten = ui.forget_gone(self.rows)
        if forgotten:
            self.rows = sched.items()
            for name in forgotten:
                self.app.receipt(f"forgot {name}: its file had been deleted")
            self.app.say(f"forgot {', '.join(display(n) for n in forgotten)}: the file had gone")
        # Only the queued: a finished item has left the queue, and its status
        # file, still fresh, is not a download going on. Nor is what a run of
        # our own wrote once it has exited — a ``nibbles now``, or the runner
        # Run now started, whose pid is in the run id either way: a paused
        # Run now said "downloading" for a minute and refused to run again.
        exited = [run.child.pid for run in (self.running, self.firing)
                  if run.child is not None and not run.alive]
        self.live = sched._running_now([row["name"] for row in self.rows
                                        if row["where"] == "queued"], exited)
        self.read_at = time.monotonic()

    #: How old a reading may get before looking at the Queue tab asks again.
    STALE = 60.0

    def refresh(self, force: bool = True) -> None:
        """Ask for a fresh reading of the window, unless one is on its way
        (or, unforced, unless the one on screen is still fresh)."""
        if self.job is not None and not self.job.finished:
            return
        if not force and self.facts and time.monotonic() - self.taken < self.STALE:
            return
        self.job = tui.Job(lambda: ui.tonight_facts(), "asking zwana", key="facts")
        self.app.start(self.job, self)

    def check_reach(self) -> None:
        """Ask whether zwana answers, now: what Now and Download now say
        depends on where the phone is (``expire_ui.reachable``)."""
        if self.manual():
            return
        if self.reach_job is not None and not self.reach_job.finished:
            return
        self.reach_job = tui.Job(ui.reachable, "asking whether zwana answers", key="reach")
        self.app.start(self.reach_job, self)

    def manual(self) -> bool:
        """A manual budget source counts every byte itself: nothing it
        spends is uncounted, so the red "charged" case never applies."""
        return bool(self.facts and self.facts.get("source") == "manual")

    def done(self, app, job) -> None:
        if job is self.reach_job:
            self.reach_job = None
            self.reached = bool(job.result) if job.error is None else False
            self.reached_at = time.monotonic()
            return
        if job is self.job:
            self.job = None
            self.taken = time.monotonic()
            if job.error is None:
                self.facts = job.result
                self.note = ""
            else:
                # The reason, short: the card's verdict already says "no
                # reading", and this is the line where its figures would be.
                self.note = str(job.error) or type(job.error).__name__

    def changed(self) -> None:
        """Something was queued, moved or removed: read again, plan again."""
        self.read()
        self.refresh()

    def _due(self) -> float:
        """How often the queue is read: each second while something
        downloads or a run of ours is alive (Run now starting, or between
        two items, is about to change it), else the idle poll."""
        return LIVE_POLL if self.downloading_name() or self.mine() else IDLE_POLL

    def tick(self) -> None:
        due = self._due()
        # A download starting or ending is read at once: the rows say where
        # it went (done, still queued, failed), and waiting the idle poll out
        # left its sheet a quarter of a minute behind.
        if time.monotonic() - self.read_at >= due or self.seen != self._seeing():
            self.read()
        seeing = self._seeing()
        # The reading outlives what it read in two ways, and each is asked
        # again once, on the edge, never on a timer: the moment it counted to
        # has come (the window opening, its stop time), or a download has
        # ended and spent what the card still offers. Left alone, the status
        # bar said the old verdict at "0s" all night and the card kept the
        # figures a firing had already spent.
        if self._expired() or self._ended(self.seen, seeing):
            self.refresh()
        self.seen = seeing

    def _seeing(self) -> tuple[bool, bool, str]:
        """What a start or an end changes: our own runs' lives (a ``nibbles
        now`` and Run now's), and the name downloading."""
        return self.running.alive, self.firing.alive, self.downloading_name()

    @staticmethod
    def _ended(was: tuple, now: tuple) -> bool:
        """Whether something downloading at *was* is not at *now*."""
        stopped = any(before and not after
                      for before, after in zip(was[:-1], now[:-1], strict=True))
        return stopped or bool(was[-1]) and was[-1] != now[-1]

    def _expired(self) -> bool:
        """Whether the moment the reading counted to has come since it was
        taken, with nothing asked since — or, what was asked having failed,
        nothing for :attr:`STALE`, so a portal that is down is not asked on
        every keypress."""
        f = self.facts
        if not f:
            return False
        at = f["stop_by"] if f["verdict"] == "go" else self.next_open()
        now = time.time()
        if at is None or math.isinf(at) or not f["now"] < at <= now:
            return False
        since = time.monotonic() - self.taken  # since the last answer, read or failed
        return since > now - at or since >= self.STALE

    def wake(self) -> float | None:
        """When the queue next needs a look: the poll, and each second of
        the last two minutes of a countdown — never one already over."""
        due = self._due()
        waits = [max(0.05, due - (time.monotonic() - self.read_at))]
        seconds = self.countdown()
        if seconds is not None and 0 < seconds < 120:
            waits.append(1.0)
        return min(waits)

    def closing(self) -> None:
        """Nothing to stop: downloads are detached and outlive the app."""

    # What is downloading ---------------------------------------------------

    def mine(self) -> bool:
        return self.running.alive or self.firing.alive

    def downloading_name(self) -> str:
        if self.running.alive:
            return self.running.name
        return self.live

    def progress(self, name: str) -> tuple[int, int, float]:
        """``(have, total, bytes a second)`` for *name*, from its own report."""
        report = ytq.now_progress(name)
        row = next((r for r in self.rows if r["name"] == name), None)
        have, total = report if report else ((row or {}).get("have", 0), 0)
        if not total and row:
            total = row.get("stated") or 0
        now = time.monotonic()
        seen = self.samples.setdefault(name, [])
        if seen and seen[-1][1] != have and now - seen[-1][0] > STILL:
            # Moving again after a stall: measured afresh, never against a
            # figure from before it.
            seen.clear()
        if not seen or seen[-1][1] != have:
            seen.append((now, have))
        while len(seen) > 2 and now - seen[0][0] > 20:
            seen.pop(0)
        rate = 0.0
        # Nothing new for STILL is nothing moving: the last two figures kept
        # their speed, and the time left with it, for as long as a stalled
        # download went on saying it was alive.
        if len(seen) >= 2 and seen[-1][0] > seen[0][0] and now - seen[-1][0] <= STILL:
            rate = max(0.0, (seen[-1][1] - seen[0][1]) / (seen[-1][0] - seen[0][0]))
        return have, total, rate

    def time_left(self, name: str) -> float | None:
        have, total, rate = self.progress(name)
        if not total or rate <= 0:
            return None
        return (total - have) / rate

    # The window --------------------------------------------------------------

    def next_open(self) -> float | None:
        """When the window that can next spend opens: this one while it is
        open — what is queued now still goes in it — unless the reading says
        it will spend nothing more, and then tomorrow's. "spent" once said
        ``opens 21:57`` of a moment already past, all through the window."""
        f = self.facts
        if not f:
            return None
        if f["now"] < f["window_open"]:
            return f["window_open"]
        stop = f["stop_by"]
        if f["verdict"] != "spent" and (math.isinf(stop) or f["now"] < stop):
            return f["window_open"]
        return f["window_open"] + 86400

    def window_word(self) -> str:
        """``03:00``: when the next window opens, on the phone's clock."""
        at = self.next_open()
        return shell.clock(at) if at else "the window"

    def counted(self) -> bool | None:
        """Whether what is spent now is counted: always under a manual
        budget; else whether zwana answered a fresh connect (asked by
        :meth:`check_reach`), and failing that the last reading. ``None``
        while nothing is known."""
        if self.manual():
            return True
        if self.reached is not None and time.monotonic() - self.reached_at < 120:
            return self.reached
        if self.reach_job is not None and not self.reach_job.finished:
            return None
        if not self.facts:
            return None
        return self.facts.get("portal") is not None

    def countdown(self) -> float | None:
        """Seconds to what the status bar counts to — the stop time while
        the window is open, else the next opening — or ``None``: a verdict
        that counts to nothing, or a moment already past. That reading is
        asked again (:meth:`tick`) rather than counted below nought, which
        said ``0s`` and woke the loop every second for as long as it stood."""
        f = self.facts
        if not f or f["verdict"] not in TIMED:
            return None
        at = f["stop_by"] if f["verdict"] == "go" else self.next_open()
        now = time.time()
        if at is None or math.isinf(at) or at <= now:
            return None
        return at - now

    def status(self, width: int) -> tuple[str, str, str, str]:
        """The status bar: a label word, the detail, the quiet right segment."""
        name = self.downloading_name()
        if name:
            have, total, _ = self.progress(name)
            pct = f"{min(99, int(have * 100 / total))}%" if total else "…"
            return (f"↓ {pct}", "warn", display(name), shell.left(self.time_left(name)))
        if self.firing.alive:
            return ("RUNNING", "warn", "starting the queue", "")
        f = self.facts
        if not f:
            if self.note:
                return ("BLOCKED", "error", f"no reading: {self.note}", "")
            return ("ASKING", "info", "asking zwana…", "")
        verdict = f["verdict"]
        label, kind = STATUS.get(verdict, ("WAITING", "primary"))
        when = shell.left(self.countdown())
        opens = f"opens {self.window_word()}"
        detail = {
            "early": opens,
            # No stop time (a blind or forced run) is said in words: an
            # endless deadline is never put through a clock.
            "go": ("no stop time" if math.isinf(f["stop_by"])
                   else f"closes {shell.clock(f['stop_by'])}"),
            "late": opens,
            "spent": f"nothing to spend · {opens}",
        }.get(verdict, ui.VERDICT_WORDS.get(verdict, f["detail"]))
        return (label, kind, detail, when)

    # Starting things -------------------------------------------------------

    def start_now(self, name: str) -> list[str] | None:
        """Hand *name* to a detached ``nibbles now``; the reasons not to, or None."""
        if self.running.alive:
            return [f"{display(self.running.name)} is already downloading",
                    f"{display(name)} is queued and will follow"]
        if ytq.queue_busy():
            return ["the queue is busy", "a nightly firing or another download holds it",
                    f"{display(name)} is queued and will run in the window"]
        self.running.start(name)
        ui._note(f"started {name} now, outside the window")
        self.read()
        return None


# --------------------------------------------------------------------------- #
# What the window would do, in the screens' words
# --------------------------------------------------------------------------- #

def verdict_line(model: QueueModel, room: int) -> list[tuple]:
    """``waiting · 03:00 (19m)``, the clock giving way before the word."""
    f = model.facts
    if not f:
        if model.note:
            return [("no reading", T.fg_base, True)]
        return [("asking zwana…", T.fg_more_subtle)]
    if f["verdict"] == "unset":
        return [("no daily allowance set", T.fg_base, True)]
    word = ui.VERDICT_WORDS.get(f["verdict"], f["detail"])
    seconds = model.countdown()
    tails = []
    if seconds is not None:
        at = f["stop_by"] if f["verdict"] == "go" else model.next_open()
        tails = [f" · {shell.clock(at)} ({shell.left(seconds)})", f" · {shell.left(seconds)}"]
    for tail in [*tails, ""]:
        if len(word) + len(tail) <= room:
            return [(word, T.fg_base, True), (tail, T.fg_more_subtle)]
    return [(word, T.fg_base, True)]


def against(model: QueueModel) -> tuple[int, int] | str:
    """``(what the next window may spend, what that is against)``, or the
    line said where those figures would be."""
    f = model.facts
    if not f:
        # A reading that failed says so where its figures would be.
        return model.note
    spend = max(0, f["spendable"])
    if f.get("source") == "manual":
        # A manual allowance: spent against what is left of it, never against
        # what "expires", which nothing can know when the rest of the phone's
        # use is not counted.
        # The spec's own shape, spendable/left (approved 2026-10-10).
        allowance = f.get("allowance") or {}
        if not allowance.get("allowance_bytes"):
            return "set it under More"
        return spend, max(0, allowance.get("left_bytes") or 0)
    doc = f.get("portal")
    if doc is None:
        if f.get("blind"):
            return f"≤{shell.size(spend)} declared"
        return "no reading, nothing to spend"
    expires = f.get("expiring")
    if expires is None:
        expires = (doc.get("free") or {}).get("left_bytes") or 0
    return spend, max(0, expires)


def figures(model: QueueModel, room: int) -> tuple[float, str]:
    """``(how full the bar is, 480/763 MiB to spend)``: what the next window
    may spend against what expires."""
    got = against(model)
    if isinstance(got, str):
        return 0.0, got
    spend, of = got
    return (spend / of if of else 0.0), pair_of(spend, of, room)


def spend_figure(model: QueueModel) -> str:
    """``480 MiB``: what the next window may spend, alone, in the unit its
    pair is said in — the tiny header's figure; ``""`` where there is no pair.
    It once cut the drawn pair at its ``/`` and wrote ``MiB`` after whatever
    was left, a GiB figure or a path in a failed reading's note included."""
    got = against(model)
    if isinstance(got, str):
        return ""
    spend, _, unit = in_one_unit(*got)
    return f"{spend} {unit}"


def in_one_unit(spend: int, of: int) -> tuple[str, str, str]:
    """``("480", "763", "MiB")``: both figures in the one unit they are said
    in — MiB below 10 GiB, whole; GiB to a tenth above."""
    MiB = 1024 * 1024
    if max(spend, of) < 10 * 1024 * MiB:
        return f"{round(spend / MiB)}", f"{round(of / MiB)}", "MiB"
    return f"{spend / (1024 * MiB):.1f}", f"{of / (1024 * MiB):.1f}", "GiB"


def pair_of(spend: int, of: int, room: int) -> str:
    """``480/763 MiB to spend``, ``1017/1144 MiB to spend``: one unit said
    once, MiB below 10 GiB (the spec's own shape, approved for the manual
    card too), whole figures, so the pair fits the 22 columns beside Run now."""
    a, b, unit = in_one_unit(spend, of)
    pair = f"{a}/{b} {unit}"
    return next((text for text in (f"{pair} to spend", pair) if len(text) <= room), pair)


def cut(order: list[str], facts: dict | None) -> tuple[int | None, str, dict]:
    """``(how many queued rows the window reaches, its line, what each gets)``.

    ``expire_ui.cut_index`` over ``expire_ui.tonight_plan`` — the runner's
    own projection, asked once and handed to both — so the line cannot
    promise what the night will refuse. Computed, never an item: the cursor
    skips it.
    """
    if not facts or not order:
        return None, "", {}
    planned = ui.tonight_plan(order, facts)
    at, line = ui.cut_index(order, facts, planned)
    return at, line, {e["name"]: e["bytes"] for e in planned}


def rule_block(text: str, width: int) -> w.Block:
    """``  ── the window ends here · 480 MiB ───``, in ``warning``.

    The fullest spelling that fits: at 32 columns the lead-in shortens to
    ``window`` (``k-narrow``), and the figure or the reason after the ``·`` is
    the part that is kept.
    """
    dash = w.glyphs.SECTION
    room = width - 3
    lead, _, tail = text.rpartition(" · ")
    short = {"the window ends here": "window", "nothing in the window": "nothing"}.get(lead, lead)
    for spelling in (text, f"{short} · {tail}" if lead else text, tail or text):
        line = f"{dash * 2} {spelling} "
        if len(line) <= room:
            break
    return w.spans([("  " + line + dash * max(0, room - len(line)), T.warning)], width)


def share(row: dict, got: int, at: str) -> str:
    """``46 MiB at 03:00`` on the one row the window only partly reaches."""
    return ui._tonight_share(row, got, at)


def amount(row: dict, have: int | None = None) -> str:
    """``0 of ≤505 MiB``: ``≤`` until a server states the size."""
    have = row["have"] if have is None else have
    got = shell.size(have) if have else "0"
    if row.get("stated"):
        return f"{got} of {shell.size(row['stated'])}"
    return f"{got} of ≤{shell.size(row.get('cap') or 0)}"


def failed_line(row: dict) -> str:
    """A failed download's second line: why, where anything says, else when
    it gave up. ``last`` is the runner's UTC log stamp of its last try, and
    is said as how long ago — on no clock at all — never drawn as it is
    (design §6); text that is not a stamp is somebody's word, and is said."""
    at = runner().unstamp(row["last"])
    if row["error"] or at is None:
        return row["error"] or row["last"] or "gave up"
    return f"gave up {shell.ago(time.time() - at)}"


def row_entry(row: dict, got: int, at: str, live: str = "", progress=None,
              held: bool = False) -> Entry:
    """One download as a two-line row: its name, then its figures (``↓ 18%``
    while it downloads, ``0 of ≤505 MiB · 46 MiB at 03:00`` while queued)."""
    name = row["name"]

    def draw(width: int, selected: bool) -> w.Block:
        sub: list = []
        if live == name:
            have, total = progress(name)[:2] if progress else (row["have"], row["stated"])
            pct = f"{min(99, int(have * 100 / total))}%" if total else "…"
            figure = (f"{shell.size(have)} of {shell.size(total)}" if total
                      else amount(row, have))
            sub = [w.Span("↓ ", w.Pen(fg=T.attention)),
                   w.Span(f"{pct}  {figure}", w.Pen(fg=T.fg_more_subtle))]
        elif row["where"] == "queued":
            sub = [w.Span(amount(row), w.Pen(fg=T.fg_more_subtle))]
            if row["error"]:
                sub = [w.Span(f"rejected: {row['error']}", w.Pen(fg=T.error))]
            part = share(row, got, at)
            if part:
                sub.append(w.Span(f" · {part}", w.Pen(fg=T.info)))
        elif row["where"] == "failed":
            sub = [w.Span(failed_line(row), w.Pen(fg=T.fg_more_subtle))]
        else:
            got_file = row["files"][0].name if row["files"] else ""
            where = "deleted" if row.get("lost") == "gone" else got_file
            figure = shell.size(row["have"] or row["total"])
            sub = [w.Span(" · ".join(p for p in (figure, where) if p),
                          w.Pen(fg=T.fg_more_subtle))]
        if selected or held:
            sub = "".join(s.text for s in sub)
        mark, color = "", None
        if held:
            mark, color = "◆", T.on_primary
        elif row["where"] == "failed":
            mark, color = "×", T.error
        elif row["where"] == "done":
            mark, color = "✓", T.success
        return w.row_item(display(name), width, subtitle=sub, selected=selected or held,
                          mark=mark, mark_color=color)

    return Entry(2, draw, key=name)


def queue_entries(rows: list[dict], facts: dict | None, at: str = "the window",
                  live: str = "", progress=None, held: str | None = None) -> list[Entry]:
    """The queued rows, in order, with the cut line between them.

    **Every row appears exactly once**, keyed on its name; the line is an
    entry of its own that the cursor cannot stop on and no tap can open
    (``selectable=False``, no key), which is the whole of how it stays
    computed rather than becoming an item. A night that reaches every row
    still gets its line, at the foot.
    """
    names = [r["name"] for r in rows]
    at_index, line, got = cut(names, facts)
    rule = Entry(1, lambda wd, sel, t=line: rule_block(t, wd), selectable=False)
    out: list[Entry] = []
    for i, r in enumerate(rows):
        if at_index is not None and i == at_index:
            out.append(rule)
        out.append(row_entry(r, got.get(r["name"], 0), at, live, progress,
                             held=r["name"] == held))
    if at_index is not None and at_index >= len(rows) and rows:
        out.append(rule)
    return out


# --------------------------------------------------------------------------- #
# The Queue tab
# --------------------------------------------------------------------------- #

GROUPS = ("queued", "failed", "done")


class QueueTab(Screen):
    """The window card, the three groups, the rows, the cut line."""

    def __init__(self, app) -> None:
        self.group = 0
        self.lists = {g: ListView() for g in GROUPS}
        #: ``(name, position)`` while a download is being moved.
        self.holding: tuple[str, int] | None = None
        self.hold_acc = 0
        self.asking_run: tui.Job | None = None

    @property
    def fullscreen(self) -> bool:
        return self.holding is not None

    def settle(self, app) -> None:
        """Let go of a held download that has left the queue meanwhile —
        finished, failed or removed while it was held — before the frame
        decides it is Move's: there is no place left to put it, and drawing
        one raised out of the loop and took the app down with it."""
        if self.holding is None:
            return
        name = self.holding[0]
        row = next((r for r in app.queue.rows if r["name"] == name), None)
        if row is not None and row["where"] == "queued":
            return
        self.holding = None
        went = {"done": "finished", "failed": "failed"}.get(row["where"] if row else "",
                                                             "left the queue")
        app.say(f"{display(name)} {went} while it was held")

    def shown(self, app) -> None:
        app.queue.read()
        app.queue.refresh(force=False)

    def wake(self, app) -> float | None:
        app.queue.tick()
        return None

    def rows(self, app, group: str) -> list[dict]:
        return [r for r in app.queue.rows if r["where"] == group]

    # Drawing --------------------------------------------------------------

    def card(self, app, width: int, run: bool) -> Piece:
        model = app.queue
        inner = width - 4
        tw = inner - (14 if run else 0)
        frac, fig = figures(model, tw)
        left = w.vstack(
            w.spans(verdict_line(model, tw), tw),
            w.bar(frac, tw),
            w.text(fig, tw, T.fg_more_subtle),
            width=tw,
        )
        body = (w.hstack(left, w.gap(1, 3), self.run_button(app, 13)) if run else left)
        block = (w.Style().border(w.rounded_border()).border_foreground(T.fg_most_subtle)
                 .padding(0, 1).width(width).render(body.block))
        return Piece(block, [h.moved(2, 1) for h in body.hits])

    def strip(self, app, width: int, run: bool) -> Piece:
        model = app.queue
        inner = width - (13 if run else 0)
        _, fig = figures(model, inner - 4)
        fig = fig.replace(" to spend", "")
        unset = bool(model.facts and model.facts["verdict"] == "unset")
        words = verdict_line(model, 0)[:1] + (
            [(f" · {fig}", T.fg_more_subtle)] if fig and not unset else [])
        left = (w.Style().border(w.rounded_border()).border_foreground(T.fg_most_subtle)
                .padding(0, 1).width(inner).render(w.spans(words, inner - 4)))
        return w.hstack(Piece(left), self.run_button(app, 13)) if run else Piece(left)

    def run_button(self, app, width: int) -> Piece:
        if self.asking_run is not None and not self.asking_run.finished:
            return w.button(f"{spin()}Run now", "", width, "off", id="run")
        facts = app.queue.facts
        if facts and facts["verdict"] == "unset":
            # Nothing to run against until an allowance is set.
            return w.button("Run now", "n", width, "off", id="run")
        return w.button("Run now", "n", width, "spend", id="run", pressed=app.pressed)

    def draw(self, app, s: Surface, height: int) -> None:
        if self.holding is not None and self.draw_moving(app, s, height):
            return
        W = s.width
        model = app.queue
        tiny = W < 36 and app.height < 13
        if tiny:
            word = verdict_line(model, 0)[0][0]
            fig = spend_figure(model)
            details = [f"{word} · {fig}" if fig else word]
        else:
            details = ["queue", time.strftime("%H:%M")] if W >= 36 else ["queue"]
        s.put(w.header(APP_NAME, details, W), 0, 0)
        y = 1
        if tiny:
            pass
        elif app.height < SHORT:
            s.put(self.strip(app, W, True), 0, y)
            y += 3
        else:
            s.put(self.card(app, W, True), 0, y)
            y += 5
        counts = [len(self.rows(app, g)) for g in GROUPS]
        names = [g.capitalize() + (f" {n}" if W >= 36 else "") for g, n in zip(GROUPS, counts, strict=True)]
        s.put(w.dock([Btn(n, "", "primary" if i == self.group else "normal", id=f"group:{i}",
                          data=i) for i, n in enumerate(names)], W, s.pressed), 0, y)
        y += 3
        if app.height >= SHORT:
            y += 1
        self.draw_rows(app, s, y, height - y)

    def entries(self, app, group: str, order: list[dict] | None = None,
                held: str | None = None) -> list[Entry]:
        model = app.queue
        rows = order if order is not None else self.rows(app, group)
        live = model.downloading_name()
        if group != "queued":
            return [row_entry(r, 0, "", live, model.progress) for r in rows]
        return queue_entries(rows, model.facts, model.window_word(), live, model.progress, held)

    def draw_rows(self, app, s: Surface, y: int, room: int) -> None:
        W = s.width
        group = GROUPS[self.group]
        view = self.lists[group]
        view.entries = self.entries(app, group)
        if not view.entries:
            empty = {"queued": "nothing queued — Search or Feed adds something",
                     "failed": "nothing has failed", "done": "nothing finished yet"}[group]
            s.put(w.wrapped(empty, W - 4, T.fg_most_subtle), 2, y)
            return
        fits = view.total_rows() <= room
        view.draw(s, 0, y, W, max(0, room), "row", bar=not fits)

    def draw_moving(self, app, s: Surface, height: int) -> bool:
        """Move's screen, or ``False`` (drawing nothing) when the held
        download is not queued any more and there is no place to show."""
        W = s.width
        name, pos = self.holding
        order = ui.preview(app.queue.rows, name, pos)
        queued = [r for r in order if r["where"] == "queued"]
        view = ListView()
        view.entries = self.entries(app, "queued", queued, held=name)
        held_index = next((i for i, e in enumerate(view.entries) if e.key == name), None)
        if held_index is None:
            self.settle(app)
            return False
        s.put(w.header(APP_NAME, [f"moving {display(name)}"], W), 0, 0)
        short = app.height < SHORT
        if short:
            s.put(self.strip(app, W, False), 0, 1)
            y = 4
        else:
            s.put(self.card(app, W, False), 0, 1)
            y = 6
        view.cursor = held_index
        top = y + (0 if short else 1)
        bottom = height - 3 - (0 if short else 1)
        view.height = bottom - top
        view.follow()
        view.draw(s, 0, top, W, bottom - top, "row-place", bar=view.total_rows() > bottom - top)
        if not short:
            s.put(w.text("  tap a row to put it there", W, T.fg_most_subtle), 0, height - 4)
        s.put(w.hstack(
            w.dock([Btn("↑", "", id="up"), Btn("↓", "", id="down"),
                    Btn("Put here", "⏎", "primary", id="put")], W - 14, s.pressed),
            w.button("Cancel", "esc", 14, id="cancel", pressed=s.pressed),
        ), 0, height - 3)
        self._place_view = view
        return True

    # Events ---------------------------------------------------------------

    def tap(self, app, hit, event) -> None:
        if self.holding is not None:
            self.tap_moving(app, hit, event)
            return
        group = GROUPS[self.group]
        if hit.id.startswith("group:"):
            self.group = hit.data
        elif hit.id == "run":
            self.run_now(app)
        elif hit.id == "row":
            self.open_row(app, self.lists[group].entries[hit.data].key)
        elif hit.id == "row-bar":
            self.lists[group].bar_tap(event.y)

    def open_row(self, app, name: str) -> None:
        model = app.queue
        row = next((r for r in model.rows if r["name"] == name), None)
        if row is None:
            return
        view = self.lists[row["where"]]
        view.cursor = next((i for i, e in enumerate(view.entries) if e.key == name), view.cursor)
        if model.downloading_name() == name:
            app.open(DownloadSheet(name))
        else:
            app.open(ItemSheet(row))

    def scroll(self, app, event) -> None:
        if self.holding is not None:
            self.hold_acc += event.dy
            while abs(self.hold_acc) >= 2:
                step = 1 if self.hold_acc > 0 else -1
                self.hold_acc -= 2 * step
                self.step_held(app, step)
            return
        view = self.lists[GROUPS[self.group]]
        if view.in_bar(event.x, event.y):
            view.bar_drag(event.dy)
        else:
            view.view(event.dy)

    def key(self, app, key: str) -> bool:
        if self.holding is not None:
            return self.key_moving(app, key)
        view = self.lists[GROUPS[self.group]]
        page = max(1, view.visible() - 1)
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
        if key in steps:
            view.move(steps[key])
            return True
        if key == "enter" and view.cursor >= 0:
            self.open_row(app, view.entries[view.cursor].key)
            return True
        if key == "n":
            self.run_now(app)
            return True
        if key in ("left", "right"):
            self.group = (self.group + (1 if key == "right" else -1)) % len(GROUPS)
            return True
        if key == "s":
            app.switch(4)
            return True
        if key == "l":
            open_runner_log(app)
            return True
        if key in ("x",) and app.queue.mine():
            app.open(DownloadSheet(app.queue.downloading_name(), follow=True))
            return True
        return False

    # Moving ---------------------------------------------------------------

    def hold(self, app, name: str) -> None:
        queued = [r["name"] for r in app.queue.rows if r["where"] == "queued"]
        if name not in queued:
            return
        self.group = 0
        self.holding = (name, queued.index(name))
        app.sheets.clear()
        app.guard.opened_by(app.last_tap)

    def step_held(self, app, step: int) -> None:
        name, pos = self.holding
        count = len([r for r in app.queue.rows if r["where"] == "queued"])
        self.holding = (name, max(0, min(count - 1, pos + step)))

    def drop(self, app) -> None:
        name, pos = self.holding
        self.holding = None
        said, moved = ui.do_reorder(app.queue.rows, name, pos)
        if moved:
            app.receipt(said)
        app.say(said)
        app.queue.changed()

    def tap_moving(self, app, hit, event) -> None:
        if hit.id == "up":
            self.step_held(app, -1)
        elif hit.id == "down":
            self.step_held(app, 1)
        elif hit.id == "put":
            self.drop(app)
        elif hit.id == "cancel":
            self.holding = None
        elif hit.id == "row-place":
            # The tapped row's place in the order as it is drawn, the held
            # row in it: the held download takes exactly that place. Counted
            # without it, a row below put it one place too high — the next
            # row down did nothing and the last place could not be tapped.
            view = self._place_view
            order = [e.key for e in view.entries if e.key]
            target = view.entries[hit.data].key
            if target in order:
                self.holding = (self.holding[0], order.index(target))
            self.drop(app)

    def key_moving(self, app, key: str) -> bool:
        if key in ("up", "down"):
            self.step_held(app, -1 if key == "up" else 1)
        elif key == "enter":
            self.drop(app)
        elif key in ("esc", "q"):
            self.holding = None
        return True

    # Run now -------------------------------------------------------------

    def run_now(self, app) -> None:
        model = app.queue
        if model.facts and model.facts["verdict"] == "unset":
            app.say("no daily allowance set: set it under More")
            return
        if model.mine() or model.live:
            app.say("something is downloading already")
            return
        if not any(r["where"] == "queued" for r in model.rows):
            app.say("nothing queued to run")
            return
        problem = ui.busy_problem()
        if problem:
            app.say(problem)
            return
        if self.asking_run is not None and not self.asking_run.finished:
            return
        self.asking_run = app.start(
            tui.Job(lambda: runner().snapshot(force=True, blind=True), "asking zwana",
                    key="run"), self)

    def done(self, app, job) -> None:
        if job is not self.asking_run:
            return
        self.asking_run = None
        if job.error is not None:
            app.say(f"could not read the queue: {job.error}")
            return
        offer = job.result
        if offer["verdict"] not in ("go", "blind"):
            # The runner's own words carry its UTC clock; the screen says the
            # same refusal in its own, on the phone's clock (design §6).
            said = ui.VERDICT_WORDS.get(offer["verdict"], offer["detail"])
            if offer["verdict"] == "early":
                said += f" · opens {shell.clock(offer['window_open'])}"
            app.say(f"not run: {said}")
            return
        app.open(run_sheet(app, offer))


def run_sheet(app, offer: dict) -> Confirm:
    """Run now's one yes. Blind: the warning border, the sentence, and the
    most the queued items declared. Counted: the window's allowance (the
    proposal in design §9, still open)."""
    model = app.queue
    figure = shell.size(max(0, offer["spendable"]))
    blind = offer["blind"]

    def go() -> None:
        log = model.firing.start(blind=blind)
        ui._note(f"started the whole queue now, outside the window (log {log.name})"
                 + (" — portal unreachable, uncounted data" if blind else ""))
        n = len(offer["items"])
        said = f"running the queue · {n} item{'s' if n != 1 else ''}"
        app.receipt(said)
        app.say(said)
        model.read()

    if blind:
        return Confirm(
            "Run now",
            "Zwana is not answering, so we do not know how much data we can spend. "
            "Proceed anyway?",
            [Choice("Run anyway", "y", "spend", f"· ≤{figure}", go), Choice("Not now", "esc")],
            grey="at most what the queue declared", border=T.warning)
    return Confirm(
        "Run now", "Run the queue now, before the window opens?",
        [Choice("Run now", "n", "spend", f"· {figure}", go), Choice("Not now", "esc")],
        grey=f"out of the {model.window_word()} window's allowance")


def open_runner_log(app) -> None:
    path = sched.LOGS / "runner.log"
    if not path.is_file():
        app.open(Notice("Runner log", ["the runner has not written a log yet",
                                       f"it would be {sched._short(path)}"]))
        return
    app.open(LogSheet("Runner log", path))


# --------------------------------------------------------------------------- #
# A download's sheet
# --------------------------------------------------------------------------- #

#: What each of ``actions_for()``'s keys is called on a button, and its kind.
ACTION_WORDS = {
    "n": ("Download now", "spend"),
    "u": ("Queue again", "normal"),
    "m": ("Move", "normal"),
    "r": ("Rename", "normal"),
    "t": ("Clear tries", "normal"),
    "o": ("Open it", "normal"),
    "l": ("Its log", "normal"),
    "d": ("Remove", "danger"),
}


def format_label(desc: str) -> str:
    found = re.search(r"\[([^\]]+)\]", desc or "")
    return found.group(1) if found else ""


class ItemSheet(Sheet):
    """One download, its facts, and ``actions_for()``'s actions as a grid."""

    def __init__(self, row: dict) -> None:
        super().__init__()
        self.name = row["name"]
        self.title = display(row["name"])
        self.opening: tui.Job | None = None

    def row(self, app) -> dict | None:
        return next((r for r in app.queue.rows if r["name"] == self.name), None)

    def body(self, app, width: int, height: int) -> Piece:
        row = self.row(app)
        if row is None:
            return Piece(w.text("it is not in the queue any more", width, T.fg_more_subtle))
        model = app.queue
        place = None
        queued = [r["name"] for r in model.rows if r["where"] == "queued"]
        if row["name"] in queued:
            place = (queued.index(row["name"]) + 1, len(queued))
        _, _, got = cut(queued, model.facts)
        part = share(row, got.get(row["name"], 0), model.window_word())
        tries = ""
        if row["attempts"] and row["where"] != "done":
            tries = f"try {row['attempts']}/{runner().MAX_ATTEMPTS}"
        elif row["where"] == "queued":
            tries = f"try 1/{runner().MAX_ATTEMPTS}"
        head = [(row["where"], T.fg_base)]
        rest = " · ".join(p for p in (f"{shell.ordinal(place[0])} of {place[1]}" if place else "",
                                      tries) if p)
        parts: list = []
        if height < SHORT:
            line = [(row["where"], T.fg_more_subtle)]
            if place:
                line.append((f" · {shell.ordinal(place[0])} of {place[1]}", T.fg_more_subtle))
            if part:
                line.append((f" · {part}", T.info))
            parts.append(w.spans(line, width))
        else:
            parts.append(w.spans(head + ([(f" · {rest}", T.fg_more_subtle)] if rest else []), width))
            parts.append(w.spans([(amount(row), T.fg_more_subtle)]
                                 + ([(f" · {part}", T.info)] if part else []), width))
            label = format_label(row["desc"])
            if row["files"]:
                where = f"here: {sched._short(row['files'][0])}"
            else:
                folder = Path(ytq.landing(row["dest"])).name or "out"
                where = f"→ {folder}/"
            parts.append(w.text(" ".join(p for p in (label, where) if p), width, T.fg_most_subtle))
            if row["error"]:
                parts.append(w.wrapped(f"rejected: {row['error']}", width, T.error))
            parts.append(w.gap(width))
        actions = ui.actions_for(row)
        grid = []
        for i in range(0, len(actions), 2):
            pair = actions[i:i + 2]
            grid.append(w.dock([Btn(ACTION_WORDS[k][0], k, ACTION_WORDS[k][1], id=f"act:{k}",
                                    data=k) for k, _ in pair], width, app.pressed))
        return w.vstack(*parts, *grid, width=width)

    def tap(self, app, hit, event) -> None:
        if hit.id.startswith("act:"):
            self.act(app, hit.data)

    def done(self, app, job) -> None:
        """Open it has come back from Android: the one opener's own sentence
        (``ytq.open_file``, which Open it when done says too)."""
        self.opening = None
        app.say(job.result if job.error is None else f"could not open {job.key.name}")

    def key(self, app, key: str) -> bool:
        row = self.row(app)
        if row is not None and key in dict(ui.actions_for(row)):
            self.act(app, key)
            return True
        return super().key(app, key)

    def act(self, app, key: str) -> None:
        row = self.row(app)
        if row is None:
            return
        model = app.queue
        if key == "m":
            app.close(self)
            app.tabs[3].hold(app, row["name"])
        elif key == "d":
            app.open(remove_sheet(app, row, self))
        elif key == "r":
            app.open(RenameSheet(row))
        elif key == "l":
            log = ui.item_log(row["name"])
            if log is None:
                app.open(Notice("Its log", ["it has not written a log yet"]))
            else:
                app.open(LogSheet(display(row["name"]), log))
        elif key == "o":
            # The file as the queue has it now, not as the row had it at the
            # last poll: that is up to a quarter of a minute old, and in it
            # the file can be delivered somewhere else or deleted.
            model.read()
            row = self.row(app)
            if row is None:
                return
            if not row["files"]:
                app.say("there is no file yet")
            else:
                # In the background: an opener that does not answer would
                # otherwise hold the whole app for its minute.
                target = row["files"][0]
                if self.opening is None or self.opening.finished:
                    self.opening = app.start(
                        tui.Job(lambda t=target: ytq.open_file(t), "opening it",
                                key=target, quiet=True), self)
        elif key in ("t", "u"):
            said = ui.do_clear_tries(row) if key == "t" else ui.do_requeue(row)
            worked = said.endswith("cleared") or said.endswith("is queued again")
            if worked:
                app.receipt(said)
            app.say(said)
            model.changed()
        elif key == "n":
            app.open(now_sheet(app, row, self))


class NowSheet(Confirm):
    """Download now's one yes, the figure on it being what is left to fetch.

    Its words wait on the fresh "does zwana answer" (asked as it opens):
    counted, it is today's allowance with no reserve kept; not, it is the
    Run now sentence, mobile data, charged, in the danger style and the
    warning border; not yet known, the yes is drawn but does nothing.
    """

    def __init__(self, app, row: dict, item: ItemSheet) -> None:
        super().__init__("Download now", "", [])
        self.row, self.item = row, item
        app.queue.check_reach()
        self.refresh(app)

    def refresh(self, app) -> None:
        row = self.row
        figure = f"· {shell.size(max(0, row['cap'] - row['have']))}"
        counted = app.queue.counted()
        if counted is None:
            self.question = "Asking whether zwana answers…"
            self.grey, self.border = "", None
            self.answers = [Choice("Download now", "y", "off", figure), Choice("Not now", "esc")]
        elif counted:
            self.question = f"Download {display(row['name'])} now, outside the window?"
            self.grey, self.border = "today's allowance, no reserve kept", None
            self.answers = [Choice("Download now", "y", "spend", figure, self.go),
                            Choice("Not now", "esc")]
        else:
            self.question = ("Zwana is not answering, so we do not know how much data we "
                             "can spend. Proceed anyway?")
            self.grey, self.border = "on mobile data, charged", T.warning
            self.answers = [Choice("Download anyway", "y", "danger", figure, self.go),
                            Choice("Not now", "esc")]
        self._app = app

    def draw(self, app, s: Surface, height: int) -> None:
        self.refresh(app)
        super().draw(app, s, height)

    def wake(self, app) -> float | None:
        return 0.1 if app.queue.counted() is None else None

    def go(self) -> None:
        app, row = self._app, self.row
        problem = ui.busy_problem()
        refused = [problem] if problem else app.queue.start_now(row["name"])
        if refused:
            app.open(Notice("Not started", refused))
            return
        app.close(self.item)
        said = f"downloading {display(row['name'])}"
        app.receipt(said if app.queue.counted() else f"{said} — not counted")
        app.say(said)


def now_sheet(app, row: dict, item: ItemSheet) -> Sheet:
    return NowSheet(app, row, item)


def remove_sheet(app, row: dict, item: ItemSheet) -> Confirm:
    """Both of ``removal_answers()``'s answers as full-width buttons, the one
    that deletes bytes in danger and never the default, No last."""
    note = ui.removal_note(row)

    def answer(bytes_too: bool):
        def go() -> None:
            said = ui.do_remove(row, bytes_too=bytes_too)
            if said.startswith("removed"):
                app.receipt(said)
                app.close(item)
            app.say(said)
            app.queue.changed()
        return go

    answers = []
    for keys, words in ui.removal_answers(row):
        deletes = keys == "b"
        answers.append(Choice(words[:1].upper() + words[1:], keys[0],
                              "danger" if deletes else "normal", act=answer(deletes),
                              also=keys[1:]))
    answers.append(Choice("No", "esc"))
    return Confirm("Remove", note[0][:1].upper() + note[0][1:], answers,
                   grey=" · ".join(note[1:]))


# --------------------------------------------------------------------------- #
# The running download
# --------------------------------------------------------------------------- #


class DownloadSheet(Sheet):
    """One reading per draw, so the words and the bar cannot disagree.

    Opened from a row it is that download's. Opened by ``x`` it *follows* our
    own run: Run now downloads one item after another and none at all while
    it starts, so the sheet takes up each item the run starts. Bound to what
    was downloading the moment it opened — nothing, often — it was a sheet
    with no name that said "downloading" over nothing and "stopped" over the
    item the run then fetched.
    """

    def __init__(self, name: str, follow: bool = False) -> None:
        super().__init__()
        self.follow = follow
        self.name = name
        self.title = display(name) if name else "Run now"

    def keep_up(self, app) -> None:
        """While following our own run, take up the item it is downloading;
        between two items, and once it ends, stay on the last one."""
        model = app.queue
        name = model.downloading_name()
        if self.follow and model.mine() and name and name != self.name:
            self.name, self.title = name, display(name)

    def live(self, app) -> bool:
        """Whether this sheet's download is the one downloading: never while
        it has none, or a sheet with no name read as live over nothing."""
        return bool(self.name) and app.queue.downloading_name() == self.name

    def draw(self, app, s: Surface, height: int) -> None:
        self.keep_up(app)
        super().draw(app, s, height)

    def mine(self, app) -> bool:
        r = app.queue.running
        return r.alive and r.name == self.name

    def where(self, app) -> str:
        """Where its item is now: ``queued`` while it runs or after a stop,
        ``done`` once the runner has archived it, or ``failed``."""
        row = next((r for r in app.queue.rows if r["name"] == self.name), None)
        return row["where"] if row else ""

    def body(self, app, width: int, height: int) -> Piece:
        model = app.queue
        if not self.name:
            # Following a run that has not started an item: the status bar's
            # own words for it, and Pause while there is a run to pause.
            said = "starting the queue" if model.mine() else "the run has ended"
            return w.vstack(w.text(said, width, T.fg_base), w.gap(width),
                            self.buttons(app, width), width=width)
        have, total, rate = model.progress(self.name)
        short = height < SHORT
        live = self.live(app)
        where = self.where(app)
        ended = not live and where in ("done", "failed")
        when = "now" if self.mine(app) or model.firing.alive else "in the window"
        if live:
            head = [("downloading", T.attention)]
        elif where == "done":
            head = [("done", T.success)]
        elif where == "failed":
            head = [("failed", T.error)]
        else:
            head = [("stopped", T.fg_base)]
        tail = shell.left(model.time_left(self.name))
        if not ended:
            head.append((f" · {when}" + (f" · {tail} left" if tail and live else ""),
                         T.fg_more_subtle))
        parts: list = [w.spans(head, width)]
        if not short:
            parts.append(w.gap(width))
        frac = 1.0 if where == "done" else have / total if total else 0.0
        parts.append(w.progress_bar(frac, width))
        figure = f"{shell.size(have)} of {shell.size(total)}" if total else shell.size(have)
        if rate > 0:
            figure += f" · {shell.size(rate)}/s"
        parts.append(w.text(figure, width, T.fg_more_subtle))
        if not short:
            parts.append(w.gap(width))
        r = model.running
        if r.askable and r.name == self.name:
            parts.append(w.checkbox("Open it when done", r.open_when_done, width, id="open"))
        elif self.asked(app) and not live:
            # Where the checkbox was: what opening it came to.
            parts.append(w.text(r.opened or "opening it…", width,
                                T.fg_more_subtle if r.opened else T.info))
        parts.append(self.buttons(app, width))
        return w.vstack(*parts, width=width)

    def buttons(self, app, width: int) -> Piece:
        if app.queue.mine():
            return w.dock([Btn("Pause", "x", id="pause"), Btn("Back", "esc", id="back")],
                          width, app.pressed)
        return w.button("Back", "esc", width, id="back", pressed=app.pressed)

    def asked(self, app) -> bool:
        """Whether this session's run of it was asked to open when done, and
        did not stop short of it."""
        r = app.queue.running
        return bool(self.name) and r.name == self.name and r.open_when_done and not r.stopped

    def wake(self, app) -> float | None:
        self.keep_up(app)
        r = app.queue.running
        if self.live(app) or (self.asked(app) and not r.settled):
            return LIVE_POLL
        return None

    def tap(self, app, hit, event) -> None:
        if hit.id == "open":
            app.queue.running.toggle_open()
        elif hit.id == "pause":
            self.pause(app)
        elif hit.id == "back":
            app.close(self)

    def pause(self, app) -> None:
        said = ""
        model = app.queue
        if model.running.alive:
            model.running.stop()
            said = "paused; what is downloaded is kept"
        elif model.firing.alive:
            model.firing.stop()
            said = "paused the run; what is downloaded is kept"
        if said:
            app.say(said)
            app.close(self)

    def key(self, app, key: str) -> bool:
        if key == "x":
            self.pause(app)
            return True
        if key == "o" and app.queue.running.askable:
            app.queue.running.toggle_open()
            return True
        return super().key(app, key)


# --------------------------------------------------------------------------- #
# Text in a sheet: rename, a log
# --------------------------------------------------------------------------- #


class FieldSheet(Sheet):
    """A sheet with one text field, its rule in grey, preset buttons, and
    ``esc Cancel`` / ``⏎ Set`` pinned at the bottom. A refused value is said
    inside the sheet in red, and nothing is written."""

    typing = True
    presets: list[tuple[str, str]] = []
    rule = ""

    def __init__(self, title: str, value: str) -> None:
        super().__init__()
        self.title = title
        self.value = value
        self.problem = ""
        self.focus = False

    def body(self, app, width: int, height: int) -> Piece:
        parts: list = [w.field(self.value, width, focus=self.focus or height < SHORT, id="field")]
        if self.rule:
            parts.append(w.text(self.rule, width, T.fg_most_subtle))
        if self.problem:
            parts.append(w.wrapped(self.problem, width, T.error, limit=3))
        if self.presets:
            parts.append(w.dock([Btn(word, "", "primary" if value == self.value else "normal",
                                     id=f"preset:{i}", data=value)
                                 for i, (word, value) in enumerate(self.presets)],
                                width, app.pressed))
        return w.vstack(*parts, width=width)

    def footer(self, app, width: int, height: int) -> Piece:
        return w.dock([Btn("Cancel", "esc", id="cancel"), Btn("Set", "⏎", "primary", id="set")],
                      width, app.pressed)

    def tap(self, app, hit, event) -> None:
        if hit.id == "field":
            self.focus = True
        elif hit.id.startswith("preset:"):
            self.value = hit.data
            self.problem = ""
        elif hit.id == "cancel":
            app.close(self)
        elif hit.id == "set":
            self.submit(app)

    def key(self, app, key: str) -> bool:
        if key == "esc":
            app.close(self)
        elif key == "enter":
            self.submit(app)
        elif key == "backspace":
            self.value = self.value[:-1]
        elif key == "ctrl-u":
            self.value = ""
        elif len(key) == 1 and self.accepts(key):
            self.value += key
            self.focus = True
        return True

    def paste(self, app, text: str) -> None:
        """A paste (``tui.Paste``): what the field takes of it, typed in
        whole. Never a submit — Set or ⏎ is."""
        self.value += "".join(ch for ch in text if self.accepts(ch))
        self.focus = True

    def accepts(self, ch: str) -> bool:
        return True

    def submit(self, app) -> None:
        raise NotImplementedError


class RenameSheet(FieldSheet):
    def __init__(self, row: dict) -> None:
        super().__init__("Rename", display(row["name"]))
        self.row = row
        self.rule = "the file keeps the name it was downloaded with"

    def submit(self, app) -> None:
        prefix = re.match(r"^(\d{2,})-", self.row["name"])
        new = f"{prefix.group(1)}-{ytq.title_name(self.value)}.py" if prefix else ""
        if not new or new == self.row["name"]:
            app.close(self)
            return
        said = ui.do_rename(self.row, new)
        if said.startswith("now "):
            app.receipt(said)
            app.say(said)
            app.queue.changed()
            app.close(self)
            item = next((s for s in app.sheets if isinstance(s, ItemSheet)), None)
            if item is not None:
                item.name, item.title = new, display(new)
        else:
            self.problem = said


class LogSheet(Sheet):
    """A log, its newest lines last, scrolled to the end."""

    def __init__(self, title: str, path: Path) -> None:
        super().__init__()
        self.title = title
        self.path = path
        self.offset = 10**9

    def body(self, app, width: int, height: int) -> Piece:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = f"could not read it: {exc}"
        lines = text.splitlines()[-400:] or ["(empty)"]
        return w.vstack(*[w.wrapped(line or " ", width - 1, T.fg_more_subtle) for line in lines],
                        width=width)

    def key(self, app, key: str) -> bool:
        steps = {"up": -1, "down": 1, "pgup": -10, "pgdn": 10}
        if key in steps:
            self.offset = max(0, self.offset + steps[key])
            return True
        return super().key(app, key)


# --------------------------------------------------------------------------- #
# More: the settings and the rest
# --------------------------------------------------------------------------- #

#: What each setting means, in the screen's words (design §5, ``k-more``).
#: A setting the runner grows and this does not name says its own label.
MEANINGS = {
    "reserve": "kept back, never spent",
    "reserve-when-paid": "keep it when paid data is there",
    "paid-min": "paid data needed to waive it",
    "auto": "the nightly job downloads",
    "notify-blocked": "say when a firing is blocked",
}

#: One key per setting, every one of ``expire_runner.SETTINGS``: a setting the
#: runner grows and this does not name still has a row (it is tappable), but a
#: test fails until it has a key. ``p`` is reserve-when-*p*aid, ``m`` the
#: *m*inimum of paid data, ``n`` the *n*otification. Never ``q`` or ``x``.
SETTING_KEYS = {
    "window": "w",
    "reserve": "r",
    "reserve-when-paid": "p",
    "paid-min": "m",
    "auto": "a",
    "notify-blocked": "n",
    # The budget source's (where the runner has one): b for budget, g for
    # the allowance in GB-ish figures (l is the runner log), t for the time
    # it resets.
    "budget": "b",
    "allowance": "g",
    "reset": "t",
}

#: The order the settings are listed in on More, where it is not
#: ``SETTINGS``' own: the budget source sits under the reserve (its proposal
#: in design/divergences.md). Anything not named keeps its place after these.
ORDER = ("window", "reserve", "reserve-when-paid", "paid-min", "budget", "allowance",
         "reset", "auto", "notify-blocked")


def shown_settings(values: dict) -> list[str]:
    """Which settings are rows, in order: ``paid-min`` only while the waiver
    is on, ``allowance`` and ``reset`` only while the budget is manual."""
    r = runner()
    shown = getattr(r, "settings_shown", None)
    # The runner's own answer for which settings apply to the source, where it
    # has one (``only`` on each spec); the ordering and the waiver are More's.
    applies = set(shown(values.get("budget"))) if shown else set(values)
    names = [n for n in ORDER if n in values] + [n for n in values if n not in ORDER]
    out = []
    for name in names:
        if name not in applies:
            continue
        if name == "paid-min" and values.get("reserve-when-paid", True):
            continue
        if name in ("allowance", "reset") and values.get("budget", "manual") != "manual":
            continue
        out.append(name)
    return out

#: And the rows below the settings, by what they do.
PAGE_KEYS = {"skip": "c", "chips": "h", "dests": "d", "job": "j", "log": "l", "quit": "q"}

#: Preset values for the number settings, so most changes need no typing.
PRESETS = {
    "window": [("30m", "30"), ("45m", "45"), ("1h", "60"), ("2h", "120")],
    "reserve": [("0", "0"), ("50 MB", "50"), ("100 MB", "100"), ("250 MB", "250")],
    "paid-min": [("0", "0"), ("50 MB", "50"), ("100 MB", "100"), ("500 MB", "500")],
    "allowance": [("500 MB", "500"), ("1 GB", "1000"), ("2 GB", "2000"), ("5 GB", "5000")],
}


def reset_word(values: dict | None = None) -> str:
    """When the allowance resets, on the phone's clock: the manual budget's
    own reset where there is one, else 00:00 UTC (the portal's day)."""
    values = values or {}
    if values.get("budget") == "manual" and "reset" in values:
        return runner().spell_setting("reset", values["reset"])
    now = time.time()
    midnight = (int(now // 86400) + 1) * 86400
    return time.strftime("%H:%M", time.localtime(midnight))


class MoreTab(Screen):
    """The settings as one scrolling list of two-line rows, then the
    destinations, the nightly job, the runner log and Quit."""

    def __init__(self, app) -> None:
        self.view = ListView()
        self.job_rows: list | None = None
        self.job_job: tui.Job | None = None
        self.arming: tui.Job | None = None

    def shown(self, app) -> None:
        if self.job_job is None or self.job_job.finished:
            self.job_job = app.start(tui.Job(sched.job_rows, "asking Android's scheduler",
                                             key="jobs"), self)

    def done(self, app, job) -> None:
        if job is self.job_job:
            self.job_job = None
            self.job_rows = job.result if job.error is None else [
                ("job", f"could not read it: {job.error}", "1;31")]
        elif job is self.arming:
            self.arming = None
            if job.error is not None:
                app.say(str(job.error), T.error)
                return
            worked, text = job.result
            if worked:
                app.receipt(text)
                ui._note(f"{job.key} the nightly job from the screen: {text}")
            app.say(text, None if worked else T.error)
            self.shown(app)

    def items(self, app) -> list[tuple]:
        """``(key, name, value, meaning, value colour, action)`` per row."""
        r = runner()
        values = r.settings()
        out = []
        for name in shown_settings(values):
            spec = r.SETTINGS[name]
            value = r.spell_setting(name, values[name])
            if spec["kind"] == "bool":
                on = bool(values[name])
                value = f"{w.glyphs.RADIO_ON if on else w.glyphs.RADIO_OFF} {value}"
            meaning = MEANINGS.get(name, spec["label"])
            if name == "window":
                meaning = f"ahead of the reset, at {reset_word(values)} here"
            stored, problem, _ = r.setting_state(name)
            out.append((SETTING_KEYS.get(name, ""), name.replace("-", " "), value, meaning, None, ("setting", name),
                        f"config.json says {stored!r}: {problem}" if problem else ""))
        prefs = ytq.prefs()
        skip = ytq.skip_codecs(prefs)
        out.append((PAGE_KEYS["skip"], "skip codecs", " ".join(skip) or "none",
                    "the quality buttons pass these over", None, ("skip",), ""))
        chips = ytq.chip_heights(prefs)
        out.append((PAGE_KEYS["chips"], "quality chips", f"{chips[0]}-{chips[-1]}" if chips else "",
                    "set by hand" if isinstance(prefs.get("chips"), list) and prefs.get("chips")
                    else "learned from what you pick", None, ("chips",), ""))
        dests = r.dests()
        folders = {str(p) for p in dests.values()}
        one = next(iter(dests.values()))
        out.append((PAGE_KEYS["dests"], "destinations", one.name if len(folders) == 1 else f"{len(folders)} folders",
                    "where finished files land", None, ("dests",), ""))
        if self.arming is not None and not self.arming.finished:
            job_value, job_fg = f"{spin()}asking", None
        elif self.job_rows is None:
            job_value, job_fg = "…", None
        else:
            armed = ui.armed(self.job_rows)
            job_value = "armed" if armed else "not armed"
            job_fg = T.success if armed else T.warning
        out.append((PAGE_KEYS["job"], "nightly job", job_value, "every 15m in the window", job_fg, ("job",), ""))
        out.append((PAGE_KEYS["log"], "runner log", "", "what the nightly job did and why", None, ("log",), ""))
        out.append((PAGE_KEYS["quit"], "quit", "", "leave nibbles", None, ("quit",), ""))
        return out

    def draw(self, app, s: Surface, height: int) -> None:
        W = s.width
        s.put(w.header(APP_NAME, ["settings"], W), 0, 0)
        y = 1
        broken = runner().config_problem()
        if broken:
            block = w.wrapped(f"× {broken}", W - 2, T.error, limit=2)
            s.put(block, 1, y)
            y += block.height
        entries = []
        for key, name, value, meaning, fg, action, problem in self.items(app):
            def draw(width, selected, k=key, n=name, v=value, m=meaning, f=fg, p=problem):
                block = w.setting_row(k, n, v, m, width, selected, f)
                if p:
                    block = w.vstack(block, w.text("   " + p, width, T.error)).block
                return block
            entries.append(Entry(3 if problem else 2, draw, key=action))
        self.view.entries = entries
        room = height - y - (1 if app.height >= SHORT else 0)
        self.view.draw(s, 0, y, W, max(0, room), "row")

    def tap(self, app, hit, event) -> None:
        if hit.id == "row":
            self.act(app, self.view.entries[hit.data].key)
        elif hit.id == "row-bar":
            self.view.bar_tap(event.y)

    def scroll(self, app, event) -> None:
        if self.view.in_bar(event.x, event.y):
            self.view.bar_drag(event.dy)
        else:
            self.view.view(event.dy)

    def key(self, app, key: str) -> bool:
        for k, _, _, _, _, action, _ in self.items(app):
            if k and key == k:
                self.act(app, action)
                return True
        page = max(1, self.view.visible() - 1)
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
        if key in steps:
            self.view.move(steps[key])
            return True
        if key == "enter" and self.view.cursor >= 0:
            self.act(app, self.view.entries[self.view.cursor].key)
            return True
        return False

    def act(self, app, action: tuple) -> None:
        what = action[0]
        r = runner()
        if what == "setting":
            name = action[1]
            spec = r.SETTINGS[name]
            if spec["kind"] in ("bool", "choice"):
                value = r.settings()[name]
                words = list(spec["words"])
                if spec["kind"] == "bool":
                    nxt = words[1] if value else words[0]
                else:
                    # A choice toggles like a switch, to the next of its words.
                    nxt = words[(words.index(value) + 1) % len(words)] if value in words else words[0]
                worked, told = sched.set_setting(name, nxt)
                said = told[-1] if told else ""
                if worked:
                    app.receipt(said)
                    ui._note(f"{name} is now {r.spell_setting(name, r.settings()[name])}")
                    app.queue.refresh()
                app.say(said, None if worked else T.error)
            else:
                app.open(SettingSheet(name))
        elif what == "skip":
            app.open(SkipSheet())
        elif what == "chips":
            app.open(ChipsSheet())
        elif what == "dests":
            app.open(DestSheet())
        elif what == "job":
            if self.job_rows is not None and ui.armed(self.job_rows):
                app.open(Confirm("Nightly job", "Stop the nightly job? Nothing downloads by "
                                 "itself after this; the queue is untouched.",
                                 [Choice("Stop it", "y", "danger",
                                         act=lambda: self.arm(app, sched.do_cancel, "unregistered")),
                                  Choice("Not now", "esc")]))
            else:
                self.arm(app, sched.do_arm, "armed")
        elif what == "log":
            open_runner_log(app)
        elif what == "quit":
            app.quit()

    def arm(self, app, work, verb: str) -> None:
        if self.arming is not None and not self.arming.finished:
            return
        self.arming = app.start(tui.Job(work, "asking Android's scheduler", key=verb), self)


class SettingSheet(FieldSheet):
    """A number setting: the field prefilled, its rule, the presets."""

    def __init__(self, name: str) -> None:
        r = runner()
        spec = r.SETTINGS[name]
        value = r.settings()[name]
        # A time of day is shown, and typed, on the phone's clock.
        shown = r.spell_setting(name, value) if spec["kind"] == "clock" else str(value)
        super().__init__(name, shown)
        self.name = name
        self.kind = spec["kind"]
        self.presets = PRESETS.get(name, [])
        if spec["kind"] == "clock":
            self.rule = "a time of day on this phone's clock, like 04:00"
        elif spec.get("zero") and "min" in spec:
            self.rule = f"MB a day; 0 is {spec['zero']}"
        elif spec["kind"] == "minutes":
            hours = spec["max"] // 60
            self.rule = (f"a multiple of {spec['step']}, {spec['min']} min to {hours} h"
                         if spec["step"] > 1 else f"{spec['min']} to {spec['max']} min")
        else:
            self.rule = f"{spec['min']} to {spec['max']} MB"

    def accepts(self, ch: str) -> bool:
        return ch.isdigit() or (self.kind == "clock" and ch == ":")

    def submit(self, app) -> None:
        worked, told = sched.set_setting(self.name, self.value or "default")
        said = told[-1] if told else ""
        if not worked:
            self.problem = said or "not a value it takes"
            return
        r = runner()
        app.receipt(said)
        ui._note(f"{self.name} is now {r.spell_setting(self.name, r.settings()[self.name])}")
        app.say(said)
        app.queue.refresh()
        app.close(self)


class SkipSheet(FieldSheet):
    def __init__(self) -> None:
        super().__init__("skip codecs", " ".join(ytq.skip_codecs()))
        self.rule = "codec families the quality buttons pass over"
        self.presets = [("av01 vp9", "av01 vp9"), ("av01", "av01"), ("vp9", "vp9"), ("none", "")]

    def submit(self, app) -> None:
        families = [f for f in re.split(r"[\s,]+", self.value.lower()) if f]
        problem = ytq.save_prefs({"skip": families})
        if problem:
            self.problem = problem
            return
        said = f"skip codecs: {' '.join(families) or 'none'}"
        app.receipt(said)
        app.say(said)
        app.close(self)


class ChipsSheet(FieldSheet):
    def __init__(self) -> None:
        prefs = ytq.prefs()
        chips = prefs.get("chips") if isinstance(prefs.get("chips"), list) else None
        super().__init__("quality chips", " ".join(str(h) for h in chips) if chips else "learned")
        self.rule = "heights for the quality buttons, or learned"
        self.presets = [("learned", "learned"), ("240-720", "240 480 720"),
                        ("360-1080", "360 720 1080")]

    def submit(self, app) -> None:
        text = self.value.strip().lower()
        if text in ("", "learned", "default"):
            problem = ytq.save_prefs({"chips": None})
            said = "quality chips: learned from what you pick"
        else:
            try:
                heights = sorted({int(h.rstrip("p")) for h in re.split(r"[\s,]+", text) if h})
            except ValueError:
                self.problem = "heights are numbers: 240 480 720"
                return
            if not heights or any(h <= 0 for h in heights):
                self.problem = "heights are numbers: 240 480 720"
                return
            problem = ytq.save_prefs({"chips": heights})
            said = f"quality chips: {' '.join(f'{h}p' for h in heights)}"
        if problem:
            self.problem = problem
            return
        app.receipt(said)
        app.say(said)
        app.close(self)


class DestSheet(Sheet):
    """Where finished downloads go: every destination; a tap changes one."""

    title = "Destinations"

    def body(self, app, width: int, height: int) -> Piece:
        r = runner()
        config = r.load_config()
        parts = []
        for kind, where in r.dests().items():
            note = "set" if config.get(f"{kind}_dir") else "default"
            problem = r.dest_problem(where)
            block = w.row_item(f"{kind} · {sched._short(where)}", width,
                               subtitle=f"{note}, used by {sched.FILLED_BY[kind]}")
            parts.append(w.piece(block, f"dest:{kind}", kind))
            if problem:
                parts.append(w.wrapped(f"× {problem}", width, T.error, limit=2))
        return w.vstack(*parts, width=width)

    def tap(self, app, hit, event) -> None:
        if hit.id.startswith("dest:"):
            app.open(PathSheet(hit.data))


class PathSheet(FieldSheet):
    def __init__(self, kind: str) -> None:
        super().__init__(kind, str(runner().dests()[kind]))
        self.kind = kind
        self.rule = "one level is created if it is not there"
        self.presets = [("default", "default")]

    def submit(self, app) -> None:
        worked, told = sched.set_dest(self.kind, self.value or "default")
        said = told[-1] if told else ""
        if not worked:
            self.problem = said or "that folder is refused"
            return
        app.receipt(said)
        ui._note(f"{self.kind} downloads now go to {runner().dests()[self.kind]}")
        app.say(said)
        app.close(self)
