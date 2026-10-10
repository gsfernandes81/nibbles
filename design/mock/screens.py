"""The proposed screens, drawn at phone size with bewitch and the kit."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from kit import *  # noqa: F401,F403
from kit import T, glyphs

W, H = 40, 24
SCREENS: list[dict] = []


def add(key, title, canvas, notes, app, width=W, keyboard_from=None):
    SCREENS.append({
        "key": key, "title": title, "app": app, "notes": notes,
        "html": to_html(canvas.render()), "width": width,
        "keyboard_from": keyboard_from,
    })


def two(title, sub, width, selected=False, mark="", mark_color=None, dimmed=False):
    return list_item(title, width, subtitle=sub, selected=selected, mark=mark,
                     mark_color=mark_color, dimmed=dimmed)


def sub_spans(*parts):
    return [Span(t, Pen(fg=c)) if c else Span(t) for t, c in parts]


VIDEOS = [
    ("Crust of Rust: Subtyping and Variance", "Jon Gjengset · ~3d · 90m34s · 41K", ""),
    ("Making a Case for Rust in the Kernel", "Some Channel · ~1w · 12m40s · 8.2K", "✓"),
    ("lofi hip hop radio - beats to relax/study to", "Lofi Girl · live · 1.1M", ""),
    ("Rust Lifetimes Finally Explained", "Let's Get Rusty · ~2y · 26m01s · 1.4M", ""),
    ("The Async Book, read aloud (part 3)", "Rust Audio · ~5mo · 2h04m · 912", ""),
    ("Why my Termux setup is ridiculous", "phonehacker · ~4d · 8m12s · 22K", "✓"),
    ("Building a TUI with blessed", "Python Corner · ~1mo · 31m09s · 5.5K", ""),
    ("Shipping software on a metered link", "Ops Talks · ~1y · 44m00s · 3.1K", ""),
    ("Charm's Lip Gloss, explained", "Terminal Joy · ~8mo · 15m30s · 60K", ""),
]


def results_list(c, top, rows, sel, width=W, items=VIDEOS, marks=None, start=0,
                 sb=True, total=None):
    """Two-line rows from *top*, *rows* tall; scrollbar in the last column."""
    marks = marks or {}
    y = top
    i = start
    while y < top + rows and i < len(items):
        t, s, m = items[i]
        mk, mc = marks.get(i, (m, T.success if m else None))
        blk = two(t, s, width - 1, selected=(i == sel), mark=mk, mark_color=mc,
                  dimmed=(m == "✓" and i != sel))
        c.compose(blk, 0, y)
        y += 2
        i += 1
    if sb:
        c.compose(scrollbar(rows, total or 20, rows // 2, start), width - 1, top)
    return y


# ---------------------------------------------------------------------------- ytq

def ytq_entry():
    c = screen(W, H)
    c.compose(header("ytq", ["search"], W), 0, 0)
    c.compose(field("crust of rust", W), 0, 2)
    c.compose(text("search ~0.1 MB · subs or later ~0.2 MB", W, T.fg_most_subtle), 0, 5)
    c.compose(dock([("Search", "⏎", "primary"), ("Subs", ""), ("Watch later", "")], W), 0, 6)
    c.compose(section("Earlier", W, "free to reopen"), 0, 10)
    c.compose(two("lofi hip hop", "20 results · 12m ago", W - 1), 0, 11)
    c.compose(two("subscriptions", "60 videos · 3m ago", W - 1), 0, 13)
    for y in range(13, H):
        c.compose(text("", W, bg=T.bg_least_visible), 0, y)
    add("ytq-entry", "Search, keyboard up", c, [
        "Everything you need while typing sits in the top ten rows, above the phone keyboard.",
        "Subs and Watch later are buttons now. Typing `subs` or `wl` still works.",
        "The price of each button is printed above the buttons, before anything is tapped.",
        "Earlier searches and feeds from this session are one tap away, and cost nothing to reopen.",
    ], "ytq", keyboard_from=13)


def ytq_results():
    c = screen(W, H)
    c.compose(header("ytq", ["crust of rust", "20"], W), 0, 0)
    c.compose(text("20 results · ~ dates approx", W, T.fg_more_subtle), 0, 1)
    results_list(c, 2, 16, 0)
    c.compose(text("", W), 0, 18)
    c.compose(spans([("  1080p last time · formats ~0.3 MB", T.fg_most_subtle)], W), 0, 19)
    c.compose(dock([("New", "/"), ("Formats", "⏎", "primary"), ("Back", "q")], W), 0, 20)
    add("ytq-results", "Results", c, [
        "Tap a row to open its formats: one tap selects the row and starts its format fetch in the background, the same as `⏎` or the Formats button.",
        "Swipe to scroll the list. The selection stays on its row unless it scrolls off screen.",
        "The scrollbar is draggable. Its hit zone is the last three columns.",
        "The row above the dock says what Formats will cost before you tap it.",
        "Each dock button shows its key in grey (`/` `⏎` `q`), so the dock doubles as the hint line.",
    ], "ytq")


def ytq_feed_end():
    feed = [
        ("Saved For Tonight", "Jon Gjengset · ~1d · 10m00s", ""),
        ("Writing a terminal emulator", "Some Channel · ~3w · 1h02m", ""),
        ("Phones are computers too", "Tech Thoughts · ~1mo · 22m15s", "✓"),
        ("What Doze does to your jobs", "Android Dev · ~2mo · 18m40s", ""),
        ("Making yt-dlp behave", "Scripting Fun · ~2mo · 9m05s", ""),
        ("A night on the vessel's link", "Ops Talks · ~3mo · 40m00s", ""),
    ]
    c = screen(W, H)
    c.compose(header("ytq", ["subscriptions", "30"], W), 0, 0)
    c.compose(text("30 videos · read 3m ago", W, T.fg_more_subtle), 0, 1)
    results_list(c, 2, 12, 5, items=feed, start=0, total=30)
    c.compose(wide("30 more", "↓", W, "spend", "· 0.4 MB total"), 0, 14)
    c.compose(text("     or keep swiping past the end", W, T.fg_most_subtle), 0, 17)
    c.compose(dock([("Reload", "r"), ("Formats", "⏎", "primary"), ("Back", "q")], W), 0, 20)
    add("ytq-feed-end", "Feed: the end of the list", c, [
        "The list ends with a full-width button for the deeper look. Its price, the total and never the increment, is on the button.",
        "Tap it, press `↓` on the last row, or keep swiping past the end. All three start the same background fetch.",
        "At the bottom of the feed, or at the 150 cap, the button becomes grey text saying which of the two it is.",
        "Reload (`r`) re-reads the list at its current depth, priced the same way.",
    ], "ytq")


def ytq_feed_loading():
    feed = [
        ("Making yt-dlp behave", "Scripting Fun · ~2mo · 9m05s", ""),
        ("A night on the vessel's link", "Ops Talks · ~3mo · 40m00s", ""),
        ("Saved For Tonight", "Jon Gjengset · ~1d · 10m00s", ""),
        ("Crust of Rust: Subtyping and Variance", "Jon Gjengset · ~3d · 90m34s", ""),
        ("Making a Case for Rust in the Kernel", "Some Channel · ~1w · 12m40s", "✓"),
        ("Building a TUI with blessed", "Python Corner · ~1mo · 31m09s", ""),
    ]
    c = screen(W, H)
    c.compose(header("ytq", ["subscriptions", "30"], W), 0, 0)
    c.compose(text("30 videos · read 3m ago", W, T.fg_more_subtle), 0, 1)
    results_list(c, 2, 12, 3, items=feed, start=0, total=30,
                 marks={3: ("⣽", T.secondary)})
    load = box(spans([("⣾ ", T.secondary), ("reading 60 · 0.4 MB", T.fg_base)], W - 4), W,
               border=T.fg_most_subtle)
    c.compose(load, 0, 14)
    c.compose(spans([("  ", None), ("⣽", T.secondary), (" formats for Crust of Rust: Subt…", T.fg_more_subtle)], W), 0, 19)
    c.compose(dock([("Stop", "x", "danger"), ("Formats", "⏎", "primary"), ("Back", "q")], W), 0, 20)
    add("ytq-async", "Background fetches", c, [
        "Every fetch runs in the background: the search, the format probe and the feed's deeper look.",
        "Here the deeper look is loading at the foot of the list, and a format probe is running on the selected row (spinner in its mark column). Both are live while you keep scrolling.",
        "If the cursor is still on that row when the probe returns, its formats open. If you have moved on, the row gets a ◆ mark and opens instantly when tapped.",
        "Stop (`x`) cancels the newest fetch. The spinners are the only things that animate, and only while something is running.",
    ], "ytq")


def ytq_formats():
    c = screen(W, H)
    c.compose(header("ytq", ["Crust of Rust: Subtyping…"], W), 0, 0)
    c.compose(text("9 formats · 3 hidden, no size · ~ est", W, T.fg_more_subtle), 0, 1)
    fm = [
        ("4.48 GiB", T.error, "2160p mp4", "(8 nights)", "av01.0.12M.08 + mp4a.40.2"),
        ("486 MiB", T.success, "1080p60 mp4", "", "avc1.640028 + mp4a.40.2 · merged"),
        ("393 MiB~", T.success, "1080p webm", "", "vp9 + opus · merged"),
        ("220 MiB", T.success, "720p mp4", "", "avc1 + mp4a · merged"),
        ("38 MiB", T.success, "360p mp4", "", "one file · avc1+mp4a"),
        ("10 MiB", T.success, "audio 129k m4a", "", "mp4a · no video"),
    ]
    y = 2
    for i, (size, col, label, nights, codecs) in enumerate(fm):
        sel = i == 1
        title = [Span(f"{size:>9}  ", Pen(fg=col if not sel else None, bold=True)),
                 Span(label)] + ([Span(" " + nights, Pen(fg=T.warning if not sel else None))] if nights else [])
        c.compose(list_item(title, W - 1, subtitle="            " + codecs, selected=sel,
                            mark="●" if i == 1 else "", mark_color=T.success_most_subtle), 0, y)
        y += 2
    c.compose(scrollbar(12, 9, 6, 0), W - 1, 2)
    c.compose(text("  cap 501 MiB · fits tonight", W, T.fg_most_subtle), 0, 15)
    c.compose(dock([("Copy URL", "c"), ("Back", "q")], W), 0, 17)
    c.compose(dock([("Now", "n", "spend", "PAID"), ("Queue tonight", "⏎", "primary")], W), 0, 20)
    add("ytq-formats", "Formats", c, [
        "Each format is a two-line row, so it is tall enough to tap. The second line carries the exact codecs on every row, so the separate detail line goes away.",
        "The size keeps its nights colour and its words: “(8 nights)” still says it without colour.",
        "The two actions that write an item get a row of their own, in the thumb zone. Now is styled as a spend and carries the word PAID.",
        "● marks the format chosen last time, where the cursor opens.",
    ], "ytq")


def ytq_confirm(now=False):
    c = screen(W, H)
    c.compose(header("ytq", ["download now" if now else "queue tonight"], W), 0, 0)
    c.compose(text("Crust of Rust: Subtyping and Variance", W, T.fg_base, True), 0, 2)
    c.compose(spans([("1080p60 mp4 · ", T.fg_more_subtle), ("486 MiB", T.success),
                     (" · cap 501 MiB", T.fg_more_subtle)], W), 0, 3)

    def frow(y, key, name, value, chevron=True):
        r = spans([(f" {key} ", T.fg_more_subtle), (f"{name:<9}", T.fg_more_subtle),
                   (value, T.fg_base)], W - 2)
        c.compose(r, 0, y)
        if chevron:
            c.compose(text(glyphs.ARROW_RIGHT, 2, T.fg_most_subtle), W - 2, y)
        c.compose(text("", W, bg=None), 0, y + 1)

    c.compose(section("Details", W), 0, 5)
    frow(6, "e", "name", "crust-of-rust-subtyping")
    frow(8, "p", "place", "last · 5th of 5" if not now else "runs now, not queued", not now)
    frow(10, " ", "goes to", "~/storage/downloads", False)
    c.compose(section("When", W), 0, 12)
    c.compose(segmented([("Tonight", "free"), ("Now", "PAID")], 1 if now else 0, W), 0, 13)
    if now:
        c.compose(spans([("  this spends 501 MiB of ", T.fg_base), ("PAID", T.error, True),
                         (" data", T.fg_base)], W), 0, 17)
        c.compose(dock([("Back", "q"), ("Start", "⏎", "spend", "· 501 MiB PAID")], W), 0, 20)
    else:
        c.compose(text("  downloads in tonight's window, 23:00Z", W, T.fg_most_subtle), 0, 17)
        c.compose(dock([("Back", "q"), ("Queue it", "⏎", "primary")], W), 0, 20)
    add("ytq-confirm-now" if now else "ytq-confirm", "Confirm: now, PAID" if now else "Confirm: tonight",
        c, ([
            "Tonight and Now are one segmented control (`t` / `n`). Changing it changes the header, the sentence and the big button together.",
            "The big button names the money on its face: “Start · 501 MiB PAID”. The PAID line above it says the same in words.",
            "The double-tap guard applies: taps are ignored for 100 ms after the screen changes, and for 300 ms a tap on the same spot as the opening tap is dropped. The tap that opened this screen cannot also press Start.",
        ] if now else [
            "Name and place are tappable rows, each with its key. Name opens a field near the top, out from under the keyboard. Place opens dlq's listing with the video held in it.",
            "A typed number and a picked place stay one field: the place row shows whichever is in force.",
            "Queue it writes through ytq.write_item, the same door as before.",
        ]), "ytq")


def ytq_duplicate():
    c = screen(W, H)
    c.compose(header("ytq", ["Galaxy Z Flip8 review"], W), 0, 0)
    for i, (sz, lb, cd) in enumerate([("4.10 GiB", "2160p mp4 (7 nights)", "av01 + mp4a"), ("812 MiB", "1440p mp4", "avc1 + mp4a"),
            ("402 MiB", "1080p mp4", "avc1 + mp4a"), ("220 MiB", "720p mp4", "avc1 + mp4a"), ("38 MiB", "360p mp4", "one file"),
            ("10 MiB", "audio 129k m4a", "mp4a"), ("6 MiB", "audio 50k webm", "opus"), ("3 MiB", "audio 48k m4a", "mp4a")]):
        c.compose(list_item(f"{sz:>9}  {lb}", W - 1, subtitle="            " + cd, selected=(i == 2)), 0, 2 + 2 * i)
    body = join_vertical(LEFT,
                         text("downloaded 2026-08-11", W - 4, T.fg_base),
                         text("as 10-samsung-galaxy-z-flip8-review", W - 4, T.fg_more_subtle),
                         text("matched on its video id", W - 4, T.fg_most_subtle),
                         Block.text(""),
                         dock([("Back", "q", "primary"), ("Queue again", "a")], W - 4))
    c.compose(box(body, W, "already downloaded"), 0, 2)
    add("ytq-duplicate", "Already have it", c, [
        "Dialogs open near the top and draw over the screen with a Canvas, never on a cleared page. Their answers are buttons inside the box.",
        "The safe answer comes first. “Queue again” keeps its key, `a`.",
    ], "ytq")


def ytq_running():
    c = screen(W, H)
    c.compose(header("ytq", ["crust of rust", "20"], W), 0, 0)
    c.compose(text("20 results · ~ dates approx", W, T.fg_more_subtle), 0, 1)
    results_list(c, 2, 14, 3, marks={0: ("✓", T.success)})
    c.compose(spans([("  ↓ crust-of-rust-subtyping", T.fg_base)], W), 0, 17)
    c.compose(join_horizontal(TOP, text("  ", 2), progress_bar(0.41, W - 4)), 0, 18)
    c.compose(text("  204/501 MiB · 4m left · PAID", W, T.fg_more_subtle), 0, 19)
    c.compose(dock([("Stop", "x", "danger"), ("Formats", "⏎", "primary"), ("Back", "q")], W), 0, 20)
    add("ytq-running", "A download running", c, [
        "A download started with Now runs detached, just as today. The results stay usable and the download reports itself above the dock.",
        "Stop (`x`) takes the dock's first slot while it runs, the same way `x` took over the hint line before.",
        "On a pasted URL, the download screen gets an “Open when done” toggle button (`o`).",
    ], "ytq")


def ytq_narrow():
    w, h = 32, 20
    c = screen(w, h)
    c.compose(header("ytq", ["crust of rust", "20"], w), 0, 0)
    results_list(c, 1, 14, 1, width=w)
    c.compose(text("", w), 0, 15)
    c.compose(dock([("New", "/"), ("Open", "⏎", "primary"), ("Back", "q")], w), 0, 17)
    SCREENS.append({"key": "ytq-narrow", "title": "Results at the floor, 32×20", "app": "ytq",
                    "notes": [
                        "At 32 columns the labels shorten from a second, tighter set: Formats becomes Open. That replaces the two hint sets.",
                        "If even the short labels will not fit, the extra buttons fold into a ⋯ More sheet. Back is never folded.",
                        "The status line under the header goes before any list row does.",
                    ], "html": to_html(c.render()), "width": w, "keyboard_from": None})


# ---------------------------------------------------------------------------- dlq

QUEUE = [
    ("ubuntu-24-04-desktop", [("18%", T.attention), ("  1.02 GiB/5.61 GiB", T.fg_more_subtle)], "●", T.attention),
    ("some-talk", [("-  0 B/≤505 MiB", T.fg_more_subtle), (" · 46 MiB tonight", T.info)], "", None),
]
AFTER = [("big-iso", [("-  0 B/≤8 GiB", T.fg_more_subtle)], "", None)]


def dlq_head(c, detail, width=W):
    c.compose(header("dlq", detail, width), 0, 0)
    c.compose(spans([("tonight: ", T.fg_more_subtle), ("waiting", T.fg_base),
                     (", opens 23:00Z (19m)", T.fg_more_subtle)], width), 0, 1)
    c.compose(text("480 MiB to spend · 763 MiB expires", width, T.fg_most_subtle), 0, 2)


def dlq_rows(c, y, sel, width=W, held=None, order=None):
    items = order or (QUEUE + AFTER)
    c.compose(section("Queued", width, str(len(items))), 0, y)
    y += 1
    for i, (name, sub, mark, mc) in enumerate(items):
        if i == 2:
            c.compose(spans([("  ── tonight ends here: 480 MiB ", T.warning), ("─" * 8, T.warning)], width), 0, y)
            y += 1
        if held == i:
            c.compose(list_item([Span(name)], width - 1, subtitle=sub_spans(*sub), selected=True,
                                mark="◆", mark_color=T.on_primary), 0, y)
        else:
            c.compose(list_item(name, width - 1,
                                subtitle="".join(t for t, _ in sub) if i == sel else sub_spans(*sub),
                                selected=(i == sel),
                                mark=mark, mark_color=mc), 0, y)
        y += 2
    return y


def dlq_list():
    c = screen(W, H)
    dlq_head(c, ["22:41Z"])
    y = dlq_rows(c, 4, 1)
    c.compose(section("Failed", W, "1"), 0, y)
    c.compose(list_item("old-podcast-ep12", W - 1, subtitle=sub_spans(("× 3 nights failed", T.error)),
                        mark="×", mark_color=T.error), 0, y + 1)
    c.compose(section("Done", W, "3 · newest first"), 0, y + 3)
    c.compose(list_item("other-talk", W - 1, subtitle=sub_spans(("complete  201 MiB", T.fg_most_subtle)),
                        mark="✓", mark_color=T.success, dimmed=True), 0, y + 4)
    c.compose(dock([("Run now", "n", "spend"), ("Settings", "s"), ("Quit", "q")], W), 0, 21)
    add("dlq-list", "The queue", c, [
        "The listing stays the whole queue. Tap a row to open it, the same as `⏎`.",
        "The cut line is still computed, never an item: taps and the cursor pass over it.",
        "The dock replaces the legend row and the hint line. Run now is styled as a spend and still goes through its single yes. The runner log moves to a row on Settings, and `l` still opens it from here.",
        "Swiping scrolls. Groups, marks and the tonight share are unchanged from today.",
    ], "dlq")


def dlq_item():
    c = screen(W, H)
    c.compose(header("dlq", ["some-talk"], W), 0, 0)
    c.compose(spans([("queued", T.fg_base), (" · 2nd of 3 · try 1/3", T.fg_more_subtle)], W), 0, 2)
    c.compose(spans([("0 B of ", T.fg_more_subtle), ("≤505 MiB", T.fg_base),
                     (" · 46 MiB tonight", T.info)], W), 0, 3)
    c.compose(text("Some talk [1080p mp4]", W, T.fg_most_subtle), 0, 4)
    c.compose(text("→ ~/storage/downloads", W, T.fg_most_subtle), 0, 5)
    g = [
        [("Download now", "n", "spend"), ("Move", "m")],
        [("Rename", "r"), ("Its log", "l")],
        [("Clear tries", "t"), ("Remove", "d", "danger")],
    ]
    y = 12
    for row in g:
        c.compose(dock(row, W), 0, y)
        y += 3
    c.compose(dock([("Back", "q")], W), 0, 21)
    add("dlq-item", "One download", c, [
        "Each action actions_for() offers becomes a button in a two-column grid. The list is filtered by the item's state exactly as today: no Move on a done item, Put back on a failed one.",
        "Every button calls the same function as its key. Download now and Remove still go through their confirms.",
        "The facts sit at the top. While it downloads, the progress bar takes row 6, from the same single reading per draw.",
    ], "dlq")


def dlq_move():
    c = screen(W, H)
    c.compose(header("dlq", ["moving big-iso"], W), 0, 0)
    c.compose(spans([("tonight: ", T.fg_more_subtle), ("waiting", T.fg_base),
                     (", opens 23:00Z (19m)", T.fg_more_subtle)], W), 0, 1)
    c.compose(text("480 MiB to spend · 763 MiB expires", W, T.fg_most_subtle), 0, 2)
    order = [QUEUE[0], AFTER[0], QUEUE[1]]
    order = [order[0], (order[1][0], [("-  0 B/≤8 GiB", T.fg_more_subtle), (" · 434 MiB tonight", T.info)], "", None), order[2]]
    dlq_rows(c, 4, None, held=1, order=order)
    c.compose(text("  tap a row to put it there", W, T.fg_most_subtle), 0, 17)
    c.compose(dock([("↑", ""), ("↓", ""), ("Drop here", "⏎", "primary"), ("Cancel", "esc")], W), 0, 21)
    add("dlq-move", "Moving one (and ytq's place picker)", c, [
        "The held item is the filled bar with a ◆. Up and down nudge it one place, tapping another row puts it there, and swiping drags it.",
        "The cut line and the tonight share are re-planned at every step, through preview(), tonight_plan() and cut_index(), as today.",
        "ytq's place picker is this same screen holding a phantom row. Its buttons read “Take this place” and “Leave it last”.",
    ], "dlq")


def dlq_now_dialog():
    c = screen(W, H)
    dlq_head(c, ["some-talk"])
    body = join_vertical(LEFT,
                         Style().foreground(T.fg_base).width(W - 4).render(
                             "zwana does not answer, so nothing is counting this.\n"
                             "505 MiB on whatever the phone is using: on mobile data that is metered and charged to you."),
                         Style().foreground(T.fg_most_subtle).width(W - 4).render("it runs in the background; x stops it"),
                         Block.text(""),
                         wide("Download · 505 MiB", "y", W - 4, "spend"),
                         wide("No", "esc", W - 4))
    c.compose(box(body, W, "download now · NOT COUNTED", border=T.warning), 0, 2)
    add("dlq-now", "Download now: the one yes", c, [
        "Anything that spends PAID or uncounted data still goes through exactly one yes. The yes is a full-width button with the figure on its face.",
        "The answers are stacked full width, so neither one is a small target beside the other, and No is the bottom one.",
        "The double-tap guard applies: the second half of a double tap cannot land on the yes.",
    ], "dlq")


def dlq_remove():
    c = screen(W, H)
    dlq_head(c, ["some-talk"])
    body = join_vertical(LEFT,
                         text("remove some-talk from the list?", W - 4, T.fg_base),
                         text("the 46 MiB already downloaded stays", W - 4, T.fg_more_subtle),
                         Block.text(""),
                         wide("Remove, keep the 46 MiB", "y", W - 4, "primary"),
                         wide("Remove and delete 46 MiB", "b", W - 4, "danger"),
                         wide("No", "esc", W - 4))
    c.compose(box(body, W, "remove"), 0, 2)
    add("dlq-remove", "Remove keeps what was paid for", c, [
        "Both answers from removal_answers() are always shown, and their keys never change. On an item with nothing downloaded, both buttons say “Remove it”.",
        "The destructive answer is the red one and never the default. No sits last, at the bottom.",
    ], "dlq")


def dlq_settings():
    c = screen(W, H)
    c.compose(header("dlq", ["settings"], W), 0, 0)
    rows = [
        ("w", "window", "60 min", "start this long before 00:00Z"),
        ("r", "reserve", "100 MB", "kept back, never spent"),
        ("p", "reserve when paid", "yes", "keep it even with paid data"),
        ("m", "paid min", "0 MB", "how much paid data waives it"),
        ("a", "auto", "◉ on", "the nightly job downloads"),
        ("n", "notify blocked", "◉ on", "say so when a firing is blocked"),
        ("d", "destinations", "Download", "where finished files land"),
        ("j", "nightly job", "armed", "every 15m in the window"),
    ]
    y = 2
    for i, (k, n, v, m) in enumerate(rows):
        c.compose(setting_row(k, n, v, m, W, selected=(i == 1),
                              value_fg=T.success if v == "armed" else None), 0, y)
        y += 2
    c.compose(text("reserve is 100 MB again (the default)", W, T.info), 0, 18)
    c.compose(dock([("Runner log", "l"), ("Back", "q")], W), 0, 21)
    add("dlq-settings", "Settings", c, [
        "Every setting is a two-line row with its key. Tapping a switch toggles it in place. Tapping a number opens its field.",
        "The said area (said_lines) stays under the rows, and settings_body still gives up blank lines first, then the meanings, then the said area, never a row.",
        "The runner log now lives here, as a button beside Back.",
    ], "dlq")


def dlq_setting_field():
    c = screen(W, H)
    c.compose(header("dlq", ["settings"], W), 0, 0)
    body = join_vertical(LEFT,
                         field("45", W - 4),
                         text("a multiple of 15, 15 min to 24 h", W - 4, T.fg_most_subtle),
                         dock([("30m", ""), ("45m", "", "primary"), ("1h", ""), ("2h", "")], W - 4),
                         dock([("Cancel", "esc"), ("Set", "⏎", "primary")], W - 4))
    c.compose(box(body, W, "window"), 0, 1)
    for y in range(15, H):
        c.compose(text("", W, bg=T.bg_least_visible), 0, y)
    SCREENS.append({"key": "dlq-field", "title": "Setting a number, keyboard up", "app": "dlq",
                    "notes": [
                        "The field dialog sits at the top, as the ask dialog already does on the bewitched branch.",
                        "Preset chips mean most changes need no typing. The field is prefilled, and typing “default” still works.",
                        "A refused value is said inside the dialog in red. The dialog stays open, and nothing is written.",
                    ], "html": to_html(c.render()), "width": W, "keyboard_from": 15})


def components():
    w = W
    c = screen(w, 19)
    c.compose(dock([("Plain", "k"), ("Primary", "⏎", "primary")], w), 0, 0)
    c.compose(dock([("Spends", "n", "spend", "92 MiB"), ("Danger", "d", "danger")], w), 0, 3)
    c.compose(dock([("Pressed", "⏎", "pressed"), ("Disabled", "", "off")], w), 0, 6)
    c.compose(segmented([("At 03:00", ""), ("Now", "")], 0, w), 0, 9)
    c.compose(field("crust of rust", w), 0, 12)
    c.compose(list_item("A selected two-line row", w - 1, subtitle="its second line", selected=True), 0, 15)
    c.compose(scrollbar(4, 20, 5, 6), w - 1, 15)
    c.compose(list_item("And one that is not", w - 1, subtitle="tap target is both lines"), 0, 17)
    SCREENS.append({"key": "kit", "title": "The pieces", "app": "kit", "notes": [
        "A button is three rows: a rounded border with the key in grey and the word in body text. On the phone that is about 11 mm tall, above Android's 48 dp minimum for a touch target.",
        "Kinds by role: plain, primary (the screen's main action), spend (warning border: this costs data), danger (destructive) and off (shown but disabled).",
        "Pressed fills with primary for one frame (~120 ms) on touch-down, so you can see what was hit. It is a single timed redraw, and then the screen is silent again.",
        "Drawing is pure: button(), dock(), segmented() and field() return Blocks. A separate HitMap records each target's id and rectangle. That keeps the drawing side movable into bewitch later.",
    ], "html": to_html(c.render()), "plain": c.render().plain(), "width": w, "keyboard_from": None})


def build():
    components()
    ytq_entry()
    ytq_results()
    ytq_async = ytq_feed_loading
    ytq_feed_end()
    ytq_async()
    ytq_formats()
    ytq_confirm()
    ytq_confirm(now=True)
    ytq_duplicate()
    ytq_running()
    ytq_narrow()
    dlq_list()
    dlq_item()
    dlq_move()
    dlq_now_dialog()
    dlq_remove()
    dlq_settings()
    dlq_setting_field()
    return SCREENS


if __name__ == "__main__":
    out = build()
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False)
    for s in out:
        print("==", s["key"])
