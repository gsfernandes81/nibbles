# Queue contract

Scripts here are run by the nightly runner (`expire_runner.py` in the queue
root) in the window before the daily reset — 00:00 UTC on the zwana portal's
plan, or the `reset` a manual budget sets; an hour by default, and `nibbles
settings window` changes it — to spend data that would otherwise expire. Drop
an item in and it runs on the next night there is allowance for it.

## Required header

```python
#!/data/data/com.termux/files/usr/bin/python3
# EXPIRE: v1
# EXPECT_BYTES: 4200000000
# PARTIAL: yes
# SLICE_MIN_BYTES: 33554432
# DESC: Ubuntu 24.04 desktop ISO
```

| Field | Required | Meaning |
|---|---|---|
| `EXPIRE: v1` | yes | marks the file as an item at all |
| `EXPECT_BYTES` | yes | honest total in bytes, rounded up, including overhead |
| `PARTIAL` | no | `yes` = can take a slice smaller than the total and resume |
| `SLICE_MIN_BYTES` | no | smallest slice worth starting (default 32 MiB) |
| `DEST` | no | where the finished file is put — see below |
| `SOURCE` | no | what this is a download *of*, for spotting duplicates |
| `DESC` | no | shown by `nibbles status` |

`DEST` is `video`, `audio`, `file`, or an absolute path. The three words are
the destinations `nibbles dest` configures — `video` and `audio` are where a
video or an audio-only pick goes, `file` where a direct file download goes —
and they are **resolved when the file is delivered**, not when the item was
queued, so changing one moves what is already waiting in the queue too. An
absolute path overrides all three.

`SOURCE` is an opaque identity, not a URL to fetch: a video is written with
its extractor and id (`youtube:<video id>`), a file download with
`url:<the url>`. Nothing downloads from it and the runner ignores it entirely —
it exists so that queueing the same video twice can be noticed *before* it is
paid for twice, whichever URL it is pasted as. An item without one can still
be recognised by its name, which is the same title, which is usually but not
always the same thing; `nibbles` says which of the two it matched on.
Hand-written items need not carry it.

**No `DEST` means the file stays in `out/<item>/`**, which is what every item
did before this existed. The item always downloads into `out/<item>/` either
way; the runner moves it afterwards, so an unreachable destination leaves the
file safe and paid-for where it landed rather than half-written somewhere else.

The header is parsed **statically** — the script is never executed to ask it
anything, because an `--estimate` mode would mean running unvetted code outside
the guarded window, exactly where a bug could spend data before any guard
exists. A file without a valid header is skipped, logged and notified.

Anything named like an item is parsed, whether or not it is one — `ITEM_RE` is
just `NN-`, so a photo saved here as `20-holiday.png` counts as a claim to be an
item and is reported as a rejected one. That is deliberate: silently ignoring it
is how a genuinely broken item goes unnoticed. Move stray files out of `queue/`
rather than leaving them to be reported every night.

`EXPECT_BYTES` is also the **cap enforced against the item**, so declare the
most you are willing to let it cost. "Unknown" is not a valid answer.

> **Shebang:** must be `#!/data/data/com.termux/files/usr/bin/python3`.
> `/usr/bin/env` does not exist on Termux and the runner rejects an item whose
> interpreter is not on disk — deliberately, because otherwise exec fails with a
> bare "No such file or directory" naming the *script*, which reads as though it
> vanished.

## Naming and order

`NN-name.py` — items run in strict lexicographic order, so `NN` is your
priority, always two digits (`100` would sort before `20`). Ordering is
completion-first and never interleaved: the earliest item takes what it can
and the remainder flows down the queue. A very large item at the head will
legitimately occupy whole nights; that is a naming decision, and Move on the
Queue tab (`nibbles queue`) is where it is made.

An item's name is also the name of its partial in `work/<item>/`, its outbox
in `out/<item>/` and its record in `state.json`, so never give a new item a
name something there still answers to: it would inherit that one's bytes and
its history. `nibbles` adds ` (2)` to a title already in use for that reason.

Stage new items in `.staging/` and `mv` them into `queue/`, so the runner never
sees a half-written file.

## Environment the item receives

