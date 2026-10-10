# nibbles — working notes for Claude

Queue YouTube videos and file downloads on the phone, and fetch them with data
that would otherwise expire. **Every byte the runner spends crosses the phone's
metered mobile radio** — the whole design is about spending allowance that
would expire anyway, and never more — and the screens are built for a
40-column portrait terminal.

ytq (the YouTube front end) and dlq (the expiring-quota download queue and its
runner) were split out of the `or3` monorepo's `termux/expire/` on 2026-08-28
and **merged into this repo on 2026-10-10**, histories kept. The modules are
flat at the root and import each other by bare name; the only sibling checkout
left is **zwana-quota** (the portal client and quota widget the zwana budget
source reads its guard figures through; a manual budget needs none):
`$ZWANA_HOME`, a clone beside this repo, then `~/zwana-quota`. `expire_sched._zwana_root` predicts the runner's resolution so
`dlq status` can name a missing checkout instead of letting an import
traceback. The phone's move from `~/dlq` + `~/ytq` to `~/nibbles` is in the
README.

## The rebuild in progress, and its spec

Both screens are being rebuilt as **one buttons-first app on blessed**, drawn
by bewitch (a sibling checkout: `$BEWITCH_HOME`, a clone beside this repo,
then `~/bewitch`). **`design/` is the spec**: `design/design.md` holds every
decision the owner made, and `design/mockups/` holds the mockups, rendered
from `design/mock/` with bewitch's own recipes, keyboard down and keyboard up.

- **Follow the mockups very closely.** Layout, wording, glyphs, colours by
  role, button sizes and what gives way first are all decisions, not
  suggestions.
- **Diverging needs the owner's approval.** If something in the spec cannot
  be built as drawn, or a better shape turns up, ask first. If the owner does
  not answer and the work would stall, diverge, and record it in
  `design/divergences.md` — what the spec said, what was built instead, and
  why — so the owner can approve it or send it back later. A divergence not
  in that file is a bug.
