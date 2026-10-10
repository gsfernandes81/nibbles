# Divergences from the design

Every place the build differs from `design.md` or the mockups, waiting for the
owner to approve it or send it back. One entry per divergence, newest last:

```
## <screen or rule> — <date>

- Spec: what design.md or the mockup says.
- Built: what was built instead.
- Why: what made the spec impossible or worse in practice.
- Status: awaiting approval | approved <date> | sent back <date>
```

The second half of this file is **filled in where the spec is silent**: things
the build had to decide that no mockup draws and `design.md` does not say. They
are not departures from anything, but they are decisions, so they are listed
for the same approval.

## The header's name — 2026-10-10

- Spec: the mockups draw ` ytq ╱╱╱…` on Search, Feed and Later and ` dlq ╱╱╱…`
  on Queue and More (they were drawn before the app had a name).
- Built: ` nibbles ╱╱╱…` on every tab, through bewitch's `header`. The `╱`
  band gives up the four columns, so every detail the mockups show still fits
  at 40 columns; at 32 the band shrinks first, as bewitch's header rule says.
- Why: it is one app now, and a header that changes name when you change tab
  reads as two apps.
- Status: approved 2026-10-10

## The checkbox's label colours — 2026-10-10

- Spec: off is a grey `•` and a grey label; ticked is a green `✓`, a bold
  label and a `success` outline (`k-download`).
- Built: bewitch's own recipe, `bubbles.huh.checkbox(boxed=True)`, which
  bewitch#1 added since the mockups: the glyphs and the outline as drawn, but
  the labels coloured as huh's Charm theme colours them — the plain text
  colour when off, `success` (not bold) when ticked. On a bewitch checkout too
  old to have it, the app draws the same look itself.
- Why: it is huh's look exactly, which is what the spec asks for, and one
  copy of it in bewitch is better than a second in nibbles.
- Status: approved 2026-10-10

---

# Filled in where the spec is silent

## The status bar for every verdict — 2026-10-10

- Spec: `WAITING` (primary) when idle and `↓ 18%` (attention) while something
  downloads, `opens 03:00` and `19m` beside it.
- Built: one label word per `gate()` verdict (`queue_screens.STATUS`, a test
  pins one per verdict): `WAITING`, `OPEN` (success, `closes 04:00`), `DONE`
  (`opens 03:00` the next day), `IDLE` (`nothing queued`), `OFF` (warn, `auto
  is off`), `SPENT`, `RUNNING` (warn: a blind run, or the whole queue starting),
  `BLOCKED` (error: zwana not answering, or a stale reading), and `ASKING`
  (info) before the first reading lands. The right segment is the countdown
  where there is one to count, and empty otherwise.

## Stop on a running fetch — 2026-10-10

- Spec: "a spinner shows what is running, Stop (`x`) cancels the newest".
- Built: `x` anywhere cancels the newest fetch (it kills the yt-dlp it holds).
  Where a fetch has a line of its own (the search under the bar, the feed's
  read beside Re-read) the line ends in a grey `x stop`, and on the search it
  is also a tap target. The video sheet's loading state is drawn exactly as
  the mockup, with no Stop on it: closing the sheet keeps the fetch, as the
  spec says.

## Notices are sheets — 2026-10-10

- Spec: confirms are sheets; refusals inside a sheet are said in red in it.
- Built: what the old screens said on a full-page message (a search that did
  not come back, nothing found, the bot check's 360p notice, a probe that
  failed, "the runner would reject this item", a download that could not
  start) is a sheet with the title, the lines wrapped, and a pinned `esc OK`.
  Its body scrolls and the OK never does (a sweep test holds that).

## Download now on a download's sheet asks once, with the figure — 2026-10-10

- Spec: Download now is a spend-style button on the item sheet; "a spend that
  nothing is counting still goes through exactly one yes"; every confirm is a
  sheet with the yes full width and the figure on it.
- Built: Download now opens that confirm: `Download now?` and `today's
  allowance, no reserve kept` with `y Download now · 505 MiB` (the figure is
  what is left to fetch), or, with zwana not answering, the Run now sentence,
  `on mobile data, charged`, `y Download anyway` in the danger style and the
  warning border. `esc Not now` last. (The video sheet's Start now needs no
  confirm: that button is its one yes, as drawn.)

