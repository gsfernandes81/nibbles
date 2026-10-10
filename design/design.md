# nibbles: the design

The owner's decisions for the one-app, buttons-first rebuild of ytq and dlq on
blessed, made on 2026-10-10 over a review of the mockups in `mockups/`. **This
file and the mockups are the spec.**

- **Follow them very closely.** Layout, wording, glyphs, colours by role, button
  sizes, what gives way first and the order things sit in are decisions, not
  suggestions. When this file and a mockup disagree, ask; until then this file
  wins on behaviour and the mockup wins on looks.
- **Diverging needs the owner's approval.** Ask before building something
  other than what is drawn, whether because it cannot be built as drawn or
  because a better shape turned up. If the owner does not answer and the work
  would stall, diverge, and record it in `divergences.md` (what the spec said,
  what was built, why) so they can approve it or send it back. A divergence
  that is not in that file is a bug.
- **Everything here was checked against what a terminal can do** (the last
  section says how, and lists what still has to be confirmed on the phone).

`mockups/index.html` is the review page: every screen keyboard down and up,
side by side, with its notes. `mockups/<screen>.<cols>x<rows>.txt` are the same
screens as text, and the `.ans` files are them in colour: `cat` one in Termux
to see the screen on the phone itself. `mock/render.py` regenerates all of them
from `mock/screens3.py` (the authoritative screens) and `mock/kit.py` (the
proposed recipes), drawn with bewitch at the real terminal size.

## Contents

1. Interaction model
2. The shell: tabs, sheets, the status bar
3. Heights: keyboard down and keyboard up
4. The pieces: buttons, choices, checkbox
5. Screens
6. Words, times and names
7. What goes away
8. How it is built
9. Settled, and still open
10. Can a terminal do this? The audit

## 1. Interaction model

- **A tap is a tap; a drag is a scroll.** Termux decides this before the app
  hears anything (`TerminalView`, checked in its source): a tap reaches the app
  as press and release together *when the finger lifts*, and only if it did not
  move; a drag never sends a press, it sends wheel events, one per row moved,
  then more of them for a fling's momentum; a long press is Termux's own text
  selection and never reaches the app. So a drag can never press a button.
- **A button acts as soon as Termux reports the tap**, and fills with
  `primary` for one frame (~120 ms) so you see what you hit: one timed redraw,
  then the screen is silent again.
- **Double-tap guard.** For 100 ms after a screen or sheet appears every tap is
  ignored; for the rest of Android's 300 ms double-tap window only a tap on the
  same cell as the one that opened it is dropped. A deliberate tap anywhere
  else acts at once.
- **One tap opens a row.** It selects the row and opens its sheet in the same
  tap. In ytq that also starts the row's format fetch (~0.3 MB). The selection
  bar stays, so keys still know which row they act on.
- **The price is on the button** (or the line directly above it). A spend that
  nothing is counting (mobile data, portal out of reach) still goes through
  exactly one yes.
- **A swipe moves the view.** The selection stays on its row until it comes
  within one item of the edge, then rides along one item in (Helix's
  scrolloff). ↑ and ↓ keep the same margin. With fewer than three items on
  screen the margin is nothing.
- **Scrollbars are draggable.** The last three columns of a list are the bar's
  zone. A tap there jumps to that point. Every wheel event of a drag carries
  the cell where the drag *began*, so a drag that starts on the bar moves the
  thumb a row per row of finger travel (a page at a time through the list); a
  drag that starts anywhere else scrolls the list a row at a time.
- **Swiping can spend, deliberately.** On Feed and Later the foot of the list
  is a full-width button, `↓ 30 more · 0.6 MB in all` (the total, never the
  increment). It is read by a tap on it, ↓ on the last row, or a **fresh** drag
  down after the list has rested at the end for about half a second. **A
  fling's momentum never fetches** (flicks are not reliable on Termux): it
  arrives as an unbroken stream of wheel events, so it can never produce that
  pause and then more.
- **Fetches run in the background**: the search, the format probe, the feed's
  deeper look. The screen stays live, a spinner shows what is running, Stop
  (`x`) cancels the newest.
- **Keys still work.** Every button shows its key in grey before its word, so
  the buttons are the hint line. The text field still types; `/`, `⏎`, `esc`,
  `q` and every old letter key keep working.
