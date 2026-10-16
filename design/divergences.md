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

## More tab and window card — the budget source settings — 2026-10-10

- Spec: section 5 lists the More tab's rows (window, reserve, auto, skip
  codecs, quality chips, destinations, nightly job, runner log, quit) and the
  Queue tab's window card draws "what the next window may spend against what
  expires". Neither knows about a budget source, because there was none.
- Built: the runner now has three more settings in `expire_runner.SETTINGS` —
  `budget` (zwana | manual), `allowance` (MB a day, "not set" at 0) and `reset`
  (a time of day; stored UTC, spelled on the phone's clock by
  `spell_setting`). Under a manual budget `snapshot()["expiring"]` is `None`:
  nothing can say what expires when the rest of the phone's use is not
  counted. The old curses settings page (`b`, `l`, `t`) shows and sets them,
  and shows only the settings that apply to the budget source
  (`expire_runner.settings_shown`): `allowance` and `reset` under manual,
  `reserve-when-paid` and `paid-min` under zwana. Below 16 rows it gives up the
  blank under its title, so all its rows fit at 40×14. The rebuilt screens are
  not touched.
- Approved for the rebuild (owner, 2026-10-10, over side-by-side sketches):
  - **More:** `b budget` as a switch row under `reserve` (`◉ manual`), with
    `l allowance` and `t reset` under it, shown only while the budget is
    manual, as `paid-min` shows only under the waiver. `allowance` opens the
    number sheet (presets `500 MB 1 GB 2 GB 5 GB`); `reset` opens a time sheet
    on the phone's clock. A change says itself on the line above the tabs
    (`allowance is 1.5 GB a day`).
  - **Window card, manual budget:** the bar draws `spendable` against
    `allowance.left_bytes`, and the figure keeps the spec's own shape,
    `1017/1144 MiB to spend` (22 columns, all there is beside Run now). Never
    "expires". Keyboard up, the strip reads `waiting · 1017/1144 MiB`.
  - **Window card, no allowance set:** `no daily allowance set` where the
    verdict would be, `set it under More` under it, and Run now drawn off. The
    status bar reads `WAITING  no allowance set`.
  - The Now sheet's red "on mobile data, charged" case never applies to a
    manual budget: what it spends is counted against the allowance either way.
- Why: a manual budget has figures the spec has no place for, and one figure
  (what expires) it cannot have at all. The first wording proposed for the
  card, `480 MiB of 1.2 GiB left to spend`, was 32 columns and did not fit.
