# nibbles — working notes for Claude

Queue YouTube videos and file downloads on the phone, and fetch them with data
that would otherwise expire. **Every byte the runner spends crosses the phone's
metered mobile radio** — the whole design is about spending allowance that
would expire anyway, and never more — and the screens are built for a
40-column portrait terminal.

ytq (the YouTube front end) and dlq (the expiring-quota download queue and its
runner) were split out of the `or3` monorepo's `termux/expire/` on 2026-08-28
and **merged into this repo on 2026-10-10**, histories kept. Since the same
day they are **one package, `nibbles/`**, importing each other as
`from nibbles import ytq` (see *Published to PyPI* below for why and for the
doors left at the root). Two sibling checkouts
are left: **zwana-quota** (the portal client and quota widget the zwana budget
source reads its guard figures through; a manual budget needs none:
`$ZWANA_HOME`, a clone beside the queue root, then `~/zwana-quota`) and
**bewitch** (the Lip Gloss port every screen is drawn with: `$BEWITCH_HOME`,
beside, then `~/bewitch`; `tui._bewitch_root`, which falls back to the
installed bewitch when there is no checkout). The installed dependencies are
**blessed**, which owns the terminal, and **bewitch** from PyPI.
`home.zwana_root` is the one resolution of the zwana-quota checkout: the
runner puts it on `sys.path` and `expire_sched._zwana_root` asks it, so
`nibbles status` can name a missing checkout instead of letting an import
traceback. **`ZWANA_HOME` is a shell's variable, and the nightly job never
has it** (2026-10-16) — JobScheduler starts the launcher in Termux's own
environment, before any rc file — so `zwana_root(job=True)` answers as the
job will, and `expire_sched.job_problem` (the launcher's shebang, then a
checkout only `ZWANA_HOME` finds) is asked by `arm` before it registers and by
`status` under its screen: one function, so the two cannot disagree. A
checkout only the variable found was imported by every shell and never by the
job, which fell back to a manual budget with nothing set and spent nothing,
night after night, while `arm` succeeded and `status` showed zwana figures.
`nibbles dump` shows both answers, and the tests lay the phone's arrangement
out with a link beside the root when they want a job that works. The phone's
move from `~/dlq` + `~/ytq` to `~/nibbles` is in the README.

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
  would otherwise search for it, a bare video id being the case. **A word is
  never asked** (2026-10-16): a token shaped like one (`ytq._WORDLIKE`:
  letters, lower case after the first, hyphen-joined — `programming`) is
  refused before yt-dlp is asked, though YouTube's extractor takes any eleven
  id characters, because a probe of a mistyped word spends data; the rare real
  id of that shape is typed as `youtu.be/<id>`. yt-dlp's own words for the
  signed-in lists (`:ytsubs`, `:ytwatchlater`) go to `ytq.main` unmarked, as
  the field takes them, so they open Feed and Later instead of being probed as
  a video. The target is the first word that is no flag's value
  (`app._target`, `app.VALUE_FLAGS`), so flags may come in any order, and an
  unquoted `ytsearch:` query's words are searched in the order typed. At the
  door `--now` and `--list` are the video's flags (`app.QUEUE_VERBS` leaves
  them out); only a bare `nibbles --list` is the queue's listing. A link is
  then a page or a file (`app._url`), and goes on in one spelling whichever it
  is — its scheme added, what is not ASCII escaped (`dlq.normal_url`): a flag
  only one of them takes says which, YouTube's hosts are pages, and otherwise
  **the server's headers decide** (`dlq.kind_of`, ~1 KB; a page is what
  `expire_dl.is_page` says, the test the download puts every answer to: HTML,
  unless it is an attachment) — never the name, and an unreachable server is
  an error, not a guess. A page goes to `ytq.main`, a file to `dlq.main`.
  **A bare `nibbles` only ever opens the app**: with no terminal it says it
  needs one (the owner retired dlq's print-the-status fallback for it). **Words are
  never a search on their own**: `nibbles search WORDS` searches, and anything
  unknown is refused, because a mistyped verb that became a search would
  spend data. There is no word of nibbles' own for Feed or Later (a tap away;
  yt-dlp's two reach them, as above), and none for
  a file (`nibbles <url>` is both); dlq's raw `queue` listing is gone.
  `test_cli.py` (dlq) pins every route. The modules keep their own `main`s
  for that door and for running a file directly; `expire_sched._me()` names
  `nibbles`.
- **The layers.** `tui.py` is the one blessed `Terminal` (fullscreen, cbreak,
  hidden cursor, clicks and the wheel in SGR, bracketed paste; restored on
  Ctrl-Z, on any exception, and on SIGHUP and SIGTERM, which `Session.read`
  turns into `SystemExit`) and turns what arrives into `Key`, `Tap`, `Scroll`
  (with the cell the drag *began* on), `Paste`, `Resize` or `Done`; a mouse
  report is never a key, and **nor is a paste** (2026-10-16): unbracketed,
  every line break in one was ⏎ and the rest acted as keys on the screen
  underneath (a probe, Now, `q`). A `Paste` is one printable line
  (`tui.one_line`) and goes only to the top screen's `paste` — the Search
  field and every `FieldSheet` — and never submits. `widgets.py` is
  bewitch-only drawing — button, dock, segmented,
  checkbox, field, tab bar, status bar, sheet, dim — each returning a `Piece`
  (a Block and its tap targets), and the `HitMap` taps are looked up in (last
  composed wins); it reads no keys and is kept separable so it can move into
  bewitch. `shell.py` is what the screens share: the words (`size`, `left`,
  `clock`), the `ListView`, `Sheet`, `Confirm`, `Notice`. `app.py` is the
  loop (`App`) and the door (`nibbles.main` calls `app.main`), and imports
  `tui`, `widgets` and `shell` only inside the functions that use them: every
  word that prints must run without bewitch or blessed, and a stale bewitch
  checkout once took `status`, `arm` and `dump` down with an import
  traceback. `yt_screens.py` and `queue_screens.py` are the screens. **bewitch
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
  press and fills for one frame (`tui.PRESSED`); `App.compose` clears
  `app.pressed` once that frame is over, for the sheets too, which read it and
  stayed filled until the next tap. `tui.Guard`: every tap is
  dropped for 100 ms after a screen or sheet appears, and one on the same cell
  for the rest of the 300 ms double-tap window. The last three columns of a
  list are its bar: a tap there jumps, and a drag that starts there moves the
  thumb a row per row of finger travel, the way the finger goes
  (`ListView.bar_drag`: Termux scrolls naturally, so a finger going down
  arrives as `Scroll(-1)`). The track stands for the view's `travel()`, the
  rows above `furthest()`, so the thumb at the bottom is the last entry on
  screen; where a row of the bar is worth less than an entry, the drag goes on
  from the finger's row (`ListView.grip`) and reaches either end. The
  selection rides one item in from the edge (Helix's scrolloff,
  `ListView.ride`/`follow`).
- **Fetches run in the background, and only a deliberate act spends.** A
  search, a format probe (one tap on a row), the feed's first read on first
  opening its tab, Re-read, and the deeper look are `tui.Job`s; inside one,
  `ytq.ask` runs yt-dlp through `tui.run_child`, which hands the child to the
  job so `x` (Stop) can kill it, and outside one (the printing paths, the
  tests) it is the plain `subprocess.run` it always was (it finds the job
  through `sys.modules["nibbles.tui"]`; under the bare `tui` it never did,
  and Stop killed nothing). **`x` stops only a fetch** (2026-10-16,
  `App.stop_newest`): the newest job marked `fetch` (`tui.Job.fetch` — a
  probe, a search, a feed read), never a question to zwana or the scheduler
  started after it, which used to be the one stopped while the read went on
  spending. **Leaving the app by any road** — `q`, ctrl-c, a hangup, SIGTERM,
  an exception — cancels every job still running but the quiet hand-offs
  (`App.closing`), which kills a fetch's yt-dlp: it runs in a session of its
  own, hears no terminal signal, and fetched the whole listing for nobody.
  **The loop waits on every job whose `Done` is
  still owed** (`App.unheard`), never only the running ones: a job that
  finished while a frame was drawn was left out of the next wait, and its
  sheet spun no more and never filled (2026-10-13). A hand-off to Android —
  the clipboard, Open it — is a `quiet` job: off the loop's thread, but no
  spinner wake and not what `x` stops. **A fling's momentum
  never fetches**: the deeper look takes a tap on `↓ 30 more`, ↓ on the last
  row, or a *fresh* drag down after the list has rested at its end for
  `yt_screens.REST`; momentum is an unbroken stream of wheel events, so it can
  never produce the rest and then more (a pty test flings and then pulls).
- **An idle screen writes nothing.** Everything goes through
  `bewitch.screen.Frame`, which writes only changed lines and nothing for an
  unchanged screen, and the loop blocks in `Session.read` until something
  happens. Only a running fetch's spinner, the selected title's marquee, a
  download's progress and the status bar's countdown wake it, and only while
  they are changing (`App.next_wake`) — the countdown each second only in its
  last two minutes. **The countdown is never a moment already past**
  (2026-10-16): a reading whose moment has come (the window opening, its stop
  time), or one taken before a download ended, is asked again once, on the
  edge (`QueueModel._expired`/`_ended`); a portal that is down is asked again
  after `QueueModel.STALE`, never on every tick; and `SPENT` inside the window
  names the next window (`QueueModel.next_open`), not one already past.
- **No size is too small to draw** (2026-10-16). Below the 32×11 floor
  nothing has to fit, but every `widgets` recipe, and the bewitch ones it
  hands on, treats a width under nought as nought, because bewitch's
  `truncate_row` never returns from a negative limit: a pinch-zoomed screen
  died in a `RecursionError` and took the receipts with it. Every target is
  clipped to the screen. `test_app_layout`'s sweep draws every tab and sheet
  down to 1×1.
- **Words** (design §6): the phone's clock and never UTC (`shell.clock`; the
  runner's own `clock()` writes UTC for its log and is not shown on a screen:
  a failed row's last try is read back by `expire_runner.unstamp` and said as
  `gave up 3h ago`, where the item has no refusal of its own to say),
  no "tonight", nothing free or paid unless it is, time left in one unit
  (`shell.left`), sizes in three figures (`shell.size`, the unit and the places
  chosen by the figure as printed — `0.98 MiB`, never `1000 KiB` — KiB to
  TiB), and **one name
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
- **A direct download is the file, whole, once, or nothing** (2026-10-16).
  `expire_dl.is_page` is the one page test (`dlq.kind_of` asks it of a link,
  `fetch` of every answer). A web page where the file should be, or a client
  error that means a dead link (not 408/425/429, not a 5xx), is "not tonight"
  until it is the `MAX_REFUSALS`-th answer in a row, then a strike, with the
  part, the validators and the size untouched; a busy code, a 5xx and an
  unreachable host stay "not tonight". The cap the runner echoes back
  (`EXPIRE_TOTAL_BYTES`) bounds spending and is never a size: a body of
  unstated length is delivered where it ends, and one that runs past its
  whole cap is a strike, never delivered cut off. One 200 to a ranged request
  keeps the part; validators that differ are a re-published file (the part
  goes, nothing learned); only a second 200 in a row sets `no_range`, and any
  206 clears it. A file already in `out/<item>/` with no part is delivered,
  never bought again. A `--sha256` is cleaned to hashlib's spelling at both
  ends (`expire_dl.sha256_digest`: upper case, a `sha256:` prefix, a whole
  `sha256sum` line), and one that is not 64 hex digits is refused before a
  byte moves. `expire_dl.move_file` is the one move across
  filesystems — the download's own into `out/`, `hand_over`'s onto the
  destination and `ytdl_item.deliver`'s: a rename, else `copyfile` to a hidden name beside the target, fsync,
  rename, unlink the source; any failure removes the copy and leaves the
  source. Never `copy2`/`shutil.move`, which copy the times and the mode after
  every byte has landed, and shared storage refuses those with EPERM. A file
  `hand_over` cannot move stays in `out/`, recorded there and said on the
  phone; the destination never holds half a file.
