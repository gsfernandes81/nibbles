"""The pieces every nibbles screen is drawn from, drawn with bewitch.

These are the recipes the mockups in ``design/mock/kit.py`` proposed, made
real: buttons three rows tall, a row of them filling its width exactly,
one-of choices as equal boxes, huh's checkbox, the text field, the tab bar,
the status bar and the bottom sheet. bewitch-only drawing, nothing here reads
a key or touches a terminal, so it can move into bewitch whole (Lip Gloss v2
has the Layer/Compositor this is a small copy of).

Every recipe returns a :class:`Piece`: a Block and the tap targets on it,
relative to its own top-left corner. Pieces stack (:func:`vstack`,
:func:`hstack`) and land on a :class:`Surface`, which keeps the
:class:`HitMap` a tap is looked up in. **Every piece is exactly the width it
was given**, which the layout tests hold as a property.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from nibbles import tui  # noqa: F401  (puts the bewitch checkout on the path)
from bewitch import glyphs
from bewitch.bubbles import dialog_title as _dialog_title
from bewitch.bubbles import header as _header
from bewitch.bubbles import list_item
from bewitch.bubbles import progress_bar as _progress_bar
from bewitch.bubbles import scrollbar, tag
from bewitch.bubbles import section as _section
from bewitch.bubbles.widgets import scroll_thumb
from bewitch.lipgloss import (
    Block,
    Canvas,
    Pen,
    Span,
    Style,
    rounded_border,
    string_width,
)
from bewitch.lipgloss._cells import blank, row_width, to_row, wrap_row
from bewitch.lipgloss._cells import truncate_row as _truncate_row
from bewitch.theme import CHARM as T

__all__ = [
    "T", "Block", "Pen", "Span", "Piece", "Hit", "HitMap", "Surface", "Btn",
    "button", "button_min", "dock", "segmented", "checkbox", "field", "text",
    "spans", "wrapped", "vstack", "hstack", "gap", "dim", "tab_bar",
    "status_bar", "sheet", "setting_row", "row_item", "scrollbar", "bar",
    "progress_bar", "list_item", "dialog_title", "TABS", "BAR_ZONE", "header",
    "section", "Style", "rounded_border", "glyphs", "piece", "string_width",
]


# --------------------------------------------------------------------------- #
# Hits
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Hit:
    """A tap target: a rectangle, an id, and whatever the screen wants back."""

    x: int
    y: int
    w: int
    h: int
    id: str
    data: object = None

    def has(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def moved(self, dx: int, dy: int) -> Hit:
        return Hit(self.x + dx, self.y + dy, self.w, self.h, self.id, self.data)


class HitMap:
    """Ids on composed rectangles, last composed wins, looked up by cell."""

    def __init__(self) -> None:
        self.hits: list[Hit] = []

    def add(self, hit: Hit) -> None:
        if hit.w > 0 and hit.h > 0:
            self.hits.append(hit)

    def at(self, x: int, y: int) -> Hit | None:
        for hit in reversed(self.hits):
            if hit.has(x, y):
                return hit
        return None

    def find(self, id: str) -> Hit | None:
        for hit in reversed(self.hits):
            if hit.id == id:
                return hit
        return None

    def ids(self) -> list[str]:
        return [hit.id for hit in self.hits]


@dataclass
class Piece:
    block: Block
    hits: list[Hit] = field(default_factory=list)

    @property
    def width(self) -> int:
        return self.block.width

    @property
    def height(self) -> int:
        return self.block.height


def piece(block: Block, id: str | None = None, data: object = None) -> Piece:
    """*block* as a piece, the whole of it one target when *id* is given."""
    hits = [Hit(0, 0, block.width, block.height, id, data)] if id else []
    return Piece(block, hits)


def vstack(*parts: Piece | Block | None, width: int | None = None) -> Piece:
    """Pieces one under another, left-aligned, padded to the widest."""
    items = [p if isinstance(p, Piece) else Piece(p) for p in parts if p is not None]
    w = max(0, width) if width is not None else max((p.width for p in items), default=0)
    rows: list = []
    hits: list[Hit] = []
    for p in items:
        for hit in p.hits:
            hits.append(hit.moved(0, len(rows)))
        rows += p.block.rows()
    return Piece(Block.from_rows(rows, w), hits)


def hstack(*parts: Piece | Block) -> Piece:
    """Pieces side by side, top-aligned, padded to the tallest."""
    items = [p if isinstance(p, Piece) else Piece(p) for p in parts]
    h = max((p.height for p in items), default=0)
    rows: list[list] = [[] for _ in range(h)]
    hits: list[Hit] = []
    x = 0
    for p in items:
        prows = p.block.rows()
        for y in range(h):
            rows[y] += prows[y] if y < len(prows) else blank(p.width)
        for hit in p.hits:
            hits.append(hit.moved(x, 0))
        x += p.width
    return Piece(Block.from_rows(rows, x), hits)


def gap(width: int, height: int = 1) -> Piece:
    width = max(0, width)
    return Piece(Block.from_rows([blank(width) for _ in range(height)], width))


class Surface:
    """A screen being drawn: a canvas and the hit map that goes with it.

    *pressed* is the id of the button that was just tapped: it is drawn
    filled in ``primary`` for one frame (``tui.PRESSED``), so you see what
    you hit.
    """

    def __init__(self, width: int, height: int, pressed: str | None = None) -> None:
        self.width = width
        self.height = height
        self.canvas = Canvas(width, height)
        self.hits = HitMap()
        self.pressed = pressed

    def put(self, p: Piece | Block, x: int = 0, y: int = 0) -> Piece:
        p = p if isinstance(p, Piece) else Piece(p)
        self.canvas.compose(p.block, x, y)
        for hit in p.hits:
            self._add(hit.moved(x, y))
        return p

    def target(self, id: str, x: int, y: int, w: int, h: int, data: object = None) -> None:
        """A tap target with nothing drawn for it (the dimmed screen, a row)."""
        self._add(Hit(x, y, w, h, id, data))

    def _add(self, hit: Hit) -> None:
        # A target is only where it was drawn: clipped to the screen. (A
        # sheet taller than a pinch-zoomed screen starts above its top.)
        x0, y0 = max(0, hit.x), max(0, hit.y)
        x1 = min(self.width, hit.x + hit.w)
        y1 = min(self.height, hit.y + hit.h)
        if x1 > x0 and y1 > y0:
            self.hits.add(Hit(x0, y0, x1 - x0, y1 - y0, hit.id, hit.data))

    def render(self) -> Block:
        return self.canvas.render()


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #


def truncate_row(row: list, limit: int, tail: list | None = None) -> list:
    """bewitch's cut, which never returns for a limit under nought: it hands
    its tail back to itself, and the tail does not fit either.

    Every Block of a stated width goes through it, and a screen pinch-zoomed,
    floated or split narrower than its own margins asks for one (``W - 14``
    at 13 columns). So every recipe here, and every bewitch one handed on,
    takes a width under nought as nought: nothing fits in less than nothing,
    what is drawn is wider than that, and the screen cuts it.
    """
    return _truncate_row(row, max(0, limit), tail)


def header(name: str, details: Sequence[str] = (), width: int = 40) -> Block:
    """bewitch's header, never less than nothing wide (:func:`truncate_row`)."""
    return _header(name, details, max(0, width))