- The decisions below describe the screens as they are **today**; where the
  spec replaces one (two hint sets, "a flick scrolls; only a keypress spends",
  the four-screen ytq, the listing's legend row, `p spot`), the spec wins once
  the rebuild lands, and the note goes when its code does.

## Decisions that travel with the queue (dlq)

- **`dlq` typed on its own opens the screen** — `default_action`, whose other
  half is the half to keep pinned: with no terminal (a pipe, a script, ssh
  with no tty) it is `status`, which is what a bare `dlq` always printed.
- **`dlq <url>` queues a direct file download**, uniform with `ytq <url>`
  (2026-08-28; it was a separate `dlq` command, then briefly a verb). A URL
  is routed before the verbs — no verb contains `://` — and `dlq.py` keeps
  its own module and flags; the dispatch in `expire_sched.main`
  is only the door.
- **The listing is the whole queue.** The old second-level queue screen is
  gone (2026-09-02) — `dlq`'s listing is the only screen there is, and its
  legend keys (`n` run now, `s` settings, `l` runner log) and the settings
  page's (`d` destinations, `j` arm/cancel) reach everything that screen used
  to. Every verb that lives at both ends is still **one function called by
  both** — `do_arm`, `do_cancel`, `set_dest`, `queue_run_argv` — because a
  screen and a command that disagree about whether arming worked leave
  nobody able to tell. It is also **ytq's screen**: `pick_place` is this
  listing holding a phantom — a video not written yet, drawn and *planned*
  through the same `preview`/`tonight_plan`/`cut_index`/`compose_rows` the
  main screen uses (`holding` is the one held-item loop, `m` and the picker
  both), so the cut line answers with the new item counted in the place it is
  being dragged to; it writes nothing, and `place` takes the place afterwards
  through `do_reorder`.
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
- **`dlq run-now --blind`** is the bargain when `ic.zwana.io` cannot be
  reached at all: every guard the runner carries is a portal figure, so a
  blind run has none and is bounded by what the items declared
  (`blind_budget`, called by the front end rather than re-derived). **Nothing
  interrupts a blind download for the time** — a run cut short would only buy
  the same bytes again; `NO_DEADLINE` is the one spelling of "no stop time".
  A blind run that finds the portal up is an ordinary run with the floor
  intact.
- **`dlq status` leads with the verdict**, and the verdict is
  `expire_runner.gate()` — the same function the firing gates on, so a screen
  saying "waiting for the window" cannot be a night the runner stopped for
  some other reason. A test must pin the *order* the gate answers in.
- **`dlq ui` is the only thing in the queue that changes anything**, and an
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
  is the one door that refuses a duplicate; `dlq` goes through it too.
- **Destinations**: `dlq dest` holds them; the item always downloads into
  `out/<item>/` and the *runner* moves it at delivery (`shutil.move`, never a
  rename — shared storage is a different filesystem), so an unreachable
  destination leaves the file safe.
- **Both commands anchor to the checkout, not an installed copy** —
  `ytq._root()` resolves the queue root (`$EXPIRE_HOME`, else this file's own
  directory *only when it holds `queue/README.md`*, else `~/nibbles`) and `dlq`
  takes the same answer, so an installed copy still manages the real queue;
  the alternative is a nightly job firing faithfully onto an empty queue,
  saying nothing. The Installing section of `docs/download-queue.md` explains it.

- **A flick scrolls; only a keypress spends** (2026-08-28). The listing
  takes wheel events — which is what Termux turns a touch drag into — through
  `ytq.enable_touch_scroll`/`ytq.read_wheel` (one copy, in ytq): the cursor
  in the list, the held item's position while moving. Wheels only, on
  purpose: a tap must never press a key on a screen whose keys fire
  downloads.
- **One reading feeds the word, the figures and the bar** (2026-08-28). The
  item screen showed a download's size twice — the head from `row["have"]`,
  counted off the disk when the listing was read, and the foot from the
  download's own `.status.json`, read fresh at draw time — so a second apart
  they disagreed and nothing said which was stale. `item_screen` now asks
  once per draw and hands the same reading to `_with_live` (head) and
  `progress_bar` (foot), and the foot is a bar rather than a second copy of
  the numbers. A live line naming a *different* item stays: that is the only
  place that says so. Two rules travel with it: **`where` is the directory,
  not the activity** — an item being downloaded is still in `queue/`, which
  is why the head said "queued" over a download in flight, so the word is
  now chosen by `Queue.downloading` while `where` goes on deciding
  everything else; and **an unstated total is never invented**, because
  `_of` prints the declared cap with a `≤` until a server states a size.
  The bar is `=` against `·` like `quota_widget`'s, never block glyphs —
  they are East-Asian ambiguous width and a phone may draw them double.
- **`dlq dump [NAME]` is the bug report** (2026-08-28): environment, how the
  queue root and zwana-quota resolved, gate verdicts, state rows, failing
  items' heads and the newest logs, every section guarded so it finishes on
  the broken trees it exists for. (The `ytdl_item.py` shim pre-split items
  imported off the queue root went with the merge: the real module is at the
  queue root now.)
- **`dlq settings` / `s` on the main screen** (2026-09-02): the window, the
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
  reserve on its way past — `dlq settings` and `dlq dump` name what they
  declined instead. **A change stays on the page and is said there**: the
  screen used to return on the first one, which put somebody back on the
  listing they had not asked for, one keypress into a page of six settings,
  with the change's own sentence — 67 columns of it — clipped onto the row the
  legend keys sit on. Both pages stay now, redraw, and say what happened in a
  **said area** under the rows (`said_lines`, wrapped, in the flash tone); the
  foot goes on carrying the hints and nothing but each screen's own one-line
  refusals, so no sentence is ever both clipped and whole. What comes back is
  the **receipts** — a list, `dest_screen`'s handed up to `settings_screen`
  and `settings_screen`'s extending the listing's — and the tonight reading is
  re-asked once, on the way out, rather than at every change. **Reading a
  broken `config.json` is forgiving; writing over one is refused** —
  `load_config` answers a file that will not parse with an empty dict, so a
  save on top of it would be a fresh file holding only the new key, with the
  destinations and the other settings gone under a line saying it worked.
  `config_problem` is the one line that says so:
  `set_setting` and `set_dest` refuse with it and write nothing, and both
  screens and the dump print it. Six settings do not fit a 20-row phone, so
  `settings_body` — the one rule, checked rather than trusted — gives up the
  blank lines between the blocks first, then the grey line saying what each
  setting means, and last the said area, never a setting's name, its value or
  a red line naming a stored value being ignored. The said area goes last of
  the three and not first: dropping it first would leave the 20-row phone that
  most needs the sentence the one screen that never shows it. And **whether a
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
  off leaves the log line and `dlq status` exactly as they were, and the
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
  lazily, by `_qw()`**, so the runner, `dlq status`, `dlq settings` and `dlq
  dump` run on a phone with no zwana-quota at all, and the four presentation
  helpers the front ends borrowed off `runner.qw` (`Paint`, `countdown`,
  `since`, `grade`) are the runner's now, taken from `quota_widget` when it
  is there. `root_problem` names a missing checkout only when zwana is the
  source. **A manual budget spends the allowance, less what the runner itself
  moved since the last reset, less the reserve, less `FLOOR_MARGIN`**
  (`manual_spendable`) — the margin for its second reason, the bytes that move
  between two looks at a running download. What it moved is a **ledger**,
  `state["spent"]`, `[epoch, bytes]` entries written by `note_spent` after
  every item `fire()` runs *and* every `dlq now`, kept for both sources so a
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
  nothing. `watch()`, an interrupted run, `fire()`'s ledger and `dlq now` all
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
  so `--blind` never flies on one, and `dlq run-now --blind` on a manual
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
  row nobody should have to read past, and it is what keeps the old settings
  page whole at 40×14 — seven settings and two page rows, with the blank under
  the title given up below 16 rows. The command line and the dump still list
  every setting. The owner approved the rebuild's More rows and window card
  for a manual budget on 2026-10-10; `design/divergences.md` has them.
- **The cut line in the queued list is computed, never an item** (2026-09-02).
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
  beside it: **the item the line falls inside of** carries `· 46 MiB tonight`
  on its own row (`_tonight_share`, off the same projection the line is drawn
  from — one plan per draw, handed to both — and on a line of its own where a
  phone cannot hold it beside the figures), because a resumable download
  above the line is not the same thing as one that finishes tonight; and
  **why there is nothing** is answered from as far up as it goes — a verdict
  that stops the night, then `_nothing_to_spend` where there is no budget at
  all, and only then the first item's own refusal, since with nothing to
  spend every item is refused and the first refusal blames the item for a
  portal that never answered.

## Decisions that travel with the YouTube front end (ytq)

- **`ytq` is a four-screen curses app**: search, results, formats, confirm.
  The search is one flat `ytsearch` request — the only place it spends data
  unasked — with `--extractor-args youtubetab:approximate_date`, which is why
  every age it prints is marked `~`.
- **The entry field's third answer is `subs`, the subscription feed** —
  `looks_like_feed` is asked *before* `looks_like_url` because the feed's URL
  passes that test too. It is not a fifth screen: `results()` draws both.
  `--playlist-end` is the whole cost argument (a test must pin `subs_argv`
  beside the search's); **↓ at the last row goes further back and every look
  re-buys the listing** (2026-08-28: the down arrow is the only key that asks
  — the `m` alias it took over from is gone; `feed_cost` is the total, never
  the increment, and `feed_meta` puts it on screen before the key is pressed);
  fewer rows back than asked for is the end of the feed, told apart from
  `SUBS_MAX` in words; the depth commits only on a fetch that came back
  (`subs_want` vs `subs_asked`).
- **Watch Later (`wl`) is the feed's twin, not another screen** (2026-09-27).
  Everything that differs between the two signed-in lists is one `Feed`
  (`SUBS`, `WATCH_LATER`, keyed in `FEEDS`): the URL, the banner, the noun,
  what the end of it is called, and what empty means — `empty_later_advice`
  says *both* things an empty Watch Later can be, because unlike the feed it
  can really be empty. `which_feed` routes; `looks_like_feed` is it as a bool,
  still asked before `looks_like_url`. `WL_PAGE` matches only the
  `/playlist?list=WL` page — a video opened from the list carries `&list=WL`
  and is that video. The app's `subs_asked`/`subs_want` are per list, so one
  list's deeper look never re-buys the other. `later_argv` is pinned beside
  `subs_argv`; the pty test drives `wl` to a listing through a stand-in
  `yt_dlp` module on `PYTHONPATH`, which `ytdl_argv` prefers, so a real one is
  never asked.
- **The cookie is asked about before anything is spent** — `cookie_state`
  reads yt-dlp's own config with `shlex`, and refuses on a missing
  `--cookies` line or a jar not on disk. **An empty feed is never reported as
  "nothing new"** — YouTube answers a logged-out feed with no entries, and
  `empty_feed_advice` says what that means and how old the jar is; a test
  must pin that it does.
- **A format list holding nothing but 360p says why** — `withheld` reads the
  RAW formats, deliberately not `choices()`'s output, scoped to
  `ADAPTIVE_ALWAYS` because the claim is only true of YouTube. Said twice on
  purpose: a full notice once a session and `withheld_note` on every list it
  applies to, measured at three widths, no `⚠` (ambiguous-width).
- **The results screen hands its place back** — `results` takes and returns
  `(cursor, top)`, keyed by query, and `viewport` is what makes a restored
  place safe on a list that grew, shrank or was resized, and it wants a test
  driving a spread of restores. `←`/`→` alias page up/down and are in neither hint set — no room
  at 38 columns; `docs/ytq.md` carries them.
- **The selected title scrolls; nothing else does, and an idle screen still
  blocks.** `marquee` holds at the start of each lap; `title_room` is the one
  place that decides both drawing and waking, and a screen of short titles
  emits **zero** bytes over three idle seconds — the property the loop was
  written for.
- **`message()` may never lose its own way out** — `message_body` is pure and
  bounded, says what it dropped, and every notice is measured against 40x24
  whole. `wrapped()` sets `break_on_hyphens=False` because a path broken
  across two lines is a path retyped wrong.
- **Two hint sets** — `HINTS` at 38 columns and `TIGHT_HINTS` at 30 — because
  a hint clipped at the floor is usually the way out that got clipped.
- **`ytq.write_item` is the one door and refuses duplicates**
  (`ytq.Duplicate`), keyed on extractor and id rather than URL; the search,
  a pasted URL, `--now`, `--from-json` and `dlq` all end there. The
  results list marks what the queue already holds — before the probe is
  spent.
- **`p` on the confirm screen is dlq's listing, not a copy of it**
  (2026-09-02). The video does not exist yet, so `expire_ui.pick_place` holds a
  phantom row and gives back a **position**; ytq writes the item last exactly
  as it always did and then asks `expire_ui.place` to put it there, so the
  numbering rule, the cut line and the refusal all stay on dlq's side and
  nothing is renamed before the file exists. **`expire_ui` is imported inside
  the key handler and never at module top** — it binds `ytq._addstr` while it
  loads, and at ytq's top that name is 1800 lines away: expire_ui imports
  expire_sched, which imports this half-built module back, so the screen would
  die at the import rather than at the key. `item_name` is the one spelling of
  the name `write_item` makes, because a picker handed a second f-string is
  holding a file nobody writes. A number typed with `e` and a place picked with
  `p` are exclusive and the row shows the one in force; `n` drops the place,
  because what starts now runs from the file under the name it was written
  with. A refused move is a receipt line, never a traceback and never a retry.
- **`next_number` caps at `MAX_PRIORITY`** — the runner sorts file names, so
  a third digit puts an item at the front, not the back.
- **Downloading now spawns a detached `dlq now`** (by path under the queue
  root: `HERE / "expire_sched.py"`), so ytq stays open and the download
  outlives the screen.
- **`Choice.kind` decides an item's destination** — never the file extension
  (at queue time there is no file); `ytq.dest_for` is the one place, `--dest`
  wins over both.
- **The format list's columns carry the codec family; the selected row says
  it exactly** (2026-08-28) — `Choice.codecs` keeps yt-dlp's full strings
  (`_exact_codec`, beside `_codec` which truncates for the columns) and the
  formats screen draws them for the cursor row alone on the line above the
  hints. `c` there copies the page URL through `to_clipboard`
  (termux-clipboard-set; its answer flashes on the same line), and the fetch
  wait is `spinner_while`'s box over the calling screen, never a page of its
  own — nothing erases, so the results stay visible behind it.

- **A flick scrolls; only a keypress spends** (2026-08-28). The results and
  formats screens take wheel events — what Termux turns a touch drag into —
  via `enable_touch_scroll` (wheels only: a tap must never press a key, and
  some keys here spend data) and `read_wheel`/`wheel_step`, which dlq's
  screen imports rather than re-spelling. The wheel deliberately does NOT
  trigger the feed's deeper look at the bottom: ↓ is a decision, a flick is
  momentum. And the deeper look completes the ↓ that asked for it —
  `bumped_place` steps the cursor onto the first new row once the longer
  listing lands.
- **A run with no stop time must never be formatted with `int()`**
  (2026-08-28, and it had been broken since long before the split). `dlq
  now` and `run-now --blind` both set `EXPIRE_STOP_EPOCH=0` on purpose —
  they are deliberately outside the window — and `expire_dl.Env.deadline`
  spells that `+inf`. Every *comparison* against it is right; the banner's
  `int(deadline - time.time())` was not, and `int(inf)` raises. So `n` on a
  video died before a byte moved, in the line that says what it is about to
  do, leaving `unhandled error: OverflowError` in a log nobody opens — while
  file downloads through `expire_dl` worked, because that module only ever
  compares. `time_left()` is the one place that phrase is built now, and it
  says "no stop time" in words.

## Checks

`make test` = `make check` = `.githooks/checks.sh`, the one copy; the pre-push
hook runs it. It runs **two suites as two pytest processes**, `tests/ytq` and
`tests/dlq` — the two repos' suites, kept as they were — because each conftest
owns the environment and `sys.modules` for its whole session. Offline: nothing
reaches YouTube or the portal. Needs the zwana-quota checkout, and a shallow
clone path — a deep worktree is itself the width the screens cannot fit.

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
to a checkout rather than to `__file__` — that is what keeps an installed `dlq`
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
nothing — do not show in a return value. `tests/dlq/test_screens.py` and
`tests/dlq/test_settings_screen.py` open the real `dlq ui` on a pty and read it
back through `pyte`, and assert on the *shape*: which screen is up by its title
bar, that a row for a download exists, that the legend keys are on the key row,
that after `m ↓ ⏎` the file on disk has a smaller number than its neighbour.
`pyte` answers neither `CSI S` nor `CSI T`, which is how ncurses scrolls a
region to reuse lines, so `tests/dlq/_pty.py` teaches it both: without them the
emulator keeps text a terminal has already scrolled away and the assertions
read a page nobody was ever shown. They are marked `tui` and are most of the
suite's wall clock.

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
| `test_manual_budget.py` | a manual budget never spends past the allowance or into the reserve: the arithmetic, the ledger since the reset, `plan()` by permutation, firings in a row, `watch()` in flight, `dlq now` charged |
| `test_budget_source.py` | the source is a setting with the runner's spec; `snapshot()` only gains keys; the runner, `status`, `settings` and `dump` run with no zwana-quota and never import it |
| `test_firing.py` | `fire()` admits through `admit()`; SIGINT and not SIGTERM; an item leads its own session |
| `test_settings.py` | a bad stored value reads as the default; a broken `config.json` is never written over; what waives the reserve |
| `test_clock.py` | the clock pinned and the timezone swept either side of the date line |
| `test_downloader.py` | `expire_dl` against a loopback server: a file smaller than one chunk is *fetched* |
| `test_listing.py` | the reader: `gone` vs `away`, and every download listed once |
| `test_ui_moves.py` | the moves and removals on a real queue: bytes never lose their item |
| `test_cut_line.py` | the cut line is computed, drawn as a heading, and moves without moving the budget |
| `test_layout.py` | every line fits, at 32, 40, 80 and swept between |
| `test_cli.py` | what a bare `dlq` does, and where each word goes |
| `test_item_contract.py` | every way an item can fail to declare itself is a reason and never an exception |
| `test_in_flight.py` | the guards that act while the bytes are moving: the byte cap, the floor, the deadline, a portal gone dark — and all of them again with the interface counters dark, as on a phone |
| `test_dump.py` | `dlq dump` finishes on the broken trees it exists for |
| `test_screens.py`, `test_settings_screen.py` | the two screens, on a pty |

**`make mutants` is the suite's own check.** poodle changes one operator,
literal or comparison at a time and runs the tests against it; a mutant that
survives is a line nothing was asserting anything about, which is the question
coverage cannot answer. `poodle_config.py` carries the whole arrangement and
the reasons — the flat layout, the sibling checkout a worker's copy cannot
find for itself, and the copy filters that keep this device's `state.json` and
`config.json` out of a run that exists to be independent of them. The curses
event loops in `expire_ui.py` are fenced `# nomut: start` / `# nomut: end`: a
mutant inside one does not fail a test, it hangs a terminal until the timeout
kills it, and what those loops do is checked under a pty instead. It is a
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
  what `dlq now` says it will spend is what is left to fetch rather than the
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
without a yes** and the figure `dlq now` quotes is what is *left* to fetch; a
download's bytes on disk are every payload file added up; a destination that
exists is used and a missing parent is refused; the status screen's reserve line
is the reserve that applies tonight, and a waived one does not read the same as
a reserve of nothing. On the screens: the cut line falls *under* a night that
reaches exactly one download; the row the line falls inside of says how much of
it goes tonight and the rows either side say nothing; the projection is the
runner's own over the snapshot's own figures, blind flag and free disk included;
and the settings page is cut to the screen it is drawn on, giving up the blanks,
then the meanings, then the sentence, and never a row.

`expire_ui`'s remaining survivors cluster in `draw_list`, `confirm`, `ask` and
`run_now` — the curses screens, whose event loops are fenced but whose drawing
is not, and which are checked under a pty instead. `_reindex`'s cluster is its
parking path and its `# pragma: no cover` guard: the orders it produces are
pinned by a property test over random sequences of moves, and what survives
inside it is set algebra that a two-item cycle cannot tell apart.

The whole run is the ratchet; the way to get an *answer* about one module is a
scoped one, because the command is run once per mutant and most of the suite
does not touch most of the code. `POODLE_TESTS` narrows it, and pairs with
poodle's own `--only`:

```
POODLE_TESTS="tests/dlq/test_gate.py tests/test_tonight_budget.py" \
    uv run --group mutants poodle --only expire_runner.py
```

The three the figures above came from, so the next run is the same run:

```
POODLE_TESTS="tests/dlq/test_gate.py tests/test_tonight_budget.py tests/test_firing.py
              tests/dlq/test_settings.py tests/test_clock.py tests/test_item_contract.py
              tests/dlq/test_in_flight.py"                      --only expire_runner.py
POODLE_TESTS="tests/dlq/test_settings.py tests/test_listing.py tests/test_cli.py
              tests/dlq/test_dump.py tests/test_layout.py"      --only expire_sched.py
POODLE_TESTS="tests/dlq/test_ui_moves.py tests/test_cut_line.py
              tests/dlq/test_layout.py"                         --only expire_ui.py
```

`test_settings_screen.py` is deliberately not in the third of those: it is a
pty test, it is a large share of the suite's wall clock, and what it drives is
the fenced event loop rather than anything a mutant reaches.

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
`EXPIRE_HOME`, `ZWANA_HOME` and `$HOME` at temp directories. An autouse
fixture empties the root between tests.

The eight files, and what each is for:

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
  id and the weaker fallback on name, two-digit names, and the picker's
  write-then-place path with `expire_ui.place` stubbed — the stub checks the
  file is on disk *before* dlq is asked to move it.
- `test_layout.py` — the widths, 32 columns up, as properties: every hint set
  in its stated room, every row inside the terminal, `viewport` always handing
  back a place the screen draws, `message_body` never growing past its own way
  out, and the marquee filling its room exactly.
- `test_cli.py` — the paths with no terminal: the flag combinations that are
  refused, `--list --from-json` printing and writing nothing, the feed
  refusing without a cookie, and the receipts printed after curses is gone.
- `test_screens.py` — the curses screens under a pty, read back with `pyte`.
  Marked `tui`. Structure only — which screen is up, that a row for a video
  exists, that the hint line still names a way out — never whole-line
  literals. Arrows go as `\x1bOA`/`\x1bOB` because keypad mode is on. It
  drives what costs nothing: the entry field, the cookie refusal, a listing
  and a format list from a saved dump, the confirmation, and the whole road
  from a dump to a written item. **The idle-screen property is here**: a
  screen of short titles emits zero bytes over two seconds and one with a
  title too long for its room does not.

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

The curses event loops in `ytq.py` are fenced with `# nomut: start` /
`# nomut: end`, and that is the only thing in the code that exists for the
mutation run: a mutant inside one does not fail a test, it hangs a terminal
until the timeout kills it. Those loops are checked under a pty instead, which
is also why the mutation command skips the `tui` mark — that code is not
mutated and those tests are most of the suite's wall clock.

**A surviving mutant is a question, not a failure.** Read it: either it names
a behaviour nobody pinned, and the answer is a test, or it is equivalent, and
the answer is to say so.

### Mutation testing since the merge

`poodle_config.py` is the two old configs merged, and **it has not been run
since the merge**: the figures above are the two old repos', and the first
whole run here sets the notch.