- **A file download keeps its file's name** (2026-10-16, design §6):
  `dlq.file_name` — Content-Disposition (`filename*` first), else the link's
  last segment or, where that names no file, where it led — cleaned by
  `ytq.title_name`'s rule with its suffix kept (or one made from the media
  type), `--name` included. The item is named after its file, as a video's is
  after its title (`ytq.title_name` of the name without its suffix). **An
  item's strings read back as themselves**: both front ends write them with
  `ytq.literal` (`repr`), because `json.dumps` spelled an emoji as a
  surrogate pair that Python reads back as two lone surrogates, a name no
  file can have; items queued that way heal where their strings come in
  (`expire_dl.whole`, in `expire_dl.run` and `ytdl_item.run`). An item whose probe saw Range ignored is
  `PARTIAL: no`, so `admit()` gives it only a firing that can take all of it;
  a probe that finds a web page queues nothing.
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
- **A stop finishes stopping** (2026-10-16). `expire_runner.Interrupts` notes
  SIGINT and SIGHUP instead of raising them while the stop is carried out:
  `run_item`'s cleanup (kill the tree, charge the ledger, save), a delivery in
  progress (the copy finishes, then the run stops), `nibbles now` from the
  spawn to its last write, and `run-now`'s front end (`expire_sched.run_queue`;
  a bare `subprocess.run` SIGKILLed the runner 0.25 s into its unwinding). A
  second ctrl-c, or Pause tapped twice, used to land inside that work and skip
  the writes the first was waiting on, and a manual budget spent the bytes
  again. A hangup is the interrupt to the runner (`_hung_up`, unless SIGHUP
  was inherited ignored, as under nohup), and `deafen()` points stdout and
  stderr at `/dev/null` first, because every echo to a hung-up terminal
  raises EIO. `kill_tree` reaps the group's leader on every look; a zombie
  leader held every stop for the full ten seconds. The ledger and the item
  record are saved before `archive()`, in `fire()` and in `nibbles now`, so a
  stop or an error during the copy onto shared storage cannot lose the spend.
