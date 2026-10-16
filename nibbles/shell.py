"""What every nibbles screen shares: words, the list, the sheet, the confirm.

The screens are :class:`Screen` objects. Each draws itself onto a
:class:`widgets.Surface` (pure: it reads state and draws, nothing else) and
handles the events the app hands it. A tab is a screen; a sheet is a screen
that sits over a tab, dimming it, and closes. The app (``app.py``) owns the
loop, the guards and which screen is on top.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from nibbles import tui
from nibbles import widgets as w
from bewitch.bubbles.spinner import Dot
from nibbles.widgets import T, Piece, Surface

# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #


#: What a size is counted in above a thousand bytes, smallest first.
UNITS = ("KiB", "MiB", "GiB", "TiB")


def size(n: float) -> str:
    """``92 MiB``, ``10.2 MiB``, ``1.02 GiB``: three figures at most.

    The one spelling of a size on these screens, so the figure on a button
    and the figure above it cannot come out different. The unit and the
    places are chosen by the figure as it will be printed, not as it stands:
    999.7 KiB would print as ``1000``, so it is ``0.98 MiB``, and 9.997 MiB
    is ``10 MiB`` and not ``10.00 MiB`` (``round`` and the format agree).
    """
    n = max(0.0, float(n))
    if round(n) < 1000:
        return f"{n:.0f} B"
    for unit in UNITS:
        n /= 1024
        if round(n) < 1000 or unit == UNITS[-1]:
            break
    if round(n, 1) >= 100:
        return f"{n:.0f} {unit}"
    if round(n, 2) >= 10:
        return f"{n:.1f} {unit}".replace(".0 ", " ")
    return f"{n:.2f} {unit}"


def mb(n: float) -> str:
    """``~0.3 MB``-style figures for what a fetch costs (decimal, one place)."""
    return f"{n / 1e6:.1f} MB"


def left(seconds: float | None) -> str:
    """Time left in one unit, the largest that is at least 1, rounded:
    ``35s``, ``5m``, ``1h`` — never ``1h11m``. ``""`` for no time at all."""
    if seconds is None or math.isinf(seconds) or seconds != seconds:
        return ""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}s"
    m = round(s / 60)
    if m < 60:
        return f"{m}m"
    h = round(s / 3600)
    if h < 24 * 2:
        return f"{h}h"
    return f"{round(s / 86400)}d"


def ago(seconds: float) -> str:
    """``3m ago``, ``just now``."""
    if seconds < 45:
        return "just now"
    return f"{left(seconds)} ago"


def clock(epoch: float, now: float | None = None) -> str:
    """When *epoch* is, on the phone's own clock: ``03:00`` within the next
    twelve hours (or the last twelve), else ``today 14:00`` or ``tomorrow
    03:00``. Never UTC: the window is named by when it opens where you are."""
    if math.isinf(epoch) or epoch != epoch:
        return "no stop time"
    now = time.time() if now is None else now
    # To the nearest minute: the portal's reset lands seconds either side of
    # the hour, and a window opening at 02:59:58 opens at 03:00 to a person.
    epoch = round(epoch / 60) * 60
    hm = time.strftime("%H:%M", time.localtime(epoch))
    if abs(epoch - now) < 12 * 3600:
        return hm
    day = time.localtime(epoch)
    today = time.localtime(now)
    if (day.tm_year, day.tm_yday) == (today.tm_year, today.tm_yday):
        return f"today {hm}"
    tomorrow = time.localtime(now + 86400)
    if (day.tm_year, day.tm_yday) == (tomorrow.tm_year, tomorrow.tm_yday):
        return f"tomorrow {hm}"
    return time.strftime("%a %H:%M", day)


SPINNER = Dot


def spin(tick: float | None = None) -> str:
    """The spinner's frame for now (Bubbles' Dot, ten frames a second)."""
    t = time.monotonic() if tick is None else tick
    return SPINNER.frame(int(t * SPINNER.fps))


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #


class Screen:
    """A tab or a sheet. Every method has a do-nothing default."""

    #: Set by a screen that holds the keyboard (a focused text field): its
    #: keys are typed, and ``q`` is a letter rather than quit.
    typing = False
    #: Set by a tab that takes the whole screen, the tab bar too (Move).
    fullscreen = False

    def draw(self, app, s: Surface, height: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def tap(self, app, hit: w.Hit, event: tui.Tap) -> None:
        pass

    def scroll(self, app, event: tui.Scroll) -> None:
        pass

    def key(self, app, key: str) -> bool:
        return False

    def done(self, app, job: tui.Job) -> None:
        pass

    def wake(self, app) -> float | None:
        """Seconds until this screen next needs drawing, or ``None``."""
        return None

    def tick(self, app, now: float | None = None) -> None:
        """Time has passed (the loop goes round): act on whatever was waiting
        for it. Asked of the tab on top, before each frame."""

    def shown(self, app) -> None:
        """Called each time it comes to the top."""


class Sheet(Screen):
    """A sheet from the bottom over a dimmed tab.

    Subclasses give :meth:`body` and :meth:`footer`; this draws them in the
    house sheet (title, ``esc ×``, the border in ``primary`` or ``warning``),
    pinned when it does not fit. ``esc`` and a tap on the dimmed part close it.
    """

    title = ""
    border = None
    #: The highest row a sheet may reach: the header stays.
    top = 1

    def __init__(self) -> None:
        self.offset = 0
        self.layout: w.SheetLayout | None = None

    def body(self, app, width: int, height: int) -> Piece:
        return w.gap(width, 0)

    def footer(self, app, width: int, height: int) -> Piece | None:
        return None

    def draw(self, app, s: Surface, height: int) -> None:
        inner = s.width - 4
        self.layout = w.sheet(
            s, self.top, self.title, self.body(app, inner, s.height),
            self.footer(app, inner, s.height), self.border, self.offset,
            pressed=app.pressed,
        )
        self.offset = self.layout.offset

    def scroll(self, app, event: tui.Scroll) -> None:
        if self.layout and self.layout.scrolls:
            self.offset = max(0, min(self.offset + event.dy,
                                     self.layout.total - self.layout.room))

    def key(self, app, key: str) -> bool:
        if key == "esc":
            app.close(self)
            return True
        return False


@dataclass
class Choice:
    """One answer on a confirm: a button, and what it does."""

    word: str
    key: str
    kind: str = "normal"
    note: str = ""
    act: Callable[[], None] | None = None
    #: Other keys that give the same answer (``removal_answers``' ``"yb"``:
    #: one answer wearing two keys, so the keys never vary with the item).
    also: str = ""


class Confirm(Sheet):
    """Every confirm is a sheet like this: the question, an optional grey
    line, then the answers as full-width buttons, the yes first with the
    figure on it, No last. Pinned, so the answers are always on screen."""

    def __init__(self, title: str, question: str, answers: Sequence[Choice],
                 grey: str = "", border=None, said: str = "") -> None:
        super().__init__()
        self.title = title
        self.question = question
        self.answers = list(answers)
        self.grey = grey
        self.border = border
        self.said = said

    def body(self, app, width: int, height: int) -> Piece:
        parts: list = [w.wrapped(self.question, width)]
        if height >= SHORT and self.grey:
            parts += [w.gap(width), w.text(self.grey, width, T.fg_most_subtle), w.gap(width)]
        if self.said:
            parts.append(w.wrapped(self.said, width, T.error))
        return w.vstack(*parts, width=width)

    def footer(self, app, width: int, height: int) -> Piece:
        return w.vstack(*[
            w.button(a.word, a.key, width, a.kind, a.note, id=f"answer:{i}", data=i,
                     pressed=app.pressed)
            for i, a in enumerate(self.answers)
        ], width=width)

    def _answer(self, app, i: int) -> None:
        a = self.answers[i]
        if a.kind == "off":
            return
        app.close(self)
        if a.act is not None:
            a.act()

    def tap(self, app, hit, event) -> None:
        if hit.id.startswith("answer:"):
            self._answer(app, hit.data)

    def key(self, app, key: str) -> bool:
        for i, a in enumerate(self.answers):
            keys = {{"⏎": "enter"}.get(a.key, a.key), *a.also}
            if key in keys:
                self._answer(app, i)
                return True
        return super().key(app, key)


class Notice(Sheet):
    """Something the app has to say at length: a refusal, the cookie advice,
    a fetch that did not come back. Lines wrapped, then ``esc OK``."""

    def __init__(self, title: str, lines: Sequence[str], border=None) -> None:
        super().__init__()
        self.title = title
        self.lines = [line for line in lines if line]
        self.border = border

    def body(self, app, width: int, height: int) -> Piece:
        parts = []
        for i, line in enumerate(self.lines):
            parts.append(w.wrapped(line, width, T.fg_base if i == 0 else T.fg_more_subtle))
        return w.vstack(*parts, width=width)

    def footer(self, app, width: int, height: int) -> Piece:
        return w.button("OK", "esc", width, "normal", id="ok", pressed=app.pressed)

    def tap(self, app, hit, event) -> None:
        if hit.id == "ok":
            app.close(self)

    def key(self, app, key: str) -> bool:
        if key in ("enter", "esc", "q"):
            app.close(self)
            return True
        return False


#: Below this many rows the compact rules apply (design §3).
SHORT = 16


# --------------------------------------------------------------------------- #
# Lists
# --------------------------------------------------------------------------- #


@dataclass
class Entry:
    """One thing in a list: how tall it is, whether the cursor may stop on it,
    and how to draw it (``draw(width, selected) -> Block``)."""

    height: int
    draw: Callable[[int, bool], w.Block]
    key: object = None
    selectable: bool = True


@dataclass
class ListView:
    """A scrolling list with a cursor, Helix's way.

    A swipe moves the view; the cursor stays on its row until it comes within
    one item of the edge, then rides along one item in (``scrolloff``). ↑ and
    ↓ keep the same margin. With fewer than three items on screen the margin
    is nothing. The last :data:`widgets.BAR_ZONE` columns are the scrollbar's:
    a tap there jumps, and a drag that **starts** there moves the thumb a row
    per row of finger travel, the way the finger went.
    """

    cursor: int = -1
    top: int = 0
    #: Wheel rows not yet turned into a whole item.
    acc: int = 0
    #: Laid out by the last draw: (entry index, y, height) for what is visible.
    shown: list[tuple[int, int, int]] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    height: int = 0
    y: int = 0
    width: int = 0
    #: Where the bar last put the thumb: its row, and the view it stood for
    #: (top, height, rows). A thumb row can be worth less than an entry, and
    #: then the view a row of the drag stands for is the one it was already
    #: on; the next row goes on from the finger, not from the thumb that view
    #: draws, or the drag would stop there for good. Anything else that moves
    #: the view leaves it standing for a view that is no longer there.
    grip: tuple[int, int, int, int] | None = None

    # Geometry -------------------------------------------------------------

    def _rows_from(self, top: int, height: int) -> int:
        """How many entries from *top* fit in *height* rows, whole."""
        n, used = 0, 0
        for e in self.entries[top:]:
            if used + e.height > height:
                break
            used += e.height
            n += 1
        return n

    def visible(self) -> int:
        return self._rows_from(self.top, self.height)

    def furthest(self) -> int:
        """The highest top that still fills the view.

        Never the end of the list itself: when the last entry is taller than
        the whole view (a setting's three rows in a list two rows high), no
        top shows it, and the furthest the view goes is the last entry that
        does fit. Counted from the end alone it was past every entry, so a
        swipe scrolled to an empty list and the cursor went with it.
        """
        used, top = 0, len(self.entries)
        while top > 0 and used + self.entries[top - 1].height <= self.height:
            top -= 1
            used += self.entries[top].height
        if top < len(self.entries):
            return top
        fits = [i for i, e in enumerate(self.entries) if e.height <= self.height]
        return fits[-1] if fits else 0

    def total_rows(self) -> int:
        return sum(e.height for e in self.entries)

    def offset_rows(self, top: int | None = None) -> int:
        """The rows above *top* (the view's own when not given)."""
        return sum(e.height for e in self.entries[: self.top if top is None else top])

    def selectable(self) -> list[int]:
        return [i for i, e in enumerate(self.entries) if e.selectable]

    def margin(self) -> int:
        return 1 if self.visible() >= 3 else 0

    # Keeping the cursor and the view together ----------------------------

    def clamp(self) -> None:
        self.top = max(0, min(self.top, self.furthest()))
        if self.cursor >= len(self.entries):
            self.cursor = len(self.entries) - 1
        if self.cursor >= 0 and not self.entries[self.cursor].selectable:
            pick = self.selectable()
            self.cursor = min(pick, key=lambda i: abs(i - self.cursor)) if pick else -1

    def settle(self) -> None:
        """Bounds, then the cursor back on screen by moving the view: what a
        list that grew, shrank or was resized hands back is a place the
        screen draws."""
        self.clamp()
        if self.cursor < 0 or not self.entries:
            return
        if self.cursor < self.top:
            self.top = self.cursor
        while self.top < self.cursor and self.cursor >= self.top + max(1, self.visible()):
            self.top += 1
        self.clamp()

    def _near(self, index: int, step: int) -> int:
        """The selectable entry nearest *index* going *step* (±1), or -1."""
        i = index
        while 0 <= i < len(self.entries):
            if self.entries[i].selectable:
                return i
            i += step
        return -1

    def follow(self) -> None:
        """Move the view so the cursor sits at least the margin in from
        either edge (or as near as the list allows)."""
        if self.cursor < 0:
            return
        m = self.margin()
        lo = self._near(self.cursor - m, -1) if m else self.cursor
        lo = self.cursor if lo < 0 else lo
        if lo < self.top:
            self.top = lo
        while self.top < self.cursor:
            hi = min(len(self.entries) - 1, self.cursor + m)
            if hi < self.top + self.visible():
                break
            self.top += 1
        self.clamp()

    def ride(self) -> None:
        """After the view moved: bring the cursor back inside the margin."""
        if self.cursor < 0:
            return
        n = self.visible()
        m = self.margin() if self.top + n < len(self.entries) or self.top > 0 else 0
        first = self.top + (m if self.top > 0 else 0)
        last = self.top + n - 1 - (m if self.top + n < len(self.entries) else 0)
        if self.cursor < first:
            self.cursor = self._near(first, 1)
        elif self.cursor > last:
            self.cursor = self._near(last, -1)
        if self.cursor < 0:
            self.cursor = self._near(self.top, 1)

    def page(self) -> int:
        """How far pgup and pgdn go: what is on screen, less the one entry
        kept in sight from where the page began."""
        return max(1, self.visible() - 1)

    def press(self, key: str, sideways: bool = False) -> bool:
        """↑ ↓ pgup pgdn, and ← → as a page where the screen has no other
        use for them (*sideways*): the cursor moved, and ``True``. Any other
        key is the screen's, and ``False``."""
        page = self.page()
        steps = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}
        if sideways:
            steps.update(left=-page, right=page)
        if key not in steps:
            return False
        self.move(steps[key])
        return True

    def wheel(self, event: tui.Scroll) -> None:
        """One row of a drag or a fling: on the bar it carries the thumb, the
        way the finger goes; anywhere else it moves the view."""
        if self.in_bar(event.x, event.y):
            self.bar_drag(event.dy)
        else:
            self.view(event.dy)

    def move(self, step: int) -> None:
        """↑ / ↓ (step ∓1), pgup / pgdn (∓ a page)."""
        pick = self.selectable()
        if not pick:
            return
        if self.cursor < 0:
            self.cursor = pick[0] if step > 0 else pick[-1]
        else:
            at = pick.index(self.cursor) if self.cursor in pick else 0
            self.cursor = pick[max(0, min(len(pick) - 1, at + step))]
        self.follow()

    def view(self, dy: int) -> None:
        """One wheel row: the view moves, an entry at a time."""
        self.acc += dy
        moved = False
        while self.acc > 0 and self.top < self.furthest():
            if self.acc < self.entries[self.top].height:
                break
            self.acc -= self.entries[self.top].height
            self.top += 1
            moved = True
        while self.acc < 0 and self.top > 0:
            if -self.acc < self.entries[self.top - 1].height:
                break
            self.top -= 1
            self.acc += self.entries[self.top].height
            moved = True
        # Rows pushed against an end are not saved up for the way back.
        if (self.acc > 0 and self.top >= self.furthest()) or (self.acc < 0 and self.top <= 0):
            self.acc = 0
        if moved:
            self.ride()

    def at_end(self) -> bool:
        return self.top >= self.furthest()

    # The bar ---------------------------------------------------------------

    def in_bar(self, x: int, y: int) -> bool:
        return (self.width - w.BAR_ZONE <= x < self.width
                and self.y <= y < self.y + self.height)

    def travel(self) -> int:
        """How far the view can scroll, in rows: those above the furthest
        top. Not every row past the view's height: the last entries can
        leave a spare row no top ever scrolls past, and a thumb scaled to
        the rows sits at the bottom an entry short of the end, where a tap
        would stop too."""
        return self.offset_rows(self.furthest())

    def thumb(self) -> tuple[int, int]:
        """The thumb as drawn, ``(start, length)``, on a track the view's
        height that stands for its :meth:`travel`."""
        return w.thumb(self.height, self.travel() + self.height, self.height,
                       self.offset_rows())

    def bar_drag(self, dy: int) -> None:
        """A drag that began on the bar: the thumb follows the finger, a row
        per row. *dy* is a :class:`tui.Scroll`'s, which is the way the view
        moves and not the finger: Termux scrolls naturally, so a finger
        going down the screen sends the wheel up (-1), and the thumb goes
        down with it."""
        start, length = self.thumb()
        if self.grip is not None and self.grip[1:] == self._gripped():
            start = self.grip[0]
        self._thumb_to(start - dy, length, way=-dy)

    def bar_tap(self, y: int) -> None:
        """A tap on the bar: the thumb's middle goes where the finger was."""
        _, length = self.thumb()
        self._thumb_to(y - self.y - length // 2, length)

    def _gripped(self) -> tuple[int, int, int]:
        return (self.top, self.height, self.total_rows())

    def _thumb_to(self, start: int, length: int, way: int = 0) -> None:
        """The thumb to *start*, and the view to the top it stands for: its
        share of the travel, to the nearest whole entry, which draws the
        thumb back on the row the finger is on whenever an entry is worth
        less than a thumb row. A drag (*way*, the finger's: +1 down the
        screen) never moves the view against it."""
        room = self.height - length
        if room <= 0:
            return
        start = max(0, min(room, start))
        target = start * self.travel() / room
        top, used = 0, 0
        while top < self.furthest() and used + self.entries[top].height / 2 <= target:
            used += self.entries[top].height
            top += 1
        if (top - self.top) * way >= 0:
            self.top = top
        self.acc = 0
        self.ride()
        self.grip = (start, *self._gripped())

    # Drawing ---------------------------------------------------------------

    def draw(self, s: Surface, x: int, y: int, width: int, height: int, id: str,
             bar: bool = True) -> None:
        """The visible entries, each a target *id* with its index, and the
        scrollbar in the last column."""
        self.y, self.height, self.width = y, height, width
        self.settle()
        self.shown = []
        row = y
        for i in range(self.top, len(self.entries)):
            e = self.entries[i]
            if row + e.height > y + height:
                break
            block = e.draw(width - (1 if bar else 0), i == self.cursor)
            s.put(block, x, row)
            if e.selectable:
                s.target(id, x, row, width - (w.BAR_ZONE if bar else 0), e.height, i)
            self.shown.append((i, row, e.height))
            row += e.height
        if bar and height > 0:
            s.put(w.scrollbar(height, self.travel() + height, height, self.offset_rows()),
                  x + width - 1, y)
            s.target(f"{id}-bar", x + width - w.BAR_ZONE, y, w.BAR_ZONE, height)