- **An idle screen writes nothing.** Everything is drawn through
  `bewitch.screen.Frame`; with nothing running the loop blocks on `inkey()`.
  Only spinners, the selected title's marquee and a running download animate,
  and only while they are.

## 2. The shell: tabs, sheets, the status bar

**One app, five tabs** along the bottom: **Search · Feed · Later · Queue ·
More**. `ytq` opens on Search, `ytq subs` on Feed, `ytq wl` on Later and `dlq`
on Queue. There are no Back buttons between tabs: the only depth is a sheet,
and a sheet closes. `q` quits from anywhere; Quit is also a row in More.

The foot of every tab screen is four rows:

1. a `─` rule in `separator`;
2. the tab labels, each tab a fifth of the width; the chosen one is a **pill**
   in `primary` with `on_primary` bold text and a column of purple either side
   of its word, centred in its fifth;
3. a blank row (rows 1–3 are the tap target for each tab);
4. **the status bar**, Lip Gloss's own status-bar style in the house roles: a
   coloured label at the left (`WAITING` in `primary` when idle, `↓ 18%` in
   `attention` while something downloads); the detail on a `bg_less_visible`
   panel (`opens 03:00`, or the download's name), cut with `…` before either
   end gives way and always keeping one clear column at its right end; a
   quieter right segment on `bg_most_visible` (the countdown `19m`, or the
   time left `1h`). The label is always a word, never only a colour.

**Sheets, not pages.** A video, a download, a confirm and a setting each open
as a sheet from the bottom: a rounded border in `primary` (in `warning` when
nothing is counting the spend), open at the bottom edge, its title as
`dialog_title` with `esc ×` at the right. The screen it came from stays visible
above it, dimmed to `bg_most_visible`. Esc, or a tap on the dimmed part, closes
it. When a sheet does not fit, it takes the full height below the header, its
main button(s) stay **pinned** at the bottom, and the rest scrolls with a
scrollbar.

## 3. Heights: keyboard down and keyboard up

Termux makes the terminal shorter when the phone keyboard opens, so every
screen is laid out by the rows it gets (SIGWINCH), and every mockup is drawn
both ways: 40×24 and 40×14, and the floor at 32×20 and 32×11. **Those heights
are estimates**; `tput lines` on the phone, both ways, settles them and the
exact cut-off.

Below 16 rows:

- the window card on Queue becomes a one-line strip beside Run now;
- hint lines (`tap a row to put it there`) and blank lines go;
- a sheet takes the full height with its button pinned; the video sheet drops
  the blank under its byline, and the duplicate sheet its `Quality` rule, so
  the quality buttons and the main button still fit without scrolling;
- **tabs, buttons and the status bar never shrink.**

At 32 columns: the window card's sentences shorten; Queued/Failed/Done drop
their counts before anything else gives way; the tab bar keeps all five tabs.
Below 13 rows at 32 columns the window card folds into the header's details.

## 4. The pieces

All drawn with bewitch; the proposed recipes are in `mock/kit.py`.

- **Buttons are three rows tall** (about 11 mm on the phone) at every height;
  lists give up rows first. A rounded border, the key in `fg_more_subtle`
  before the word in `fg_base`, centred. Kinds by role: plain (border
  `fg_most_subtle`), primary (border `primary`, bold word), spend (border
  `warning`), danger (border `destructive`), off (border `bg_most_visible`,
  grey word, does nothing), pressed (filled `primary` for a frame).
- **A row of buttons fills its width exactly**, spare columns shared out, and
  is never wider than it was given: when labels do not fit, the widest button
  gives a column and its label ends in `…`. Buttons are roomy at every width; a
  wider screen adds buttons rather than narrowing them.
- **One-of choices are equal-width boxes side by side**, labels centred: the
  chosen one outlined in `primary` with `◉` and a bold word, the rest grey with
  `○`. Equal widths keep a short option (Now) as big a target, and as heavy on
  the screen, as a long one (At 03:00). Used for At/Now and Smallest/Largest.
- **A checkbox is drawn the way Charm's huh draws one**: a full-width
  three-row box; off is a grey `•` and grey label; ticked is a green `✓`
  (`success`), a bold label and a `success` outline. Used for "Open it when
  done". bewitch draws it: `bubbles.huh.checkbox`, boxed (gsfernandes81/bewitch#1).
- **List rows are two lines** (title, then a grey line), a one-column mark
  before the title (`✓` have it, `×` failed, `↓` downloading, `◆` held, a
  spinner while fetching), the selection a filled `primary` bar.
- **Text fields** are a rounded box, `primary` when focused, with a block
  cursor in `secondary`; anything you type into sits at the top, above the
  keyboard.

## 5. Screens

Each has a mockup, keyboard down and up: `mockups/<key>.*`.

**Search tab** (`k-search`). The search bar (field plus a `⏎ Go` button) at the
top, `a search is ~0.1 MB` under it, then **Recent**: earlier searches and
feeds from this session, which reopen for free. Typing `subs` or `wl` jumps to
those tabs; a pasted URL opens its video sheet.

**Search results** (`k-results`). Under the search bar, which a tap edits:
`20 results · ~ dates approx`, then the rows (`✓` on anything the queue already
holds), scrollbar at the right.

**The video sheet** replaces the formats, confirm and duplicate screens; every
choice on it is a tap.

- *Loading* (`k-sheet-loading`): opens on the tap with the title and byline the
  row already had; `⣾ asking YouTube for formats` and `~0.3 MB`; the main
  button drawn but off. Closing it does not cancel the fetch: the answer is
  kept for the session.
- *Ready* (`k-sheet`): **Quality** rule with the tier and the count, then the
  **tier buttons**: the heights *you* use, learned from what you pick (and
  settable in More), in height order, plus `audio`; at 40 columns that is your
  three most-used heights plus audio, and other heights live under Formats.
  Then **Smallest | Largest** beside a **Formats** button: Smallest or Largest
  picks within the tier, and is remembered with your last format, separately
  for video and audio, so the sheet opens on your usual (smallest at 480p
  takes no taps). Then the one figure: the size in `success` (nights colour
  rule as before) with container and codecs, and `skipped vp9` in grey only
  when the chips passed a codec over (no size, no "avoided"). Then **At 03:00 |
  Now**, then the main button repeating the figure: `⏎ Queue for 03:00 · 92
  MiB`.
- *Audio* (`k-sheet-audio`): the audio button turns the tier row into bitrates
  with `← video` first; Smallest/Largest picks within a bitrate.
- *Now* (`k-sheet-now`): the button becomes `⏎ Start now · 92 MiB` in the
  spend style, and one grey line says what differs: `today's allowance, no
  reserve kept`. Off the vessel's wifi (zwana does not answer) that line is
  `on mobile data, charged` and the button turns `destructive` red. That
  button is the one yes.
- *Already have it* (`k-sheet-dup`): `✓ already downloaded 2026-08-11` sits
  directly above `a Queue it again anyway`, pinned with it.
- There is **no name row** and **no place row**: a download is named after its
  title (section 6), and ordering is Move on the Queue tab.

**Formats** (`k-formats`): a sheet over the video sheet, opened at the tier you
were on, grouped by tier, smallest first, `~` marking an estimate; skipped
codecs dimmed and marked `skipped` but still tappable. A tap picks the row and
returns to the video sheet.

**Feed and Later** (`k-feed`): read on first opening the tab in a session
(~0.2 MB each), `60 videos` / `read 3m ago · 0.4 MB` beside an `r Re-read`
button, the rows, and the `↓ 30 more · 0.6 MB in all` button at the foot
(section 1). At the end of the feed or at the 150 cap it becomes a sentence
saying which. An empty feed still says the cookie is the likely cause and how
old the jar is; Later says both things an empty Watch Later can be.

**Queue tab** (`k-queue`). The **window card**: the verdict from `gate()`
(`waiting · 03:00 (19m)`), a gradient bar of what the next window may spend
against what expires, `480/763 MiB to spend`, and a `n Run now` spend button
beside it. Then **Queued 3 · Failed 1 · Done 3** as one-of buttons (one group
at a time; Done newest first). Then the rows: `↓ 18%` on the one downloading;
the cut line `── the window ends here · 480 MiB ──` in `warning`, computed,
never an item, skipped by taps and the cursor; `· 46 MiB at 03:00` in `info` on
the row it falls inside.

**A download's sheet** (`k-item`): its title, `queued · 2nd of 3 · try 1/3`,
`0 of ≤505 MiB · 46 MiB at 03:00`, `1080p mp4 → Download/`, then
`actions_for()`'s actions as a two-column grid of buttons (Download now in the
spend style, Remove in danger). Keyboard up: the facts fold into one line and
the whole grid still fits.

