# nibbles — working notes for Claude

Queue YouTube videos and file downloads on the phone, and fetch them with data
that would otherwise expire. **Every byte the runner spends crosses the phone's
metered mobile radio** — the whole design is about spending allowance that
would expire anyway, and never more — and the screens are built for a
40-column portrait terminal.

ytq (the YouTube front end) and dlq (the expiring-quota download queue and its
runner) were split out of the `or3` monorepo's `termux/expire/` on 2026-08-28
and **merged into this repo on 2026-10-10**, histories kept. The modules are
flat at the root and import each other by bare name. Two sibling checkouts
are left: **zwana-quota** (the portal client and quota widget the zwana budget
source reads its guard figures through; a manual budget needs none:
`$ZWANA_HOME`, a clone beside this repo, then `~/zwana-quota`) and **bewitch**
(the Lip Gloss port every screen is drawn with: `$BEWITCH_HOME`, beside, then
`~/bewitch`; `tui._bewitch_root`). The one installed dependency is
**blessed**, which owns the terminal. `expire_sched._zwana_root` predicts the runner's resolution so
`nibbles status` can name a missing checkout instead of letting an import
traceback. The phone's move from `~/dlq` + `~/ytq` to `~/nibbles` is in the
README.

## The app, and its spec

ytq and dlq are **one buttons-first app on blessed**, drawn by bewitch, since
2026-10-10: five tabs along the bottom (Search, Feed, Later, Queue, More),
sheets from the bottom over a dimmed tab, and a status bar on the last row.
`nibbles` opens it on Search (`nibbles queue` on Queue, `nibbles more` on More). **`design/` is the spec**:
`design/design.md` holds every decision the owner made, `design/mockups/` the
mockups (rendered from `design/mock/` with the same recipes, keyboard down and
up), and `design/divergences.md` every place the build differs or had to fill
in what nothing draws.

- **Follow the mockups very closely.** Layout, wording, glyphs, colours by
  role, button sizes and what gives way first are all decisions, not
  suggestions.
- **Diverging needs the owner's approval.** If something in the spec cannot
  be built as drawn, or a better shape turns up, ask first. If the owner does
  not answer and the work would stall, diverge, and record it in
  `design/divergences.md` — what the spec said, what was built instead, and
  why — so the owner can approve it or send it back later. A divergence not
  in that file is a bug.