- **The download holds the lock** (2026-10-16). Every item inherits the
  runner's lock file (`expire_runner.holding`, `lock_fds`, `pass_fds`), and an
  `flock` belongs to the open file, so a runner or a `nibbles now` killed
  outright cannot leave the queue looking free while its item writes — the
  next `nibbles now` or forced firing used to open a second writer on the same
  `.part`. It is released by closing, never `LOCK_UN`, which would take it
  from the item too. The cost: a blind run's orphan, which has no stop time,
  is no longer reaped by the next firing (that firing cannot take the lock);
  it spends what is left of its slice and no more.
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
- **Armed means job 2400 starts this root's runner** (2026-10-16):
  `armed_script` reads job 2400's own line of `--pending`, because a
  substring `2400` was also job 12400, a forty-minute period, or job 2400 left
  starting `~/dlq`'s runner. Job 2400 starting another root's runner is "not
  armed here", so More offers Arm, which registers the id here again. `arm`,
  `cancel` and `status` answer in a sentence whatever the launcher holds and
  wherever the scheduler stops answering.
- **The printed screens measure in columns** (2026-10-16): `ytq.cols` is
  bewitch's rule spelled with the standard library, so the printing paths and
  `--status` need no bewitch; `ytq.fit` clips by it, and `expire_sched` lays
  out, pads and wraps by it, because a name keeps its title's CJK. `match()`
  asks for the name with its case before the name in any case, and the same
  for the stem, so `99-Intro.py` beside `99-INTRO.py` still leaves Download
  now (which hands `nibbles now` the exact name) one item to start.
- **`nibbles queue` is the only thing in the queue that changes anything**, and an
  item is *four* things — the file in `queue/`, the partial in `work/<item>/`,
  anything finished in `out/<item>/`, and its record in `state.json`.
  `expire_ui.belongings` is the only place that decides that; every move and
  removal is spelled from it.