**Moving a download** (`k-place`): Move on its sheet holds it as a `◆` row in
the selection bar; `↑`, `↓`, `⏎ Put here` and `esc Cancel` along the bottom;
a tap on another row puts it there; a swipe drags it; the window card and the
cut line re-plan at every step.

**The running download** (`k-download`), opened from its row: `downloading ·
now · 1h left`, the bar, `1.02 of 5.61 GiB · 1.1 MiB/s`, the **Open it when
done** checkbox (only for a download this session started), then `x Pause` (not
the danger style: SIGINT, every byte kept, it resumes in the next window or with
Download now) and `esc Back`.

**Run now** (`k-run`), with zwana not answering: title `Run now`, border in
`warning`, the sentence *Zwana is not answering, so we do not know how much data
we can spend. Proceed anyway?*, the grey line `at most what the queue
declared`, then `y Run anyway · ≤1.2 GiB` and `esc Not now`, pinned. Every
confirm is a sheet like this: the yes full width with the figure on it, No
last.

**Remove** (round one's design, as a sheet): both answers from
`removal_answers()` as full-width buttons, the bytes-deleting one in danger,
never the default, No last; the keys never vary with the item.

**More tab** (`k-more`): the settings as two-line rows (key, name, value in
`primary`, a grey line saying what it means), one scrolling list: window,
reserve, auto, skip codecs (`av01 vp9`: the quality buttons pass these over),
quality chips (learned from what you pick), destinations, nightly job, runner
log, quit. A switch toggles where it sits; a number opens a sheet; what a
change did is said on the line above the tabs. `paid-min` shows under
"reserve when paid" only while the waiver is on.

**Setting a number** (`k-setting`): a sheet with the field prefilled, its rule
in grey, preset buttons (`30m 45m 1h 2h`) so most changes need no typing, then
`esc Cancel` and `⏎ Set`, pinned above the keyboard. A refused value is said
inside the sheet in red, and nothing is written.

## 6. Words, times and names

- **Your clock, not UTC.** The window is named by when it opens on the phone's
  clock: `at 03:00`, `tomorrow 03:00`, `today 14:00` (00:00 UTC minus the
  window, wherever you are); the reset reads the same way (`the 04:00 reset`).
  No screen says UTC or "tonight". The mockups assume UTC+4.
- **Nothing is called free or paid unless it is.** On the vessel's wifi the
  window and Now come out of the same allowance; what Now changes is that no
  reserve is kept. Only mobile data with the portal out of reach is called
  charged.
- **Time left is one unit**, the largest that is at least 1, rounded: `35s`,
  `5m`, `1h` — never `1h11m`.
- **One name everywhere.** A video's download is named after its title, cleaned
  only of the characters Android's shared storage refuses (`/ \ : * ? " < >
  |`) and capped well under 255 bytes: `40-Crust of Rust - Subtyping and
  Variance.py` in the queue, `Crust of Rust - Subtyping and Variance.mp4` in
  Downloads. A file download keeps its file's name. The `NN-` prefix still
  carries the order. Rename on a download's sheet covers the rare change.
- **Pause, not Stop. Back, not Hide.**
- **No "in the background"** on any screen.
- **No cap on any screen**: the size is the one figure. The cap still exists
  inside the item, where the runner enforces it; the queue still shows
  `≤505 MiB` for a download no server has sized yet (the old rule that an
  unstated total is never invented).

## 7. What goes away

These old rules end when the rebuild lands (their notes in `CLAUDE.md` go with
their code): the four-screen ytq and its confirm screen; the two hint sets
(`HINTS`/`TIGHT_HINTS`, now button label sets); "a flick scrolls; only a
keypress spends" and `enable_touch_scroll`/`read_wheel`/`wheel_step`; the
listing's legend row; `p spot`, `pick_place`, the phantom row and
write-then-place (ytq queues last; Move does the rest); the name row; the
two-row running-download strip and the `↓` badge on the Queue tab (the status
bar says it); curses itself.

## 8. How it is built

- **`tui.py`**: the one blessed `Terminal` and session (fullscreen, cbreak,
  hidden cursor, click and wheel reporting in SGR), SIGWINCH as a resize event,
  the terminal restored on Ctrl-Z, on resume and on any exception, mouse bytes
  nobody asked for dropped, never a byte of an escape sequence through as a
  key. `read_event()` returns a Key, a Tap(x, y), a Scroll(dy, x, y) with the
  drag's starting cell, a Resize, or a Done(fetch). Fetches are threads holding
  their subprocess so Stop can kill it; while one runs the loop wakes at the
  spinner's rate, otherwise it blocks.
- **`widgets.py`**: button, dock, segmented, checkbox, field, tab bar, status
  bar, sheet, dim — bewitch-only drawing, kept separable so it can move into
  bewitch — plus a **HitMap**: ids on composed rectangles, last composed wins,
  a lookup by cell (Lip Gloss v2's Layer/Compositor model).
- **Screens** are `draw(state, w, h) -> (Block, HitMap)`, pure, and
  `handle(state, event)`. Every button calls the same function as its key and
  its command (`do_arm`, `do_cancel`, `set_dest`, `queue_run_argv`,
  `do_reorder`, `write_item`). The Queue and More tabs come from dlq's
  modules, imported when first opened and never at module top.
- **One blessed session**: the queue's tabs draw into ytq's session; nothing
  opens a second `Terminal`.
- **Tests**: the pty pumps answer CPR (`ESC[6n` → `ESC[1;1R`) and DECRQM
  (`ESC[?<mode>$p` → `ESC[?<mode>;2$y`), as Termux does. New pty tests: a tap
  on a button acts; a tap outside every button does nothing; a drag never
  presses anything; momentum never fetches. Layout tests sweep widths 32–80 and
  heights 11–30: every line fits, nothing overlaps, buttons stay three rows,
  the pinned button is always on screen.

## 9. Settled, and still open

Settled in the review: buttons first, keys second; one shell; sheets; one tap
opens; the price on the button; one yes for uncounted spends; the 100 ms guard
and same-cell double-tap guard; swipe moves the view with a one-item scrolloff;
draggable scrollbars; deliberate pulls fetch and momentum never does; Feed and
Later read themselves on first open; three-row buttons at every height; blessed
as a runtime dependency (`pip install blessed`); the name nibbles; one repo.

Still open:

- What a bare `nibbles` command opens. Proposed: Search.
- The Run now sheet when the portal *does* answer (only the blind case is
  drawn). Proposed: the same sheet, `n Run now · 480 MiB` with `out of the 03:00
  window's allowance` as its grey line, primary border.
- The heights (`tput lines` both ways) and the exact compact cut-off.

## 10. Can a terminal do this? The audit

| Decision | Why it can be built | Still to confirm on the phone |
|---|---|---|
| Taps act on Termux's report | Termux sends press+release on lift, no press for a drag (`TerminalView.onUp`, `onScroll`) | — |
| Drag-the-bar by where the drag began | Termux stamps every wheel event of a gesture with its starting cell (`sendMouseEventCode`) | the feel of a row per row |
| Momentum never fetches | a fling is a post()ed stream of wheel events with no pause | the 0.5 s rest threshold |
| Pressed flash, guards | one timed redraw; timestamps on taps | — |
| Mouse decoding at all | blessed decodes SGR only when DECRQM is answered; Termux answers (`ESC[?1006;2$y`, checked on the phone) | — |
| Keyboard up/down | Termux resizes the terminal; SIGWINCH | the two heights |
| Colours, gradients, panels | Termux draws 24-bit colour (`TERMUX_VERSION` → truecolor in bewitch) | — |
| Glyphs | all from `bewitch.glyphs` (tested on the phone), plus `≤`, which dlq already draws there, and the rounded borders bewitch's dialogs use | `python -m bewitch` once more |
| Progress bar `█`/`░` | bewitch's house style: both one column on the phone (checked 2026-10-10) | — |
| Local time | Python's `localtime` on Termux reads Android's timezone through bionic | `python3 -c "import time; print(time.strftime('%H:%M %Z'))"` |
| Idle silence | `Frame` writes nothing for an unchanged screen; blocking `inkey()` | — |
| Names with spaces | the queue's own files live in Termux's home (ext4); the runner and items never pass a name through a shell; Android's shared storage refuses only the characters cleaned | — |