def section(title: str, width: int, info: str | None = None) -> Block:
    """bewitch's section, never less than nothing wide (:func:`truncate_row`)."""
    return _section(title, max(0, width), info)


def dialog_title(title: str, width: int) -> Block:
    """bewitch's dialog title, never less than nothing wide (:func:`truncate_row`)."""
    return _dialog_title(title, max(0, width))


def progress_bar(fraction: float, width: int, show_percentage: bool = True) -> Block:
    """bewitch's progress bar, never less than nothing wide (:func:`truncate_row`)."""
    return _progress_bar(fraction, max(0, width), show_percentage=show_percentage)


def _exact(row: list, width: int, pen: Pen | None = None) -> list:
    width = max(0, width)
    row = truncate_row(row, width)
    return row + blank(width - row_width(row), pen or Pen())


def text(s: str, width: int, fg=None, bold=None, bg=None) -> Block:
    """One line of *s*, cut with … to *width*."""
    width = max(0, width)
    pen = Pen(fg=fg or T.fg_base, bold=bold, bg=bg)
    row = truncate_row(to_row(s, pen), width, to_row(glyphs.ELLIPSIS, pen))
    return Block.from_rows([row + blank(width - row_width(row), Pen(bg=bg))], width)


def spans(parts: Sequence[tuple], width: int, bg=None) -> Block:
    """One line from ``(text, fg[, bold])`` parts, cut with … to *width*."""
    width = max(0, width)
    row: list = []
    for s, fg, *rest in parts:
        row += to_row(s, Pen(fg=fg, bold=rest[0] if rest else None, bg=bg))
    last = row[-1][1] if row else Pen(bg=bg)
    row = truncate_row(row, width, to_row(glyphs.ELLIPSIS, last))
    return Block.from_rows([row + blank(width - row_width(row), Pen(bg=bg))], width)


