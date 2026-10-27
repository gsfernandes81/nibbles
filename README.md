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

**`nibbles` is the one command** (`nibbles help` lists it all); it installs
no `ytq` or `dlq`.

- **`nibbles`** opens the app, on Search; `nibbles queue` or `more` on another
  tab. Feed and Later are a tap away.
- **`nibbles <url>`** takes whatever yt-dlp would — a link with or without its
  scheme, a bare video id, `ytsearch:words` — and a plain file URL too. A video
  page opens its sheet (`--now` starts it); a file is queued as a download.
  Which is which is the server's own answer, from its headers (~1 KB), unless
  a flag already says. `nibbles search crust of rust` searches, and
  `nibbles --list …` prints with no screen at all. `docs/ytq.md` is the guide.
- **The queue**: every verb (`status`, `list`, `settings`, `arm`, `run-now`,
  `dump`, …) is a `nibbles` verb. `docs/download-queue.md` is the guide;
  `queue/README.md` is the item contract.

`design/` holds the agreed design and its mockups, which are the spec the
screens follow; `design/divergences.md` lists where the build differs.

## Layout

- `nibbles/` is the package. `app.py`: the app's loop, and `nibbles.main`,
  the one command's door. `tui.py`: the terminal (blessed), read as taps,
  drags and keys. `widgets.py`: the buttons, sheets and bars, drawn with
  bewitch. `shell.py`: what the screens share. `yt_screens.py`: Search, Feed,
  Later and the video sheet. `queue_screens.py`: Queue and More.
- `nibbles/ytq.py`: the YouTube half's logic and its command line.
  `ytdl_item.py`: what the items it writes download through.
- `nibbles/expire_runner.py`: the scheduled runner. `expire_dl.py`: the shared
  downloader. `expire_sched.py`, `expire_ui.py`, `dlq.py`: the queue's command
  line and its actions. `home.py`: where the queue lives.
- `expire_runner.py`, `expire_sched.py`, `ytdl_item.py` and `expire_dl.py` at
  the root are doors to the package's modules, kept for a phone armed, and
  holding items queued, before nibbles was a package. They are not shipped.
- `queue/`: the queue, with the item contract in `queue/README.md`.
- `Dockerfile.dev`, `docker-child-init.dev.sh`, `docker-login.dev.sh`: the
  owner's dev container, `nibbles-dev`, which the infra repo builds from
  `main` (see Checks). Not shipped.
- **`~/zwana-quota`** (a clone beside the queue root, else under `~`): the
  portal client and quota widget the zwana budget source reads every guard
  figure through. Not needed with a manual budget. `$ZWANA_HOME` points a
  shell (and the tests) at a clone somewhere else, but **never the nightly
  job**: the job scheduler starts the runner without any shell's
  environment, so it looks only beside the queue root and then in
  `~/zwana-quota`. While the only clone is one `ZWANA_HOME` finds, `nibbles
  arm` refuses and `nibbles status` says `BROKEN`; link it to where the job
  looks (`ln -s <the clone> ~/zwana-quota`).
- Installed dependencies: **blessed**, which owns the terminal, and
  **bewitch**, the styling library every screen is drawn with. A bewitch
  checkout (`$BEWITCH_HOME`, beside this one, or `~/bewitch`) wins over the
  installed one.

The queue root is `$EXPIRE_HOME`, else this checkout, else `~/nibbles` — never
an installed copy's own directory, so an installed `nibbles` still works the
real queue. An installed copy makes `~/nibbles` the first time it runs: the
item contract, and the `expire_runner.py` launcher `nibbles arm` registers
with the job scheduler. It writes into no checkout and into no folder that
already holds something else.

## Install

### Termux, once, first

```
pkg install python termux-api     # and the Termux:API app, from where Termux came from
termux-setup-storage              # lets Termux reach Downloads, where files land
mkdir -p ~/.termux
echo 'allow-external-apps = true' >> ~/.termux/termux.properties
termux-reload-settings
```

**Without `allow-external-apps = true`, no download will open from the app.**
Since termux-app 0.118, Termux hands no file to another app — the video
player, the PDF viewer, the installer — until `termux.properties` says it
may, and it reads that file only when it starts or on
`termux-reload-settings`. Open it on a download's sheet, and Open it when
done, ask first and say so (`could not open film.mp4: Termux shares no file
with another app until ~/.termux/termux.properties has allow-external-apps =
true: add it, then run termux-reload-settings`) rather than send a file
nothing will open. The value must be exactly `true`. Termux reads the first
of `~/.termux/termux.properties` and `~/.config/termux/termux.properties`
that exists, so if your settings live in the second, put the line there
instead: creating the first would hide them.

yt-dlp is a separate install, on PATH; [docs/ytq.md](docs/ytq.md) has what
YouTube needs of it.

### nibbles

From PyPI:

```
uv tool install nibbles        # or: pip install nibbles
nibbles                        # makes ~/nibbles on its first run
nibbles arm                    # register the nightly job
```

`uv tool upgrade nibbles` (or `pip install -U nibbles`) updates it, and the
next `nibbles` points the launcher at the new copy.

Or from a checkout, which is what the phone runs (`git pull` is the update):

```
git clone https://github.com/gsfernandes81/nibbles ~/nibbles
git clone https://github.com/gsfernandes81/bewitch ~/bewitch
uv tool install --editable ~/nibbles
ln -s ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
```

or, with nothing installed but `pip install blessed`, `python3 -m nibbles`
from `~/nibbles`, which takes the same words.

On a phone that already runs a checkout, pulling the change that made nibbles
a package needs nothing else: the job is still armed at
`~/nibbles/expire_runner.py`, items queued before it still import
`ytdl_item`/`expire_dl` off `~/nibbles`, and the editable install's `nibbles`
still finds `nibbles.main` — the doors at the root answer all three.

## Releasing

A push to `main` that changes `version` in `pyproject.toml` to one PyPI does
not have yet is a release: `.github/workflows/release.yml` runs both suites,
builds, installs the wheel in a clean environment and makes a queue root with
it, then publishes by PyPI's trusted publishing (no token is stored anywhere)
and tags `v<version>`. Bump `__version__` in `nibbles/__init__.py` with it; a
test holds the two together. bewitch is released the same way from its own
repo, and has to be on PyPI before a nibbles that needs it.

## Moving the phone from ~/dlq and ~/ytq (one-time)

The queue's runtime state lives in the checkout, gitignored, so it moves by
hand. Do it outside the window, with nothing downloading (`nibbles status` says
so):

```
git clone https://github.com/gsfernandes81/nibbles ~/nibbles
git clone https://github.com/gsfernandes81/bewitch ~/bewitch    # if not there yet
python3 ~/dlq/expire_sched.py cancel                    # stop the old job firing
mv ~/dlq/queue/*.py ~/nibbles/queue/                    # pending items
mv ~/dlq/{work,out,done,failed,logs} ~/nibbles/         # partials + history
mv ~/dlq/{state.json,config.json} ~/nibbles/ 2>/dev/null
sed -i 's|/home/dlq|/home/nibbles|g; s|/home/ytq|/home/nibbles|g' ~/nibbles/queue/*.py
uv tool install --editable ~/nibbles
ln -sf ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
nibbles arm                                                 # register the runner in ~/nibbles
nibbles status                                              # says what it found
```

The `sed` matters while `~/dlq` and `~/ytq` are still there: an item spells
the directory it was written in into its own `sys.path.insert` line, ahead of
everything else, so until the line is changed it imports the old copy's
downloader. (Once they are gone an old item still finds this checkout's: the
runner and `nibbles now` hand every item the package on `PYTHONPATH`, and the
doors at the root answer the old flat imports.) `nibbles dump` shows an item's
head if one fails to import. Keep `~/dlq` and `~/ytq` until a night has gone
through, then delete them, along with the old completions (`rm
~/.config/fish/completions/{dlq,ytq}.fish`) if they are still there. (The old
commands are run by path above because they may already be uninstalled:
`uv tool uninstall dlq; uv tool uninstall ytq` if not.)

## Checks

`make dev` (`uv sync`, once, networked) puts the locked pytest, pyte and
hypothesis into `.venv`; then `make test` or `make check`, both of which are
`.githooks/checks.sh`, the one copy of what runs. The pre-push hook
(`git config core.hooksPath .githooks`, once per clone) refuses a push that
fails it, because a push here is a deploy: the phone pulls it and the nightly
runner runs what landed.

There are two suites, `tests/ytq` and `tests/dlq`, from the two repos, run as
two pytest processes. Each builds its own queue root under a temporary
directory, copies this checkout's package into it, points `EXPIRE_HOME` and
`HOME` at it and imports from there, so the checks never read or write the
queue this checkout manages and never reach the network. The app is opened on a
pty that answers blessed's startup queries the way Termux does
(`tests/termux_pty.py`), tapped and dragged the way Termux sends a finger, and
read back with `pyte`; and every tab and sheet is composed at every width from
32 to 80 and every height from 11 to 30.

Two failures that are not regressions: a long checkout path (the screens check
every line fits 32 columns, and the root is on the status screen), and a
missing zwana-quota or bewitch checkout.

In the dev container (`nibbles-dev`) all of that is already there: the
checkout is `/workspace`, bewitch and zwana-quota are cloned beside it at
`/bewitch` and `/zwana-quota` on every start (anonymously, so both have to stay
public), the locked venv is first on `PATH`, and the pre-push hook is armed.
`cd /workspace && make test`. Termux is not in there, so neither is anything
that needs it — the job scheduler, `termux-*`, yt-dlp — and the suites need
none of it.

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

## Licence

AGPL-3.0-or-later; see `LICENSE`.
