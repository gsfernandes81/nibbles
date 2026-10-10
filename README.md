# nibbles

Queue YouTube videos and file downloads on your phone, and fetch them with data
that would otherwise expire.

The phone's data plan grants free data daily and wipes whatever is unused at
the daily reset. In the window before that reset (an hour, by default), a
scheduled job spends the leftover on downloads queued here, always leaving a
floor for the morning (100 MB, by default) and never touching the paid
reserve. Everything says what it costs before it spends anything.

How much there is to spend comes from a **budget source**: the zwana crew
portal (the default wherever the zwana-quota checkout is there), or a manual
daily allowance and reset time for a plan with no portal, spent down from the
runner's own count of what it moved. `budget` on the More tab chooses (or
`nibbles settings budget`);
`docs/download-queue.md` has the section on both.

ytq and dlq were two repos until 2026-10-10; this is both of them, with their
histories, and **one app**: five tabs along the bottom — Search, Feed, Later,
Queue, More — with buttons first and keys second, laid out for a phone in
portrait. A tap on a button acts, a drag scrolls, and anything that spends data
says what it costs on the button that spends it.

**`nibbles` is the one command** (`nibbles help` lists it all). It installs
no `ytq` or `dlq`, so an old install of either can stay on PATH beside it
until the move below is done.

- **`nibbles`** opens the app on Search; off a terminal it prints the status.
  `nibbles subs`, `wl`, `queue` or `more` open another tab.