- **The order is a position, never a number** — always **two digits**, because
  the runner sorts *file names*: `100` sorts before `20`. `ytq.next_number`
  caps at `MAX_PRIORITY` for the same reason (the ytq half says how it
  counts). **A move answers to the rename's collision rule** (2026-10-16) —
  `expire_ui._occupied`: a name held by `failed/`, `done/`, a leftover
  `work/` or `out/`, or a record in `state.json` is no room, because the keys
  a move hands out are the keys `next_number` handed out before, and landing
  on one made two items one (the record inherited, the finished row gone from
  the listing, or a raw "Directory not empty"). `_taken`, `do_reorder`'s fast
  path and `_reindex` (its fresh keys and its parking key) all answer to it.
  It is `ytq.names_in_use` (what `write_item` writes by) less what the
  moving items own, so a move and a write cannot disagree about a name. A stray `NN-` file that is not `NN-name.py` is listed but
  neither moved nor renamed, and a reorder leaves it its name.
- **Removing keeps what was paid for.** The confirm's keys never vary with the
  item (`removal_answers` guarantees it). A done download whose file was
  deleted removes itself, gated on `_readable` — an `os.listdir`, because
  Android's Downloads *is there* and raises before `termux-setup-storage`.
  Unreadable is `away` and left alone; only `gone` is acted on. Keeping is
  decided from the disk at the moment of the answer, never from the row the
  confirm was built from, because a confirm can stay up across a firing:
  `removal()` measures `work/`, `do_remove` measures again for what it says,
  and a delete that would take more than the answer named is refused.
- **What `n` says depends on where the phone is** —
  `expire_runner.portal_reachable`, a 1.5 s TCP connect to `ic.zwana.io`;
  the portal is on the vessel's network, so it answering *is* "on vessel
  wifi".
- **Nothing is queued twice** — items record `# SOURCE:` and `ytq.write_item`
  is the one door that refuses a duplicate; a file URL goes through it too.
- **Destinations**: `nibbles dest` holds them; the item always downloads into
  `out/<item>/` and the *runner* moves it at delivery (`hand_over`,
  `expire_dl.move_file` — shared storage is a different filesystem),
  so an unreachable destination leaves the file safe. **A destination that
  cannot be a folder reads as the default** (`dest_state`, keyed on the key
  being present, for the reason settings do): a `*_dir` that was not a string
  raised at delivery, after the bytes were spent. `set_dest` reads `default`
  as `set_setting` does, any case and spaces round it. **Admission asks the
  disk for what finishing takes** (2026-10-16, `disk_needed`, called by
  `admit`): what is left to fetch, a second whole copy for an item with a
  DEST (yt-dlp's merge output, and the delivery copy onto shared storage,
  which on a phone is the same flash), and `DISK_SPARE`; what is already on
  disk is not asked for again, and `plan()` works its one disk reading down
  by what it admits.
- **Every command line anchors to the queue root, not an installed copy** —
  `home.root()` resolves it (`$EXPIRE_HOME`, else the checkout the package
  sits in *only when it holds `queue/README.md`*, else `~/nibbles`), and
  `ytq.HERE`, `expire_sched.ROOT` and `expire_runner.ROOT` are all that one
  answer, so an installed copy still manages the real queue; the alternative
  is a nightly job firing faithfully onto an empty queue, saying nothing. The
  Installing section of `docs/download-queue.md` explains it.
- **Published to PyPI** (2026-10-10, the owner's: package it properly,
  AGPL-3.0-or-later, released from `main`). Why a package: thirteen flat
  modules would have landed in site-packages as top-level `shell`, `tui`,
  `widgets`… The wheel is `nibbles/` and the item contract
  (`queue/README.md`, force-included as `nibbles/queue-README.md`).
  **An installed copy makes its own root** — `home.ensure`, called by the
  door on every run: the contract and the launcher `~/nibbles/expire_runner.py`
  (Termux shebang, sets `EXPIRE_HOME` to its own directory, puts
  `home.SOURCE` on sys.path, runs `nibbles.expire_runner.main`), rewritten
  only while it is one of ours (`home.GENERATED`) and only when the package
  moved, and written whole or not at all (a file beside it and a rename; an
  empty launcher, which is what a cut-short write leaves, counts as ours, a
  binary one does not); never into a checkout, a root `EXPIRE_HOME` names, or
  a non-empty folder that is not a queue. Queue items put `home.SOURCE` (the
  checkout or site-packages) on sys.path and import `nibbles.ytdl_item` /
  `nibbles.expire_dl`, because the job starts them with Termux's own
  interpreter, which knows no venv; and both spawns — `run_item` and `nibbles
  now` — give every item `home.child_env()`, the package first on
  `PYTHONPATH`, so an item finds the package however it was written (a
  reinstall that moved it used to fail every queued item nightly while
  Download now worked). `nibbles now` itself is `python -m nibbles now` under
  `sys.executable` in the same environment. **The doors at the root** —
  `expire_runner.py`, `expire_sched.py`, `ytdl_item.py`, `expire_dl.py` — are
  for the phone's checkout, which predates the package: the armed job's path, items already
  queued, and `python3 expire_sched.py`. Imported, each *is* its module
  (`sys.modules[__name__]`); run, it runs `main`. They are not shipped, and
  can go once no phone has a job or an item that names them. **A release is a
  version bump landing on `main`**: `.github/workflows/release.yml` runs both
  suites (cloning bewitch and zwana-quota beside), builds, smoke-tests the
  wheel in a clean venv, publishes by trusted publishing (environment
  `pypi`, no token) and tags `v<version>`; `__version__` moves with
  `pyproject`'s (`test_install.py` holds them together). bewitch is released
  the same way and has to reach PyPI first.

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
  2026-10-10, design §10). A figure that has not moved for
  `queue_screens.STILL` (three status intervals) has no speed and no time
  left, and a resumed download is measured afresh (2026-10-16).
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
  command and the dump all print it (ytq's own preferences and last format,
  `ytq_prefs` and `ytq_last_format`, are refused the same way by
  `ytq.save_prefs`, the one write `learn` and `remember_format` make).
  `_read_config` is the one reader behind both, so a file one declines the
  other names (a config that was not UTF-8 crashed More and every setter).
  The state file is the other way round: **a `state.json` that cannot be read
  is never written over as empty** (2026-10-16) — `load_state` hands back
  `{"ledger_lost": <now>}`, so the first save after it (a firing, Put it back,
  `nibbles now`) carries "the day cannot be read, so it reads as spent" in the
  file itself until the next reset, and the bad file is copied to
  `state.json.unreadable` first. Every writer loads, changes and saves, and an
  empty state saved over the bad file was a valid one with no ledger, which a
  manual budget read as an allowance nobody had touched. Both files are
  written through `_write_whole` (a per-process temp name, fsync before the
  rename). And **whether a
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
  switch is asked in `say_blocked`, not inside `notify`. **A notification
  carries one id per thing to say** (2026-10-16): the firing's own word (ran,
  blocked) is `NOTICE`, `expire-queue`, where the newest is the one that is
  true; a malformed item, an item set aside and a file that could not reach
  its folder each have their own, per item where it is about one, so a
  firing's summary never replaces the warning it follows. And the window is a
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
  source. `portal_now` turns every failure of the asking — a timeout, a
  hang-up, a reset, a captive page, a bad shape — into a missing reading with
  its reason; only ctrl-c propagates (2026-10-16). One that escaped killed the
  running download as "runner interrupted" and took the firing down unlogged,
  so the five-minute dark timer never ran. **A manual budget spends the
  allowance, less what the runner itself moved since the last reset, less the
  reserve, less `FLOOR_MARGIN`** (`manual_spendable`) — the margin for its
  second reason, the bytes that move between two looks at a running download. What it moved is a **ledger**,
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
  Recent lists this session's searches and feeds, which reopen for free. The
  field's focus is one answer, `SearchTab.focused` (2026-10-16): tapped, or
  the keyboard up with nothing searched and no search running (`k-search`).
  The drawing, `typing` and the keys all ask it, because a field drawn focused
  while the keys went elsewhere let `q` quit and ate the `x` of `xbox`. A
  second Go or ⏎ on the same words while they are being fetched, or while
  their answer is still owed, is no second request: `SearchTab.search` keeps
  the first.
