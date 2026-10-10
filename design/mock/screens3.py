"""Round three: every screen laid out by its height, keyboard down and up."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from kit import *  # noqa: F401,F403
from kit import T, glyphs
import screens2
from screens2 import Q, VIDEOS, dim, kv, minibar, tabbar
from screens2 import queue_rows as _queue_rows
from screens2 import tonight_card as _tonight_card

# Local time throughout (the mock phone is at UTC+4): the reset at 00:00Z is
# 04:00 here, so a 60-minute window opens at 03:00.
OPENS = "03:00"


def filters(active: int, width=40):
    """Queued, Failed, Done; below 36 columns the counts go before the words do."""
    names = ["Queued 3", "Failed 1", "Done 3"] if width >= 36 else ["Queued", "Failed", "Done"]
    return dock([(n, "", "primary" if i == active else "normal") for i, n in enumerate(names)], width)


def tonight_card(width=40, verdict=("waiting", " · 03:00 (19m)"), fig="480/763 MiB to spend", run=True):
    return _tonight_card(width, verdict=verdict, fig=fig, run=run)


def queue_rows(c, y, sel=None, width=40, order=None, held=None, cut_after=2, cut="the window ends here · 480 MiB"):
    return _queue_rows(c, y, sel, width, order=order, held=held, cut_after=cut_after, cut=cut)

# One name everywhere: a file download keeps its file's name, a video its title.
Q[:] = [
    ("ubuntu-24.04-desktop-amd64.iso", [("↓ ", T.attention), ("18%  1.02 of 5.61 GiB", T.fg_more_subtle)]),
    ("Some Talk About Rust", [("0 of ≤505 MiB", T.fg_more_subtle), (" · 46 MiB at 03:00", T.info)]),
    ("big.iso", [("0 of ≤8 GiB", T.fg_more_subtle)]),
]

W = 40
DOWN, UP = 24, 14
SHORT = 16  # below this many rows the compact rules apply
SCREENS: list[dict] = []


def _ansi(block):
    from bewitch import ansi
    from bewitch.colorprofile import Profile
    return ansi.render(block, Profile.TRUE_COLOR)


def add(key, title, group, make, notes, width=W, heights=(DOWN, UP)):
    shots = []
    for h in heights:
        c = make(h)
        block = c.render()
        shots.append({"rows": h, "html": to_html(block), "plain": block.plain(),
                      "ansi": _ansi(block)})
    SCREENS.append({"key": key, "title": title, "app": group, "notes": notes,
                    "width": width, "shots": shots, "full": heights[0]})


def clip(block: Block, n: int) -> Block:
    return Block.from_rows(block.rows()[:n], block.width)


def place_sheet(c: Canvas, h: int, width: int, title: str, parts: list[Block],
                footer: Block | None = None, border=None, offset: int = 0):
    """A bottom sheet over the screen. If it does not fit, it takes the whole
    height below the header and its body scrolls, with the footer pinned."""
    inner = width - 4
    head = join_horizontal(TOP, dialog_title(title, inner - 8), text("  esc ×", 8, T.fg_most_subtle))
    body = join_vertical(LEFT, *parts)
    foot_h = footer.height if footer else 0
    room = h - 1 - 2 - foot_h  # header row stays; border + title
    scroll = body.height > room
    if scroll:
        body = Block.from_rows(body.rows()[offset:offset + room], inner)
    stack = [head, body] + ([footer] if footer else [])
    sh = (Style().border(rounded_border(), True, True, False, True)
          .border_foreground(border or T.primary).padding(0, 1).width(width)
          .render(join_vertical(LEFT, *stack)))
    y = h - sh.height
    c.compose(sh, 0, y)
    if scroll:
        total = len(join_vertical(LEFT, *parts).rows())
        c.compose(scrollbar(room, total, room, offset), width - 2, y + 2)


def search_bar(c, y, query, focus=False, width=W):
    c.compose(join_horizontal(TOP, field(query, width - 10, focus=focus),
                              button("Go", "⏎", 10, "primary" if focus else "normal")), 0, y)


def list_rows(c, top, height, sel, items, width=W, marks=None, total=20, offset=0):
    marks = marks or {}
    y, i = top, 0
    while y + 1 < top + height and i < len(items):
        t, s, m = items[i]
        mk, mc = marks.get(i, (m, T.success if m else None))
        c.compose(list_item(t, width - 1, subtitle=s, selected=(i == sel), mark=mk, mark_color=mc,
                            dimmed=(m == "✓" and i != sel)), 0, y)
        y += 2
        i += 1
    if height > 0:
        c.compose(scrollbar(height, total, height // 2, offset), width - 1, top)


TABS = ["Search", "Feed", "Later", "Queue", "More"]
IDLE = ("WAITING", "primary", "opens 03:00", "19m")


def shell_tabbar(active: int, width: int, status=None) -> Block:
    """Three rows. The first is a rule carrying the queue's status, like the
    word in the corner of Crush's status bar; the second the tabs, the
    chosen one a pill with a column of primary either side; the third blank,
    so each tab is a three-row target."""
    rule = to_row(glyphs.SECTION * width, Pen(fg=T.separator))
    status_row = status_bar(status or IDLE, width).rows()[0]
    edges = [round(i * width / len(TABS)) for i in range(len(TABS) + 1)]
    labels = []
    for i, name in enumerate(TABS):
        w = edges[i + 1] - edges[i]
        on = i == active
        pill = (to_row(" " + name + " ", Pen(fg=T.on_primary, bg=T.primary, bold=True)) if on and w >= len(name) + 2
                else to_row(name, Pen(fg=T.on_primary, bg=T.primary, bold=True) if on else Pen(fg=T.fg_more_subtle)))
        pad = w - row_width(pill)
        labels += blank(pad // 2) + pill + blank(pad - pad // 2)
    return Block.from_rows([rule, labels, blank(width), status_row], width)


def status_bar(status, width: int) -> Block:
    """Lip Gloss's own status-bar example, in the house roles: a coloured
    label at the left, the detail on a lifted panel, a quieter segment at the
    right. The label is a word and never only a colour; the detail is cut
    with … before either end gives way."""
    label, kind, detail, right = status
    lab = tag(label, kind).rows()[0]
    rgt = to_row(f" {right} ", Pen(fg=T.fg_base, bg=T.bg_most_visible)) if right else []
    room = width - row_width(lab) - row_width(rgt)
    mid_pen = Pen(fg=T.fg_more_subtle, bg=T.bg_less_visible)
    # One column of the panel is always kept clear at its right end, so the
    # detail never runs straight into the next segment's background.
    mid = truncate_row(to_row(" " + detail, mid_pen), room - 1, to_row(glyphs.ELLIPSIS, mid_pen))
    mid += blank(room - row_width(mid), Pen(bg=T.bg_less_visible))
    return Block.from_rows([lab + mid + rgt], width)


def downloading(name, pct, rate):
    return ("↓ " + pct, "warn", name, rate)


def tab_screen(h, active, busy=False, width=W, status=None):
    """Tab bar at the foot; returns (canvas, last free row + 1, None)."""
    c = Canvas(width, h)
    if busy and status is None:
        status = downloading("ubuntu-24.04-desktop-amd64.iso", "18%", "1h")
    c.compose(shell_tabbar(active, width, status), 0, h - 4)
    return c, h - 4, None


# --- ytq --------------------------------------------------------------------------

def search_tab(h):
    up = h < SHORT
    c, bottom, _ = tab_screen(h, 0)
    c.compose(header("ytq", ["search"], W), 0, 0)
    search_bar(c, 1, "crust of rust", focus=up)
    c.compose(text("a search is ~0.1 MB", W, T.fg_most_subtle), 0, 4)
    y = 5 if up else 6
    c.compose(section("Recent", W, "free to reopen"), 0, y)
    recents = [("lofi hip hop", "20 results · 12m ago", ""), ("rust lifetimes", "20 results · 40m ago", ""),
               ("subscriptions", "60 videos · 3m ago", ""), ("termux tips", "20 results · 1h ago", "")]
    list_rows(c, y + 1, bottom - y - 1, -1, recents, total=4)
    return c


def results(h, sel=-1):
    c, bottom, strip = tab_screen(h, 0, busy=True, status=downloading("big.iso", "62%", "25m"))
    c.compose(header("ytq", ["crust of rust", "20"], W), 0, 0)
    search_bar(c, 1, "crust of rust")
    c.compose(text("20 results · ~ dates approx", W, T.fg_most_subtle), 0, 4)
    list_rows(c, 5, bottom - 5, sel, VIDEOS)
    if strip is not None:
        c.compose(minibar("big.iso", 0.62, "62% · now", W), 0, strip)
    return c


def video_parts(state, short=False):
    inner = W - 4
    audio = state == "audio"
    parts = [text("Jon Gjengset · ~3d · 90m34s · 41K", inner, T.fg_more_subtle)]
    if not short:
        parts.append(Block.text(""))
    info = {"loading": None, "audio": "129k · 2 formats"}.get(state, "480p · 3 formats")
    if not (short and state == "dup"):
        parts.append(section("Quality", inner, info))
    if state == "loading":
        parts += [Block.text(""),
                  spans([("⣾ ", T.secondary), ("asking YouTube for formats", T.fg_base)], inner),
                  text("  ~0.3 MB", inner, T.fg_most_subtle),
                  Block.text(""), Block.text(""), Block.text(""), Block.text(""), Block.text(""),
                  segmented([("At 03:00", ""), ("Now", "")], 0, inner),
                  Block.text(""), Block.text("")]
        return parts, wide("Queue for 03:00", "⏎", inner, "off")
    if audio:
        tiers = dock([("← video", ""), ("48k", ""), ("129k", "", "primary"), ("160k", "")], inner)
    else:
        tiers = dock([("240p", ""), ("480p", "", "primary"), ("720p", ""), ("audio", "")], inner)
    pick = join_horizontal(TOP, segmented([("Smallest", ""), ("Largest", "")], 1 if audio else 0, inner - 11),
                           button("Formats", "", 11))
    if audio:
        detail = spans([("10.2 MiB", T.success, True), (" · m4a · mp4a 129k", T.fg_more_subtle)], inner)
        why = Block.text("")
    else:
        detail = spans([("92 MiB", T.success, True), (" · mp4 · avc1+mp4a", T.fg_more_subtle)], inner)
        why = text("skipped vp9", inner, T.fg_most_subtle)
    now = state == "now"
    parts += [tiers, pick, detail, why,
              segmented([("At 03:00", ""), ("Now", "")], 1 if now else 0, inner)]
    size = "· 10.2 MiB" if audio else "· 92 MiB"
    if now:
        parts.append(text("today's allowance, no reserve kept", inner, T.fg_most_subtle))
        return parts, wide("Start now", "⏎", inner, "spend", "· 92 MiB")
    if state == "dup":
        return parts, join_vertical(LEFT,
                                    spans([("✓ ", T.success), ("already downloaded 2026-08-11", T.fg_base)], inner),
                                    wide("Queue it again anyway", "a", inner))
    return parts, wide("Queue for 03:00", "⏎", inner, "primary", size)


def video_sheet(state):
    def make(h):
        c = Canvas(W, h)
        c.compose(dim(results(h).render()))
        parts, footer = video_parts(state, short=h < SHORT)
        place_sheet(c, h, W, "Crust of Rust: Subtyping and Variance", parts, footer)
        return c
    return make


def formats_sheet(h):
    c = Canvas(W, h)
    c.compose(dim(results(h).render()))
    inner = W - 4
    groups = [
        ("480p", [("71 MiB~", "480p webm", "vp9 + opus · skipped", "avoid"),
                  ("92 MiB", "480p mp4", "avc1.4d401e + mp4a.40.2", "sel"),
                  ("104 MiB", "480p mp4", "av01.0.04M.08 · skipped", "avoid")]),
        ("360p", [("58 MiB", "360p mp4", "avc1 + mp4a · merged", "")]),
        ("240p", [("31 MiB", "240p mp4", "avc1 + mp4a · merged", "")]),
    ]
    blocks = [text("smallest first · ~ an estimate", inner, T.fg_most_subtle)]
    for tier, fs in groups:
        blocks.append(section(tier, inner - 1, f"{len(fs)}"))
        for sz, lb, cd, kind in fs:
            sel = kind == "sel"
            title = [Span(f"{sz:>9}  ", Pen(fg=None if sel else (T.fg_more_subtle if kind == "avoid" else T.success), bold=True)),
                     Span(lb)]
            blocks.append(list_item(title, inner - 1, subtitle=cd, selected=sel, mark="●" if sel else "",
                                    mark_color=T.success_most_subtle, dimmed=kind == "avoid"))
    place_sheet(c, h, W, "Formats · 480p", blocks)
    return c


FEED = [
    ("Saved For Tonight", "Jon Gjengset · ~1d · 10m00s", ""),
    ("Writing a terminal emulator", "Some Channel · ~3w · 1h02m", ""),
    ("Phones are computers too", "Tech Thoughts · ~1mo · 22m15s", "✓"),
    ("What Doze does to your jobs", "Android Dev · ~2mo · 18m40s", ""),
    ("Making yt-dlp behave", "Scripting Fun · ~2mo · 9m05s", ""),
    ("A night on the vessel's link", "Ops Talks · ~3mo · 40m00s", ""),
]


def feed(h):
    c, bottom, _ = tab_screen(h, 1)
    c.compose(header("ytq", ["subscriptions", "60"], W), 0, 0)
    info = join_vertical(LEFT, text("60 videos", 26, T.fg_base), text("read 3m ago · 0.4 MB", 26, T.fg_most_subtle),
                         Block.text(""))
    c.compose(join_horizontal(TOP, text(" ", 1), info, button("Re-read", "r", 13)), 0, 1)
    load = 1 if h < SHORT else 3
    list_rows(c, 4, bottom - 4 - load, -1, FEED, total=60, offset=60)
    if load == 3:
        c.compose(wide("30 more", "↓", W, "spend", "· 0.6 MB in all"), 0, bottom - 3)
    else:
        c.compose(spans([("  ↓ ", T.warning), ("pull again: 30 more · 0.6 MB in all", T.fg_more_subtle)], W), 0, bottom - 1)
    return c


# --- dlq --------------------------------------------------------------------------

def tonight_strip(width=W, run=True):
    """The card in one line, for a short screen: verdict and figure beside Run now."""
    inner = width - (13 if run else 0)
    left = (Style().border(rounded_border()).border_foreground(T.fg_most_subtle).padding(0, 1).width(inner)
            .render(spans([("waiting", T.fg_base, True), (" · 480/763 MiB", T.fg_more_subtle)], inner - 4)))
    return join_horizontal(TOP, left, button("Run now", "n", 13, "spend")) if run else left


def queue_top(c, h, width=W, run=True):
    """Tonight card (or strip on a short screen); returns the next free row."""
    if h < SHORT:
        c.compose(tonight_strip(width, run), 0, 1)
        return 4
    c.compose(tonight_card(width, run=run), 0, 1)
    return 6


def queue(h, sel=None, busy=False):
    c, bottom, strip = tab_screen(h, 3, busy=busy)
    c.compose(header("dlq", ["queue", "02:41"], W), 0, 0)
    y = queue_top(c, h)
    c.compose(filters(0, W), 0, y)
    y += 3
    if h >= SHORT:
        y += 1
    sub = Canvas(W, max(0, bottom - y))
    queue_rows(sub, 0, sel, W)
    c.compose(sub.render(), 0, y)
    if strip is not None:
        c.compose(minibar("ubuntu-24.04-desktop-amd64.iso", 0.18, "18%", W), 0, strip)
    return c


def item_sheet(h):
    c = Canvas(W, h)
    c.compose(dim(queue(h, sel=1).render()))
    inner = W - 4
    grid = [
        [("Download now", "n", "spend"), ("Move", "m")],
        [("Rename", "r"), ("Its log", "l")],
        [("Clear tries", "t"), ("Remove", "d", "danger")],
    ]
    if h < SHORT:
        facts = [spans([("queued · 2nd of 3 · ", T.fg_more_subtle), ("46 MiB at 03:00", T.info)], inner)]
    else:
        facts = [spans([("queued", T.fg_base), (" · 2nd of 3 · try 1/3", T.fg_more_subtle)], inner),
                 spans([("0 of ≤505 MiB", T.fg_more_subtle), (" · 46 MiB at 03:00", T.info)], inner),
                 text("1080p mp4 → Download/", inner, T.fg_most_subtle),
                 Block.text("")]
    place_sheet(c, h, W, "Some Talk About Rust", facts + [dock(r, inner) for r in grid])
    return c


def placing(h):
    c = Canvas(W, h)
    c.compose(header("dlq", ["moving big.iso"], W), 0, 0)
    y = queue_top(c, h, run=False)
    order = [Q[0], (Q[2][0], [("0 of ≤8 GiB", T.fg_more_subtle), (" · 434 MiB at 03:00", T.info)]),
             (Q[1][0], [("0 of ≤505 MiB", T.fg_more_subtle)])]
    sub = Canvas(W, h - 3 - y - (1 if h >= SHORT else 0))
    queue_rows(sub, 1 if h >= SHORT else 0, None, order=order, held=1, cut_after=2)
    c.compose(sub.render(), 0, y)
    if h >= SHORT:
        c.compose(text("  tap a row to put it there", W, T.fg_most_subtle), 0, h - 4)
    c.compose(dock([("↑", ""), ("↓", ""), ("Put here", "⏎", "primary")], W - 14), 0, h - 3)
    c.compose(button("Cancel", "esc", 14), W - 14, h - 3)
    return c


def toggle(word: str, on: bool, width: int) -> Block:
    """A checkbox the way Charm's huh draws one: ✓ in green when ticked,
    a quiet • when not, on a full-width tap target."""
    glyph = to_row("✓ " if on else "• ", Pen(fg=T.success if on else T.fg_most_subtle))
    row = glyph + to_row(word, Pen(fg=T.fg_base if on else T.fg_more_subtle, bold=on or None))
    inner = width - 2
    pad = inner - row_width(row)
    row = blank(pad // 2) + row + blank(pad - pad // 2)
    return (Style().border(rounded_border()).border_foreground(T.success if on else T.fg_most_subtle)
            .width(width).render(Block.from_rows([row])))


def download_sheet(h):
    c = Canvas(W, h)
    c.compose(dim(queue(h, busy=True).render()))
    inner = W - 4
    parts = [spans([("downloading", T.attention), (" · now · 1h left", T.fg_more_subtle)], inner)]
    if h >= SHORT:
        parts.append(Block.text(""))
    parts += [progress_bar(0.18, inner), text("1.02 of 5.61 GiB · 1.1 MiB/s", inner, T.fg_more_subtle)]
    if h >= SHORT:
        parts.append(Block.text(""))
    parts += [toggle("Open it when done", h >= SHORT, inner),
              dock([("Pause", "x"), ("Back", "esc")], inner)]
    place_sheet(c, h, W, "ubuntu-24.04-desktop-amd64.iso", parts)
    return c


def run_sheet(h):
    c = Canvas(W, h)
    c.compose(dim(queue(h).render()))
    inner = W - 4
    wrap = Style().foreground(T.fg_base).width(inner)
    parts = [wrap.render("Zwana is not answering, so we do not know how much data we can spend. Proceed anyway?")]
    if h >= SHORT:
        parts.append(Block.text(""))
        parts.append(text("at most what the queue declared", inner, T.fg_most_subtle))
        parts.append(Block.text(""))
    foot = join_vertical(LEFT, wide("Run anyway", "y", inner, "spend", "· ≤1.2 GiB"), wide("Not now", "esc", inner))
    place_sheet(c, h, W, "Run now", parts, foot, border=T.warning)
    return c


SETTINGS = [
    ("w", "window", "60 min", "ahead of the reset, at 04:00 here", None),
    ("r", "reserve", "100 MB", "kept back, never spent", None),
    ("a", "auto", "◉ on", "the nightly job downloads", None),
    ("c", "skip codecs", "av01 vp9", "the quality chips pass these over", None),
    ("h", "quality chips", "240-720", "learned from what you pick", None),
    ("d", "destinations", "Download", "where finished files land", None),
    ("j", "nightly job", "armed", "every 15m in the window", T.success),
    ("l", "runner log", "", "what the nightly job did and why", None),
    ("q", "quit", "", "leave ytq and dlq", None),
]


def more(h):
    c, bottom, _ = tab_screen(h, 4)
    c.compose(header("dlq", ["settings"], W), 0, 0)
    said = 1
    room = bottom - 1 - said - (1 if h >= SHORT else 0)
    y = 1
    for k, n, v, m, f in SETTINGS:
        if y + 2 > 1 + room:
            break
        c.compose(setting_row(k, n, v, m, W - 1, value_fg=f), 0, y)
        y += 2
    c.compose(scrollbar(room, len(SETTINGS) * 2, room, 0), W - 1, 1)
    c.compose(text("reserve is 100 MB again (the default)", W, T.info), 0, bottom - 1)
    return c


def setting_sheet(h):
    c = Canvas(W, h)
    c.compose(dim(more(h).render()))
    inner = W - 4
    parts = [field("45", inner, focus=h < SHORT),
             text("a multiple of 15, 15 min to 24 h", inner, T.fg_most_subtle),
             dock([("30m", ""), ("45m", "", "primary"), ("1h", ""), ("2h", "")], inner)]
    place_sheet(c, h, W, "window", parts, dock([("Cancel", "esc"), ("Set", "⏎", "primary")], inner))
    return c


def narrow_queue(h):
    w = 32
    c, bottom, _ = tab_screen(h, 3, width=w, status=downloading("ubuntu-24.04-desktop-amd64.iso", "18%", "1h"))
    if h < 13:
        c.compose(header("dlq", ["waiting · 480 MiB"], w), 0, 0)
        y = 1
    else:
        c.compose(header("dlq", ["queue"], w), 0, 0)
        c.compose(tonight_card(w, verdict=("waiting", " · 19m"), fig="480/763 MiB"), 0, 1)
        y = 6
    c.compose(filters(0, w), 0, y)
    y += 3
    sub = Canvas(w, max(0, bottom - y))
    queue_rows(sub, 0, None, w, cut="window · 480 MiB")
    c.compose(sub.render(), 0, y)
    return c


# ---------------------------------------------------------------------------------

def build():
    K = "Keyboard up: "
    add("k-search", "Search", "ytq", search_tab, [
        "Keyboard down, the Search tab shows the bar and your recent searches, which reopen for free.",
        K + "the bar takes focus and the recents shrink to what fits. Everything you need while typing stays above the keyboard, and the phone keyboard's enter key searches.",
        "Subs and Watch later are the Feed and Later tabs; typing `subs` or `wl` still jumps to them.",
    ])
    add("k-results", "Search results", "ytq", lambda h: results(h, 0), [
        "One tap on a row opens the video sheet and starts its format fetch.",
        "Above the tabs, on every tab, a status bar in Lip Gloss's own status-bar style: a coloured label, the detail on a lifted panel, a quieter segment at the right. “↓ 62%” in amber with big.iso and the time it has left while something downloads; “WAITING” in purple, “opens 03:00” and “19m” when nothing does. It sits on the very last row, where Crush keeps its status, under three-row tabs, and it is there at every height.",
        K + "the list keeps three rows; the search bar, the status and the tabs stay, because they are how you get anywhere.",
    ])
    add("k-sheet-loading", "Video sheet, formats on the way", "ytq", video_sheet("loading"), [
        "The sheet opens on the tap, before anything comes back. The format fetch runs behind it and is kept for the session if you close the sheet.",
        K + "the sheet takes the whole height below the header and its button stays pinned at the bottom.",
    ])
    add("k-sheet", "Video sheet: pick and queue", "ytq", video_sheet("ready"), [
        "One sheet replaces the formats and confirm screens; every choice on it is a tap.",
        "The quality buttons are your heights (240p, 480p, 720p, audio) at full size. A wider screen adds buttons rather than shrinking them. The sheet opens on your last height and rule, so smallest at 480p is no taps at all.",
        "One figure: the size in green, repeated on the button. A quiet “skipped vp9” appears only when the chips passed a codec over.",
        "No name row. A download has one name everywhere, the video's own title cleaned of the characters Android's shared storage refuses: `Crust of Rust - Subtyping and Variance.mp4` in Downloads, and the same name behind `NN-` in the queue. Rename on the download's sheet in the Queue tab covers the rare change.",
        K + "the sheet keeps the quality buttons and the Queue button. “At 03:00” or Now scrolls under them, with a scrollbar saying there is more. The common path never needs the scroll.",
    ])
    add("k-sheet-audio", "Video sheet: audio", "ytq", video_sheet("audio"), [
        "The audio button turns the row into bitrates, with ← video to go back; Smallest or Largest picks inside a bitrate.",
        K + "the same pinned button and scrolled tail as the video sheet.",
    ])
    add("k-sheet-now", "Video sheet: now", "ytq", video_sheet("now"), [
        "Now turns the button into “Start now · 92 MiB”, in the spend style, and one grey line says what is different: it comes out of today's allowance with no reserve kept back. That button is the one yes.",
        "Off the vessel's wifi (zwana does not answer) the line becomes “on mobile data, charged” and the button turns red. That is the one case where now costs money and the window would not.",
        K + "the Start button is pinned, so it is never scrolled away from the figure on it.",
    ])
    add("k-sheet-dup", "Video sheet: already have it", "ytq", video_sheet("dup"), [
        "The duplicate screen is a line on the sheet, directly above the button that answers it: “✓ already downloaded 2026-08-11”, then “Queue it again anyway”.",
        K + "the ✓ line is pinned with the button, so the notice and its answer stay together however the sheet scrolls.",
    ])
    add("k-formats", "All formats", "ytq", formats_sheet, [
        "Grouped by height, smallest first, opened at the height the sheet was on. Skipped codecs are dimmed but stay tappable.",
        K + "the same list, shorter; it scrolls.",
    ])
    add("k-feed", "Feed tab", "ytq", feed, [
        "The tab reads the feed when first opened. At the end of the list sits “↓ 30 more · 0.6 MB in all”, the total price of the deeper look. A tap on it, ↓ on the last row, or a fresh drag down once the list has come to rest at the end, reads the next page; the button turns into its spinner while it loads.",
        "A fling's momentum never fetches. It scrolls to the end and stops there, and the next page waits for a deliberate pull: the list has to sit still at the end (about half a second) before a drag down counts. Momentum arrives as an unbroken stream of wheel events, so it can never produce that pause and then more.",
        K + "the button becomes one line saying the same thing, and the list keeps three rows.",
    ])
    add("k-queue", "Queue tab", "dlq", lambda h: queue(h, busy=True), [
        "The window card leads: verdict, a bar of what the next window may spend against what expires, and Run now. Queued, Failed and Done filter the list. The cut line is unchanged.",
        "The selected tab is a pill with a column of purple either side of its word, so “Queue” sits as centred as “Search”. The running download is in the status rule above the tabs, so the tab itself carries no badge.",
        K + "the card becomes a one-line strip beside Run now. The filters, the status and the tabs keep their full size.",
    ])
    add("k-item", "A download's sheet", "dlq", item_sheet, [
        "A sheet over the queue with actions_for()'s buttons in a grid; each calls what its key calls.",
        K + "the facts fold into one line so the whole grid still fits without scrolling.",
    ])
    add("k-place", "Moving a download", "dlq", placing, [
        "Move on a download's sheet holds it as a ◆ row. ↑ and ↓ step it, a tap on a row puts it there, a swipe drags it, and the cut line re-plans at every step. Here big.iso has taken Some Talk About Rust's share of the 03:00 window.",
        "Ordering lives only here now. The video sheet no longer has a place row: ytq queues last, and anything that should go sooner is moved here, with the cut line showing what that costs the night.",
        K + "the card is a strip, the hint line goes, and the row being moved stays in view.",
    ])
    add("k-download", "The running download", "dlq", download_sheet, [
        "One reading per draw, so the words and the bar cannot disagree.",
        "Time left is always one unit, rounded to the nearest: 35s, 5m, 1h, never 1h10m. The status bar shows it rather than the speed; the speed stays here, on the line under the bar.",
        "“Open it when done” is a checkbox drawn the way Charm's huh draws one: a quiet • when off (right), a green ✓ and outline when ticked (left). A tap or `o` toggles it. It is offered only for a download this session started, because the ask lives in this session; on a nightly run the row is not there.",
        "Pause is what Stop always did: SIGINT, the bytes so far are kept, and the download carries on in the next window or with Download now. Nothing is lost, so it is not drawn as a destructive button.",
        K + "the blank lines go; nothing else does.",
    ])
    add("k-run", "Run now: the one yes", "dlq", run_sheet, [
        "Every confirm is a sheet from the bottom. The yes is full width with the figure on it, No is last, and the border turns warning-coloured when nothing is counting the spend.",
        "With zwana out of reach the question is the one sentence: “Zwana is not answering, so we do not know how much data we can spend. Proceed anyway?” The yes answers it, “Run anyway · ≤1.2 GiB”, the most the queued items declared.",
        K + "the grey line goes; the question and both answers stay.",
    ])
    add("k-more", "More: settings and the rest", "dlq", more, [
        "Settings, destinations, the nightly job, the runner log and Quit, as one scrolling list of two-line rows. A switch toggles in place; a number opens a sheet.",
        K + "fewer rows show and the list scrolls; the line saying what just changed stays above the tabs.",
    ])
    add("k-setting", "Setting a number", "dlq", setting_sheet, [
        "Preset buttons mean most changes need no typing at all: with the keyboard down, tap 45m and Set.",
        K + "the field takes focus, still prefilled, and Set stays pinned above the keyboard.",
    ])
    add("k-narrow", "The floor: 32 columns", "dlq", narrow_queue, [
        "At 32 columns the card's sentences shorten and the tabs keep all five at six columns each.",
        "Keyboard up (11 rows): the card folds into the header's details, and the filters, the list and the tabs keep their size.",
    ], width=32, heights=(20, 11))
    return SCREENS





# --- the button-height question --------------------------------------------------

def chip1(word: str, on: bool = False, kind: str = "normal") -> list:
    """A one-row chip: the word on a filled pill, no border."""
    if on:
        pen = Pen(fg=T.on_primary, bg=T.primary, bold=True)
    elif kind == "spend":
        pen = Pen(fg=T.bg_base, bg=T.warning, bold=True)
    else:
        pen = Pen(fg=T.fg_base, bg=T.bg_most_visible)
    return to_row(f" {word} ", pen)


def chip_line(chips: list[tuple], width: int) -> Block:
    """Equal-width one-row chips with a one-column gap between them; each
    chip's pill fills its cell, word centred."""
    n = len(chips)
    cell = (width - (n - 1)) // n
    extra = (width - (n - 1)) - cell * n
    row = []
    for i, (word, on, kind) in enumerate(chips):
        w = cell + (1 if i < extra else 0)
        pen = (Pen(fg=T.on_primary, bg=T.primary, bold=True) if on else
               Pen(fg=T.bg_base, bg=T.warning, bold=True) if kind == "spend" else
               Pen(fg=T.fg_base, bg=T.bg_most_visible))
        word = word[:w]
        pad = w - len(word)
        row += to_row(" " * (pad // 2) + word + " " * (pad - pad // 2), pen)
        if i < n - 1:
            row += blank(1)
    return Block.from_rows([row], width)


def compact_sheet(h, one_row: bool):
    c = Canvas(W, h)
    c.compose(dim(results(h).render()))
    inner = W - 4
    if one_row:
        parts = [text("Jon Gjengset · ~3d · 90m34s · 41K", inner, T.fg_more_subtle),
                 section("Quality", inner, "480p · 3 formats"),
                 chip_line([("240p", False, ""), ("480p", True, ""), ("720p", False, ""), ("audio", False, "")], inner),
                 Block.text(""),
                 chip_line([("◉ Smallest", True, ""), ("○ Largest", False, ""), ("Formats", False, "")], inner),
                 spans([("92 MiB", T.success, True), (" · mp4 · avc1+mp4a", T.fg_more_subtle)], inner),
                 chip_line([("◉ At 03:00", True, ""), ("○ Now", False, "")], inner)]
        foot = Block.from_rows([blank(inner)] + [chip_line([("⏎ Queue for 03:00 · 92 MiB", True, "")], inner).rows()[0]], inner)
    else:
        parts, foot = video_parts("ready", short=True)
    place_sheet(c, h, W, "Crust of Rust: Subtyping and Variance", parts, foot)
    return c


def chips_question():
    return [{"label": "three-row buttons · 40×14", "html": to_html(compact_sheet(UP, False).render())},
            {"label": "one-row chips · 40×14", "html": to_html(compact_sheet(UP, True).render())}]


if __name__ == "__main__":
    out = build()
    out.append({"key": "q-chips", "shots_free": chips_question()})
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False)