## Run now when the portal answers — 2026-10-10

- Spec: open question (design §9), proposed: the same sheet, `n Run now ·
  480 MiB` with `out of the 03:00 window's allowance`, primary border.
- Built: exactly the proposal, with the question `Run the queue now, before
  the window opens?`. A run the runner would refuse (empty, off, spent, past
  the stop time) is not offered: the line above the tabs says why, in the
  screen's words and on the phone's clock.

## A bare `nibbles` — 2026-10-10

- Spec: open question (design §9), proposed: Search.
- Built: Search. `nibbles queue` (or `feed`, `later`, `more`) opens another
  tab; `ytq` and `dlq` keep their own words.

## The More tab's other rows and their sheets — 2026-10-10

- Spec: `k-more` draws window, reserve, auto, skip codecs, quality chips,
  destinations, nightly job, runner log, quit; "a number opens a sheet";
  `paid-min` only while the waiver is on.
- Built: every setting in `expire_runner.SETTINGS`, in its order, so
  `reserve when paid` and `notify blocked` are rows too (with `p` and `n`), and
  any setting the runner grows appears without a screen change. The three
  rows the mockup draws without a sheet open one each in `k-setting`'s shape
  (field, rule, presets, `esc Cancel` / `⏎ Set`): skip codecs (presets `av01
  vp9`, `av01`, `vp9`, `none`), quality chips (`learned`, `240-720`,
  `360-1080`), and destinations (a sheet listing video, audio and file with
  where each goes; a tap on one opens its path in the same field sheet, with a
  `default` preset). The nightly job row arms on a tap and asks before it
  stops (`y Stop it` in danger, `esc Not now`). The runner log and an item's
  log are a scrolling sheet of the file's last lines.

## Words where no mockup has any — 2026-10-10

- A failed download's second line is its last error; a finished one's is its
  size and the file it delivered (or `deleted since`).
- Before the first reading lands the window is `the window` (`Queue for the
  window`), never a made-up time.
- An empty group says so: `nothing queued — Search or Feed adds something`,
  `nothing has failed`, `nothing finished yet`.
- At 32 columns the cut line shortens its lead-in (`── window · 480 MiB`, as
  `k-narrow` draws it) and keeps the figure or the reason.
- Rename is a field sheet titled `Rename`, prefilled with the name.
- What a queueing did is said on the line above the tabs (`queued Crust of
  Rust - Subtyping and Variance · 92 MiB`), as More's changes are.

## Keys the spec does not list — 2026-10-10

- `Tab` and `Shift-Tab` step through the tabs (a keyboard needs a way along
  the bottom row). `s` on Queue opens More and `l` the runner log, as they did
  on dlq's listing. On the video sheet `n` toggles Now, `f` opens Formats, `s`
  and `l` pick Smallest and Largest, `←`/`→` step the tier, and `c` copies the
  page's URL (ytq's old `c`). `/` focuses the search field from Search, Feed
  and Later.

## Pause only on a download this session can stop — 2026-10-10

- Spec: `k-download` draws `x Pause` and `esc Back` under the running
  download.
- Built: Pause is there for a download this session started (Download now,
  Start now, or Run now). A nightly firing's download, or a `dlq now` in
  another terminal, gets `esc Back` alone, full width: this app holds no
  handle on it, and a Pause that says "paused" over a download that carries
  on is worse than none (dlq's old rule for `x`).

## Skip codecs starts empty — 2026-10-10

- Spec: `k-more` shows `skip codecs  av01 vp9`.
- Built: nothing is skipped until it is set (presets `av01 vp9`, `av01`,
  `vp9`, `none`); the mockup's value is read as the owner's own setting, not
  as a default for everyone.

## The allowance's key on More — 2026-10-10

- Spec: the approved budget-source entry (PR #1's divergences) has
  `l allowance` on More.
- Built: `g allowance`. `l` is already `runner log` on More (`k-more`), and a
  key can only do one thing on a page; `b budget` and `t reset` are as
  approved. `g` because the presets are in GB.
- Why: two approved rows asked for the same key; the runner log's was there
  first, in the mockup.
- Status: awaiting approval