- **Feed and Later read themselves on first opening their tab** (~0.2 MB),
  and **every deeper look re-buys the listing**: `feed_cost` is the total,
  never the increment, and it is on the `↓ 30 more · 0.6 MB in all` button
  before anything is spent. `--playlist-end` is the whole cost argument (a
  test must pin `feed_argv` beside the search's); fewer rows back than asked
  for is the end of the feed, told apart from `SUBS_MAX` in words; the depth
  commits only on a fetch that came back (`YouTube.want` vs `.asked`, per
  list); and `bumped_place` puts the cursor on the first new row when ↓ on
  the last one asked. A read that fails, comes back empty or finds no cookie
  jar is said whatever is on screen (`FeedTab.failed`, 2026-10-16): before
  anything is listed it is drawn in the list's place; after, it is a Notice
  over the old rows, said when the tab is next on top with nothing over it.
  Otherwise the old rows say nothing, which is the "nothing new" an empty feed
  must never read as.
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
  reads the one user config yt-dlp reads (`user_config`: the first of its
  seven candidates that opens) with `shlex`, expanding the jar as yt-dlp's
  `expand_path` does, and refuses on a missing `--cookies` line or a jar not
  on disk; a `--cookies` line in a later file, which yt-dlp never opens, is
  named as hidden and not taken. **An empty feed is never reported as
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
  does not cancel it, and the sheet opens on it at once next time. A probe is
  `--flat-playlist --playlist-end 1` (`probe_argv`, 2026-10-16), so a link
  that is a list — a playlist, a channel, a page of embeds — is refused off
  its first page rather than after every entry was extracted in full, and
  `multi_video` is refused beside `playlist`. Each
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
  `✓` line directly above `a Queue it again anyway`, pinned with it. Heights
  set by hand can outnumber the row: it keeps the tier it is on and those
  around it (`yt_screens.around`, the audio row's rule), never narrower
  buttons. An item that cannot be written (a full phone) is a Notice over the
  kept sheet, and a Start now that cannot start says `Queued, not started`;
  neither is a crash (2026-10-16).
- **The selected title scrolls; nothing else does, and an idle screen still
  blocks.** `marquee` holds at the start of each lap; `yt_screens.overflows`
  is the one place that decides both drawing it moving and waking to move it,
  and a screen of short titles emits **zero** bytes over two idle seconds —
  the property the loop was written for, held by a pty test. `marquee` takes
  the measure `overflows` decides with (`w.string_width`), so a CJK or emoji
  title moves rather than sitting clipped while the loop wakes to move it.
- **A notice never loses its own way out** — what the old full-page messages
  said is a `shell.Notice` sheet whose body scrolls and whose `esc OK` is
  pinned; a sweep holds it at every size. `widgets.wrapped`
  (bewitch's `wrap_row`) never breaks at a hyphen, because a path broken across two lines is a path
  retyped wrong.
- **`ytq.write_item` is the one door and refuses duplicates**
  (`ytq.Duplicate`), keyed on extractor and id rather than URL; the search,
  a pasted URL, `--now`, `--from-json` and `dlq` all end there. The name
  fallback compares `same_name` (casefolded, letters and digits in any
  script), because `slugify` made every non-Latin title `video`. **It never
  replaces** (2026-10-16): a name still in use (`names_in_use`: `queue/`,
  `done/`, `failed/`, `work/`, `out/`, a state record) takes ` (2)`, ` (3)`…
  after the title, chosen under a lock in `.staging`, and a failed write leaves
  nothing staged — whatever answers to a name next inherits its partial, its
  outbox and its record. The results list marks what the queue already holds —
  before the probe is spent.
- **Outside words are cleaned once, where they come in** (2026-10-16) —
  `ytq.one_line`: every space and line break one space; every other control,
  every format character but ZWJ/ZWNJ (Termux counts them a column, bewitch
  none) and any lone surrogate dropped. `entries`, `probe` and `load_json`
  (through `cleaned`: title, channel, uploader) apply it, and `render` and
  `title_name` apply it again because they must hold whoever calls them: a
  title must never end the item's `# DESC:` comment or its docstring
  (TikTok's title is its caption, line breaks kept), nor reach the terminal
  as an escape. `title_name` maps spaces before it drops the unprintable, so
  a non-breaking space or a line break never glues two words together.
- **A download is named after its title** (2026-10-10, design §6) —
  `ytq.title_name`, the title cleaned only of `/ \ : * ? " < > |` and capped
  well under 255 bytes, so `40-Crust of Rust - Subtyping and Variance.py` is
  in the queue and `Crust of Rust - Subtyping and Variance.mp4` in Downloads.
  `item_name` is the one spelling of the file name `write_item` makes, and
  Rename on a download's sheet goes through the same cleaning. ytq queues
  last; Move on the Queue tab is the only place an order is chosen.
- **yt-dlp is never told the title** (2026-10-16). An item's yt-dlp runs in
  `work/<item>/dl` on paths relative to it (`-P home:. -P temp:`) and writes
  `ytdl_item.STEM` (`media.<ext>`); `ytdl_item.deliver` renames the finished
  file to `<title>.<ext>`. yt-dlp puts its paths and templates through
  `expandvars`/`expanduser` (no escape for `$` on POSIX) and `%`-formatting,
  and the item's directory is named after the title too, so a `$PATH` or `%(`
  in a title once sent a whole video where nothing meters or delivers. `temp`
  is pinned because `--paths` is a dictionary and the person's config (read
  on purpose) could otherwise move every partial outside the meter.
  `ytdl_item.adopt` renames partials an older firing left under the title
  onto the stem before yt-dlp starts, so they resume rather than being bought
  again. `ytdl_item.PP_MARKERS` names only postprocessors yt-dlp runs after
  the download; one that runs before it (SponsorBlock, the thumbnail
  convertor) froze the meter at nought for the whole firing. And
  `ytdl_item.scaffolding` is the one rule for what is yt-dlp's bookkeeping,
  anchored at the end of a name (`expire_sched._is_payload` asks it too), so a
  title holding `.temp.` is never taken for a merge in progress.
- **`next_number` counts `queue/` alone and caps at `MAX_PRIORITY`**
  (2026-10-16) — the runner sorts file names, so a third digit puts an item
  at the front, not the back. `done/` and `failed/` keep their numbers, and
  counting them put every item from the tenth ever at 99, run in title order.
  At the cap it has `expire_ui._reindex` deal the queue fresh keys first
  (`_make_room`), unless `busy_problem` says a firing or a download holds it.
- **Downloading now spawns a detached `nibbles now`** (`ytq.now_argv`:
  `python -m nibbles now NAME --yes` under `sys.executable`, in a session of
  its own, `home.child_env()`, the queue root its cwd), so the app stays open
  and the download outlives the screen.
- **`Choice.kind` decides an item's destination** — never the file extension
  (at queue time there is no file); `ytq.dest_for` is the one place, `--dest`
  wins over both.
- **The Formats sheet's rows carry the codec family; the selected row says
  it exactly** (2026-08-28) — `Choice.codecs` keeps yt-dlp's full strings
  (`_exact_codec`, beside `_codec` which truncates for the printed columns),
  grouped by tier, smallest first, opened at the tier the video sheet was on.
  `c` on the video sheet copies the page URL through `to_clipboard`
  (termux-clipboard-set; its answer is said above the tabs).
- **One opener, and it refuses aloud what Termux refuses in silence**
  (2026-10-16). `ytq.open_file` opens for Open it and Open it when done, and
  Open it re-reads the queue first. termux-open exits 0 once its broadcast is
  sent, so everything Termux would refuse with only a logcat line is asked
  first, of the file at the moment of opening, never of the listing: it must
  be there, readable and a file; its canonical path must be under Termux's
  files or the primary storage (`termux_serves`, the provider's own prefix
  test — an SD card is neither); and `allow-external-apps` must be `true` in
  the first of `~/.termux/termux.properties` and
  `~/.config/termux/termux.properties` that exists (`termux_shares`;
  `java_properties` is `java.util.Properties.load`, trailing blanks and all,
  so `true ` is false to Termux). Since termux-app 0.118 the provider serves
  no file to another app without it — the owner's "files won't open" — and the
  refusal names the line, the file and `termux-reload-settings`. termux-open
  is handed a `file://` URI (`file_uri`), never a bare path, because `am`
  parses it with `Uri.parse`; and because 0.118 re-parses the path into its
  content:// URI, a path holding `%`, `#` or `?` goes through a link in
  `$TMPDIR/nibbles-open/` named with full-width lookalikes (`uri_safe`).
  xdg-open keeps the plain path. A model of Android's `Uri.parse` in
  `test_queue_items.py` holds the round trip for both receivers.
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

**Both suites run the package out of a copy.** A checkout is its own queue
root, which here is the real queue, so neither suite may import a module from
here (an editable install puts this checkout on sys.path, which is why the
copy is asserted): each conftest copies the package and the root's doors into
a temporary queue root shaped like a checkout, points `EXPIRE_HOME` and `HOME` at
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
copies this checkout's package into a temporary directory, points
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
`nibbles.app.App` with no terminal (`App(None, tab, size=...)`), sets its reading,
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
| `test_tonight_budget.py` | the sum `plan()` promises is never more than the budget, for any ordering; every refusal `admit()` gives has a sentence on it; the disk an item is admitted against is what finishing it takes (`disk_needed`), never refused half-way for the room it has used, and asked the same by the line and the firing |
| `test_gate.py` | the order `gate()` answers in — two things wrong at once, and which is reported — including where a manual budget's `unset` sits |
| `test_manual_budget.py` | a manual budget never spends past the allowance or into the reserve: the arithmetic, the ledger since the reset, `plan()` by permutation, firings in a row, `watch()` in flight, `nibbles now` charged (paused twice, too); a day that could not be read stays spent through every write that follows |
| `test_budget_source.py` | the source is a setting with the runner's spec; `snapshot()` only gains keys; the runner, `status`, `settings` and `dump` run with no zwana-quota and never import it; the screens name the checkout the runner imports, and what they say the job finds is what it finds |
| `test_firing.py` | `fire()` admits through `admit()`; SIGINT and not SIGTERM; an item leads its own session; a stop (a second one, a hangup, run-now's front end) finishes stopping; the spend is on disk before delivery; the download holds the lock; both spawns hand the item the package; nothing a firing says once is replaced before it is read |
| `test_settings.py` | a bad stored value reads as the default; a broken `config.json` is never written over; what waives the reserve; whatever is in the file is read or said, never raised; a destination that cannot be a folder reads as the default |
| `test_clock.py` | the clock pinned and the timezone swept either side of the date line |
| `test_downloader.py` | `expire_dl` against a loopback server: a file smaller than one chunk is *fetched*; nothing that is not the file is delivered, and a page or a dead link three times in a row is a strike; the cap is never a size; one odd answer never condemns a download; a digest however it was pasted; `move_file` lands whole or not at all |
| `test_listing.py` | the reader: `gone` vs `away`, and every download listed once; a title never reads as bookkeeping; a name that is exactly an item's is never ambiguous |
| `test_ui_moves.py` | the moves and removals on a real queue: bytes never lose their item, a move never lands on a name something else holds, a stray neither moves nor stops a move, and a removal never deletes bytes its question did not name |
| `test_cut_line.py` | the cut line is computed, an entry nothing can select, and moves without moving the budget |
| `test_layout.py` | every line fits, at 32, 40, 80 and swept between, a wide name in the columns it takes; every verdict has a word and a status label; every action and every setting has its row |
| `test_cli.py` | what a bare `nibbles` does, and where each word goes — every route `nibbles` has, that it is the only executable, and that the words that print need none of the screens; a word shaped like an id refused, flags in any order, one spelling of a link; `arm` and `status` agree about the job; a file's name, and whether it is partial |
| `test_item_contract.py` | every way an item can fail to declare itself is a reason and never an exception |
| `test_in_flight.py` | the guards that act while the bytes are moving: the byte cap, the floor, the deadline, a portal gone dark — and all of them again with the interface counters dark, as on a phone; every way a portal poll can fail is a missing reading |
| `test_dump.py` | `nibbles dump` finishes on the broken trees it exists for, and says where the nightly job looks |
| `test_queue_flows.py` | the tabs' flows headless: Remove keeps the bytes unless told (and what a firing bought while it asked), Rename moves everything, a setting set from its presets, a refused value written nowhere, a broken config never written over; Move's hold let go when its download leaves, a tap putting it exactly there; Open it on the file as it is now; `x` following the run; a reading asked again once on its edge, a countdown never past, a stalled download with no speed, a failed row without the UTC stamp |
| `test_screens.py` | the Queue and More tabs, on a pty |
| `test_install.py` | an installed copy makes its own queue root and launcher, and writes into no checkout, no `EXPIRE_HOME` and no folder of somebody's; the launcher runs the runner in its own root, and a write of it cut short leaves the old one; the wheel ships the contract where the package looks |

**`make mutants` is the suite's own check.** poodle changes one operator,
literal or comparison at a time and runs the tests against it; a mutant that
survives is a line nothing was asserting anything about, which is the question
coverage cannot answer. `poodle_config.py` carries the whole arrangement and
the reasons — the flat layout, the sibling checkout a worker's copy cannot
find for itself, and the copy filters that keep this device's `state.json` and
`config.json` out of a run that exists to be independent of them. The app's
event loops (`app.App.run`, `tui.Session.read`) are fenced `# nomut:
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
    uv run --group mutants poodle --only nibbles/expire_runner.py
```

The three the figures above came from, so the next run is the same run:

```
POODLE_TESTS="tests/dlq/test_gate.py tests/dlq/test_tonight_budget.py tests/dlq/test_firing.py
              tests/dlq/test_settings.py tests/dlq/test_clock.py tests/dlq/test_item_contract.py
              tests/dlq/test_in_flight.py"                      --only nibbles/expire_runner.py
POODLE_TESTS="tests/dlq/test_settings.py tests/dlq/test_listing.py tests/dlq/test_cli.py
              tests/dlq/test_dump.py tests/dlq/test_layout.py"      --only nibbles/expire_sched.py
POODLE_TESTS="tests/dlq/test_ui_moves.py tests/dlq/test_cut_line.py
              tests/dlq/test_layout.py"                         --only nibbles/expire_ui.py
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

- `test_item_bytes.py` — the metering. A rename is not new bytes; a stream is
  the sum of its files at one look (a fragment in flight,
  `x.part-FragN.part`, is its stream's); a `.part` that comes back smaller was
  started over and what it holds is new; the freeze holds the *last* figure;
  `ytdl_item.scaffolding` (the one rule, anchored at the end of a name, which
  `expire_sched._is_payload` also asks) never hides a title's own bytes.
  Properties say the count never goes down, and is never less than was
  fetched nor more but for one fragment a stream.
- `test_item_firing.py` — one firing: the resuming argv, `time_left` on an
  endless deadline, which file was produced and where it goes, and the whole
  decision table (a slice too small to extract in, no time left, already
  delivered, finished, exit 0 with nothing to show, the zero-firing strikes).
  No title reaches what yt-dlp expands, the file arrives under the title
  whatever it is, partials left under a title are resumed rather than bought
  again, a temp path in the config cannot move them, and a postprocessor that
  runs before the download is not the end of it. The poll loop runs on a
  **fake clock** (`Clock`) and a fake child, so the budget stop, the deadline
  stop and the postprocessing lift are deterministic and instant.
- `test_asking.py` — what is asked for and what is said before asking:
  `--flat-playlist`, `--playlist-end`, the probe bounded to a list's first
  page, a word never asked of yt-dlp, the four ways `ask` fails, the feed's
  price being the total, `next_page`'s two different sentences, the cookie
  states and the one user config yt-dlp reads, the ages that mark themselves
  approximate, and the upgrade line (a uv receipt's extras and pins, a
  self-updating release).
- `test_formats.py` — what is offered and at what cap: unsized formats hidden
  and counted, storyboards dropped, merges paired by container family, the
  3%/12% margin, `withheld` scoped to YouTube and never conflated with
  `choices`'s `unsized`, and where the cursor opens.
- `test_queue_items.py` — the one door. The item the runner has to be able to
  read (asked of `expire_runner.parse_item`), the duplicate refusal keyed on
  id and the weaker fallback on name (any script), two-digit names, and the
  duplicate's verdict fitting the narrowest sheet. No title or id ever reaches
  the item as code; nothing is written over; downloads run in the order
  queued; a broken `config.json` is never written over by `learn`; the
  opener's refusals, and its URI round trip through a model of Android's
  `Uri.parse`.
- `test_layout.py` — the printed rows, 32 columns up, as properties: every
  row inside the terminal, the marquee filling its room exactly, wrapping
  never losing a word; a column counted as the screens count it, wide titles
  scrolling in columns, and a title from outside drawn on its own row.
- `test_cli.py` — the paths with no terminal: the flag combinations that are
  refused, `--list --from-json` printing and writing nothing, the feed
  refusing without a cookie, `subs`/`wl` reaching the app by the one road,
  the search's words one search wherever a flag falls, and the receipts
  printed after the app gives the terminal back.
- `test_app_pieces.py` — the app's pieces with no terminal: a mouse report or
  a paste is never a key (a paste arrives as one printable line), the two tap
  guards, the hit map, a row of buttons filling its width exactly, nothing
  drawn in less than nothing, one-unit time, sizes in three figures that read
  back as themselves, the phone's clock, title names (words never glued
  together), outside words one line and drawable, tier picks and the skipped
  codec, the learned heights, and the list's scrolloff and a bar that follows
  the finger to either end.
- `test_app_flows.py` — the YouTube tabs' flows headless, through the real
  `nibbles.app.App` with no terminal: one tap opens a row and starts its probe, a
  closed sheet keeps its probe, the withheld notice once a session and on
  top, Stop closing its sheet, the button writing the item under the video's
  own name, Now as the one yes, the duplicate's answer, `q` typing into a
  focused field. The field's focus acting as drawn, a second Go buying
  nothing, `x` stopping a fetch and never a question asked after it, leaving
  stopping every fetch, a paste typed and never submitted, a pressed button
  on a sheet unfilled after one frame, a feed failure said over a listing, a
  full phone said, and what the door hands the app landing where the field
  would.
- `test_app_layout.py` — **the layout sweep** (design §8): every tab and every
  sheet at widths 32 to 80 and heights 11 to 30 — every line exactly the
  width, no two targets overlapping, buttons three rows, the pinned answers
  and `esc ×` always on screen, the five tabs always there, hand-set quality
  chips never squeezing a tier button — and below the floor, down to 1×1, the
  screen's own size with every target on it.
- `test_screens.py` — the app under a pty through `termux_pty`, marked `tui`.
  Structure only — which tab is up, that a row for a video exists, that the
  button carries the price — never whole-line literals. It drives what costs
  nothing (the field, the cookie refusal on Feed and Later, a listing and a
  video sheet from a saved dump, Now, the duplicate line, the whole road from
  a dump to a written item) and, through a stand-in `yt_dlp`, Watch Later and
  **momentum never fetching**: a fling far past the end asks nothing, a
  rested pull asks once. **The idle-screen property is here**: a screen of
  short titles, selected or not, emits zero bytes over two seconds, and a
  selected title too long for its row does not. A paste is typed into the
  field and never submits, nothing the app started to fetch outlives it, and
  a drag on the bar carries the thumb the way the finger goes.

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

The event loops (`app.App.run` and `tui.Session.read`, as the curses loops
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
