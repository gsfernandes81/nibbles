"""Mockup kit: the proposed button/dock/sheet recipes, drawn with bewitch.

Everything here is a sketch of what ytq's shared screen layer would draw.
It renders to bewitch Blocks; to_html turns a Block into a <pre>.
"""

from __future__ import annotations

import html
import sys

import os  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

# bewitch is a sibling checkout: $BEWITCH_HOME, a clone beside this repo, then
# ~/bewitch, the same order every sibling lookup here uses.
_REPO = _Path(__file__).resolve().parents[2]
_BEWITCH = (os.environ.get("BEWITCH_HOME")
            or next((str(p) for p in (_REPO.parent / "bewitch", _Path.home() / "bewitch")
                     if (p / "bewitch").is_dir()), str(_REPO.parent / "bewitch")))
sys.path.insert(0, _BEWITCH)

from bewitch import glyphs  # noqa: E402
from bewitch.bubbles import (  # noqa: E402
    dialog_title,
    header,
    list_item,
    progress_bar,
    scrollbar,
    section,
    short_help,
    tag,
)
from bewitch.bubbles.spinner import Dot  # noqa: E402
from bewitch.lipgloss import (  # noqa: E402
    LEFT,
    Block,
    Canvas,
    Pen,
    Span,
    Style,
    join_horizontal,
    join_vertical,
    rounded_border,
    string_width,
)
from bewitch.lipgloss._cells import blank, row_width, to_row, truncate_row  # noqa: E402
from bewitch.theme import CHARM as T  # noqa: E402

TOP = 0

# --- buttons ------------------------------------------------------------------

KINDS = {
    #          border             key                 word              fill
    "normal": (T.fg_most_subtle, T.fg_more_subtle, T.fg_base, None),
    "primary": (T.primary, T.fg_more_subtle, T.fg_base, None),
    "spend": (T.warning, T.fg_more_subtle, T.fg_base, None),
    "armed": (T.attention, T.bg_base, T.bg_base, T.attention),
    "danger": (T.destructive, T.fg_more_subtle, T.fg_base, None),
    "pressed": (T.primary, T.on_primary, T.on_primary, T.primary),
    "off": (T.bg_most_visible, T.fg_most_subtle, T.fg_most_subtle, None),
}


def button(word: str, key: str = "", width: int | None = None, kind: str = "normal",
           note: str = "") -> Block:
    """A 3-row tap target: rounded border, `key word`, optional grey note."""
    border, kpen, wpen, fill = KINDS[kind]
    row = []
    if key:
        row += to_row(key, Pen(fg=kpen, bg=fill)) + blank(1, Pen(bg=fill))
    row += to_row(word, Pen(fg=wpen, bg=fill, bold=kind in ("primary", "armed") or None))
    if note:
        row += to_row(" " + note, Pen(fg=T.fg_more_subtle if not fill else wpen, bg=fill))
    need = row_width(row) + 4
    w = width or need
    inner = w - 4
    row = truncate_row(row, inner, to_row(glyphs.ELLIPSIS, Pen(fg=wpen, bg=fill)))
    pad = inner - row_width(row)
    lpad = pad // 2
    row = blank(lpad, Pen(bg=fill)) + row + blank(pad - lpad, Pen(bg=fill))
    style = Style().border(rounded_border()).border_foreground(border).padding(0, 1).width(w)
    if fill:
        style = style.background(fill)
    return style.render(Block.from_rows([row]))


def button_min(word, key="", note=""):
    return string_width(word) + (string_width(key) + 1 if key else 0) + (
        string_width(note) + 1 if note else 0) + 4


def dock(buttons: list[tuple], width: int) -> Block:
    """A row of buttons filling *width* exactly; spare columns shared out."""
    mins = [button_min(*b[:2], **({"note": b[3]} if len(b) > 3 else {})) for b in buttons]
    spare = width - sum(mins)
    widths = list(mins)
    i = 0
    while spare > 0:
        widths[i % len(widths)] += 1
        spare -= 1
        i += 1
    while spare < 0:
        # Too tight: the widest button gives a column (its label ends in …),
        # so the row is never wider than it was given.
        widths[widths.index(max(widths))] -= 1
        spare += 1
    blocks = []
    for b, w in zip(buttons, widths):
        word, key = b[0], b[1]
        kind = b[2] if len(b) > 2 else "normal"
        note = b[3] if len(b) > 3 else ""
        blocks.append(button(word, key, w, kind, note))
    return join_horizontal(TOP, *blocks)


def wide(word, key="", width=40, kind="normal", note=""):
    return button(word, key, width, kind, note)


# --- other pieces ---------------------------------------------------------------


def text(s: str, width: int, fg=None, bold=None, bg=None) -> Block:
    row = to_row(s, Pen(fg=fg or T.fg_base, bold=bold, bg=bg))
    row = truncate_row(row, width)
    return Block.from_rows([row + blank(width - row_width(row), Pen(bg=bg))], width)


def spans(parts, width, bg=None) -> Block:
    row = []
    for s, fg, *rest in parts:
        bold = rest[0] if rest else None
        row += to_row(s, Pen(fg=fg, bold=bold, bg=bg))
    row = truncate_row(row, width)
    return Block.from_rows([row + blank(width - row_width(row), Pen(bg=bg))], width)