- **`nibbles` is the one command** (the owner, 2026-10-10). `pyproject`
  installs only `nibbles`. `nibbles.main` is a door, not a parser: every word
  goes to the module that always answered it — `search`/`queue`/`ui`/`more`
  to the app (`queue` through `expire_sched`'s `ui`, which names a broken
  checkout first), `--list subs|wl` and `--from-json` to `ytq.main`, the
  queue's verbs to `expire_sched.main`, and anything else to **what yt-dlp
  would take** (`ytq.read_input`): a link with or without its scheme,
  `ytsearch…:words` (the search), or whatever one of yt-dlp's own extractors
  matches — asked of yt-dlp offline (`ytq.yt_dlp_takes`, in yt-dlp's own
  interpreter), and handed to the app as `--link` (`LINK_KEY`) when the field
  would otherwise search for it, a bare video id being the case. A link is
  then a page or a file (`nibbles._url`): a flag only one of them takes says
  which, YouTube's hosts are pages, and otherwise **the server's headers
  decide** (`dlq.kind_of`, ~1 KB; HTML is a page, an attachment or anything
  else a file) — never the name, and an unreachable server is an error, not
  a guess. A page goes to `ytq.main`, a file to `dlq.main`. **A bare
  `nibbles` only ever opens the app**: with no terminal it says it needs one
  (the owner retired dlq's print-the-status fallback for it). **Words are
  never a search on their own**: `nibbles search WORDS` searches, and anything
  unknown is refused, because a mistyped verb that became a search would
  spend data. There is no word for Feed or Later (a tap away), and none for
  a file (`nibbles <url>` is both); dlq's raw `queue` listing is gone.
  `test_cli.py` (dlq) pins every route. The modules keep their own `main`s
  for that door and for running a file directly; `expire_sched._me()` names
  `nibbles`.
- **The layers.** `tui.py` is the one blessed `Terminal` (fullscreen, cbreak,
  hidden cursor, clicks and the wheel in SGR, restored on Ctrl-Z and on any
  exception) and turns what arrives into `Key`, `Tap`, `Scroll` (with the
  cell the drag *began* on), `Resize` or `Done`; a mouse report is never a
  key. `widgets.py` is bewitch-only drawing — button, dock, segmented,
  checkbox, field, tab bar, status bar, sheet, dim — each returning a `Piece`
  (a Block and its tap targets), and the `HitMap` taps are looked up in (last
  composed wins); it reads no keys and is kept separable so it can move into
  bewitch. `shell.py` is what the screens share: the words (`size`, `left`,
  `clock`), the `ListView`, `Sheet`, `Confirm`, `Notice`. `nibbles.py` is the
  loop. `yt_screens.py` and `queue_screens.py` are the screens. **bewitch
  draws; it does not read the keyboard** — that is blessed's, here.
- **Every button calls what its key and its command call** — `write_item`,
  `do_reorder`, `do_remove`, `do_rename`, `do_requeue`, `do_clear_tries`,
  `set_setting`, `set_dest`, `do_arm`, `do_cancel`, `queue_run_argv` — and
  `queue_screens` is imported by the app when it starts, never at a module's
  top, because `expire_ui` imports `expire_sched`, which imports `ytq`. **One
  blessed session**: the queue's tabs draw into the same one.
- **A tap is a tap; a drag is a scroll.** Termux decides before the app hears
  anything: a tap is a press and a release sent on lift, only if the finger
  did not move; a drag is wheel events, one per row, every one stamped with
  where it began; a long press is Termux's selection. A button acts on the
  press and fills for one frame (`tui.PRESSED`). `tui.Guard`: every tap is
  dropped for 100 ms after a screen or sheet appears, and one on the same cell
  for the rest of the 300 ms double-tap window. The last three columns of a
  list are its bar: a tap there jumps, a drag that starts there moves the
  thumb a row per row (`ListView.bar_drag`). The selection rides one item in
  from the edge (Helix's scrolloff, `ListView.ride`/`follow`).
- **Fetches run in the background, and only a deliberate act spends.** A
  search, a format probe (one tap on a row), the feed's first read on first
  opening its tab, Re-read, and the deeper look are `tui.Job`s; inside one,
  `ytq.ask` runs yt-dlp through `tui.run_child`, which hands the child to the
  job so `x` (Stop) can kill it, and outside one (the printing paths, the
  tests) it is the plain `subprocess.run` it always was. **A fling's momentum
  never fetches**: the deeper look takes a tap on `↓ 30 more`, ↓ on the last
  row, or a *fresh* drag down after the list has rested at its end for
  `yt_screens.REST`; momentum is an unbroken stream of wheel events, so it can
  never produce the rest and then more (a pty test flings and then pulls).
- **An idle screen writes nothing.** Everything goes through
  `bewitch.screen.Frame`, which writes only changed lines and nothing for an
  unchanged screen, and the loop blocks in `Session.read` until something
  happens. Only a running fetch's spinner, the selected title's marquee, a
  download's progress and the status bar's countdown wake it, and only while
  they are changing (`App.next_wake`).
- **Words** (design §6): the phone's clock and never UTC (`shell.clock`; the
  runner's own `clock()` writes UTC for its log and is not shown on a screen),
  no "tonight", nothing free or paid unless it is, time left in one unit
  (`shell.left`), sizes in three figures (`shell.size`), and **one name
  everywhere**: a video's download is its title cleaned only of what Android's
  shared storage refuses (`ytq.title_name`), behind the `NN-`.
- **Pause is SIGINT, both kinds**: `Firing.stop` (the whole queue) always was,
  and `ytq.Running.stop` (one `nibbles now`) is now too — it used to send SIGTERM;
  the interrupt is the ctrl-c it replaces, and it reaches yt-dlp in the same
  process group, which closes its part file.

## Decisions that travel with the queue (dlq)

- **`expire_sched.py` run on its own opens the screen** — `default_action`,
  whose other half is still pinned for that file: with no terminal it is
  `status`. (A bare `nibbles` no longer does this; see the one command.)
- **`nibbles <url>` queues a direct file download** when the server says it
  is a file (2026-10-10; before that `dlq <url>`, and once a separate
  command). `dlq.py` keeps its own module and flags.
- **The Queue tab is the whole queue.** dlq's listing and its legend row,
  the item screen and the settings page are gone (2026-10-10): the window
  card (the verdict, a bar of what the next window may spend against what
  expires, Run now), the Queued/Failed/Done filters and the rows are the tab,
  a tap on a row opens its sheet with `actions_for`'s actions as buttons, and
  More holds the settings, the destinations, the nightly job and the runner
  log. Every verb that lives at both ends is still **one function called by
  both** — `do_arm`, `do_cancel`, `set_dest`, `queue_run_argv` — because a
  screen and a command that disagree about whether arming worked leave
  nobody able to tell. **Ordering lives only here**: Move holds a download as
  a `◆` row, the window card and the cut line re-planned at every step through
  `preview`, and drops it through `do_reorder`; ytq queues last and has no
  place picker any more (the phantom row and write-then-place went with it).
- **Done is newest first** (2026-10-08) — `_paths` orders `done/` by
  `_finished_order`: the day directory, then the item file's `st_ctime`
  (it arrives by rename, so that is when it finished — which is what lets
  downloads archived before this was written sort too, with nothing new
  recorded), then the name, since a firing runs items in name order.
- **`run-now` carries `--force`**, and that is what makes now mean now: it
  overrides the clock gate and nothing else — the floor, the per-item caps and
  the portal reading still decide everything they decided.
- **Stopping a run from the screen is SIGINT, never SIGTERM**
  (`Firing.SIGNAL`): the item downloads in a session of its own, so what stops
  the download is the runner *unwinding* — `run_item` kills the item's tree on
  the way past — and only an interrupt does that. SIGTERM leaves yt-dlp
  spending data with nothing watching it.
- **`nibbles run-now --blind`** is the bargain when `ic.zwana.io` cannot be
  reached at all: every guard the runner carries is a portal figure, so a
  blind run has none and is bounded by what the items declared
  (`blind_budget`, called by the front end rather than re-derived). **Nothing
  interrupts a blind download for the time** — a run cut short would only buy
  the same bytes again; `NO_DEADLINE` is the one spelling of "no stop time".
  A blind run that finds the portal up is an ordinary run with the floor
  intact.
- **`nibbles status` leads with the verdict**, and the verdict is
  `expire_runner.gate()` — the same function the firing gates on, so a screen
  saying "waiting for the window" cannot be a night the runner stopped for
  some other reason. A test must pin the *order* the gate answers in.
- **`nibbles queue` is the only thing in the queue that changes anything**, and an
  item is *four* things — the file in `queue/`, the partial in `work/<item>/`,
  anything finished in `out/<item>/`, and its record in `state.json`.
  `expire_ui.belongings` is the only place that decides that; every move and
  removal is spelled from it.
- **The order is a position, never a number** — always **two digits**, because
  the runner sorts *file names*: `100` sorts before `20`. `ytq.next_number`
  caps at `MAX_PRIORITY` for the same reason.
- **Removing keeps what was paid for.** The confirm's keys never vary with the
  item (`removal_answers` guarantees it). A done download whose file was
  deleted removes itself, gated on `_readable` — an `os.listdir`, because
  Android's Downloads *is there* and raises before `termux-setup-storage`.
  Unreadable is `away` and left alone; only `gone` is acted on.
- **What `n` says depends on where the phone is** —
  `expire_runner.portal_reachable`, a 1.5 s TCP connect to `ic.zwana.io`;
  the portal is on the vessel's network, so it answering *is* "on vessel
  wifi".
- **Nothing is queued twice** — items record `# SOURCE:` and `ytq.write_item`
  is the one door that refuses a duplicate; a file URL goes through it too.
- **Destinations**: `nibbles dest` holds them; the item always downloads into
  `out/<item>/` and the *runner* moves it at delivery (`shutil.move`, never a
  rename — shared storage is a different filesystem), so an unreachable
  destination leaves the file safe.
- **Every command line anchors to the checkout, not an installed copy** —
  `ytq._root()` resolves the queue root (`$EXPIRE_HOME`, else this file's own
  directory *only when it holds `queue/README.md`*, else `~/nibbles`) and the queue's
  commands take the same answer, so an installed copy still manages the real queue;
  the alternative is a nightly job firing faithfully onto an empty queue,
  saying nothing. The Installing section of `docs/download-queue.md` explains it.

- **One reading feeds the word, the figures and the bar** (2026-08-28). A
  download's size was once shown twice, from two readings a second apart that
  disagreed. The running download's sheet asks `QueueModel.progress` once per
  draw and hands that one reading to the line, the figures and the bar. Two
  rules travel with it: **`where` is the directory, not the activity** — an
  item being downloaded is still in `queue/`, so the word is chosen by what
  is downloading while `where` decides everything else; and **an unstated
  total is never invented**, because `queue_screens.amount` (like `_of` for
  the printed listing) shows the declared cap with a `≤` until a server
  states a size, and a bar with no total stays empty. The bar is bewitch's
  `█` against `░`, both one column in Termux (checked on the phone,
  2026-10-10, design §10).
- **`nibbles dump [NAME]` is the bug report** (2026-08-28): environment, how the
  queue root and zwana-quota resolved, gate verdicts, state rows, failing
  items' heads and the newest logs, every section guarded so it finishes on
  the broken trees it exists for. (The `ytdl_item.py` shim pre-split items
  imported off the queue root went with the merge: the real module is at the
  queue root now.)
- **`nibbles settings` / the More tab** (2026-09-02): the window, the
  reserve, `reserve-when-paid`, `paid-min`, `auto` and `notify-blocked` live
  in `config.json` beside the destinations, and are read at the moment they
  are used, never cached — `expire_runner.SETTINGS` is the one spec, and both
  front ends read it through the runner rather than keeping a second copy of
  the names, the defaults or the rules. **`off` is the first thing `gate()`
  asks**, ahead of the empty queue, because it is the answer to "why did
  nothing happen tonight" on every night it is off; `run-now`'s `--force`
  steps over it exactly as it steps over the clock, because the switch is a
  *when*, not a guard over money — the reserve, the per-item caps and the
  portal reading answer to nobody's `--force`. A value found in `config.json`
  that fails its rule reads as the default rather than raising: this is read
  at the top of a firing nobody is watching, and a stray character typed into
  the file must not be able to stop a night's downloads or take out the
  reserve on its way past — `nibbles settings` and `nibbles dump` name what they
  declined instead. **A change stays on the page and is said there**: More
  is a tab, a switch flips where it sits, a number opens a sheet that closes
  on Set, and what the change did is said on the line above the tabs; every
  change that took is also a receipt printed once the terminal is given back.
  Every setting in `SETTINGS` is a row, in its order, with a key in
  `queue_screens.SETTING_KEYS` (a test fails until a new one has one), and
  `paid-min` is a row only while the waiver is on. **Reading a
  broken `config.json` is forgiving; writing over one is refused** —
  `load_config` answers a file that will not parse with an empty dict, so a
  save on top of it would be a fresh file holding only the new key, with the
  destinations and the other settings gone under a line saying it worked.
  `config_problem` is the one line that says so:
  `set_setting` and `set_dest` refuse with it and write nothing, and More, the
  command and the dump all print it (ytq's own preferences, `ytq_prefs`, are
  refused the same way by `ytq.save_prefs`). And **whether a
  stored value is in force is one function's answer** — `setting_state`, keyed
  on the key being *present*, because the three places that show the settings
  each used to decide it and a file holding `null` read as refused on the
  screen and as nothing at all from the command. The reserve is waived on
  `paid.left_bytes` alone, never on
  `free.left_bytes`, because `paid.left_bytes` can only understate what is
  actually paid for while `free.left_bytes` can only overstate what is
  actually free — "there is paid data" is the one direction that reading
  cannot be wrong about, so it is the only reading the waiver asks.
  **`paid-min` defaults to 0, which is that same question**
  (`reserve_waived`'s threshold floors at one byte, so nought means "any paid
  data at all" and the waiver behaves exactly as it did before there was a
  figure); a figure above it is the person's own judgement that their last few
  MB of paid data are not worth the reserve they would stand down, and because
  the reading understates, wanting "at least this much" can only ever keep the
  reserve for longer. It qualifies `reserve-when-paid` and does nothing on its
  own, which the setting's own sentence says rather than a refusal saying it.
  **`notify-blocked` covers the blocked-firing notification and no other** —
  that one repeats every ~15 minutes on a phone off the vessel's wifi, which
  is how a person learns to ignore notifications, while a malformed item and
  an item that has run out of nights each happen once and still need somebody;
  off leaves the log line and `nibbles status` exactly as they were, and the
  switch is asked in `say_blocked`, not inside `notify`. And the window is a
  multiple of 15 minutes because that is JobScheduler's own floor for a
  periodic job — a window that is not a multiple of one would buy nothing
  beyond the nearest firing below it.
- **Where the budget comes from is a setting** (2026-10-10): `budget = zwana |
  manual` in `expire_runner.SETTINGS`, with `allowance` (decimal MB, 0 is "not
  set") and `reset` (stored as UTC `HH:MM`, typed and spelled on the phone's
  clock). **zwana is today's runner, unchanged**: a reading is still the
  `quota_widget.derive` document and every function that took one still does;
  the manual reading is a dict of its own shape (`source: "manual"`) and
  `is_manual` is the one test that tells them apart, so the zwana path is the
  code it was. zwana is the default wherever `quota_widget` can be *found*
  (`ZWANA_IMPORTABLE`, a `find_spec`, decided at import — a firing is a
  process of its own) and manual otherwise; **`quota_widget` is imported
  lazily, by `_qw()`**, so the runner, `nibbles status`, `nibbles settings` and `nibbles
  dump` run on a phone with no zwana-quota at all, and the four presentation
  helpers the front ends borrowed off `runner.qw` (`Paint`, `countdown`,
  `since`, `grade`) are the runner's now, taken from `quota_widget` when it
  is there. `root_problem` names a missing checkout only when zwana is the
  source. **A manual budget spends the allowance, less what the runner itself
  moved since the last reset, less the reserve, less `FLOOR_MARGIN`**
  (`manual_spendable`) — the margin for its second reason, the bytes that move
  between two looks at a running download. What it moved is a **ledger**,
  `state["spent"]`, `[epoch, bytes]` entries written by `note_spent` after
  every item `fire()` runs *and* every `nibbles now`, kept for both sources so a
  switch mid-day starts from what was spent, and entries rather than a total
  so "since the reset" is right however the reset is moved. **On the phone
  the interface counters cannot be read** (`/proc/net/dev` is permission
  denied to an app, and the owner's rule is to assume it is for everyone), and
  `iface_bytes` answers that with nought, so every guard built on it read
  "nothing moved": a manual ledger that never grew, and on zwana a byte cap
  and a floor projection that never fired, with only the minute's portal poll
  left. So `iface_readable()` is asked per item, and where it is false the
  child carries a **`Meter`**: the item's own `payload_bytes_this_slice` for
  this run id, else how much its `work/` and `out/` grew, at `WIRE_FACTOR`.
  The report wins over the growth because the growth over-counts a merge, and
  a cap that stops a download at its last second has spent the bytes for
  nothing. `watch()`, an interrupted run, `fire()`'s ledger and `nibbles now` all
  charge by it; where the counters can be read nothing changes. The interface
  delta, where there is one, errs high — but neither count can see what the
  rest of the phone used, which is why the reserve is **never waived** on a
  manual reading (`reserve-when-paid` turns on a paid figure only the portal
  has) and why the status screen says so under the figures. A ledger that
  cannot be read — `state.json` that will not parse, `spent` not a list —
  reads as the whole allowance spent, because forgetting a day's spending
  reads as an allowance nobody touched. In flight, `watch()` projects the
  manual remainder down by that same count exactly as it projects the
  portal's between polls, with nothing to poll and no portal to go dark.
  **`gate()` gains one verdict, `unset`, after `empty` and before `early`**:
  a standing setting rather than a moment, like `off`, so it is the answer at
  noon and not only inside the window — the person setting the phone up learns
  it then rather than the first night nothing happens; after `empty` because
  with nothing queued there is nothing to spend an allowance on either way;
  not a fault, since a heartbeat is enough and a notification every fifteen
  minutes for a setting not yet made is noise; and no flag reaches it.
  "Spent for today" is **the existing `spent`** in its existing place, with
  its own sentence: it is the same night (nothing above the reserve until the
  reset), so the screens already say it. A manual reading is always `usable`,
  so `--blind` never flies on one, and `nibbles run-now --blind` on a manual
  budget runs the ordinary run and says why. **`snapshot()` only gains keys**:
  `source`, `allowance` (the manual reading, or `None`) and `expiring` (the
  portal's free grant left, or `None` — a manual source cannot know what
  expires, and inventing it would be the one figure on the window card that
  is a guess); `portal` is `None` under manual, `deadline` is the manual
  reset, `spendable` the manual figure. The window card's "what the next
  window may spend against what expires" is therefore `spendable` against
  `expiring` under zwana, and against `allowance["left_bytes"]` — "left of the
  allowance", never "expires" — under manual.
  **A screen shows only the settings that apply to the source**
  (`settings_shown`, off each spec's `only`): a row that changes nothing is a
  row nobody should have to read past. The More tab builds its rows from it
  (`queue_screens.shown_settings`, which adds the order — the budget source
  under the reserve — and `paid-min` only while the waiver is on), and
  scrolls rather than giving one up. The command line and the dump still list
  every setting. The owner approved the rebuild's More rows and window card
  for a manual budget on 2026-10-10; `design/divergences.md` has them.
- **The cut line in the queued list is computed, never an item** (2026-09-02).
  It is an entry the cursor cannot stop on and no tap can open — not
  selectable and with no name — between the rows `queue_entries` builds, and
  it says `the window ends here · 480 MiB` (or `nothing in the window · why`;
  `── window · 480 MiB` at 32 columns), never "tonight".
  `expire_runner.admit()` is the one admission rule — what a single item may
  take in a firing, and why not — and `fire()` calls it instead of carrying
  its own copy of the arithmetic; `plan()` is the one projection, walking a
  night of firings against `admit()` the same way `fire()` would. The sum
  `plan()` gives back is never more than the budget it was given, for *any*
  ordering of the items — a test must prove it by permutation rather than
  trusting one order to stand for all of them. Reordering the queue moves the
  line, never the budget: the example to pin is the user's own one-keypress
  one, queue `one, two | three` becoming `one, three | two` after moving
  `three` up once — the line still falls after exactly as much as the budget
  allows, just between a different pair of names. The projection assumes
  every firing lands, which is the same bias the README already names for
  the pre-midnight window itself — Doze can still defer a firing the plan
  counted on. Two things the line cannot say on its own, and both are said
  beside it: **the item the line falls inside of** carries `· 46 MiB at 03:00`
  on its own row (`_tonight_share`, off the same projection the line is drawn
  from — `queue_screens.queue_entries` asks `tonight_plan` once and hands it
  to `cut_index` and the rows), because a resumable download above the line
  is not the same thing as one that finishes in the window; and
  **why there is nothing** is answered from as far up as it goes — a verdict
  that stops the night, then `_nothing_to_spend` where there is no budget at
  all, and only then the first item's own refusal, since with nothing to
  spend every item is refused and the first refusal blames the item for a
  portal that never answered.

## Decisions that travel with the YouTube front end (ytq)

- **`nibbles` opens the app on its Search tab.** The search is one flat
  `ytsearch` request (`⏎ Go`, ~0.1 MB), with `--extractor-args
  youtubetab:approximate_date`, which is why every age it prints is marked
  `~`. The field takes three things: words, a URL (its video sheet opens), or
  a feed word (`subs`, `wl`: the Feed and Later tabs) — `looks_like_feed` is
  asked *before* `looks_like_url` because the feed's URL passes that test too.
  Recent lists this session's searches and feeds, which reopen for free.
- **Feed and Later read themselves on first opening their tab** (~0.2 MB),
  and **every deeper look re-buys the listing**: `feed_cost` is the total,
  never the increment, and it is on the `↓ 30 more · 0.6 MB in all` button
  before anything is spent. `--playlist-end` is the whole cost argument (a
  test must pin `subs_argv` beside the search's); fewer rows back than asked
  for is the end of the feed, told apart from `SUBS_MAX` in words; the depth
  commits only on a fetch that came back (`YouTube.want` vs `.asked`, per
  list); and `bumped_place` puts the cursor on the first new row when ↓ on
  the last one asked.
- **Watch Later (`wl`) is the feed's twin** (2026-09-27). Everything that
  differs between the two signed-in lists is one `Feed` (`SUBS`,
  `WATCH_LATER`, keyed in `FEEDS`): the URL, the noun, what the end of it is
  called, and what empty means — `empty_later_advice` says *both* things an
  empty Watch Later can be, because unlike the feed it can really be empty.
  `which_feed` routes; `WL_PAGE` matches only the `/playlist?list=WL` page —
  a video opened from the list carries `&list=WL` and is that video. The two
  lists' depths are kept apart, so one list's deeper look never re-buys the
  other. The pty tests drive `wl` to a listing through a stand-in `yt_dlp`
  module on `PYTHONPATH`, which `ytdl_argv` prefers, so a real one is never
  asked.
- **The cookie is asked about before anything is spent** — `cookie_state`
  reads yt-dlp's own config with `shlex`, and refuses on a missing
  `--cookies` line or a jar not on disk. **An empty feed is never reported as
  "nothing new"** — YouTube answers a logged-out feed with no entries, and
  `empty_feed_advice` says what that means and how old the jar is; a test
  must pin that it does.
- **A format list holding nothing but 360p says why** — `withheld` reads the
  RAW formats, deliberately not `choices()`'s output, scoped to
  `ADAPTIVE_ALWAYS` because the claim is only true of YouTube. Said twice on
  purpose: a full notice once a session and `withheld_note` on every video
  sheet it applies to, measured at three widths, no `⚠` (ambiguous-width).
- **One tap opens a row** — selected, its video sheet up, its format probe
  going (~0.3 MB) — and the probe is kept for the session: closing the sheet
  does not cancel it, and the sheet opens on it at once next time. Each
  listing keeps its own `ListView` (cursor and view) for the session, and
  `ListView.settle` is what makes a restored place safe on a list that grew,
  shrank or was resized.
- **The video sheet is the formats, the confirm and the duplicate screen.**
  The tier buttons are the heights you use (`ytq.chip_heights`: set by hand in
  More, else the three you pick most, else 240/480/720) plus `audio`;
  Smallest/Largest picks inside a tier (`ytq.pick_in_tier`), passing over the
  codec families More's `skip codecs` names but never emptying a tier, and
  saying `skipped vp9` only when it passed one over that would have won. The
  rule is remembered per kind and the last format with it (`ytq.learn`, in
  `config.json`'s `ytq_prefs` and `ytq_last_format`). The size is the one
  figure, on the button; Now makes the button the one yes. A duplicate is the
  `✓` line directly above `a Queue it again anyway`, pinned with it.
- **The selected title scrolls; nothing else does, and an idle screen still
  blocks.** `marquee` holds at the start of each lap; `yt_screens.overflows`
  is the one place that decides both drawing it moving and waking to move it,
  and a screen of short titles emits **zero** bytes over two idle seconds —
  the property the loop was written for, held by a pty test.
- **A notice never loses its own way out** — what the old full-page messages
  said is a `shell.Notice` sheet whose body scrolls and whose `esc OK` is
  pinned; a sweep holds it at every size. `wrapped()` sets
  `break_on_hyphens=False` because a path broken across two lines is a path
  retyped wrong.
- **`ytq.write_item` is the one door and refuses duplicates**
  (`ytq.Duplicate`), keyed on extractor and id rather than URL; the search,
  a pasted URL, `--now`, `--from-json` and `dlq` all end there. The
  results list marks what the queue already holds — before the probe is
  spent.
- **A download is named after its title** (2026-10-10, design §6) —
  `ytq.title_name`, the title cleaned only of `/ \ : * ? " < > |` and capped
  well under 255 bytes, so `40-Crust of Rust - Subtyping and Variance.py` is
  in the queue and `Crust of Rust - Subtyping and Variance.mp4` in Downloads.
  `item_name` is the one spelling of the file name `write_item` makes, and
  Rename on a download's sheet goes through the same cleaning. ytq queues
  last; Move on the Queue tab is the only place an order is chosen.
- **`next_number` caps at `MAX_PRIORITY`** — the runner sorts file names, so
  a third digit puts an item at the front, not the back.
- **Downloading now spawns a detached `nibbles now`** (by path under the queue
  root: `HERE / "expire_sched.py"`), so ytq stays open and the download
  outlives the screen.
- **`Choice.kind` decides an item's destination** — never the file extension
  (at queue time there is no file); `ytq.dest_for` is the one place, `--dest`
  wins over both.
- **The Formats sheet's rows carry the codec family; the selected row says
  it exactly** (2026-08-28) — `Choice.codecs` keeps yt-dlp's full strings
  (`_exact_codec`, beside `_codec` which truncates for the printed columns),
  grouped by tier, smallest first, opened at the tier the video sheet was on.
  `c` on the video sheet copies the page URL through `to_clipboard`
  (termux-clipboard-set; its answer is said above the tabs).
- **A run with no stop time must never be formatted with `int()`**
  (2026-08-28, and it had been broken since long before the split). `nibbles
  now` and `run-now --blind` both set `EXPIRE_STOP_EPOCH=0` on purpose —
  they are deliberately outside the window — and `expire_dl.Env.deadline`
  spells that `+inf`. Every *comparison* against it is right; the banner's
  `int(deadline - time.time())` was not, and `int(inf)` raises. So `n` on a
  video died before a byte moved, in the line that says what it is about to
  do, leaving `unhandled error: OverflowError` in a log nobody opens — while
  file downloads through `expire_dl` worked, because that module only ever
  compares. `time_left()` is the one place that phrase is built now, and it
  says "no stop time" in words; on the screens, `shell.clock` and
  `shell.left` say it (or nothing) for an endless deadline rather than put it
  through a clock.

## Checks

`make test` = `make check` = `.githooks/checks.sh`, the one copy; the pre-push
hook runs it. It runs **two suites as two pytest processes**, `tests/ytq` and
`tests/dlq` — the two repos' suites, kept as they were — because each conftest
owns the environment and `sys.modules` for its whole session. Offline: nothing
reaches YouTube or the portal. Needs the zwana-quota and bewitch checkouts,
and a shallow clone path — a deep worktree is itself the width the screens
cannot fit.

**The pty tests stand in for Termux** (`tests/termux_pty.py`, shared by both
suites): they answer blessed's startup queries the way Termux does — a
cursor-position request with `ESC[1;1R`, a DECRQM query with `ESC[?<mode>;2$y`
— because without the first blessed waits out a five-second timeout and
without the second it never decodes a mouse report; and they send a tap as
Termux does (press and release at one cell) and a drag as wheel events stamped
with the cell it began on. pyte is taught `CSI S` and `CSI T` there too.

**Both suites run the modules out of a copy.** This checkout's own
`expire_runner` anchors its root on its own directory, which is the real queue,
so neither suite may import a module from here: each conftest copies the
modules into a temporary queue root, points `EXPIRE_HOME` and `HOME` at
temporary directories and imports (or, under a pty, executes) the copy. The ytq
conftest asserts the `ytq` it imported is the copy; the dlq conftest asserts
every root the modules spelled is the temporary one, and an autouse fixture
checks the real `config.json`, `state.json` and `queue/` are untouched.

### The queue's suite (tests/dlq)

About half a minute; `make mutants` is the slow half and is deliberately not
in it.

**The suite has one seam and it is the queue root.** Every module here anchors
to a checkout rather than to `__file__` — that is what keeps an installed `nibbles`
managing the real queue — so the only honest way to test one is to build a
checkout somewhere else and run the modules out of *it*. `tests/dlq/conftest.py`
copies this checkout's modules into a temporary directory, points
`EXPIRE_HOME` and `HOME` at it and imports them there, so `expire_runner.ROOT`,
`ytq.HERE` and every path spelled from them land under `tmp_path`. `HOME` is
what keeps the suite offline: `zwana_quota` reads its credentials from
`$HOME/zwana-quota/.env` and its cookie from `$HOME/.cache`, so with neither
there the portal call fails at the credentials, before a socket is opened —
every test that needs a reading builds one by handing raw portal figures to
`quota_widget.derive`, the function that builds the real one. The import is
done once for the session and the tree is *emptied* between tests rather than
rebuilt, because the import is the expensive part and every path the modules
spelled is a constant; an autouse fixture asserts the real `config.json`,
`state.json` and `queue/` are untouched afterwards, which is the check that a
stray `ROOT` would fail.

**A screen is checked on a screen.** The front ends *are* their screens, and
the failures worth catching there — a page that leaves when it should stay, a
sentence clipped over the keys, a move that says it happened and renames
nothing — do not show in a return value. `tests/dlq/test_screens.py` opens the
real `nibbles queue` on a pty through `termux_pty` and taps and presses what somebody
would, and asserts on the *shape*: which tab is up by its header, that a row
for a download exists, that the tabs are on their row, that a tap outside
every button changes nothing, that after Move, ↓, Put here the file on disk
has a smaller number than its neighbour. The headless half builds the real
`nibbles.App` with no terminal (`App(None, tab, size=...)`), sets its reading,
and composes it: the Queue tab's rows, the sheets' buttons and the More tab's
rows are asked of the screen that draws them. The pty tests are marked `tui`
and are most of the suite's wall clock.

**What is pinned is behaviour, never wording.** A reworded refusal, a
rearranged screen and a renamed helper are all things this code does; a test
that fails on one of them is a test that has to be rewritten to say the same
thing again. So the assertions are on properties and round-trips: the sum a
projection promises against the budget it was given, for every permutation and
over random nights (`hypothesis`); a figure spelled and parsed back; every line
of every screen fitting the terminal at any width from 32 up; every download
appearing on the listing exactly once. Where a sentence *is* the behaviour —
`admit`'s refusal, quoted word for word on the cut line — what is checked is
that there is one and that it is the same one, not what it says.

One file per guarantee, and each says which:

| file | what it pins |
|---|---|
| `test_tonight_budget.py` | the sum `plan()` promises is never more than the budget, for any ordering; every refusal `admit()` gives has a sentence on it |
| `test_gate.py` | the order `gate()` answers in — two things wrong at once, and which is reported — including where a manual budget's `unset` sits |
| `test_manual_budget.py` | a manual budget never spends past the allowance or into the reserve: the arithmetic, the ledger since the reset, `plan()` by permutation, firings in a row, `watch()` in flight, `nibbles now` charged |
| `test_budget_source.py` | the source is a setting with the runner's spec; `snapshot()` only gains keys; the runner, `status`, `settings` and `dump` run with no zwana-quota and never import it |
| `test_firing.py` | `fire()` admits through `admit()`; SIGINT and not SIGTERM; an item leads its own session |
| `test_settings.py` | a bad stored value reads as the default; a broken `config.json` is never written over; what waives the reserve |
| `test_clock.py` | the clock pinned and the timezone swept either side of the date line |
| `test_downloader.py` | `expire_dl` against a loopback server: a file smaller than one chunk is *fetched* |
| `test_listing.py` | the reader: `gone` vs `away`, and every download listed once |
| `test_ui_moves.py` | the moves and removals on a real queue: bytes never lose their item |
| `test_cut_line.py` | the cut line is computed, an entry nothing can select, and moves without moving the budget |
| `test_layout.py` | every line fits, at 32, 40, 80 and swept between; every verdict has a word and a status label; every action and every setting has its row |
| `test_cli.py` | what a bare `nibbles` does, and where each word goes — every route `nibbles` has, and that it is the only executable |
| `test_item_contract.py` | every way an item can fail to declare itself is a reason and never an exception |
| `test_in_flight.py` | the guards that act while the bytes are moving: the byte cap, the floor, the deadline, a portal gone dark — and all of them again with the interface counters dark, as on a phone |
| `test_dump.py` | `nibbles dump` finishes on the broken trees it exists for |
| `test_queue_flows.py` | the tabs' flows headless: Remove keeps the bytes unless told, Rename moves everything, a setting set from its presets, a refused value written nowhere, a broken config never written over |
| `test_screens.py` | the Queue and More tabs, on a pty |

**`make mutants` is the suite's own check.** poodle changes one operator,
literal or comparison at a time and runs the tests against it; a mutant that
survives is a line nothing was asserting anything about, which is the question
coverage cannot answer. `poodle_config.py` carries the whole arrangement and
the reasons — the flat layout, the sibling checkout a worker's copy cannot
find for itself, and the copy filters that keep this device's `state.json` and
`config.json` out of a run that exists to be independent of them. The app's
event loops (`nibbles.App.run`, `tui.Session.read`) are fenced `# nomut:
start` / `# nomut: end`: a mutant inside one does not fail a test, it hangs a
terminal until the timeout kills it, and what those loops do is checked under
a pty instead. It is a
**ratchet and never a gate** — some mutants are equivalent, and a good few are
a message reworded, which this suite declines to pin on purpose — so
`--fail_under` sits under the score already reached and goes up when the score
does. It is out of `make test` and out of the pre-push hook because it takes
hours, and a push here is a deploy.

**Where the score stands, and what is left in it.** Scoped runs, one module
against the tests that reach it, on two workers (2026-09-03):

| module | mutants | score | wall clock |
|---|---|---|---|
| `expire_runner.py` | 2045 | 55.2% → **60.4%** | ~26 min at four workers, ~48 at two |
| `expire_sched.py` | 2895 | **38.4%** | ~83 min |
| `expire_ui.py` | 2845 | **38.4%** | ~82 min |

Every one of those figures is a **lower bound on what the whole run would
say**: a scoped run puts each mutant to a subset of the suite, and `make
mutants` puts every mutant to all of it. `--fail_under` is therefore left
where it is until a whole run has actually been timed — a ratchet notch set
from a scoped number is a notch nobody has proved.

Every survivor of the runner's run was read. They fall into five heaps and
only the first was acted on:

* **A guard nothing was checking.** `watch()` — the interface cap, the floor
  projected between polls, the floor re-asked of every fresh reading, the
  deadline, and the timer on a portal gone dark — was never called by a test
  at all. It is the only guard that acts while the bytes are moving, and it is
  the last thing between a runaway `yt-dlp` and the reserve; it has a file of
  its own now. Beside it: the night's budget coming down as items spend it and
  never going up when a fresh reading says there is more; the discount on the
  expiring allowance; a whole item admitted only if it finishes with time to
  spare, finished once, and not offered again; an item's own refusal not
  stopping the queue behind it; a stall that is not a strike and a strike that
  is not the last one. In `expire_sched`: **nothing spends without a yes**, and
  what `nibbles now` says it will spend is what is left to fetch rather than the
  whole declaration.
* **A message reworded.** The largest heap by far — a third of the runner's
  survivors and better than half of `expire_sched`'s sit on a line that is a
  log line, a refusal, a notification or a drawn row. What a refusal *says* is
  free to improve, and a test that fails when it does is a test that has to be
  rewritten to say the same thing again. Where the sentence *is* the behaviour
  — `admit`'s refusal, quoted on the cut line — what is pinned is that there is
  one and that it is the same one.
* **Cosmetic.** A colour code, a column width, a label that shortens on a
  phone. `test_layout.py` pins that every line *fits*; which of two spellings
  it fits with is the layout's business.
* **Equivalent in effect.** `>` against `>=` where nothing lands on the
  boundary; a byte either side of a hundred-megabyte reserve; a second either
  side of a five-minute timer; a `break` that becomes a `continue` in a loop
  whose next test is the one that just fired; a default argument value every
  caller passes explicitly; a poll cadence, which costs a wakeup and decides
  nothing.
* **Out of that run's reach.** `read_status`'s clamp is pinned by
  `test_downloader.py` and `snapshot`'s row fields by `test_listing.py` and
  `test_cut_line.py`, neither of which is in the runner's scoped set. They are
  survivors of the *scope*, not of the suite — which is the other reason a
  scoped score reads low.

The two front ends read the same way and sit lower for the reason they should:
they are mostly presentation, and presentation is the heap this suite declines
to pin. Better than a third of `expire_sched`'s survivors and better than a
third of `expire_ui`'s are on a line that is a printed message or a drawn row,
and `String` alone is the largest mutator in both. What was worth taking out of
them was the handful of lines that decide money or lose bytes: **nothing spends
without a yes** and the figure `nibbles now` quotes is what is *left* to fetch; a
download's bytes on disk are every payload file added up; a destination that
exists is used and a missing parent is refused; the status screen's reserve line
is the reserve that applies tonight, and a waived one does not read the same as
a reserve of nothing. On the screens: the cut line falls *under* a night that
reaches exactly one download; the row the line falls inside of says how much of
it goes tonight and the rows either side say nothing; the projection is the
runner's own over the snapshot's own figures, blind flag and free disk included;
and the settings page is cut to the screen it is drawn on, giving up the blanks,
then the meanings, then the sentence, and never a row.

`expire_ui`'s survivors clustered in `draw_list`, `confirm`, `ask` and
`run_now` — the curses screens, which went with the rebuild (2026-10-10), so
that figure overstates what is left. `_reindex`'s cluster is its
parking path and its `# pragma: no cover` guard: the orders it produces are
pinned by a property test over random sequences of moves, and what survives
inside it is set algebra that a two-item cycle cannot tell apart.

The whole run is the ratchet; the way to get an *answer* about one module is a
scoped one, because the command is run once per mutant and most of the suite
does not touch most of the code. `POODLE_TESTS` narrows it, and pairs with
poodle's own `--only`:

```
POODLE_TESTS="tests/dlq/test_gate.py tests/dlq/test_tonight_budget.py" \
    uv run --group mutants poodle --only expire_runner.py
```

The three the figures above came from, so the next run is the same run:

```
POODLE_TESTS="tests/dlq/test_gate.py tests/dlq/test_tonight_budget.py tests/dlq/test_firing.py
              tests/dlq/test_settings.py tests/dlq/test_clock.py tests/dlq/test_item_contract.py
              tests/dlq/test_in_flight.py"                      --only expire_runner.py
POODLE_TESTS="tests/dlq/test_settings.py tests/dlq/test_listing.py tests/dlq/test_cli.py
              tests/dlq/test_dump.py tests/dlq/test_layout.py"      --only expire_sched.py
POODLE_TESTS="tests/dlq/test_ui_moves.py tests/dlq/test_cut_line.py
              tests/dlq/test_layout.py"                         --only expire_ui.py
```

No pty test is in any of those: they are a large share of the suite's wall
clock, and what they drive is the fenced event loop rather than anything a
mutant reaches.

Same mutants, same verdicts, a fraction of the wall clock — and a survivor
list short enough to read.

Two things that fail for reasons that are not regressions: a **long checkout
path**, because the front ends check that every line fits 32 columns and the
root is on the status screen; and a **missing zwana-quota checkout**, because
the runner imports it the same way a real run does.

### The YouTube front end's suite (tests/ytq)

`tests/ytq/conftest.py` is the hermetic half and the only place that knows the
environment. `ytq` anchors `HERE`/`QUEUE`/`DONE`/`FAILED` at **import time**,
so the pointing has to happen before the first `import ytq` anywhere: it
builds a throwaway queue root in a temp directory, **copies** this checkout's modules
into it (copies and not symlinks — `expire_runner` anchors its own root on
`Path(__file__).resolve().parent`, and a symlink resolves back to the real
checkout and its `config.json`), imports `ytq` from the copy, and points
`EXPIRE_HOME`, `ZWANA_HOME` and `$HOME` at temp directories, and
`BEWITCH_HOME` at the real bewitch checkout. An autouse fixture empties the
root between tests. The app's own modules are in the copy too, so this suite
also carries the app's pieces and its layout sweep.

The files, and what each is for:

- `test_item_bytes.py` — the metering. The merge case above all: a rename is
  not new bytes, two names for one stream are one high-water mark, the freeze
  holds the *last* figure, and a property says the count can never go down
  however the files move about.
- `test_item_firing.py` — one firing: the resuming argv, `time_left` on an
  endless deadline, which file was produced and where it goes, and the whole
  decision table (a slice too small to extract in, no time left, already
  delivered, finished, exit 0 with nothing to show, the zero-firing strikes).
  The poll loop runs on a **fake clock** (`Clock`) and a fake child, so the
  budget stop, the deadline stop and the postprocessing lift are deterministic
  and instant.
- `test_asking.py` — what is asked for and what is said before asking:
  `--flat-playlist`, `--playlist-end`, the four ways `ask` fails, the feed's
  price being the total, `next_page`'s two different sentences, the cookie
  states, and the ages that mark themselves approximate.
- `test_formats.py` — what is offered and at what cap: unsized formats hidden
  and counted, storyboards dropped, merges paired by container family, the
  3%/12% margin, `withheld` scoped to YouTube and never conflated with
  `choices`'s `unsized`, and where the cursor opens.
- `test_queue_items.py` — the one door. The item the runner has to be able to
  read (asked of `expire_runner.parse_item`), the duplicate refusal keyed on
  id and the weaker fallback on name, two-digit names, and the duplicate's
  verdict fitting the narrowest sheet.
- `test_layout.py` — the printed rows, 32 columns up, as properties: every
  row inside the terminal, the marquee filling its room exactly, wrapping
  never losing a word.
- `test_cli.py` — the paths with no terminal: the flag combinations that are
  refused, `--list --from-json` printing and writing nothing, the feed
  refusing without a cookie, `subs`/`wl` reaching the app by the one road,
  and the receipts printed after the app gives the terminal back.
- `test_app_pieces.py` — the app's pieces with no terminal: a mouse report is
  never a key, the two tap guards, the hit map, a row of buttons filling its
  width exactly, one-unit time, the phone's clock, title names, tier picks
  and the skipped codec, the learned heights, and the list's scrolloff and
  draggable bar.
- `test_app_flows.py` — the YouTube tabs' flows headless, through the real
  `nibbles.App` with no terminal: one tap opens a row and starts its probe, a
  closed sheet keeps its probe, the withheld notice once a session and on
  top, Stop closing its sheet, the button writing the item under the video's
  own name, Now as the one yes, the duplicate's answer, `q` typing into a
  focused field.
- `test_app_layout.py` — **the layout sweep** (design §8): every tab and every
  sheet at widths 32 to 80 and heights 11 to 30 — every line exactly the
  width, no two targets overlapping, buttons three rows, the pinned answers
  and `esc ×` always on screen, the five tabs always there.
- `test_screens.py` — the app under a pty through `termux_pty`, marked `tui`.
  Structure only — which tab is up, that a row for a video exists, that the
  button carries the price — never whole-line literals. It drives what costs
  nothing (the field, the cookie refusal on Feed and Later, a listing and a
  video sheet from a saved dump, Now, the duplicate line, the whole road from
  a dump to a written item) and, through a stand-in `yt_dlp`, Watch Later and
  **momentum never fetching**: a fling far past the end asks nothing, a
  rested pull asks once. **The idle-screen property is here**: a screen of
  short titles, selected or not, emits zero bytes over two seconds, and a
  selected title too long for its row does not.

Two helpers deleted with the old self-tests are back as tests rather than as
code: the shebang question (`test_the_runner_admits_what_ytq_writes` expects
exactly one objection off Termux, where the item's interpreter is not on disk)
and the json leak (`null`/`true`/`false` are valid Python *names*, so an item
holding one compiles and fails only on the night it was queued for).

#### Mutation testing (ytq's half, before the merge)

`uv run --group mutants poodle` (an optional group: a plain `uv sync` does not
install it). It changes one operator, literal or comparison at a time and
re-runs the suite; a mutant that **survives** is a line nothing was actually
asserting anything about. The score is a **ratchet, not a gate** — some
mutants cannot be killed by any test worth having, so 100% is not a target and
`--fail_under 50` is there to catch a suite going backwards. `poodle_config.py`
carries the reasons for every setting; the two that matter are
`source_folders = ["."]` (the modules are at the root, not under `src/`) and
the copy filters (poodle copies the tree per worker — and carries every
module's bytecode but the two being mutated, which halves the run).

**3133 mutants, 53.3% killed** (2026-09-03, ~65 minutes on four cores). Read
the survivor list with that number in mind: the four groups below are most of
it, and none of them is a behaviour nobody pinned — they are behaviour pinned
somewhere this run cannot see, or wording and constants that only a brittle
test could hold down. What is left over is where the next test goes.

- **the screens** (~535). `duplicate_screen`, `entry`, `message`, `app`,
  `pick`, `confirm`, `results` and the printing paths are covered by
  `test_screens.py` and `test_cli.py`, but the mutation command excludes the
  `tui` mark for runtime, so nothing in the run is there to kill them.
- **prose** (427 String mutants). poodle rewrites `"queued"` as
  `"XXqueuedXX"`, which every `in` assertion still passes. Killing those needs
  exact-equality assertions on wording, which is the brittleness this suite is
  written to avoid.
- **numbers read through their own constant** (a large share of 450). A test
  that asks `cost_band(NIGHT_BYTES)` moves with a mutated `NIGHT_BYTES`;
  pinning it would mean writing the byte count out by hand in the test.
- **equivalent** — e.g. `ceiling = max(budget // 2, budget - guard)`, whose
  first arm is unreachable while `MIN_USEFUL_SLICE` is eight times
  `GUARD_FLOOR`, and `state.pop("zero_firings", None)` whose default is never
  returned.

The event loops (`nibbles.App.run` and `tui.Session.read`, as the curses loops
in `ytq.py` were) are fenced with `# nomut: start` / `# nomut: end`, and that is
the only thing in the code that exists for the mutation run: a mutant inside
one does not fail a test, it hangs a terminal until the timeout kills it.
Those loops are checked under a pty instead, which is also why the mutation
command skips the `tui` mark — that code is not mutated and those tests are
most of the suite's wall clock.

**A surviving mutant is a question, not a failure.** Read it: either it names
a behaviour nobody pinned, and the answer is a test, or it is equivalent, and
the answer is to say so.

### Mutation testing since the merge

`poodle_config.py` is the two old configs merged, with the app's modules
added, and **it has not been run since the merge or the rebuild**: the figures
above are the two old repos', and the first whole run here sets the notch.
(The ytq figure counted the curses screens as ~535 survivors; they are gone.)