- Status: approved 2026-10-10
- Since: the card's figure keeps GiB where `shell.size` says so (`0.99/1.12 GiB
  to spend` rather than `1017/1144 MiB to spend`), as the owner said on
  2026-10-10, and the allowance's key is `g` (see "The allowance's key on
  More" below).

## The allowance's key on More — 2026-10-10

- Spec: the approved budget-source entry (PR #1's divergences) has
  `l allowance` on More.
- Built: `g allowance`. `l` is already `runner log` on More (`k-more`), and a
  key can only do one thing on a page; `b budget` and `t reset` are as
  approved. `g` because the presets are in GB.
- Why: two approved rows asked for the same key; the runner log's was there
  first, in the mockup.
- Status: approved 2026-10-10

---

# Filled in where the spec is silent

**Status: approved 2026-10-10, all of them**, from the rendered page
(`design/mockups/fillins.html`, drawn by the real app), with one change the
owner asked for: a Done download whose file was removed says `deleted`, not
`deleted since`.

## The status bar for every verdict — 2026-10-10

- Spec: `WAITING` (primary) when idle and `↓ 18%` (attention) while something
  downloads, `opens 03:00` and `19m` beside it.
- Built: one label word per `gate()` verdict (`queue_screens.STATUS`, a test
  pins one per verdict): `WAITING`, `OPEN` (success, `closes 04:00`), `DONE`
  (`opens 03:00` the next day), `IDLE` (`nothing queued`), `OFF` (warn, `auto
  is off`), `SPENT`, `RUNNING` (warn: a blind run, or the whole queue starting),
  `BLOCKED` (error: zwana not answering, or a stale reading), and `ASKING`
  (info) before the first reading lands. The right segment is the countdown
  where there is one to count, and empty otherwise. `SPENT` inside the window
  names the next window (`opens tomorrow 21:57`, `23h`), never one already
  past. *Amended 2026-10-16, awaiting approval: it said `opens 21:57 · 0s`
  of the window it was in.*

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
- Built: Search, always — with no terminal it says it needs one rather than
  printing the status (the owner, 2026-10-10). `nibbles queue` or `more` opens
  another tab; Feed and Later have no word, being a tap away. `nibbles` is the
  one command, and `nibbles <url>` takes what yt-dlp would plus a plain file
  URL (the owner's, 2026-10-10).

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

- A failed download's second line is the item's refusal where it has one,
  else `gave up 3h ago` (the runner records no error, and its UTC log stamp
  is never drawn); a finished one's is its size and the file it delivered (or
  `deleted`). *Amended 2026-10-16, awaiting approval: this said "its last
  error", which drew the runner's UTC stamp of its last try.*
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

## A download's sheet once it has ended — 2026-10-13

- Spec: `k-download` draws a download while it runs (`downloading · now ·
  1h left`, the bar, the figures, Open it when done, Pause and Back) and
  nothing for after; the build said `stopped` for every ending, a finished
  one included, and the checkbox went with no word on what it came to.
- Built: the head says where the download went once it has left the run:
  `done` (success, the bar full) when the runner archived it, `failed`
  (error) when it was given up on, and `stopped` only for one still queued
  (paused, or out of its slice); an ended one drops the `· now` tail. Where
  the checkbox was, a download that was asked to open says what opening it
  came to — `opening it…` (info) until the opener answers, then its own
  answer (`opened film.mp4`, `could not open film.mp4`, or that it did not
  finish, so nothing was opened).
- Why: "Open it when done" ran and nothing on the screen said so, and the
  sheet a person watches for the end of a download is the one place it must
  say the download ended.
- Status: awaiting approval

## Feed and Later: a read that fails over a listing — 2026-10-16

- Spec: `k-feed` draws the list once read, and design §5 says an empty feed
  still says the cookie is the likely cause and how old the jar is. Nothing
  draws a Re-read or a deeper look that fails, comes back empty, or finds the
  cookie jar gone once a listing is already up.
- Built: the old rows stay, and what went wrong is a notice over them (titled
  `Feed` or `Later`, the reason, then the cookie's fix, `esc OK`), as a search
  that did not come back is: in `error` when the read failed, plain for an
  empty answer or a missing jar. One that comes back while another tab or a
  sheet is up is said when the tab is next on top with nothing over it. With
  no listing yet it is drawn where the list would be, as before.
- Why: the failure was kept and never drawn once a listing was up, so a
  Re-read with expired cookies came back to the same rows and `read 3h ago`
  with nothing said — the "nothing new" an empty feed must never read as —
  and each `↓ 30 more` spent again with no word why.
- Status: awaiting approval

## Quality chips set by hand that outnumber the row — 2026-10-16

- Spec: the tier buttons are the heights you use plus `audio` (at 40 columns
  your three most-used); other heights live under Formats, and a wider
  screen adds buttons rather than narrowing them. Nothing says which heights
  set by hand under More stay when there are more than the row holds (More's
  own `240-720` and `360-1080` at 32 columns, four or more at 40).
- Built: the row holds as many as it has room for: the tier the sheet is on
  and those around it, in height order (the rule the audio row already uses
  for bitrates), then `audio`. The rest are under Formats. More still shows
  the whole range you set.
- Why: every button was narrowed instead, until the labels read `36…` and
  `…`, and at 32 columns the last ones and `audio` were cut off.
- Status: awaiting approval

## The search bar while a search runs, keyboard up — 2026-10-16

- Spec: `k-search` keyboard up: "the bar takes focus"; the search's own line
  ends in `x stop` ("Stop on a running fetch"). No mockup draws a search
  running with the keyboard up.
- Built: with the keyboard up and nothing searched the bar holds the keyboard
  as drawn, `q` and `x` included. While a search runs it lets go and is drawn
  so (no cursor, Go plain): `x` is the Stop its line offers and `q` quits; a
  letter or a tap on the field takes it back.
- Why: the bar was drawn focused while the keys went elsewhere: `q` quit the
  app and the `x` of `xbox` was swallowed. A bar that keeps the keys during a
  search would make the `x stop` beside it type an `x` instead.
- Status: awaiting approval

## An item that could not be written — 2026-10-16

- Spec: nothing draws a queueing that fails to write (a full phone).
- Built: a notice, `Not queued`, in `error`, with the system's reason, over
  the video sheet. The sheet stays as it was, formats and choice kept, so the
  next try is the same tap. A Start now that cannot start the download after
  the item was written says `Queued, not started`, as the busy-queue case
  does, and gives the receipt.
- Why: the app ended with a traceback, and the session's listings and probes
  went with it.
- Status: awaiting approval

## A download that leaves the queue while Move holds it — 2026-10-16

- Spec: `k-place` draws Move holding a `◆` row; it says nothing of the held
  download finishing, failing or being removed meanwhile.
- Built: the hold is let go before the frame is drawn, the Queue tab comes
  back with its tabs, and the line above them says `<name> finished while it
  was held` (or `failed …`, or `left the queue …`). Nothing is renamed.
- Why: there is no place left to put it; drawing one crashed the app.
- Status: awaiting approval

## The download sheet `x` opens while Run now is starting — 2026-10-16

- Spec: `k-download` is a named download's sheet, opened from its row.
- Built: `x` on the Queue tab while our Run now is alive opens a sheet that
  follows the run. It takes up each item the run starts. Before the first, it
  is titled `Run now`, says `starting the queue` (the status bar's words) and
  offers `x Pause` and `esc Back`. If the run ends without an item it says
  `the run has ended`.
- Why: bound to whatever was downloading when it opened (often nothing), it
  said "downloading" over nothing and "stopped" over the item the run then
  fetched.
- Status: awaiting approval

## Paste — 2026-10-16

- Spec: the Search field takes "a pasted URL"; nothing draws a paste, or
  says what one does anywhere else.
- Built: bracketed paste is asked of Termux. A paste is typed into the Search
  field (focusing it, appended to what is there, even with results up) or
  into an open sheet's field (only what that field accepts), with line breaks
  and tabs as spaces. It never submits; ⏎ or Go does. On a screen with no
  field it is dropped.
- Why: unbracketed, each line break in a paste was ⏎, and the rest acted as
  keys on the screen underneath — a search, a probe for the selected row,
  Now, `q`.
- Status: awaiting approval

## Two items with one name — 2026-10-16

- Spec: design §6 — a video's download is its title, behind the `NN-`.
  Nothing draws two items with the same title.
- Built: the second is written as `NN-<title> (2).py` (then ` (3)`…), so its
  Queue row reads `Talk (2)`. The file it delivers keeps the title, and the
  runner's `free_name` settles a clash in the destination (`Talk (2).mp4`,
  as for any file already there).
- Why: an item's name keys its `work/`, `out/` and state record, and reusing
  one resumed another video's partial or inherited a finished record
  ("nothing left to fetch" every night).
- Status: awaiting approval

## Open it refuses what Termux would refuse in silence — 2026-10-16

- Spec: the 2026-10-13 entry above records the opener's answers as `opened
  film.mp4`, `could not open film.mp4`, or that it did not finish.
- Built: those stay. A hand-off Termux would refuse with only a logcat line
  is now refused before anything is sent, as `could not open film.mp4: <why:
  the fix>`. The reasons are:
  - it is not in <folder> any more;
  - it cannot be read (`run termux-setup-storage`);
  - it is not a file;
  - it is outside Termux's folders and internal storage (`move it to
    internal storage, or set its destination there in More`);
  - Termux has not been told it may share files (`Termux shares no file with
    another app until ~/.termux/termux.properties has allow-external-apps =
    true: add it, then run termux-reload-settings`, with variants for a file
    Termux cannot load or a value that is not `true`).
- Why: termux-open exits 0 once its broadcast is sent, so each of these read
  "opened" while nothing opened. This is the owner's "termux not opening
  files".
- Status: awaiting approval