def field(value: str, width: int, placeholder: str = "", focus=True) -> Block:
    """An input: rounded border, text, a block cursor."""
    inner = width - 4
    if value:
        row = to_row(value, Pen(fg=T.fg_base))
    else:
        row = to_row(placeholder, Pen(fg=T.fg_most_subtle))
    if focus:
        row = (to_row(value, Pen(fg=T.fg_base)) + to_row(" ", Pen(bg=T.secondary))
               if value else to_row(" ", Pen(bg=T.secondary)) + to_row(placeholder, Pen(fg=T.fg_most_subtle)))
    row = truncate_row(row, inner)
    return (Style().border(rounded_border())
            .border_foreground(T.primary if focus else T.fg_most_subtle)
            .padding(0, 1).width(width).render(Block.from_rows([row])))


def segmented(options: list[tuple[str, str]], chosen: int, width: int) -> Block:
    """One-of choices as equal-width boxes side by side, each label centred.

    The chosen box is outlined in primary with ◉ and a bold word; the others
    are grey with ○. Equal widths keep a short option (Now) as big a target,
    and as heavy on the screen, as a long one (At 03:00).
    """
    n = len(options)
    widths = [width // n + (1 if i < width % n else 0) for i in range(n)]
    boxes = []
    for i, ((word, note), w) in enumerate(zip(options, widths)):
        on = i == chosen
        g = glyphs.RADIO_ON if on else glyphs.RADIO_OFF
        row = to_row(g + " ", Pen(fg=T.primary if on else T.fg_most_subtle))
        row += to_row(word, Pen(fg=T.fg_base if on else T.fg_more_subtle, bold=on or None))
        if note:
            row += to_row(" " + note, Pen(fg=T.fg_more_subtle))
        inner = w - 2
        row = truncate_row(row, inner)
        pad = inner - row_width(row)
        row = blank(pad // 2) + row + blank(pad - pad // 2)
        boxes.append(Style().border(rounded_border()).border_foreground(T.primary if on else T.fg_most_subtle)
                     .width(w).render(Block.from_rows([row])))
    return join_horizontal(TOP, *boxes)


def chips(words: list[str], chosen: int | None, width: int) -> Block:
    """Preset values as small 3-row buttons in a row."""
    blocks = []
    for i, w in enumerate(words):
        blocks.append(button(w, "", None, "primary" if i == chosen else "normal"))
    return join_horizontal(TOP, *blocks)


def box(body: Block, width: int, title: str = "", border=None) -> Block:
    parts = []
    if title:
        parts += [dialog_title(title, width - 4), Block.text("")]
    parts.append(body)
    return (Style().border(rounded_border()).border_foreground(border or T.primary)
            .padding(0, 1).width(width).render(join_vertical(LEFT, *parts)))


def setting_row(key, name, value, meaning, width, selected=False, value_fg=None):
    """A settings row as a 2-line tap target."""
    bg = T.bg_less_visible if selected else None
    left = to_row(f" {key} ", Pen(fg=T.fg_more_subtle, bg=bg)) + to_row(name, Pen(fg=T.fg_base, bg=bg))
    right = to_row(value + " ", Pen(fg=value_fg or T.primary, bg=bg, bold=True))
    gap = width - row_width(left) - row_width(right)
    r1 = left + blank(max(1, gap), Pen(bg=bg)) + right
    r2 = to_row("   " + meaning, Pen(fg=T.fg_most_subtle, bg=bg))
    r2 = truncate_row(r2, width)
    r2 += blank(width - row_width(r2), Pen(bg=bg))
    return Block.from_rows([truncate_row(r1, width), r2], width)


# --- rendering ------------------------------------------------------------------


def screen(width: int, height: int) -> Canvas:
    return Canvas(width, height)


BOX = {"─": "h", "│": "v", "┃": "thumb", "╭": "tl", "╮": "tr", "╰": "bl", "╯": "br", "█": "full"}


def _cells_html(text: str) -> str:
    """ASCII runs as text; every other character in a cell exactly 1ch wide,
    and box-drawing drawn by CSS so lines join across rows in any font."""
    out, run = [], []
    for ch in text:
        if ord(ch) < 128:
            run.append(ch)
            continue
        if run:
            out.append(f'<span class="r" style="width:{len(run)}ch">{html.escape("".join(run))}</span>')
            run = []
        cls = BOX.get(ch)
        if cls:
            out.append(f'<span class="c b {cls}"></span>')
        else:
            out.append(f'<span class="c">{html.escape(ch)}</span>')
    if run:
        out.append(f'<span class="r" style="width:{len(run)}ch">{html.escape("".join(run))}</span>')
    return "".join(out)


def to_html(block: Block) -> str:
    out = []
    for line in block.lines:
        parts = []
        for span in line:
            p = span.pen
            css = []
            fg, bg = p.fg, p.bg
            if p.reverse:
                fg, bg = (bg or T.bg_base), (fg or T.fg_base)
            if fg is not None:
                css.append(f"color:{fg.hex}")
            if bg is not None:
                css.append(f"background:{bg.hex}")
            if p.bold:
                css.append("font-weight:700")
            t = _cells_html(span.text)
            parts.append(f'<span style="{";".join(css)}">{t}</span>' if css else t)
        out.append("".join(parts))
    return "\n".join(out)


__all__ = [n for n in dir() if not n.startswith("_")]
