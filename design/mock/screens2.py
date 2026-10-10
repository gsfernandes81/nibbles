"""Round two: one app shell with tabs, sheets instead of pages."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from kit import *  # noqa: F401,F403
from kit import T, glyphs

W, H = 40, 24
SCREENS: list[dict] = []


def add(key, title, canvas, notes, group, width=W, keyboard_from=None):
    SCREENS.append({"key": key, "title": title, "app": group, "notes": notes,
                    "html": to_html(canvas.render()), "width": width,
                    "keyboard_from": keyboard_from})


# --- shell pieces ---------------------------------------------------------------

TABS = ["Search", "Feed", "Later", "Queue", "More"]


def tabbar(active: int, width: int = W, queue_busy: bool = False) -> Block:
    """Three rows: a rule, the labels, a blank. Each tab owns 1/5 of the width."""
    edges = [round(i * width / len(TABS)) for i in range(len(TABS) + 1)]
    rule = to_row(glyphs.SECTION * width, Pen(fg=T.separator))
    labels: list = []
    for i, name in enumerate(TABS):
        w = edges[i + 1] - edges[i]
        label = name + (" ↓" if queue_busy and name == "Queue" and w >= len(name) + 3 else "")
        label = label[:w] if len(label) > w else label
        pad = w - len(label)
        lp = pad // 2
        if i == active:
            pen = Pen(fg=T.on_primary, bg=T.primary, bold=True)
            cell = blank(lp, Pen(bg=T.primary)) + to_row(label, pen) + blank(pad - lp, Pen(bg=T.primary))
        else:
            cell = blank(lp) + to_row(label, Pen(fg=T.fg_more_subtle)) + blank(pad - lp)
            if queue_busy and name == "Queue":
                cell = blank(lp) + to_row(name, Pen(fg=T.fg_more_subtle)) + to_row(" ↓", Pen(fg=T.attention)) + blank(pad - lp - 2)
        labels += cell
    return Block.from_rows([rule, labels, blank(width)], width)


def dim(block: Block) -> Block:
    """What sits behind a sheet: every colour pushed back to the faintest grey."""
    rows = []
    for row in block.rows():
        rows.append([(ch, Pen(fg=T.bg_most_visible if ch.strip() else None)) for ch, _ in row])
    return Block.from_rows(rows, block.width)


def sheet(parts: list[Block], width: int = W, title: str = "", border=None, close=True) -> Block:
    """A bottom sheet: rounded top corners, open at the bottom edge."""
    inner = width - 4
    head = []
    if title:
        tb = dialog_title(title, inner - (8 if close else 0))
        if close:
            tb = join_horizontal(TOP, tb, text("  esc ×", 8, T.fg_most_subtle))
        head = [tb]
    body = join_vertical(LEFT, *head, *parts)
    return (Style().border(rounded_border(), True, True, False, True)
            .border_foreground(border or T.primary).padding(0, 1).width(width).render(body))


def minibar(name: str, pct: float, note: str, width: int = W) -> Block:
    """The running download, two rows, the whole strip one tap target."""
    top = spans([(" ↓ ", T.attention), (name, T.fg_base)], width - len(note) - 1)
    top = join_horizontal(TOP, top, text(note + " ", len(note) + 1, T.fg_more_subtle))
    bar = join_horizontal(TOP, text(" ", 1), progress_bar(pct, width - 2, show_percentage=False), text(" ", 1))
    return join_vertical(LEFT, top, bar)


def link(label: str, width: int, key: str = "") -> Block:
    row = spans(([(key + " ", T.fg_more_subtle)] if key else []) + [(label, T.fg_subtle)], width - 2)
    return join_horizontal(TOP, row, text(glyphs.ARROW_RIGHT, 2, T.fg_most_subtle))


def kv(key: str, name: str, value: str, width: int, chevron=True, value_fg=None) -> Block:
    left = spans([(f"{key} " if key else "  ", T.fg_more_subtle), (f"{name:<7}", T.fg_more_subtle),
                  (value, value_fg or T.fg_base)], width - 2)
    return join_horizontal(TOP, left, text(glyphs.ARROW_RIGHT if chevron else "", 2, T.fg_most_subtle))


VIDEOS = [
    ("Crust of Rust: Subtyping and Variance", "Jon Gjengset · ~3d · 90m34s · 41K", ""),
    ("Making a Case for Rust in the Kernel", "Some Channel · ~1w · 12m40s · 8.2K", "✓"),
    ("lofi hip hop radio - beats to relax/study to", "Lofi Girl · live · 1.1M", ""),
    ("Rust Lifetimes Finally Explained", "Let's Get Rusty · ~2y · 26m01s · 1.4M", ""),
    ("The Async Book, read aloud (part 3)", "Rust Audio · ~5mo · 2h04m · 912", ""),
    ("Why my Termux setup is ridiculous", "phonehacker · ~4d · 8m12s · 22K", "✓"),
    ("Building a TUI with blessed", "Python Corner · ~1mo · 31m09s · 5.5K", ""),
    ("Shipping software on a metered link", "Ops Talks · ~1y · 44m00s · 3.1K", ""),
]


def rows(c, top, height, sel, items, width=W, marks=None, total=20, offset=0):
    marks = marks or {}
    y, i = top, 0
    while y + 1 < top + height and i < len(items):
        t, s, m = items[i]
        mk, mc = marks.get(i, (m, T.success if m else None))
        c.compose(list_item(t, width - 1, subtitle=s, selected=(i == sel), mark=mk, mark_color=mc,
                            dimmed=(m == "✓" and i != sel)), 0, y)
        y += 2
        i += 1
    c.compose(scrollbar(height, total, height // 2, offset), width - 1, top)


def search_bar(c, y, query, focus=False, width=W):
    c.compose(join_horizontal(TOP, field(query, width - 10, focus=focus),
                              button("Go", "⏎", 10, "primary" if focus else "normal")), 0, y)


# --- ytq: search and the video sheet ---------------------------------------------

def results_base(width=W, busy=True):
    c = screen(width, H)
    c.compose(header("ytq", ["crust of rust", "20"], width), 0, 0)
    search_bar(c, 1, "crust of rust", width=width)
    c.compose(text("20 results · ~ dates approx", width, T.fg_most_subtle), 0, 4)
    rows(c, 5, 14, -1 if not busy else -1, VIDEOS, width, marks={})
    if busy:
        c.compose(minibar("big-iso", 0.62, "62% · PAID", width), 0, 19)
    c.compose(tabbar(0, width, queue_busy=busy), 0, 21)
    return c


def s_search():
    c = screen(W, H)
    c.compose(header("ytq", ["search"], W), 0, 0)
    search_bar(c, 1, "crust of rust", focus=True)
    c.compose(text("a search is ~0.1 MB", W, T.fg_most_subtle), 0, 4)
    c.compose(section("Recent", W, "free to reopen"), 0, 6)
    c.compose(list_item("lofi hip hop", W - 1, subtitle="20 results · 12m ago"), 0, 7)
    c.compose(list_item("rust lifetimes", W - 1, subtitle="20 results · 40m ago"), 0, 9)
    for y in range(11, H):
        c.compose(text("", W, bg=T.bg_least_visible), 0, y)
    add("s-search", "Search tab, typing", c, [
        "The search bar sits at the top of the Search tab, with its own Go button. The phone keyboard's enter key also searches.",
        "Subs and Watch later are not typed any more: they are the Feed and Later tabs. Typing `subs` or `wl` still jumps to them.",
        "Earlier searches from this session sit under the bar and reopen for free.",
    ], "ytq", keyboard_from=11)


def s_results():
    c = results_base()
    c2 = screen(W, H)
    c2.compose(c.render())
    rows(c2, 5, 14, 0, VIDEOS)
    add("s-results", "Search results", c2, [
        "Results stay under the search bar, which can be tapped to edit the query. There is no separate results page and no Back.",
        "One tap on a row opens the video sheet right away and starts its format fetch in the background.",
        "A running download follows you as a two-row strip above the tabs (here `big-iso`, started from the queue). Tapping the strip opens its sheet. The Queue tab carries a ● while anything downloads.",
        "The tab bar is the way around. Each tab is a fifth of the width and three rows tall, the same height as a button.",
    ], "ytq")


def chip_row(labels: list[str], chosen: int, width: int) -> Block:
    """Compact tap targets: a rounded border hugging the label, spare columns shared out."""
    mins = [len(l) + 2 for l in labels]
    spare = width - sum(mins)
    widths = [m + spare // len(mins) + (1 if i < spare % len(mins) else 0) for i, m in enumerate(mins)]
    blocks = []
    for i, (l, w) in enumerate(zip(labels, widths)):
        on = i == chosen
        blocks.append(Style().border(rounded_border()).border_foreground(T.primary if on else T.fg_most_subtle)
                      .width(w).align_horizontal(0.5)
                      .render(Block.from_rows([to_row(l, Pen(fg=T.fg_base, bold=on or None))])))
    return join_horizontal(TOP, *blocks)


def video_sheet(state: str):
    base = results_base()
    c = screen(W, H)
    c.compose(dim(base.render()))
    inner = W - 4
    meta = text("Jon Gjengset · ~3d · 90m34s · 41K", inner, T.fg_more_subtle)
    parts = [meta]
    if state == "dup":
        parts.append(spans([("✓ ", T.success), ("already downloaded 2026-08-11", T.fg_base)], inner))
    else:
        parts.append(Block.text(""))
    audio = state == "audio"
    info = {"loading": None, "audio": "129k · 2 formats"}.get(state, "480p · 3 formats")
    parts.append(section("Quality", inner, info))
    if state == "loading":
        parts += [
            Block.text(""),
            spans([("⣾ ", T.secondary), ("asking YouTube for formats", T.fg_base)], inner),
            text("  ~0.3 MB, in the background", inner, T.fg_most_subtle),
            Block.text(""),
            Block.text(""),
            Block.text(""),
            Block.text(""),
            Block.text(""),
            segmented([("Tonight", "free"), ("Now", "PAID")], 0, inner),
            Block.text(""),
            Block.text(""),
            wide("Queue tonight", "⏎", inner, "off"),
        ]
    else:
        if audio:
            tiers = dock([("← video", ""), ("48k", ""), ("129k", "", "primary"), ("160k", "")], inner)
        else:
            tiers = dock([("240p", ""), ("480p", "", "primary"), ("720p", ""), ("audio", "")], inner)
        pick = join_horizontal(TOP, segmented([("Smallest", ""), ("Largest", "")], 1 if audio else 0, inner - 11),
                               button("Formats", "", 11))
        if audio:
            detail = spans([("10.2 MiB", T.success, True), (" · m4a · mp4a 129k · tonight", T.fg_more_subtle)], inner)
            why = Block.text("")
        else:
            detail = spans([("92 MiB", T.success, True), (" · mp4 · avc1+mp4a · tonight", T.fg_more_subtle)], inner)
            why = text("skipped vp9", inner, T.fg_most_subtle)
        parts += [tiers, pick, detail, why]
        now = state == "now"
        parts.append(segmented([("Tonight", "free"), ("Now", "PAID")], 1 if now else 0, inner))
        parts.append(kv("e", "name", "crust-of-rust-subtyping", inner))
        if now:
            parts.append(wide("Start now", "⏎", inner, "spend", "· 92 MiB PAID"))
        elif state == "dup":
            parts.append(kv("p", "place", "last · 5th of 5", inner))
            parts.append(wide("Queue it again anyway", "a", inner))
        else:
            parts.append(kv("p", "place", "last · 5th of 5", inner))
            parts.append(wide("Queue tonight", "⏎", inner, "primary", "· 10.2 MiB" if audio else "· 92 MiB"))
    sh = sheet(parts, W, "Crust of Rust: Subtyping and Variance")
    c.compose(sh, 0, H - sh.height)
    return c


def s_sheet_loading():
    add("s-sheet-loading", "Video sheet, formats on the way", video_sheet("loading"), [
        "The sheet opens on the same tap, before anything comes back. Its title and line come from the result row, which is already on screen.",
        "The format fetch runs behind it. If you close the sheet (esc, or a tap on the dimmed list above it) the fetch finishes anyway and is kept for the session, so reopening is instant.",
        "Queue tonight is drawn but disabled until the formats land.",
    ], "ytq")


def s_sheet_ready():
    add("s-sheet", "Video sheet: pick and queue", video_sheet("ready"), [
        "This one sheet replaces the formats screen and the confirm screen. Every choice on it is a tap; nothing after the search needs the keyboard.",
        "The chips are the heights you use, not YouTube's top four, and they keep the full roomy size. At 40 columns that is four: your three most-used heights in order (here 240p, 480p and 720p) plus audio. A wider screen adds chips (360p would be next) rather than narrowing them. The set is learned from what you pick and can be set by hand in More; any other height is under Formats.",
        "The sheet opens on the height and the Smallest or Largest rule you used last, so the usual case (smallest at 480p) takes no taps at all.",
        "The size under the chips is the one figure on the sheet, and the button repeats it. When the chips passed over a codec, a quiet grey line says “skipped vp9” and nothing more.",
        "Formats is a button that opens the full table at the tier you are on.",
    ], "ytq")


def s_sheet_audio():
    add("s-sheet-audio", "Video sheet: audio", video_sheet("audio"), [
        "The audio chip turns the tier row into bitrates, with ← video to go back. The same Smallest or Largest rule then picks inside a bitrate, for example m4a against opus at 129k.",
        "Largest is shown here, because for audio either can be the one you want. The video and audio rules are remembered separately.",
    ], "ytq")


def s_sheet_now():
    add("s-sheet-now", "Video sheet: now, PAID", video_sheet("now"), [
        "Choosing Now turns the big button into “Start now · 92 MiB PAID”. That button is the one yes; there is no second dialog and no second copy of the figure.",
        "Place disappears, because a download that starts now is never queued behind anything.",
    ], "ytq")


def s_sheet_dup():
    add("s-sheet-dup", "Video sheet: already have it", video_sheet("dup"), [
        "The duplicate screen becomes a line on the sheet: what it is, when and under which name. The button changes to “Queue it again anyway”, and a still works.",
        "Because the result row already carried a ✓, most repeats never get this far.",
    ], "ytq")


def s_all_formats():
    base = video_sheet("ready")
    c = screen(W, H)
    c.compose(dim(base.render()))
    inner = W - 4
    groups = [
        ("480p", [("71 MiB~", "480p webm", "vp9 + opus · skipped", "avoid"),
                  ("92 MiB", "480p mp4", "avc1.4d401e + mp4a.40.2", "sel"),
                  ("104 MiB", "480p mp4", "av01.0.04M.08 · skipped", "avoid")]),
        ("360p", [("58 MiB", "360p mp4", "avc1 + mp4a · merged", "")]),
    ]
    blocks = [text("smallest first · ~ an estimate", inner, T.fg_most_subtle)]
    for tier, fs in groups:
        blocks.append(section(tier, inner - 1, f"{len(fs)}"))
        for sz, lb, cd, kind in fs:
            sel = kind == "sel"
            title = [Span(f"{sz:>9}  ", Pen(fg=None if sel else (T.fg_more_subtle if kind == "avoid" else T.success), bold=True)), Span(lb)]
            blocks.append(list_item(title, inner - 1, subtitle=cd, selected=sel,
                                    mark="●" if sel else "", mark_color=T.success_most_subtle,
                                    dimmed=kind == "avoid"))
    body = join_vertical(LEFT, *blocks)
    body = join_horizontal(TOP, body, scrollbar(body.height, 26, body.height, 3))
    sh = sheet([body], W, "Formats · 480p")
    c.compose(sh, 0, H - sh.height)
    add("s-formats", "All formats", c, [
        "The full table opens on the tier the sheet was on, grouped by tier, smallest first. Every tier is one swipe away.",
        "Skipped codecs stay in the table, dimmed, so they are one tap away for a video that only has them.",
        "A tap on a row picks it and returns to the sheet. The tier chip follows, and the grey line reads “picked by hand”.",
    ], "ytq")


# --- feed ------------------------------------------------------------------------

def s_feed():
    feed = [
        ("Saved For Tonight", "Jon Gjengset · ~1d · 10m00s", ""),
        ("Writing a terminal emulator", "Some Channel · ~3w · 1h02m", ""),
        ("Phones are computers too", "Tech Thoughts · ~1mo · 22m15s", "✓"),
        ("What Doze does to your jobs", "Android Dev · ~2mo · 18m40s", ""),
        ("Making yt-dlp behave", "Scripting Fun · ~2mo · 9m05s", ""),
        ("A night on the vessel's link", "Ops Talks · ~3mo · 40m00s", ""),
    ]
    c = screen(W, H)
    c.compose(header("ytq", ["subscriptions", "60"], W), 0, 0)
    info = join_vertical(LEFT, text("60 videos", 26, T.fg_base), text("read 3m ago · 0.4 MB", 26, T.fg_most_subtle),
                         Block.text(""))
    c.compose(join_horizontal(TOP, text(" ", 1), info, button("Re-read", "r", 13)), 0, 1)
    rows(c, 4, 12, -1, feed, total=60, offset=50)
    c.compose(spans([("  ⣾ ", T.secondary), ("reading 90 · 0.6 MB in all", T.fg_more_subtle)], W), 0, 17)
    c.compose(text("  up to 150; past that, the cap", W, T.fg_most_subtle), 0, 18)
    c.compose(tabbar(1), 0, 21)
    add("s-feed", "Feed tab, scrolling on", c, [
        "Opening the tab reads the feed if this session has not read it yet, and the price is on screen while it loads. Your subscriptions are the reason to open the tab, so there is no button to press first.",
        "Scrolling to the end, by swipe, by the scrollbar or with ↓, reads the next page in the background. The spinner row says what the deeper look costs as a total. The rows above it stay usable.",
        "At the bottom of the feed or at the 150 cap, the spinner row becomes a sentence saying which of the two it is. An empty feed still says that the cookie is the likely cause, and how old the cookie jar is.",
        "Later is the same tab shape for Watch Later.",
    ], "ytq")


# --- dlq: the queue tab ----------------------------------------------------------

def tonight_card(width=W, verdict=("waiting", " · 23:00Z (19m)"), pct=0.63, fig="480 of 763 MiB tonight", run=True):
    inner = width - 4
    tw = inner - (14 if run else 0)
    left = join_vertical(LEFT,
                         spans([(verdict[0], T.fg_base, True), (verdict[1], T.fg_more_subtle)], tw),
                         progress_bar(pct, tw, show_percentage=False),
                         text(fig, tw, T.fg_more_subtle))
    body = join_horizontal(TOP, left, text(" ", 1), button("Run now", "n", 13, "spend")) if run else left
    return (Style().border(rounded_border()).border_foreground(T.fg_most_subtle)
            .padding(0, 1).width(width).render(body))


def filters(active: int, width=W):
    names = [("Queued 3", ""), ("Failed 1", ""), ("Done 3", "")]
    return dock([(n, k, "primary" if i == active else "normal") for i, (n, k) in enumerate(names)], width)


Q = [
    ("ubuntu-24-04-desktop", [("● ", T.attention), ("18%  1.02 of 5.61 GiB", T.fg_more_subtle)]),
    ("some-talk", [("0 of ≤505 MiB", T.fg_more_subtle), (" · 46 MiB tonight", T.info)]),
    ("big-iso", [("0 of ≤8 GiB", T.fg_more_subtle)]),
]


def queue_rows(c, y, sel=None, width=W, order=None, held=None, cut_after=2, cut="tonight ends here · 480 MiB"):
    items = order or Q
    for i, (name, sub) in enumerate(items):
        if i == cut_after:
            dash = glyphs.SECTION
            line = f"{dash * 2} {cut} "
            c.compose(spans([("  " + line, T.warning), (dash * (width - 3 - len(line)), T.warning)], width), 0, y)
            y += 1
        if held == i:
            c.compose(list_item(name, width - 1, subtitle="".join(t for t, _ in sub), selected=True,
                                mark="◆", mark_color=T.on_primary), 0, y)
        else:
            s = "".join(t for t, _ in sub) if i == sel else [Span(t, Pen(fg=f)) for t, f in sub]
            c.compose(list_item(name, width - 1, subtitle=s, selected=(i == sel)), 0, y)
        y += 2
    return y


def queue_base(width=W, sel=None, busy=False):
    c = screen(width, H)
    c.compose(header("dlq", ["queue", "22:41Z"], width), 0, 0)
    c.compose(tonight_card(width), 0, 1)
    c.compose(filters(0, width), 0, 6)
    queue_rows(c, 10, sel, width)
    if busy:
        c.compose(minibar("ubuntu-24-04-desktop", 0.18, "18% · tonight", width), 0, 19)
    c.compose(tabbar(3, width, queue_busy=busy), 0, 21)
    return c


def s_queue():
    add("s-queue", "Queue tab", queue_base(busy=True), [
        "Tonight is a card at the top: the verdict from gate(), a bar of what tonight may spend against what expires, and Run now beside it. Run now still asks its one question.",
        "Queued, Failed and Done are filter buttons with their counts, so a phone shows one group at a time instead of three stacked lists. Done is newest first, as now.",
        "The cut line is unchanged: computed, never an item, with the share on the row it falls inside.",
        "A tap on a row opens its sheet.",
    ], "dlq")


def s_item():
    base = queue_base(sel=1)
    c = screen(W, H)
    c.compose(dim(base.render()))
    inner = W - 4
    grid = [
        [("Download now", "n", "spend"), ("Move", "m")],
        [("Rename", "r"), ("Its log", "l")],
        [("Clear tries", "t"), ("Remove", "d", "danger")],
    ]
    parts = [
        spans([("queued", T.fg_base), (" · 2nd of 3 · try 1/3", T.fg_more_subtle)], inner),
        spans([("0 of ≤505 MiB", T.fg_more_subtle), (" · 46 MiB tonight", T.info)], inner),
        text("Some talk [1080p mp4] → Download/", inner, T.fg_most_subtle),
        Block.text(""),
    ] + [dock(r, inner) for r in grid]
    sh = sheet(parts, W, "some-talk")
    c.compose(sh, 0, H - sh.height)
    add("s-item", "A download's sheet", c, [
        "The item screen becomes a sheet over the queue, so the cut line and its neighbours stay in view (dimmed) above it.",
        "actions_for() still decides which buttons appear, so a failed item shows Put back and a done one shows Open. Every button calls the function its key calls.",
        "Download now and Remove each open their one confirm. Remove still offers keep-the-bytes and delete-the-bytes, with the same keys every time.",
    ], "dlq")


def s_place():
    c = screen(W, H)
    c.compose(header("dlq", ["placing crust-of-rust-subtyping"], W), 0, 0)
    c.compose(tonight_card(W, run=False, fig="480 of 763 MiB tonight"), 0, 1)
    order = [Q[0], ("crust-of-rust-subtyping", [("new · ≤95 MiB", T.info)]), Q[1], Q[2]]
    queue_rows(c, 7, None, order=order, held=1, cut_after=2)
    c.compose(text("  tap a row to put it there", W, T.fg_most_subtle), 0, 17)
    c.compose(dock([("↑", ""), ("↓", ""), ("Put it here", "⏎", "primary")], W - 12), 0, 21)
    c.compose(button("Last", "esc", 12), W - 12, 21)
    add("s-place", "Placing a new video", c, [
        "Place on the video sheet opens this screen: dlq's queue holding the unwritten video as a phantom ◆ row. It is the same holding mode Move uses.",
        "Up and down step it one place, a tap on another row puts it there, and a swipe drags it. The card and the cut line re-plan at every step, so you can watch it take tonight's last place.",
        "Put it here returns to the sheet with the place filled in. The video is still written first and moved afterwards through place() and do_reorder().",
    ], "dlq")


def s_run_now():
    base = queue_base()
    c = screen(W, H)
    c.compose(dim(base.render()))
    inner = W - 4
    parts = [
        Style().foreground(T.fg_base).width(inner).render(
            "zwana does not answer, so nothing is counting this. A blind run is bounded by what the items declared."),
        Block.text(""),
        spans([("up to ", T.fg_more_subtle), ("1.2 GiB", T.warning, True), (" on whatever the phone", T.fg_more_subtle)], inner),
        text("is using; on mobile data, charged", inner, T.fg_more_subtle),
        Block.text(""),
        wide("Run blind", "y", inner, "spend", "· ≤1.2 GiB"),
        wide("Not now", "esc", inner),
    ]
    sh = sheet(parts, W, "Run now · NOT COUNTED", border=T.warning)
    c.compose(sh, 0, H - sh.height)
    add("s-run", "Run now: the one yes", c, [
        "Every confirm is a sheet from the bottom, inside thumb reach, never a centred box. The yes is full width and has the figure on its face. No is the bottom button.",
        "The wording comes from run_note(), and the figure from the runner's blind_budget, as now. The sheet's border turns warning-coloured when nothing is counting the spend.",
    ], "dlq")


def s_download():
    base = queue_base(busy=True)
    c = screen(W, H)
    c.compose(dim(base.render()))
    inner = W - 4
    parts = [
        spans([("downloading", T.attention), (" · nightly · 1.1 MiB/s", T.fg_more_subtle)], inner),
        Block.text(""),
        progress_bar(0.18, inner),
        text("1.02 of 5.61 GiB · stops at 00:00Z", inner, T.fg_more_subtle),
        Block.text(""),
        segmented([("Open when done", ""), ("Leave it", "")], 1, inner),
        dock([("Stop", "x", "danger"), ("Hide", "esc")], inner),
    ]
    sh = sheet(parts, W, "ubuntu-24-04-desktop")
    c.compose(sh, 0, H - sh.height)
    add("s-download", "The running download", c, [
        "Tapping the strip above the tabs opens this sheet. It shows one reading per draw, so the words and the bar cannot disagree.",
        "Stop sends SIGINT, as the screen does today. “Open when done” is offered only for a download this session started.",
        "Hide closes the sheet, and the download carries on with its strip still showing.",
    ], "dlq")


def s_more():
    c = screen(W, H)
    c.compose(header("dlq", ["settings"], W), 0, 0)
    rows_ = [
        ("w", "window", "60 min", "start this long before 00:00Z", None),
        ("r", "reserve", "100 MB", "kept back, never spent", None),
        ("a", "auto", "◉ on", "the nightly job downloads", None),
        ("c", "skip codecs", "av01 vp9", "the quality chips pass these over", None),
        ("h", "quality chips", "240-720", "learned from what you pick", None),
        ("d", "destinations", "Download", "where finished files land", None),
        ("j", "nightly job", "armed", "every 15m in the window", T.success),
    ]
    y = 1
    for i, (k, n, v, m, f) in enumerate(rows_[:6]):
        c.compose(setting_row(k, n, v, m, W - 1, value_fg=f), 0, y)
        y += 2
    c.compose(scrollbar(12, 18, 12, 0), W - 1, 1)
    c.compose(text("reserve is 100 MB again (the default)", W, T.info), 0, 14)
    c.compose(dock([("Runner log", "l"), ("Quit", "q")], W), 0, 16)
    c.compose(tabbar(4), 0, 21)
    add("s-more", "More: settings and the rest", c, [
        "The fifth tab holds the settings, the destinations, the nightly job, the runner log and Quit. Quit is here because the tabs left no Back to quit from. `q` still quits from any tab.",
        "A switch toggles where it sits. A number opens a sheet with preset chips. What each change did is said under the rows, as said_lines() does now.",
        "paid-min appears under “reserve when paid” only while the waiver is on, because on its own it does nothing. The page scrolls.",
        "“skip codecs” is ytq's: av01, vp9 and h264 as on/off chips in a sheet. The quality chips on the video sheet read it, and so does the order of the full format table.",
    ], "dlq")


def s_narrow():
    w = 32
    c = screen(w, 20)
    c.compose(header("dlq", ["queue"], w), 0, 0)
    c.compose(tonight_card(w, verdict=("waiting", " · 19m"), fig="480/763 MiB"), 0, 1)
    c.compose(filters(0, w), 0, 6)
    queue_rows(c, 9, None, w, cut="tonight · 480 MiB")
    c.compose(tabbar(3, w), 0, 17)
    SCREENS.append({"key": "s-narrow", "title": "The floor: 32×20", "app": "dlq", "notes": [
        "At 32 columns the card's sentences shorten and the filter buttons drop their counts before anything else gives way. The tab bar keeps all five tabs at six columns each.",
        "At 20 rows the list keeps what is left, and the running-download strip folds into the Queue tab's ● until there is room for it.",
    ], "html": to_html(c.render()), "width": w, "keyboard_from": None})


def build():
    s_search()
    s_results()
    s_sheet_loading()
    s_sheet_ready()
    s_sheet_audio()
    s_sheet_now()
    s_sheet_dup()
    s_all_formats()
    s_feed()
    s_queue()
    s_item()
    s_place()
    s_download()
    s_run_now()
    s_more()
    s_narrow()
    return SCREENS


if __name__ == "__main__":
    out = build()
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False)
