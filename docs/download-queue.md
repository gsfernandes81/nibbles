# The overnight download queue

The data plan grants ~763 MiB of free data a day, and whatever is unused is
wiped at 00:00 UTC. In the window before that reset — an hour by default —
a scheduled job spends the leftover on downloads you queued — always leaving
a floor for the morning (100 MB by default) and never touching the paid
reserve. `nibbles settings` changes the window, the floor, what the job says, or
turns it off outright — see [Settings](#settings).

The queue and its YouTube front end live in one checkout, `~/nibbles/` (they
were two repos, `dlq` and `ytq`, until 2026-10-10). **One command is
installable**, `nibbles` (see [Installing](#installing-the-commands)), and it
then works from any directory: on its own it opens [the app](#the-app) on
Search, `nibbles queue` opens it on its Queue tab, which is where the queue is
worked on, `nibbles <url>` queues a plain file URL (or opens a video page's
sheet), and every verb in these docs (`nibbles status`, `nibbles settings`,
…) is one of its words — `nibbles help` lists them all. Without installing, every line
in these docs also works as `python3 -m nibbles …` from `~/nibbles`.

The runner reads the portal through the quota widget in a second checkout,
`~/zwana-quota`, found beside this one or under `~`. `EXPIRE_HOME` and
`ZWANA_HOME` override where either lives. A phone with no zwana portal sets a
daily allowance instead and needs no second checkout at all — see [Budget
sources](#budget-sources).

If you need something before the window rather than during it, see
[Downloading something now](#downloading-something-now) — that spends data
nothing is holding back, and says so, and says whether anything is counting it,
before it does. If the crew portal cannot be reached
at all, which is what being on mobile data looks like from here, see [When the
portal cannot be reached](#when-the-portal-cannot-be-reached).

## Queue something

| You have | Run |
|---|---|
| a video page (YouTube etc.) | `nibbles <url>` — see [ytq.md](ytq.md) |
| no link, just a title | `nibbles search <words>` |
| a direct file URL | `nibbles <url>` — the same command |
| something more exotic | write an item by hand — `queue/README.md` is the contract |

`nibbles <url>` first asks the server what the URL is — its headers only,
~1 KB: HTML is a page, for yt-dlp and the video sheet; anything else is a
file. (YouTube's own hosts are pages without asking, and any of the flags
below says "a file" without asking.) For a file it then sizes it from the
same kind of headers (no payload), writes the queue item, and prints where
the file will land:

```
nibbles <url>                    # probe the size, queue it
nibbles <url> --name x.iso       # choose the saved file name
nibbles <url> --sha256 <hex>     # verify the file before delivery
nibbles <url> --probe            # just print size + resume support
nibbles <url> --expect-bytes N   # server won't state a size: set the
                                 # most you are willing to let it cost
nibbles <url> --again            # queue it even though it is already
                                 # queued or already downloaded
```

A URL that is already in the queue, already downloaded or already given up on
is refused rather than queued a second time, naming what it already is; the
same check catches a video queued before, on the id rather than the URL
— see [ytq.md](ytq.md#it-will-not-queue-the-same-video-twice).

Nothing downloads when you queue — the item just waits for the nightly window.

## Installing the commands

One command, `nibbles`, from PyPI or from the checkout. It depends on
**blessed**, which owns the terminal, and **bewitch**, the library the screens
are drawn with; yt-dlp is a separate binary on PATH, and `~/zwana-quota` a
checkout beside this one (`$ZWANA_HOME`), needed only for the zwana budget.

**From PyPI** — a copy in the tool's own environment, upgraded by uv:

```
uv tool install nibbles
uv tool upgrade nibbles             # later
```

**Editable, from the checkout** — what the phone runs: the command runs the
package in `~/nibbles` as it is, so edits take effect immediately and a pull
needs no reinstall. A bewitch checkout beside it (`~/bewitch`, or
`$BEWITCH_HOME`) wins over the installed bewitch, so it is pulled the same way:

```
uv tool install --editable ~/nibbles
```

Either way the queue is **`~/nibbles/`, never the installed copy's own
directory** — the queue has to be the one the nightly runner reads. The root is
`$EXPIRE_HOME`, else the checkout the package sits in, else `~/nibbles`
(`nibbles.home.root`), because the alternative fails without saying so: a copy
in site-packages would queue into its own directory, where the runner never
looks, and the symptom would be a job firing faithfully every night onto an
empty queue.

An installed copy makes that root the first time `nibbles` runs: the item
contract in `queue/README.md` (which is what marks a root) and
`expire_runner.py`, the launcher `nibbles arm` registers with the job
scheduler. The launcher names the package's path, so every `nibbles` rewrites
it if an upgrade moved the package — run `nibbles` once after upgrading, before
the window. Nothing is written into a checkout (its own `expire_runner.py` is
tracked), into a root `EXPIRE_HOME` names, or into a `~/nibbles` that already
holds something that is not a queue.

Set `EXPIRE_HOME` if the queue is somewhere other than `~/nibbles`:

```
EXPIRE_HOME=~/src/nibbles nibbles <url>
```

`uv` builds an isolated environment under `~/.local/share/uv/tools/` and links
the command into `~/.local/bin`; if it is not found afterwards, `~/.local/bin`
is not on PATH, and `uv tool update-shell` fixes that. The install fetches
blessed and bewitch (and, for the editable one, the **≈1 MB** hatchling build
backend) from PyPI once; after that they are served from uv's cache. (Add
`--offline` to have it refuse rather than fetch on a metered connection.)

To remove: `uv tool uninstall nibbles`. Nothing else
in the queue depends on the install — the nightly runner is registered by
absolute path and is unaffected by it, and queue items already written keep
working.

### Fish completions

```
ln -s ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
```

Symlinks rather than copies, so pulling the repo updates them. New shells pick
them up; `exec fish` in the current one. They complete the subcommands and
options, and — for `nibbles path` — the download names themselves, each shown
with its state:

```
$ nibbles path <tab>
40-ubuntu-24-04.py  (queued, 1 GiB here)  60-some-talk.py  (queued)
```

That list comes from `nibbles names`, which walks the queue directories and parses
nothing, because it runs on every press of the tab key.

## One-time setup

```
nibbles arm
```

Registers the job with Android's scheduler (needs the **Termux:API app**, not
just the package). It survives reboots and Termux being killed; `nibbles cancel`
unregisters it. Both are also the **nightly job** row on [the More
tab](#settings) (`j`), which says which it currently is — a tap arms it when
it says not armed, and stops it, after asking (because what follows is
silence), when it says armed. `arm`
registers the runner **in the queue root** (`~/nibbles/expire_runner.py`), so
re-arm after moving `~/nibbles`.

## Watching one download

While anything downloads, the status bar on every tab says `↓ 18%`, its name
and the time left. On the Queue tab a tap on its row opens the running
download's sheet: `downloading · now · 1h left`, a bar, and `1.02 of 5.61 GiB ·
1.1 MiB/s`. The words and the bar are one reading — the download's own
progress file, asked once per redraw — so they cannot disagree, and a total no
server has stated is never invented: the bar stays empty until there is one.

For a download this session started, the sheet has **Pause** (`x`), which
interrupts it rather than killing it, so every byte is kept and it resumes in
the next window or with Download now. One started with Download now (or Now on
a video) also gets **Open it when done** (`o`): ticked, the file is handed to
Android the moment this run delivers it. `esc Back` leaves it running.

## When something fails

`nibbles dump` prints one paste of everything a bug report needs: the
environment, how each sibling checkout resolved, what the gate thinks, the
state rows, the head of each failing item (its `sys.path` lines are usually
the evidence) and the tails of the newest logs. `nibbles dump NAME` narrows it
to one download. Every section is guarded, so it finishes on broken trees —
which is when it is needed.

Items queued **before the split** import `ytdl_item` off the queue root;
the module moved to the ytq checkout, and a shim at the queue root answers
that import with the real module, so pre-split items keep downloading
without being edited.

## Checking on it

```
nibbles status      # what happens next, and what it turns on
nibbles list        # every download, and how much of it is here
nibbles queue       # the same queue, on a screen that can change it
nibbles path NAME   # where a finished download landed
nibbles logs        # last 40 lines of the runner log
nibbles run-now     # run the whole queue now, without waiting for the window
nibbles run-now --blind   # ...with no portal reading, on mobile data
```

All of these except `path` are in the app too — Run now sits on the Queue
tab's window card (see [The Queue tab](#the-queue-tab)), and the More tab
holds the window, the reserve, the destinations, the nightly job and the
runner log (`s` and `l` on the Queue tab go there directly). The command
line is what is left for the things a screen cannot do: `path` prints a path
and nothing else, so `cd (nibbles path ubuntu)` works; and `nibbles status`
prints the status screen in a pipe or a script, where there is no app.

`nibbles status` answers "is it going to download tonight, and what". It leads
with that answer and then shows the working:

```
DOWNLOAD QUEUE                    22:41Z
  waiting for tonight
  opens in 19m (23:00Z)

data
   1.12 GiB left today
    763 MiB of it expires at 00:00Z
     100 MB is always kept back
    480 MiB the queue may spend tonight
  800 KiB/s measured download speed

queue (2)
  40-ubuntu-24-04-desktop-amd64
  18%  1.02 GiB/5.61 GiB  try 2/3

  60-some-talk
    -  0 B/≤505 MiB

  3 done, 1 failed - nibbles list

job       armed, fires every 15m
last run
  22:30Z (11m ago) not yet: window opens
  23:00Z
root      ~/nibbles
```

The first line under the heading is the whole answer, and there are only ten
of them: **automatic downloads are off** (the `auto` switch — see
[Settings](#settings), asked before anything else), **waiting for tonight**,
**window open, downloading**, **downloading now** (something is being
downloaded at this second, by the nightly job or by the screen's `n`), **done
for tonight**, **nothing queued**, **no data to spend tonight**, **PAID: no
portal, downloading** (a `--blind` run, on mobile data — see [When the portal
cannot be reached](#when-the-portal-cannot-be-reached)), and the two blocked
ones — the portal not answering, or its reading being too old to spend
against. They come from the same function the runner itself gates on, so the
screen cannot say one thing while the runner does another.

The figures under `data` are the arithmetic the runner does, in the order it
does it: what is left, how much of that dies at the reset, the reserve that
is never spent (100 MB unless `nibbles settings` says otherwise), and therefore
what tonight may use. The speed under them is what the last download actually
managed, which is what the runner sizes each slice against. `try 2/3` on an
item means one night already failed and it has two left before it is set
aside for you.

`nibbles status` is read-only and takes no lock, so it answers while a firing is
in progress. It exits non-zero when it prints a `BROKEN` line.

`nibbles list` is the "where is everything" answer — queued, failed and done in
that order, done newest first, with what is on the disk against what it is
going to be:

```
queued (2)
  40-ubuntu-24-04           16%  1 GiB of 5.61 GiB   Ubuntu 24.04 desktop ISO
  60-some-talk                -  0 B of ≤506 MiB     Some talk [1080p mp4]
done (1)
  50-other-talk         complete  201 MiB            other-talk.mp4
```

The figure is measured from the files on disk, not read out of what the item
last claimed, so it survives a kill. `≤` means no server has stated a size yet
and the number shown is the item's declared cap, which is deliberately larger
than the file. Amber is started, grey is waiting, green is here, red is failed.

A finished download whose file you have since deleted says **file gone**, and
one whose folder cannot be reached at all — card out, storage permission not
granted — says **folder away**. Those are different facts and only the first is
about the file. Neither is a download waiting to happen: an item leaves the
queue when it finishes and the runner only ever looks in `queue/`, so nothing
can start it again. To download it a second time, queue it again.

It lays itself out to the terminal it is in. On a phone in portrait the
description goes and, if the names are long, each download takes two lines
rather than having its name clipped — the name is what you type back at
`nibbles path`, so it is the last thing to lose room. Both lines of a download sit
at the same indent and a blank line separates one download from the next,
since a phone loses two columns to every level of indent and the eye reads the
gap anyway:

```
queued (2)
  40-ubuntu-24-04-desktop-amd64
  18%  1.02 GiB/5.61 GiB

  60-some-talk
    -  0 B/≤505 MiB
```

`NAME` is name-ish: any unambiguous part of the name (`ubuntu`, `some-talk`)
or the priority number (`40`). Anything matching two downloads is refused with
both listed.

`nibbles path` prints only the path, so `cd (nibbles path ubuntu)` works, and exits
non-zero if the download has not finished — it still prints where it is going
to land. For one that finished and whose file has since gone, it prints where
it *was* delivered and exits non-zero, because that is the only record of where
it went and it is still the answer to the question.

`nibbles logs` does the same thing to the runner's log: on a phone the date is
lifted off the lines and printed once above them — but only when every line on
the screen really is that one day, since the queue runs across midnight — and a
long line is wrapped with its continuations indented rather than left to break
wherever the screen ends.

Finished files land in the configured download directory — see [Where downloads
go](#where-downloads-go); on the phone that is Android's Downloads. The item
script itself moves to `done/` when finished, or to `failed/` after three failed
nights (you get a notification either way something needs you).

## The app

```
nibbles queue     # the app on its Queue tab
nibbles           # ...on Search
```

`nibbles queue` opens the app on its Queue tab, a bare `nibbles` on Search,
and `nibbles more` on More. With no terminal to draw on — a pipe, a script —
there is no app, and it says so; `nibbles status` is the printed view.

**One app, five tabs** along the bottom: **Search · Feed · Later · Queue ·
More**. The first three are YouTube — see [ytq.md](ytq.md); Queue is the queue
and More the settings. There are no pages to step back through: the only depth
is a **sheet**, which comes up from the bottom over the tab it was opened from
— a download, a confirm, a setting — with the tab still there above it,
dimmed. Esc, `esc ×` at its top right, or a tap on the dimmed part closes it.
`q` quits from anywhere (Tab and Shift-Tab step through the tabs), and what was
changed is printed on the terminal on the way out.

**Buttons first, keys second.** Every button is three rows tall and shows its
key in grey before its word, so the buttons are the hint line: `n Run now` is a
tap or an `n`. A tap acts at once, and the button flashes so you see what you
hit; just after a sheet opens a tap is ignored, so the second half of a double
tap cannot press what the sheet put under your finger.

**A tap is a tap; a drag scrolls.** Termux reports a finger that moved as
scrolling, never as a tap, so a drag can never press a button. A swipe moves
the list; the selection stays on its row until it nears the edge, then rides
along one row in. The last three columns of a list are its **scrollbar**: a tap
there jumps to that point, and a drag that starts there moves the thumb a row
per row of finger travel — a page at a time through a long list.

**The status bar** is the last row of every tab: a word at the left —
`WAITING`, `OPEN`, `DONE`, `IDLE`, `OFF`, `SPENT`, `BLOCKED`, `RUNNING`, or
`ASKING` before the first reading, and `↓ 18%` while something downloads —
then what it is about (`opens 03:00`, or the download's name), then the
countdown or the time left. Every time on the screens is the phone's own
clock, never UTC. What a change did is said on the line just above the tabs.

### The Queue tab

```
╭──────────────────────────────────────╮
│ waiting · 03:00 (19m)  ╭───────────╮ │
│ ██████████████░░░░░░░░ │ n Run now │ │
│ 480/763 MiB to spend   ╰───────────╯ │
╰──────────────────────────────────────╯
[  Queued 3  ][  Failed 1  ][  Done 3  ]

   ubuntu-24.04-desktop-amd64.iso
   ↓ 18%  1.02 of 5.61 GiB
   Some Talk About Rust
   0 of ≤505 MiB · 46 MiB at 03:00
  ── the window ends here · 480 MiB ───
   big.iso
   0 of ≤8 GiB
```

The **window card** leads: the verdict, when the window opens and how long
until then, a bar of what the next window may spend against what expires, and
the two figures — the same facts `nibbles status` opens with, kept in view while
you work the queue instead of a screen away. **Run now** sits beside it. With
the keyboard up the card folds into a one-line strip beside Run now.

**Queued · Failed · Done** choose which group the list shows (←→ step
between them); Done is newest first. Each download is two lines: its name,
then `↓ 18%` on the one downloading, `0 of ≤505 MiB` on one waiting (`≤` as in
`nibbles list`), the last error on a failed one (`×`), and the size and the file
it delivered on a done one (`✓`).

**The cut line is computed, never an item.** Taps and the cursor skip straight
over it, and it is worked out fresh from wherever the items are, including live
while one is being moved: hold `big.iso` and move it above `Some Talk About
Rust`, and the line follows it down one step at a time, because the line is a
projection of the runner's own admission rule (`expire_runner.admit`, the same
function `fire()` calls in the window) taken over the runner's own budget, run
against the queue in whatever order it is currently in. **Moving an item
across the line moves the line, never the budget** — reordering only changes
which items the budget reaches first, so a window that would spend 480 MiB
spends 480 MiB whichever way the queue is arranged; move `Some Talk About
Rust` above the ISO and the line still falls wherever 480 MiB runs out, just
between a different pair of names.

When nothing would get anything — the window closed, no reading to spend
against, every queued item too big for what is left — the line moves to the
top of the queued group and names why instead of a byte figure:
`── nothing in the window · done ──` once the window has closed,
`── nothing in the window · no portal reading ──` on a phone away from the
vessel's wifi, and the item's own reason — `── nothing in the window · needs
200 MiB, 50 MiB spendable ──` — only where there is a budget and the queue
still does not fit inside it. On a 32-column phone the lead-in shortens
(`── window · 480 MiB`, `── nothing · no portal reading`) before the figure or
the reason gives way. There is no line at all before the first reading has
come back — the card reads `asking zwana…` until it does.

A download the window only gets part-way through says so on its own row:
`0 of ≤210 MiB · 46 MiB at 03:00` sits above the line, because it does get
bytes, and the figure is how many of them. Items that finish in the window and
items below the line carry nothing extra.

**Run now is `nibbles run-now`, and it means now.** The window is a schedule, not
a permission: it ignores the window exactly as Download now does, and so does
`auto` being off — everything else stays, the reserve floor, the per-item caps,
and the portal reading the whole budget is derived from. It asks once, on a
sheet with the figure on its button: `n Run now · 480 MiB`, `out of the 03:00
window's allowance`. With the portal unreachable it is [a blind
run](#when-the-portal-cannot-be-reached) instead, in a warning border: *Zwana
is not answering, so we do not know how much data we can spend. Proceed
anyway?*, `at most what the queue declared`, then `y Run anyway · ≤1.2 GiB`
and `esc Not now`. The figure is the runner's own — the same one the cut line already
projected, never a second sum worked out here. A run that would do nothing —
nothing queued, something already downloading, the queue busy — is not
offered: the line above the tabs says why. It runs detached, so the tab stays
usable and keeps drawing; the running download's sheet pauses it, and what is
downloaded is kept for the next window.

The card's figures come from a background reading — the portal is a network
call, and asking it on every redraw would be hammering, not watching — taken
when the app starts, again on opening the Queue tab once the one on screen is
a minute old, and at once after anything that changes the queue or a
setting. A failed one keeps the previous reading rather than blanking it. What *is* live regardless is a download in
flight, read off its own progress file every second, and the list itself,
re-read off the disk every fifteen seconds so a firing that starts shows up.

### A download's sheet

Reorder, rename, remove, put a failed download back, give it its nights back,
download one now, open a finished one, read its log: there are no commands for
any of those — each is easier to do to a download you are looking at than to a
name you have to type correctly first. A tap on a row (or ⏎) opens its sheet:

```
 Some Talk About Rust ╱╱╱╱╱╱╱  esc ×
 queued · 2nd of 3 · try 1/3
 0 of ≤505 MiB · 46 MiB at 03:00
 1080p mp4 → Download/
 [  n Download now  ][   m Move   ]
 [    r Rename      ][ l Its log  ]
 [  t Clear tries   ][  d Remove  ]
```

The buttons are only the ones that mean something for that download, and the
download being changed is the one named at the top of the sheet:

| Button | |
|---|---|
| `n` Download now | download it now — asks once, and says what it will cost |
| `m` Move | move it in the queue — [below](#moving-a-download) |
| `u` Queue again | put a failed download back, with its three nights again |
| `t` Clear tries | clear the failed nights counted against it |
| `r` Rename | rename it; the number in front stays |
| `o` Open it | open the finished file |
| `l` Its log | that item's own log, from its last night |
| `d` Remove | remove it from the list |

**Removing keeps what was paid for.** Remove takes the download off the list
and leaves every byte where it is — the partial in `work/`, anything finished
in `out/`. Its sheet offers a second answer that also deletes the partial,
with its size on it, in red and never the default, and `No` last. A file
already delivered to Downloads is not touched either way: it is yours, not the
queue's. A download that has fetched nothing has nothing to keep, so there the
sheet has one answer, `y Remove it`.

**A rename takes the download with it**, and so does a move. An item is four
things: the file in `queue/`, the part-downloaded file in `work/<item>/`,
anything waiting in `out/<item>/`, and its record in `state.json` — the
attempts, and where its files were delivered. All four move together, so
putting a half-downloaded 5 GB ISO at the front of the queue costs nothing and
it carries on from where it stopped. The same rename by hand with `mv` on the
queue file alone starts that download again from zero, on the next night,
without a word anywhere.

**Nothing can be changed while the queue is busy.** A firing or a download in
progress is writing into `work/<item>/` and will archive the item the moment it
finishes, so every action refuses and says so rather than moving the ground
under a download.

Every change is written into `logs/runner.log`, beside the runner's own
reasoning — that file is where to look when a download is not where you left
it. Per-item logs are the exception: `logs/<date>-<item>.log` is the record of
one particular night and keeps the name the item had then.

### Moving a download

**Order is a place in a list, not a number.** Move holds the download as a
`◆` row; `↑` and `↓` (buttons or keys) move it, a swipe drags it, and
`⏎ Put here` drops it — or a tap on another row puts it there at once.
`esc Cancel` leaves it where it was. Nothing is renamed until it is dropped, so
a move thought better of costs nothing. The window card and the cut line are
re-planned at every step with the held download counted in the place it is
being moved to, so you can see it take the window's last place off something
else, or fall below the line itself.

The screens show names and positions ("2nd of 3"); the `NN-` prefix that
actually carries the order is bookkeeping, and nothing asks you to type it.
Underneath, dropping one usually renames a single file, and when two
neighbours have no room between them the whole queue is quietly dealt fresh
numbers instead. This is the only place an order is chosen: a new download queues last
and has no place picker.

### Downloading one now

Download now on a download's sheet (`n`). It asks once, on a sheet, and what
it says depends on where the phone is — the portal at `ic.zwana.io` is on the
vessel's own network, so whether it answers a quick connect, made as the sheet
opens, is the difference between data that is counted and data that is not
(the yes does nothing for the second or so that takes). Counted, it is
*Download Some Talk About Rust now, outside the window?*, `today's allowance,
no reserve kept` and `y Download now · 505 MiB`. With zwana not answering, the border turns to a warning, the question becomes
*Zwana is not answering, so we do not know how much data we can spend. Proceed
anyway?*, the grey line says `on mobile data, charged`, and the yes is
`y Download anyway · 505 MiB` in red. One yes or no either way, and the figure
is on both: what is left to fetch, not the whole declaration.

The download itself runs detached, so the sheet closes and the status bar shows
its progress; its own sheet pauses it. Everything else is as it always was — it
downloads into the same place the nightly job would, so pausing it is safe,
what is downloaded stays, and the nightly window carries on from there. A
download started this way never counts as one of an item's three nightly
attempts, and it takes the runner's lock, so it cannot collide with a firing.
Now on a video's sheet is the same thing with the queueing folded in.

### Downloads that are no longer there

A finished download whose file you have since deleted is dropped from the list
by itself, the next time the app reads the queue, and says so. The record it
keeps — where the file went — answers a question nobody can ask once the file
is gone, and the row would otherwise sit there looking like work outstanding.

That only happens on the evidence of having looked: the folder has to be
readable. A card that is out or a storage permission that was never granted
changes nothing and waits (`nibbles list` calls it **folder away**). It is the
difference between a file that was deleted and a file that cannot be seen, and
only the first one is a fact.

## Where downloads go

```
nibbles dest                        # show all three, and where they came from
nibbles dest video ~/storage/movies # where finished videos go
nibbles dest audio ~/storage/music  # where audio-only picks go
nibbles dest file  ~/storage/downloads
nibbles dest video default          # put the built-in default back
```

Or **destinations** on [the More tab](#settings) (`d`), a sheet showing all
three, which of them is a default, and a red line under any that cannot be
written to. A tap on one opens its folder in a field; the `default` preset (or
`default` typed in) puts the built-in one back.

Three destinations, because a film, a song and an installer do not belong in
the same folder on a phone. **Which one an item uses is decided by the row you
picked**, not by the file extension: an audio pick on a video sheet
goes to `audio`, and every other video goes to `video`. On a phone
that matters more than it sounds — the music player and the video player look
in different folders, and a song delivered among the films is one nothing
offers to play.

**On Termux all three default to Android's own Downloads**
(`/storage/emulated/0/Download`) — the folder the Downloads app lists and the
media scanner indexes, and one that survives Termux being uninstalled. That
needs `termux-setup-storage` to have been run once; until it has, `nibbles dest`
says so rather than letting you find out after the data is spent. Anywhere
else — the container on zero — the default stays the queue's own `out/`.

A setting is read **when the file is delivered**, not when it was queued, so
changing one moves everything already waiting in the queue as well — including
the audio ones, which is the point of them being a kind rather than a folder
chosen once. For a one-off, `nibbles <url> --dest DIR` writes an
absolute path into that item instead, and that wins over the kind.

Finished files land directly in the folder, named as they were downloaded. A
name already taken gets Android's own suffix — `report (2).pdf` — and nothing
is ever overwritten. `nibbles path NAME` tells you where one went; the queue keeps
a record, because once a file is in a folder shared with every other app on the
phone nothing can work out which one was yours by looking.

If the destination cannot be reached when the moment comes — permission never
granted, card unmounted, disk full — **the file stays in `out/<item>/`**,
complete and already paid for, with a warning in the log and a notification.
It is never half-written into a place it cannot go.

## Settings

```
nibbles settings                        # show them all, and what they are set to
nibbles settings window 45              # start downloads 45 min before the reset
nibbles settings window 2h              # ...or say it in hours
nibbles settings reserve 150            # keep 150 MB back instead of 100
nibbles settings reserve-when-paid no   # waive the reserve when paid data is there
nibbles settings paid-min 150           # ...but only with 150 MB of it left
nibbles settings auto off               # the nightly job fires and does nothing
nibbles settings notify-blocked off     # a blocked firing goes to the log only
nibbles settings budget manual          # no portal: spend a daily allowance instead
nibbles settings allowance 2GB          # ...of 2 GB a day
nibbles settings reset 05:30            # ...that starts again at 05:30, phone time
nibbles settings window default         # put the built-in default back
```

Or the **More tab** (`s` from the Queue tab), which shows the ones that
apply to the [budget source](#budget-sources) — `allowance` and `reset` only
on a manual budget, `reserve-when-paid` and `paid-min` only on zwana — as one
scrolling list of two-line rows: the key, the name and the value, then a grey
line saying what it means. It takes the same changes. **A switch toggles where
it sits**: a tap on `auto` turns it off, and a tap on `budget` steps to the
other source. **A number opens a sheet** with the field prefilled, its rule in
grey, and preset buttons (`30m 45m 1h 2h` for the window, `500 MB 1 GB 2 GB
5 GB` for the allowance) so most changes need no typing; `⏎ Set` saves it and
`esc Cancel` does not. The field takes digits — minutes for the window, MB for
the others — and an empty one puts the built-in default back. `reset` is typed
as `HH:MM` on the phone's clock. A refused value is said inside the sheet in
red, and nothing is written. `paid-min` is a row only while
`reserve-when-paid` is `no`, since it does nothing otherwise.

Below the settings, in the same layout: **skip codecs** and **quality chips**,
which are ytq's (see [ytq.md](ytq.md#the-video-sheet-and-the-formats-sheet));
**destinations** — the folder they all share, by its own name (`Download`),
or how many there are (see [Where downloads go](#where-downloads-go));
the **nightly job**, armed or not armed, which a tap arms and, after asking,
stops; the **runner log**; and **quit**. Each row's key is beside its name
(`w r p m b a n c h d j l q` on zwana, `w r b g t a n c h d j l q` on a
manual budget).

**A change stays on the tab.** The row redraws with the new value, the line
above the tabs says what it did in the setting's own sentence, and everything
the session changed is printed on the way out.

| setting              | default | what it does                                     |
|----------------------|---------|---------------------------------------------------|
| `window`             | 60 min  | how long before the 00:00Z reset downloads may start — a multiple of 15 minutes, 15 to 1440 |
| `reserve`            | 100 MB  | data kept back and never spent                     |
| `reserve-when-paid`  | yes     | keep the reserve even when paid data is on the account; `no` waives it |
| `paid-min`           | 0 MB    | how much paid data `reserve-when-paid no` wants before it waives; 0 is any paid data at all |
| `auto`               | on      | let the nightly job actually download              |
| `notify-blocked`     | on      | a firing stopped by a fault says so on the phone   |
| `budget`             | zwana, if zwana-quota imports; else manual | where the figure to spend comes from — see [Budget sources](#budget-sources) |
| `allowance`          | not set | the manual budget's daily allowance, in MB or GB   |
| `reset`              | 00:00 UTC, shown on the phone's clock | when the manual budget's day starts again |
| `destinations` (`d`) | Downloads | where finished files land, by kind — opens the destinations sheet |
| `nightly job` (`j`)  | as registered | arm the scheduled firing, or cancel it with a confirm |

A value typed as `45`, `45m` or `2h` sets the window; `150` or `150MB` sets
the reserve and `paid-min`; `on`, `off`, `yes`, `no`, `true`, `false`, `1` and
`0` all work for the switches, case-insensitively. A value hand-edited into
`config.json` that does not fit the rule — a window that is not a multiple of
15, a negative reserve — is never applied: the setting reads as its default
instead, and `nibbles settings` and `nibbles dump` both say which stored value they
declined and why, rather than letting a stray character in a file stop a
night's downloads.

A `config.json` that will not parse **at all** — a trailing comma, a missing
brace — is the same for the runner: every setting reads as its default and the
night goes ahead. It is not the same for changing one. `nibbles settings NAME
VALUE` and `nibbles dest KIND PATH` refuse and write nothing, saying which file
will not parse, and the More tab says the same line in red, because saving
on top of a file nothing can read means saving the one new key and losing the
destinations and the other settings with it.

**`reserve-when-paid no` waives the reserve; it does not lower it or remove
the guarantee behind it.** With it set to `no`, the runner stops holding the
configured reserve back on any reading where the portal says paid data is
left — the free allowance can be spent down to the runner's own margin, since
nothing is being held back for the morning. That margin is not a second
reserve to be waived in turn: it is the headroom the projection between portal
polls needs, and the haircut the free figure is discounted by because the
portal states it as an upper bound. Neither is money kept for you, and both
stand with the reserve waived. The waiver answers to the reading in hand, not
to the night as a whole: paid data bought at 23:50 waives the reserve from the
next poll on, and losing it partway through a run brings the reserve straight
back for whatever is left to download. Left at the default, `yes`, the reserve
is kept regardless of what is paid for, which is the point of having one for
most people.

**`paid-min` is how much paid data that waiver wants to see**, and it does
nothing at all while `reserve-when-paid` is `yes` — it qualifies that setting
rather than standing on its own. Left at `0`, the default, the waiver means
what it has always meant: any paid data at all, down to the last byte the
portal reports. Set it to `150` and the reserve is only waived on a reading
with at least 150 MB of paid data behind it — for the account whose last few
MB of paid data are worth less than the reserve they would stand down. It is
measured against `paid.left_bytes`, which can only understate what is actually
paid for, so asking for "at least this much" errs towards keeping the reserve
rather than towards spending it. The threshold is checked on each reading,
like the waiver itself: paid data falling below it partway through a night
brings the reserve back for whatever is left to download.

**`auto off` stops the nightly job from downloading; it does not stop the job
from running.** The job stays armed and keeps firing every ~15 minutes; each
firing does nothing, and `nibbles status` leads with **automatic downloads are
off** instead of one of the usual verdicts. `nibbles run-now` and Run now on the
Queue tab still download with the switch off, the same way `--force` still overrides
the clock: a person asking for a download now is not the schedule, and the
switch is only ever a schedule. Nothing about money moves with it — the
reserve, the per-item caps and the portal reading go on deciding exactly what
they decided with the switch on.

**`notify-blocked off` silences one notification and no others.** With it on,
a firing stopped by a fault — the portal not answering, or its reading being
too old to spend against — posts **Download queue blocked** to the phone. That
is the one that repeats: a firing lands every ~15 minutes, so a phone away
from the vessel's wifi says it all evening, which is the fastest way to teach
anyone to ignore the notification that matters. Turned off, the runner still
logs why it stopped and `nibbles status` still leads with it; only the phone goes
quiet. An item that has run out of nights, a malformed item and a download
folder that cannot be reached go on notifying either way — each happens once,
and nothing else is ever going to mention them.

## Budget sources

Every guard the runner keeps spends against one figure: how much it may spend
before the reset. Where that figure comes from is the **budget source**,
`nibbles settings budget`, and there are two.

- **`zwana`**, the crew portal, read through `~/zwana-quota`. Everything
  else in this guide describes it: the portal knows what is left, how much of
  it expires at the reset, and whether paid data is behind it, and the runner
  re-reads it while a download runs. It is the default wherever the
  zwana-quota checkout can be imported.
- **`manual`**, for a plan with no portal — a daily-reset mobile plan, a
  night bundle, a capped link. You say how much the plan gives a day
  (`nibbles settings allowance`, in MB or GB) and when its day starts again
  (`nibbles settings reset`, typed and shown on the phone's own clock, stored in
  UTC so a timezone crossed between two resets does not move it). It is the
  default on a phone with no zwana-quota checkout, and nothing about it needs
  one: the runner, `nibbles status`, `nibbles settings` and `nibbles dump` all work
  without it.

**What a manual budget may spend** is the allowance, less what the runner
itself has moved since the last reset, less the reserve, less a margin of 32
MiB for the bytes that move between two looks at a download. The runner keeps
its own ledger of what it moved, in `state.json` — every nightly item and
every `nibbles now`. **On a phone that count comes from the download itself**:
Android does not let an app read the interface counters (`/proc/net/dev` is
permission denied), so the runner reads each download's own progress report
— the figure video and file items both keep, merges and renames included — and
failing that, how much its files grew on disk, and charges either at 8% over
for what the wire costs on top. Where the interface counters can be read, they
are what is used, and they count every byte on the radio. `nibbles status` lays it
out:

```
data
   1.40 GiB the plan gives each day
        0 B spent since reset
     100 MB is always kept back
   1.27 GiB the queue may spend by 05:30
  800 KiB/s measured download speed
  what the rest of the phone uses is not
  counted; the reserve is for it
```

That last line is the limit of a manual budget, and the reason the reserve
matters more here than with the portal: **the runner counts only what it
moved.** Whatever else the phone used today — a browser, a video call — is
invisible to it, so set the reserve to cover what the rest of the day normally
takes. For the same reason a manual budget **never waives the reserve**:
`reserve-when-paid` and `paid-min` turn on a paid figure that only the portal
can give, and do nothing here.

While a download runs, the guard is the same projection the portal's floor
gets between polls: what was left when the item started, less what the
download has moved since by that same count, stopped before the reserve. There is
no portal to poll and nothing to go dark. And no flag reaches past it:
`--force` changes *when*, never how much, and `run-now --blind` has no portal
to do without — on a manual budget it is an ordinary run against the
allowance, and says so.

Two verdicts are the manual budget's own. **no daily allowance set** is said
all day, not only inside the window — it comes straight after an empty queue
and ahead of the clock, because it is a setting nobody has made yet rather
than a moment, and the place to learn that is while the phone is being set
up. It is not a fault, so it is not notified every fifteen minutes. **Spent
for the day** is the ordinary *no data to spend* verdict, in its ordinary
place, said with the allowance's figures.

A `state.json` that will not parse, or a ledger that is not a list of spends,
is a day's spending forgotten — which would read as an allowance nobody had
touched. A manual budget reads it as spent instead, spends nothing, and `nibbles
status` and `nibbles dump` say why.

`nibbles dump` has a **budget source** section: which source the next reading
comes from and how that was decided (set, or the default and why), whether
zwana-quota imports, and for a manual budget the allowance, the last and next
reset, what was spent since, and what is left to spend.

## Downloading something now

The whole point of the queue is to spend data that is about to be wiped, so
everything above waits for the window before the reset (an hour by default —
`nibbles settings window` changes it). When you need a file before then, that is
Download now on its sheet in the Queue tab — see [Downloading one
now](#downloading-one-now). Now on a video's sheet (or `nibbles --now URL`) is the
same thing for something not queued yet: it writes the item and starts it
detached, so the app stays where it was and the status bar reports the
download. Pause on the running download's sheet stops either.

Whatever starts it, the download is outside the expiring window by
definition, so none of the runner's three guarantees are in play: no reserve
floor, no midnight stop, no cap against the free allowance. What is on the
screen before it starts is the number it may spend, and whether anything is
counting it. On a [manual budget](#budget-sources) what it moved still goes
into the runner's ledger, so the window that night spends only what is left.

Everything else is kept. It downloads into the same place the nightly job
would, so pausing it is safe: what is downloaded stays, the item stays queued,
and the nightly window carries on from there. It takes the runner's lock, so it
cannot collide with a firing that is already going; and if it finishes, the
item is archived to `done/` exactly as a nightly one would be. A manual run
never counts as one of an item's three nightly attempts.

## When the portal cannot be reached

Every figure the runner decides on comes from the crew portal at
`ic.zwana.io` — how much is left, how much of it expires tonight, how much is
already paid for. The portal is on the vessel's own network, so **the phone on
mobile data cannot see it at all**, and neither can anyone while it is down.
With no reading there is nothing to spend against, so the nightly job stops and
says so:

```
data
  no reading, so nothing can be spent
  no credentials: set zwana_username and zwana_password in ~/zwana-quota/.env
  nibbles run-now --blind spends mobile data instead
```

That last line is the way through, and it is the same bargain Download now
strikes, taken for the queue rather than one item. It is also Run now on [the
Queue tab](#the-queue-tab), which asks the same single question with the same
figure on its button; on the command line:

```
nibbles run-now --blind        # run the queue with no portal reading
nibbles run-now --blind --yes  # without being asked to confirm
```

```
the queue    : 2 items, no portal reading
will spend   : up to 5.59 GiB of mobile data
run the queue now? [y/N] y
ctrl-c stops it; what is downloaded is kept and resumes
```

**That figure is what the items declared, and it is ordinary mobile data.**
There is no floor, no free-allowance cap and no measurement of what is left,
because all three are portal figures; what is left is each item's own
`EXPECT_BYTES`, which is enforced against it as usual, so the queue cannot take
more than the sum shown — only less, when an item finishes early.

Two things change with the clock, both for the same reason: there is no
expiring grant to land inside. It does not wait for the window, and **nothing
interrupts it for the time** — no nine-minute slice, no midnight stop, no
`timeout` around the download. A run cut short would only have to buy the same
bytes over again, so it works the queue until the queue is done, however long
that takes and across as many midnights as it needs.

**Ctrl-c is what stops it**, and it leaves exactly what a deadline used to: the
download stopped cleanly, the file resumable, the item still queued. Everything
else is untouched too — the per-item caps, the lock, `done/`, and the three
nightly attempts a manual run still never spends.

The flag only does anything when the portal really is unreachable. If it
answers, the run is an ordinary one with the floor and the free-allowance cap
back in force — `--blind` is what to do without a reading, never what to do
instead of one.

## What to expect

- Nothing runs before the window opens — an hour before the reset unless
  `nibbles settings window` says otherwise. Firings come every ~15 minutes and
  each works for at most ~9 minutes — Android's limit, not a bug.
- Big files span nights. Both file and video items resume from where they
  stopped; a multi-GB file finishing over several nights is normal.
- Items run in name order: the `NN-` prefix is the priority, lower first. The
  head of the queue takes what it can and the remainder flows down.
- Guarantees, whatever an item does: the configured reserve is left
  afterwards (100 MB unless changed, waived only if `reserve-when-paid` is
  `no` and paid data is there — see [Settings](#settings)), nothing runs past
  00:00 UTC, and the paid reserve is never spent. All three are measured
  against the portal, so all three are off for the two things that
  deliberately spend paid data and say so first — Download now (and Now on a
  video) and `nibbles run-now --blind`.
- `nibbles settings auto off` leaves all of the above scheduled but idle: the job
  still fires, it just downloads nothing until a person asks for it by name.

## When something looks wrong

- `nibbles status` — start here. Its first line is what the next firing would do
  and why, and the rest is what that turned on: the budget, the window, every
  item's progress and attempts, why any item was rejected, and whether the job
  is still registered. (`python3 expire_runner.py --status` draws the same
  screen, minus the job registration.) The `last run` line at the bottom is the
  heartbeat, which is also readable on its own with `cat heartbeat`.
- `logs/runner.log` is the runner's reasoning; `logs/<date>-<item>.log` is one
  item's own output for that night.
- An item in `failed/` kept its logs and its attempt history in `state.json` —
  diagnose before re-queueing. Its sheet on the Queue tab reads its log
  (`l Its log`) and puts it back (`u Queue again`), which also clears the
  three spent nights; by hand it is a
  move back into `queue/`, and the attempts have to be cleared too or the first
  firing to touch it gives up on it again.