| Variable | Meaning |
|---|---|
| `EXPIRE_SLICE_BYTES` | payload bytes **this slice** may take, already derated for wire overhead |
| `EXPIRE_BUDGET_BYTES` | same value; kept for items written against the older contract |
| `EXPIRE_TOTAL_BYTES` | the item's own `EXPECT_BYTES`, echoed back: a cap on spending, never the file's size |
| `EXPIRE_STOP_EPOCH` | UTC epoch second the item will be killed at; `0` is no stop time |
| `EXPIRE_RUN_ID` | nonce to stamp into the status file |
| `EXPIRE_WORK` | scratch, **persists between nights** — download here |
| `EXPIRE_OUT` | finished artifacts, and only when complete |
| `PYTHONPATH` | the nibbles package first, so `from nibbles import …` works whatever path the item was written with |

The item also inherits the runner's lock, open, and holds it for as long as it
runs: a download outlives a runner killed outright, and the queue must not
look free while it is still writing.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | finished; archived to `done/`, never runs again |
| `75` | not finished — took a slice, or could do nothing. Stays queued, no strike |
| anything else | failed attempt; after 3, moves to `failed/` |

`75` covers both "made progress" and "did nothing" because that distinction is a
*quantity*, not a state — it belongs in the status file. An item that returns
`75` while moving under 1 MiB despite being given room and time accrues a stall
strike, and three of those count as one failed attempt, so nothing can sit in
the queue forever.

## Use the shared downloader

`expire_dl` handles slicing, resume, validators and reporting. For a direct
file URL, `nibbles <url>` writes this whole item for you, sized from the
server's own headers, and `nibbles <url> --dry-run` prints the item it would
write for this install without queueing it. What it writes looks like this:

```python
#!/data/data/com.termux/files/usr/bin/python3
# EXPIRE: v1
# EXPECT_BYTES: 6302290248
# PARTIAL: yes
# DEST: file
# SOURCE: url:https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso
# DESC: ubuntu-24.04-desktop-amd64.iso (5.69 GiB, direct download)
"""ubuntu-24.04-desktop-amd64.iso

https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso

Sized 6,114,656,256 bytes by a header probe on 2026-10-16; EXPECT_BYTES adds a
3% + 4 MiB margin for wire overhead and retries.
"""

import sys

sys.path.insert(0, "/data/data/com.termux/files/home/nibbles")
from nibbles import expire_dl  # noqa: E402

sys.exit(expire_dl.run(
    "https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso",
    "ubuntu-24.04-desktop-amd64.iso",
    expect_sha256=None,
    total_hint=6114656256,
))
```

The `sys.path` line names the directory the `nibbles` package is in — a
checkout, as here, or an installed copy's site-packages. The runner and
`nibbles now` also put the package first on the item's `PYTHONPATH`, so an
item whose line names a directory that has since gone (a reinstall moves the
package) still imports it; a hand-written item can rely on that and leave the
line out. Termux's own interpreter runs the item, and knows nothing of a
tool's virtual environment, so `from nibbles import expire_dl` is the import:
never a bare `import expire_dl`, which only a checkout's root answers.

`expect_sha256` takes the digest however it was pasted — hex in either case,
a `sha256:` prefix, or a whole `sha256sum` line — and anything that is not
64 hex digits is a failed attempt before a byte is fetched, never found out
after the whole file was paid for.

It requests `Range: bytes=off-(off+slice-1)`, so the **server** ends the
transfer at the slice boundary rather than the item racing to abort locally.
The resume offset is always `stat(.part).st_size`, and writes are append-only,
so whatever is on disk is a valid prefix of the remote file however the
process died — and nothing is ever appended to a part that is not that file's:

- **A server that ignores `Range`** answers with the whole file. From byte 0,
  one that says it is bigger than the slice is closed unread and remembered,
  so no slice is bought that nothing could resume; from then on a firing
  whose slice cannot hold the whole file is a failed attempt, so a file too
  big for one firing is set aside rather than a doomed slice being bought
  every night. `nibbles
  <url>` looks first, and a server it sees ignore `Range` is written
  `PARTIAL: no`, so the runner offers that item only a firing that can take
  all of it.
- **One 200 to a resumed request** is not yet such a server: the part is kept
  and the next firing asks again. Validators that differ mean the file was
  re-published, and the part is discarded; only a second 200 in a row is a
  server that cannot resume. A 206 forgets what the 200s taught.