def wrapped(s: str, width: int, fg=None, limit: int | None = None) -> Block:
    """*s* wrapped to *width*, at most *limit* lines (the last one cut)."""
    width = max(0, width)
    pen = Pen(fg=fg or T.fg_base)
    rows = wrap_row(to_row(s, pen), width) or [[]]
    if limit is not None and len(rows) > limit:
        rest = [cell for r in rows[limit - 1:] for cell in ([(" ", pen)] + r)][1:]
        rows = rows[: limit - 1] + [truncate_row(rest, width, to_row(glyphs.ELLIPSIS, pen))]
    return Block.from_rows([_exact(r, width) for r in rows], width)


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #

KINDS = {
    #          border             key                 word              fill
    "normal": (T.fg_most_subtle, T.fg_more_subtle, T.fg_base, None),
    "primary": (T.primary, T.fg_more_subtle, T.fg_base, None),
    "spend": (T.warning, T.fg_more_subtle, T.fg_base, None),
    "danger": (T.destructive, T.fg_more_subtle, T.fg_base, None),
    "pressed": (T.primary, T.on_primary, T.on_primary, T.primary),
    "off": (T.bg_most_visible, T.fg_most_subtle, T.fg_most_subtle, None),
}


@dataclass(frozen=True)
class Btn:
    """A button to be laid out: its word, key, kind, note and id."""

    word: str
    key: str = ""
    kind: str = "normal"
    note: str = ""
    id: str = ""
    data: object = None


def button_min(word: str, key: str = "", note: str = "") -> int:
    """The narrowest a button can be with nothing cut."""
    return (
        string_width(word)
        + (string_width(key) + 1 if key else 0)
        + (string_width(note) + 1 if note else 0)
        + 4
    )