- **The YouTube half** (ytq's words): `nibbles search crust of rust` searches,
  `nibbles <url>` opens that video, `--now` starts it, and `nibbles --list …`
  prints with no screen at all. `docs/ytq.md` is the guide.
- **The queue** (dlq's words): `nibbles file <url>` queues a plain file URL,
  and every verb (`status`, `list`, `settings`, `arm`, `run-now`, `dump`, …)
  is a `nibbles` verb; dlq's `queue` (the raw item files) is `nibbles files`,
  because `queue` is the tab. `docs/download-queue.md` is the guide;
  `queue/README.md` is the item contract.

`design/` holds the agreed design and its mockups, which are the spec the
screens follow; `design/divergences.md` lists where the build differs.

## Layout

- `nibbles.py`: the app's loop. `tui.py`: the terminal (blessed), read as
  taps, drags and keys. `widgets.py`: the buttons, sheets and bars, drawn with
  bewitch. `shell.py`: what the screens share. `yt_screens.py`: Search, Feed,
  Later and the video sheet. `queue_screens.py`: Queue and More.
- `ytq.py`: the YouTube half's logic and its command line. `ytdl_item.py`:
  what the items it writes download through.
- `expire_runner.py`: the scheduled runner. `expire_dl.py`: the shared
  downloader. `expire_sched.py`, `expire_ui.py`, `dlq.py`: the queue's command
  line and its actions. `nibbles.main` is the one door to all three command
  lines.
- `queue/`: the queue, with the item contract in `queue/README.md`.
- Two separate checkouts, each found as its variable, then a clone beside this
  one, then under `~`: **`~/zwana-quota`** (`$ZWANA_HOME`), the portal client
  and quota widget the zwana budget source reads every guard figure through
  (not needed with a manual budget), and **`~/bewitch`** (`$BEWITCH_HOME`),
  the styling library every screen is drawn with.
- One installed dependency: **blessed**, which owns the terminal.

The queue root is this checkout (`$EXPIRE_HOME` overrides), never an installed
copy's own directory, so an installed `nibbles` still works the real queue.

## Install

`git clone https://github.com/gsfernandes81/bewitch ~/bewitch` beside it. Then
either install the commands (which brings blessed with them):

```
uv tool install --editable ~/nibbles
ln -s ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
```

or run the files as they are, after `pip install blessed`:
`python3 ~/nibbles/nibbles.py`, which takes the same words.

## Moving the phone from ~/dlq and ~/ytq (one-time)

The queue's runtime state lives in the checkout, gitignored, so it moves by
hand. Do it outside the window, with nothing downloading (`nibbles status` says
so):

```
git clone https://github.com/gsfernandes81/nibbles ~/nibbles
git clone https://github.com/gsfernandes81/bewitch ~/bewitch    # if not there yet
dlq cancel                                              # the OLD dlq: stop its job firing
mv ~/dlq/queue/*.py ~/nibbles/queue/                    # pending items
mv ~/dlq/{work,out,done,failed,logs} ~/nibbles/         # partials + history
mv ~/dlq/{state.json,config.json} ~/nibbles/ 2>/dev/null
sed -i 's|/home/dlq|/home/nibbles|g; s|/home/ytq|/home/nibbles|g' ~/nibbles/queue/*.py
uv tool install --editable ~/nibbles                    # adds nibbles; ytq and dlq stay
ln -sf ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
nibbles arm                                                 # register the runner in ~/nibbles
nibbles status                                              # says what it found
```

The `sed` matters: an item spells the absolute paths of the modules it imports
into its own `sys.path.insert` lines, and an item that cannot import its
downloader fails every night without spending a byte. `nibbles dump` shows an
item's head if one does. Keep `~/dlq` and `~/ytq` until a night has gone
through, then delete them, and the old commands with them: `uv tool uninstall
dlq; uv tool uninstall ytq`, and their completions (`rm
~/.config/fish/completions/{dlq,ytq}.fish`). Until then the old `ytq` and
`dlq` still run, against the old checkouts: nothing they install has a name
`nibbles` installs.

## Checks

`make dev` (`uv sync`, once, networked) puts the locked pytest, pyte and
hypothesis into `.venv`; then `make test` or `make check`, both of which are
`.githooks/checks.sh`, the one copy of what runs. The pre-push hook
(`git config core.hooksPath .githooks`, once per clone) refuses a push that
fails it, because a push here is a deploy: the phone pulls it and the nightly
runner runs what landed.

There are two suites, `tests/ytq` and `tests/dlq`, from the two repos, run as
two pytest processes. Each builds its own queue root under a temporary
directory, copies this checkout's modules into it, points `EXPIRE_HOME` and
`HOME` at it and imports from there, so the checks never read or write the
queue this checkout manages and never reach the network. The app is opened on a
pty that answers blessed's startup queries the way Termux does
(`tests/termux_pty.py`), tapped and dragged the way Termux sends a finger, and
read back with `pyte`; and every tab and sheet is composed at every width from
32 to 80 and every height from 11 to 30.

Two failures that are not regressions: a long checkout path (the screens check
every line fits 32 columns, and the root is on the status screen), and a
missing zwana-quota or bewitch checkout.

`make mutants` runs poodle; it is a ratchet, outside the checks, and
`poodle_config.py` says how it is arranged.

## Scheduling on Android — findings the nightly job stands on

Measured on this phone in 2026-08, and still what `nibbles arm` relies on:

- **JobScheduler, not runit/cron/nohup.** A userspace poll loop lives only
  while Termux does; JobScheduler is the system's own scheduler — it survives
  Termux being killed and restores after a reboot. `termux-job-scheduler`
  needs the Termux:API **app**, not just the CLI package (without the app it
  hangs).
- **15 minutes is Android's floor** for a periodic job (clamped since N).
  The real uncertainty is **Doze**: screen off, unplugged and stationary,
  firings defer into maintenance windows; charging suppresses Doze entirely.
  The pre-reset window is a *bias*, not a guarantee — an accepted trade,
  since a missed night just means the job tries again the next evening. A
  night that matters: put the phone on charge over the reset.
- **A job body must never take Termux's wake lock.** JobScheduler holds one
  across the job's execution, and Termux's own lock is a single global flag
  with no reference counting — `termux-wake-unlock` releases it regardless of
  who acquired it, so a job that unlocked on its way out would silently drop
  a lock taken for something else.