- **A body of unstated length** is delivered where it ends. From a server
  that ignores `Range`, one that is still going at the end of the slice is
  discarded and remembered, and one that runs past the whole cap it was
  queued under is a failed attempt, never delivered cut short at the cap.
- **An answer that is not the file** — a web page where the file should be,
  or a status that means the link has died (403, 404, 410…) — leaves the
  part, the validators and the size exactly as they were: twice it is "not
  tonight", and from the third in a row on it is a failed attempt. A busy
  server (408, 425, 429, any 5xx) or one that cannot be reached is only ever
  "not tonight".
- **A file already in `$EXPIRE_OUT`** with no part beside it was delivered by
  a firing stopped before it could archive the item, and is reported complete
  rather than fetched again.

## Videos: `nibbles <url>` too

`nibbles <url>` on a video page writes the item for you, from its video
sheet. It runs a metadata-only extraction, lists every format with the size
yt-dlp states for it, and puts that figure in `EXPECT_BYTES` with a stated
margin — so the cap is a measurement rather than a guess, which is the whole
reason "unknown" is not allowed there. It stages and renames, as above.
`nibbles --list <url>` prints the same table without writing anything;
`nibbles --from-json FILE` re-uses a saved `yt-dlp -J` dump so changing your
mind costs no data.

The item it writes calls `ytdl_item.run(...)` (`from nibbles import
ytdl_item`), which invokes **yt-dlp on every firing** rather than resolving a
media URL once and handing it to `expire_dl`. That is deliberate: media URLs
are signed and expire in about six hours, so a video spanning two nights would
resume against a dead link. yt-dlp re-extracts each firing and resumes its own
`.part`.

The trade against `expire_dl`, which is worth knowing before choosing:

| | `expire_dl` | `ytdl_item` |
|---|---|---|
| slice edge | the server stops at the byte boundary — exact | watches the file grow and stops the child; lands a second or two short |
| resume across nights | dies when a signed URL expires | re-extracts every firing |
| per-firing overhead | none | one extraction, ~0.1-0.5 MB |

`nibbles <url>` makes the choice by asking the server's headers (~1 KB): a
web page goes to yt-dlp and the video sheet, anything else is a file for
`expire_dl`.

## What the runner guarantees whatever an item does

- **The configured reserve left afterwards** — 100 MB by default, changed with
  `nibbles settings reserve` and waived (only) when `reserve-when-paid` is `no`
  and the portal reports paid data left. Checked against the portal's
  measured remainder every 60s during a transfer, and projected down between
  polls by what the download has moved: the interface counters where they can
  be read, which over-count and so err safe; and on a phone, where an app may
  not read them, the item's own report of what it fetched this run (the
  status file), else how much its `work/` and `out/` grew, charged 8% over for
  the wire.
- **Nothing runs past the reset** — a `timeout` wrapper decided at spawn holds
  even if the runner dies.
- **The paid reserve is never spent** — the budget is capped by the free
  allowance, discounted because that figure can only over-state.

On a manual budget there is no portal: the reserve is kept against the daily
allowance less what the runner has counted since the reset, projected down in
flight by the same count, and never waived.

The item's self-imposed stop is deliberately earlier than every one of those, so
a well-behaved item is never killed and always leaves a resumable file.

All three are read off the portal, so all three are gone when it cannot be
reached — the phone on mobile data, or the portal down — and a run in that state
has to be asked for by name (`nibbles run-now --blind`, which says what it will
spend and waits for a yes). **Nothing about the contract changes**, and no item
needs to know it is happening: it is still handed `EXPIRE_SLICE_BYTES`, still
killed if it crosses its cap on the wire, and still expected to leave a
resumable file. What holds a blind run in is `EXPECT_BYTES` — enforced against
the item exactly as it always is, and now the only ceiling there is.

The one field that reads differently is `EXPIRE_STOP_EPOCH`, and only because a
blind run has no deadline to put there: it arrives as **`0`**, which the
contract already defines as "no stop" and which `nibbles now` has always
passed. An item that honours it needs no change; one that assumed a non-zero
epoch was already wrong for `nibbles now`.