def button(
    word: str,
    key: str = "",
    width: int | None = None,
    kind: str = "normal",
    note: str = "",
    id: str = "",
    data: object = None,
    pressed: str | None = None,
) -> Piece:
    """A three-row tap target: a rounded border, ``key word``, an optional
    grey note, centred. *kind* is ``normal``, ``primary``, ``spend``,
    ``danger`` or ``off``; it is drawn ``pressed`` when *pressed* is its id."""
    if id and pressed == id and kind != "off":
        kind = "pressed"
    border, kpen, wpen, fill = KINDS[kind]
    row: list = []
    if key:
        row += to_row(key, Pen(fg=kpen, bg=fill)) + blank(1, Pen(bg=fill))
    row += to_row(word, Pen(fg=wpen, bg=fill, bold=kind in ("primary",) or None))
    if note:
        row += to_row(" " + note, Pen(fg=T.fg_more_subtle if not fill else wpen, bg=fill))
    w = max(5, width if width is not None else row_width(row) + 4)
    inner = w - 4
    row = truncate_row(row, inner, to_row(glyphs.ELLIPSIS, Pen(fg=wpen, bg=fill)))
    pad = inner - row_width(row)
    row = blank(pad // 2, Pen(bg=fill)) + row + blank(pad - pad // 2, Pen(bg=fill))
    style = Style().border(rounded_border()).border_foreground(border).padding(0, 1).width(w)
    if fill:
        style = style.background(fill)
    block = style.render(Block.from_rows([row]))
    return piece(block, id or None, data)


def dock(buttons: Sequence[Btn], width: int, pressed: str | None = None) -> Piece:
    """A row of buttons filling *width* exactly; spare columns shared out.

    Never wider than it was given: when the labels do not fit, the widest
    button gives a column at a time and its label ends in ``…``.
    """
    width = max(0, width)
    if not buttons:
        return gap(width, 3)
    widths = [button_min(b.word, b.key, b.note) for b in buttons]
    spare = width - sum(widths)
    i = 0
    while spare > 0:
        widths[i % len(widths)] += 1
        spare -= 1
        i += 1
    while spare < 0 and max(widths) > 5:
        widths[widths.index(max(widths))] -= 1
        spare += 1
    parts = [
        button(b.word, b.key, w, b.kind, b.note, b.id, b.data, pressed)
        for b, w in zip(buttons, widths, strict=True)
    ]
    out = hstack(*parts)
    if out.width > width:
        # Too many buttons for the room even at their narrowest: cut, never
        # overflow. The layout tests never ask for this.
        out = Piece(Block.from_rows([_exact(r, width) for r in out.block.rows()], width),
                    [h for h in out.hits if h.x + h.w <= width])
    return out


def equal_widths(width: int, n: int) -> list[int]:
    return [width // n + (1 if i < width % n else 0) for i in range(n)]


def segmented(
    options: Sequence[str],
    chosen: int,
    width: int,
    id: str = "",
    pressed: str | None = None,
) -> Piece:
    """One-of choices as equal-width boxes side by side, labels centred.

    The chosen box is outlined in ``primary`` with ``◉`` and a bold word, the
    rest grey with ``○``. Equal widths keep a short option (Now) as big a
    target, and as heavy on the screen, as a long one (At 03:00). Each box is
    a target ``id`` with its index as the data.
    """
    width = max(0, width)
    parts = []
    for i, (word, w) in enumerate(zip(options, equal_widths(width, len(options)), strict=True)):
        on = i == chosen
        g = glyphs.RADIO_ON if on else glyphs.RADIO_OFF
        row = to_row(g + " ", Pen(fg=T.primary if on else T.fg_most_subtle))
        row += to_row(word, Pen(fg=T.fg_base if on else T.fg_more_subtle, bold=on or None))
        inner = w - 2
        row = truncate_row(row, inner, to_row(glyphs.ELLIPSIS, Pen(fg=T.fg_more_subtle)))
        pad = inner - row_width(row)
        row = blank(pad // 2) + row + blank(pad - pad // 2)
        border = T.primary if on else T.fg_most_subtle
        style = Style().border(rounded_border()).border_foreground(border).width(w)
        hit_id = f"{id}:{i}" if id else ""
        if hit_id and pressed == hit_id:
            style = style.background(T.primary)
        parts.append(piece(style.render(Block.from_rows([row])), hit_id or None, i))
    return hstack(*parts)


try:  # bewitch's own recipe (bewitch#1), when the checkout has it
    from bewitch.bubbles.huh import checkbox as _huh_checkbox
except ImportError:  # an older bewitch checkout: the same look, drawn here
    _huh_checkbox = None


def checkbox(word: str, on: bool, width: int, id: str = "") -> Piece:
    """A checkbox the way Charm's huh draws one, as a full-width three-row
    tap target: a green ``✓`` and a ``success`` outline when ticked, a quiet
    ``•`` when not. bewitch's ``bubbles.huh.checkbox``, boxed."""
    width = max(0, width)
    if _huh_checkbox is not None:
        return piece(_huh_checkbox(word, on, width, boxed=True), id or None)
    glyph = to_row(("✓" if on else glyphs.BULLET) + " ",
                   Pen(fg=T.success if on else T.fg_most_subtle))
    row = glyph + to_row(word, Pen(fg=T.success if on else T.fg_base))
    inner = width - 2
    row = truncate_row(row, inner)
    pad = inner - row_width(row)
    row = blank(pad // 2) + row + blank(pad - pad // 2)
    block = (Style().border(rounded_border())
             .border_foreground(T.success if on else T.fg_most_subtle)
             .width(width).render(Block.from_rows([row])))
    return piece(block, id or None)


def field(value: str, width: int, placeholder: str = "", focus: bool = True,
          id: str = "") -> Piece:
    """A text input: a rounded box, ``primary`` when focused, the text and a
    block cursor in ``secondary`` at its end. A value too long shows its tail,
    because the tail is what is being typed."""
    width = max(0, width)
    inner = max(1, width - 4)
    cursor = to_row(" ", Pen(bg=T.secondary)) if focus else []
    if value:
        row = to_row(value, Pen(fg=T.fg_base))
        room = inner - row_width(cursor)
        while row_width(row) > room and row:
            row = row[1:]
        row += cursor
    else:
        row = cursor + to_row(placeholder, Pen(fg=T.fg_most_subtle))
    row = truncate_row(row, inner)
    block = (Style().border(rounded_border())
             .border_foreground(T.primary if focus else T.fg_most_subtle)
             .padding(0, 1).width(width).render(Block.from_rows([row])))
    return piece(block, id or None)


# --------------------------------------------------------------------------- #
# Lists
# --------------------------------------------------------------------------- #

#: The last columns of a list are its scrollbar's: a tap there jumps, and a
#: drag that *starts* there moves the thumb.
BAR_ZONE = 3


def row_item(title, width: int, subtitle=None, selected: bool = False,
             mark: str = "", mark_color=None, dimmed: bool = False) -> Block:
    """A two-line list row (bewitch's ``list_item``)."""
    return list_item(title, max(0, width), subtitle=subtitle, selected=selected,
                     mark=mark, mark_color=mark_color, dimmed=dimmed)


def setting_row(key: str, name: str, value: str, meaning: str, width: int,
                selected: bool = False, value_fg=None) -> Block:
    """A setting as a two-line row: key, name, the value in ``primary`` at
    the right, and a grey line saying what it means."""
    width = max(0, width)
    bg = T.bg_less_visible if selected else None
    left = to_row(f" {key} " if key else "   ", Pen(fg=T.fg_more_subtle, bg=bg))
    left += to_row(name, Pen(fg=T.fg_base, bg=bg))
    right = to_row(value + " ", Pen(fg=value_fg or T.primary, bg=bg, bold=True)) if value else []
    room = width - row_width(left) - 1
    right = truncate_row(right, max(0, room), to_row(glyphs.ELLIPSIS, Pen(fg=value_fg or T.primary, bg=bg)))
    gap_w = width - row_width(left) - row_width(right)
    r1 = left + blank(max(1, gap_w), Pen(bg=bg)) + right
    r2 = to_row("   " + meaning, Pen(fg=T.fg_most_subtle, bg=bg))
    r2 = truncate_row(r2, width, to_row(glyphs.ELLIPSIS, Pen(fg=T.fg_most_subtle, bg=bg)))
    r2 += blank(width - row_width(r2), Pen(bg=bg))
    return Block.from_rows([_exact(r1, width, Pen(bg=bg)), r2], width)


def bar(fraction: float, width: int) -> Block:
    """A gradient bar with no percentage: the window card's."""
    return progress_bar(fraction, width, show_percentage=False)


def thumb(height: int, total: int, visible: int, offset: int) -> tuple[int, int]:
    return scroll_thumb(height, total, visible, offset)


# --------------------------------------------------------------------------- #
# The shell
# --------------------------------------------------------------------------- #

TABS = ("Search", "Feed", "Later", "Queue", "More")


def tab_edges(width: int) -> list[int]:
    """Where each tab's fifth starts, Go's rounding (half away from zero)."""
    return [int(math.floor(i * width / len(TABS) + 0.5)) for i in range(len(TABS) + 1)]


def tab_bar(active: int, width: int, status: tuple[str, str, str, str]) -> Piece:
    """The four rows at the foot of every tab screen: a rule, the tab labels
    (the chosen one a pill in ``primary`` with a column of purple either
    side), a blank row, and the status bar. Rows one to three are each tab's
    target."""
    width = max(0, width)
    rule = to_row(glyphs.SECTION * width, Pen(fg=T.separator))
    edges = tab_edges(width)
    labels: list = []
    hits = []
    for i, name in enumerate(TABS):
        w = edges[i + 1] - edges[i]
        on = i == active
        pen = Pen(fg=T.on_primary, bg=T.primary, bold=True)
        if on and w >= string_width(name) + 2:
            pill = to_row(" " + name + " ", pen)
        elif on:
            pill = to_row(name[:w], pen)
        else:
            pill = truncate_row(to_row(name, Pen(fg=T.fg_more_subtle)), w)
        pad = w - row_width(pill)
        labels += blank(pad // 2) + pill + blank(pad - pad // 2)
        hits.append(Hit(edges[i], 0, w, 3, "tab", i))
    status_row = status_bar(status, width).rows()[0]
    block = Block.from_rows([rule, labels, blank(width), status_row], width)
    return Piece(block, hits)


#: The status bar's label kinds, by what the label says.
STATUS_KINDS = {"primary", "warn", "error", "info", "success"}


def status_bar(status: tuple[str, str, str, str], width: int) -> Block:
    """Lip Gloss's own status bar in the house roles: a coloured label word
    at the left, the detail on a lifted panel (cut with … before either end
    gives way, one clear column kept at its right end), and a quieter segment
    at the right. The label is always a word, never only a colour."""
    width = max(0, width)
    label, kind, detail, right = status
    lab = tag(label, kind if kind in STATUS_KINDS else "primary").rows()[0]
    rgt = to_row(f" {right} ", Pen(fg=T.fg_base, bg=T.bg_most_visible)) if right else []
    if row_width(lab) + row_width(rgt) > width:
        rgt = []
    lab = truncate_row(lab, width)
    room = width - row_width(lab) - row_width(rgt)
    mid_pen = Pen(fg=T.fg_more_subtle, bg=T.bg_less_visible)
    mid = truncate_row(to_row(" " + detail, mid_pen), max(0, room - 1),
                       to_row(glyphs.ELLIPSIS, mid_pen)) if room > 1 else []
    mid += blank(max(0, room - row_width(mid)), Pen(bg=T.bg_less_visible))
    return Block.from_rows([lab + mid + rgt], width)


def dim(block: Block) -> Block:
    """What sits behind a sheet: every colour pushed back to the faintest
    grey, no backgrounds."""
    rows = []
    for row in block.rows():
        rows.append([(ch, Pen(fg=T.bg_most_visible if ch.strip() else None)) for ch, _ in row])
    return Block.from_rows(rows, block.width)


@dataclass
class SheetLayout:
    """Where a sheet landed: its top row, and its body's scroll."""

    y: int
    room: int
    total: int
    offset: int
    body_y: int

    @property
    def scrolls(self) -> bool:
        return self.total > self.room


def sheet(
    surface: Surface,
    top: int,
    title: str,
    body: Piece,
    footer: Piece | None = None,
    border=None,
    offset: int = 0,
    pressed: str | None = None,
) -> SheetLayout:
    """A bottom sheet on *surface*, its top no higher than row *top*.

    A rounded border open at the bottom edge, the title as ``dialog_title``
    with ``esc ×`` at its right. When the body does not fit, the sheet takes
    every row from *top* down, the *footer* stays pinned at the bottom, and
    the body scrolls (from *offset*) with a scrollbar.
    """
    width, height = surface.width, surface.height
    inner = width - 4
    close = button_close(pressed)
    head = hstack(Piece(dialog_title(title, inner - 8)), close)
    foot_h = footer.height if footer else 0
    room = max(0, height - top - 2 - foot_h)  # the border row and the title
    total = body.height
    offset = max(0, min(offset, max(0, total - room)))
    shown = body
    if total > room:
        rows = body.block.rows()[offset:offset + room]
        hits = []
        for hit in body.hits:
            y0, y1 = max(hit.y, offset), min(hit.y + hit.h, offset + room)
            if y1 > y0:
                hits.append(Hit(hit.x, y0 - offset, hit.w, y1 - y0, hit.id, hit.data))
        shown = Piece(Block.from_rows(rows, max(0, inner)), hits)
    stack = vstack(head, shown, footer, width=inner)
    block = (Style().border(rounded_border(), True, True, False, True)
             .border_foreground(border or T.primary).padding(0, 1).width(width)
             .render(stack.block))
    y = height - block.height
    surface.target("sheet", 0, y, width, block.height)
    surface.put(Piece(block, [h.moved(2, 1) for h in stack.hits]), 0, y)
    body_y = y + 1 + head.height
    if total > room:
        surface.put(scrollbar(room, total, room, offset), width - 2, body_y)
        surface.target("sheet-bar", width - 2, body_y, 2, room)
    return SheetLayout(y, room, total, offset, body_y)


def button_close(pressed: str | None = None) -> Piece:
    """``esc ×`` at a sheet's top right: the close target."""
    pen = Pen(fg=T.on_primary, bg=T.primary) if pressed == "close" else Pen(fg=T.fg_most_subtle)
    return piece(Block.from_rows([blank(2) + to_row("esc ×", pen) + blank(1)], 8), "close")
