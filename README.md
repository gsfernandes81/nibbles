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
runner's own count of what it moved. `dlq settings budget` chooses;
`docs/download-queue.md` has the section on both.

ytq and dlq were two repos until 2026-10-10; this is both of them, with their
histories. The two commands keep their names for now:

- **`ytq`**: search YouTube (or paste a URL, or open your subscriptions or
  Watch Later), pick a quality, queue it. `docs/ytq.md` is the guide.
- **`dlq`**: the queue itself. Bare on a terminal it opens the queue's screen;
  off one it prints status. `dlq <url>` queues a plain file URL.
  `docs/download-queue.md` is the guide; `queue/README.md` is the item
  contract.

A one-app, buttons-first rebuild of both screens on blessed is in progress:
`design/` holds the agreed design and its mockups, and they are the spec.

## Layout

- `ytq.py`: the YouTube front end. `ytdl_item.py`: what the items it writes
  download through.
- `expire_runner.py`: the scheduled runner. `expire_dl.py`: the shared
  downloader. `expire_sched.py`, `expire_ui.py`, `dlq.py`: the `dlq` command
  and its screen.
- `queue/`: the queue, with the item contract in `queue/README.md`.
- `~/zwana-quota`, a separate checkout: the portal client and quota widget the
  zwana budget source reads every guard figure through. Found as
  `$ZWANA_HOME`, then a clone beside this one, then `~/zwana-quota`. Not
  needed with `dlq settings budget manual`.

The queue root is this checkout (`$EXPIRE_HOME` overrides), never an installed
copy's own directory, so an installed `ytq` or `dlq` still works the real queue.

## Install

Optional: `python3 ~/nibbles/ytq.py` and `python3 ~/nibbles/expire_sched.py`
work as they are.

```
uv tool install --editable ~/nibbles
ln -s ~/nibbles/completions/ytq.fish ~/.config/fish/completions/
ln -s ~/nibbles/completions/dlq.fish ~/.config/fish/completions/
```

## Moving the phone from ~/dlq and ~/ytq (one-time)

The queue's runtime state lives in the checkout, gitignored, so it moves by
hand. Do it outside the window, with nothing downloading (`dlq status` says
so):

```
git clone https://github.com/gsfernandes81/nibbles ~/nibbles
dlq cancel                                              # stop the old job firing
mv ~/dlq/queue/*.py ~/nibbles/queue/                    # pending items
mv ~/dlq/{work,out,done,failed,logs} ~/nibbles/         # partials + history
mv ~/dlq/{state.json,config.json} ~/nibbles/ 2>/dev/null
sed -i 's|/home/dlq|/home/nibbles|g; s|/home/ytq|/home/nibbles|g' ~/nibbles/queue/*.py
uv tool uninstall dlq; uv tool uninstall ytq
uv tool install --editable ~/nibbles
ln -sf ~/nibbles/completions/dlq.fish ~/nibbles/completions/ytq.fish ~/.config/fish/completions/
dlq arm                                                 # register the runner in ~/nibbles
dlq status                                              # says what it found
```

The `sed` matters: an item spells the absolute paths of the modules it imports
into its own `sys.path.insert` lines, and an item that cannot import its
downloader fails every night without spending a byte. `dlq dump` shows an
item's head if one does. Keep `~/dlq` and `~/ytq` until a night has gone
through, then delete them.

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
queue this checkout manages and never reach the network. The screens are
opened on a pty and read back with `pyte`.

Two failures that are not regressions: a long checkout path (the screens check
every line fits 32 columns, and the root is on the status screen), and a
missing zwana-quota checkout.

`make mutants` runs poodle; it is a ratchet, outside the checks, and
`poodle_config.py` says how it is arranged.

## Scheduling on Android — findings the nightly job stands on

Measured on this phone in 2026-08, and still what `dlq arm` relies on:

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
