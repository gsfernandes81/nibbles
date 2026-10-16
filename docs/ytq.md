# ytq — find a video and queue it for overnight download

(ytq is the YouTube half of nibbles; its command is `nibbles` now.)

`nibbles` searches YouTube and queues what you pick for the
[overnight download queue](download-queue.md). It asks yt-dlp for **metadata
only** (~0.1–0.5 MB, no media), shows every format with the size yt-dlp states
for it, and writes a queue item with that measured size as its spending cap.
The video itself downloads during the nightly window and appears in your video
download directory — on the phone that is Android's Downloads until you point
it somewhere else with `nibbles dest video <dir>`.

## Use

```
nibbles            # the app, on its Search tab: search, or paste a URL
nibbles search crust of rust  # straight to the results
nibbles <url>          # straight to that video's sheet
nibbles --now <url>    # its sheet, set to start it now
```

`nibbles <url>` takes what yt-dlp itself would take: a link with or without
its scheme (`youtu.be/dQw4w9WgXcQ`), a bare video id (`dQw4w9WgXcQ` — asked of
yt-dlp's own extractors, offline), or `ytsearch:words`, which is the search.
Anything that is not a page — a plain file URL — is queued as a file download
instead; which it is comes from the server's headers (~1 KB), never the name.

- **A word on its own is never a video.** YouTube's extractor would take any
  eleven letters as an id, so `nibbles programming` would have bought a probe
  of a video that does not exist; anything shaped like a word (letters, lower
  case after the first, hyphens between) is refused before yt-dlp is asked,
  and costs nothing. `nibbles search programming` searches for it. The rare
  real id that looks like a word goes in as `youtu.be/<id>`.
- **yt-dlp's own words for your lists** work too: `nibbles :ytsubs` opens the
  Feed tab and `nibbles :ytwatchlater` the Later tab, exactly as typing them
  in the field does — never a probe of the whole feed as if it were a video.
- **Flags go anywhere**: `nibbles --dest ~/storage/dcim <url>` and `nibbles
  <url> --dest ~/storage/dcim` are the same, and a flag's value is never
  taken for the link. `ytsearch:crust of rust` needs no quotes; its words are
  searched in the order typed.
- **`--now` and `--list` are the video's**: `nibbles --now <id>` opens that
  video's sheet set to start it, and `nibbles --list <id>` prints its formats.
  Only a bare `nibbles --list` is the queue's own listing (`nibbles list`).
- A link goes on in one spelling, its scheme added and anything not ASCII
  escaped, so the headers asked, the item written and the duplicate check all
  see the same link.

`nibbles` is the one command once installed — see
[Installing](download-queue.md#installing-the-commands). Uninstalled, it is
`python3 -m nibbles <url>` from `~/nibbles`, and every `nibbles` line below reads the
same way. `nibbles help` lists every word it takes.

`nibbles` opens one app with five tabs along the bottom — **Search · Feed · Later
· Queue · More** — on Search. The first three are YouTube; Queue is the queue
itself, which is what `nibbles queue` opens. How the app works as a whole — sheets,
buttons that show their key, taps and drags, the scrollbar, the status bar —
is in [The app](download-queue.md#the-app). What matters here:

1. **Search** — the field at the top takes words to search for, a pasted
   URL, or `subs` and `wl`, which go to the Feed and Later tabs. It tells
   them apart by looking, so there is one field rather than three. `⏎ Go`
   searches; what it costs is printed underneath before you spend it. A
   paste goes into the field whole, line breaks and all as spaces, and never
   searches by itself: ⏎ or Go does. Go again on the same words while they
   are still being fetched buys nothing more.
2. **Results** — 20 hits under the field (the Feed and Later tabs list 30),
   each a two-line row: the title, then the channel, the age, the length and
   the views. **One tap on a row opens its video sheet** and starts asking
   YouTube for its formats; ↑↓ and enter do the same from the keyboard, and
   ←→ (or page up/down) jump a screenful. **Each list keeps its place** for
   the session: closing a sheet, switching tabs and back, a deeper look and a
   re-read all leave you where you were rather than at the top.
3. **The video sheet** — a quality, then **At 03:00** or **Now**, then the
   button at the bottom, which carries the size: `⏎ Queue for 03:00 · 92
   MiB`. See [The video sheet](#the-video-sheet-and-the-formats-sheet).

Queueing closes the sheet and leaves you on the row you were on, with a `✓`
on it and `queued <name> · 92 MiB` on the line above the tabs — so finding
three things to download is one search rather than three. A `✓` is also on
anything the queue *already* holds — queued, downloaded or given up on — so
most repeats are visible in the list before a single byte is spent asking
about them. If the item cannot be written at all — a full phone — a notice
says so over the sheet, which stays as it was, so trying again is the same
tap.

## It will not queue the same video twice

A video that is already in the queue or has already been downloaded says so
on its sheet, directly above the button, and the button changes:

```
 ✓ downloaded 2026-08-11
 ╭──────────────────────────────────╮
 │     a Queue it again anyway      │
 ╰──────────────────────────────────╯
```

Esc closes the sheet and nothing is queued. Nothing about it is a guess: an
item records what it is a download of (`# SOURCE: youtube:<video id>`), so the
same video is recognised however its URL was written — `youtu.be/x`,
`watch?v=x`, `watch?v=x&list=…` are one video, not three.

Items queued before that header existed have no id, so they are matched on
their name instead — the same title, which is usually but not always the same
video. The line says which of the two it matched (`same name, done
2026-08-11`), because they are not equally good evidence.

The check is in the one line every route to a queue item goes through, so it
covers the search, a pasted URL, `--now` and `--from-json` alike; a plain file
queued by `nibbles <url>` is the same, keyed on the URL, with `--again` for
meaning it.

When you leave, it prints what the session queued:

```
queued 50-Some Talk.py — 487 MiB (1080p mp4), cap 506 MiB
```

**A download is named after its title**, cleaned only of the characters
Android's shared storage refuses (`/ \ : * ? " < > |`) and put on one line
(a TikTok caption keeps its line breaks; they become spaces). The download
then runs on the next night(s) with allowance to spare, and the finished file
appears in the video download directory as `Some Talk.mp4`. `nibbles list`
shows progress and `nibbles path "some talk"` says where it went.

Two downloads with one title — two videos that share it, or the same one
queued again on purpose — are two items: the second is `Some Talk (2)` in the
queue, because an item's name is what its partial and its record are kept
under, and sharing one would resume one video's bytes into the other. Its
file still arrives as `Some Talk.mp4`, or `Some Talk (2).mp4` beside the
first.

```
nibbles dest video ~/storage/movies   # change it for everything
nibbles --dest ~/storage/dcim <url>    # or for this one only
```

## Where it goes in the queue

New videos are queued **last** and downloaded in the order the queue is in, so
most of the time there is nothing to decide. When there is, the order is the
Queue tab's business, not the video sheet's: tap the download there, then
**Move**, and the cut line shows what the window reaches as you move it — see
[Moving a download](download-queue.md#moving-a-download). The video sheet has
no place row and no name row: the name is the title, and a rename is on the
download's own sheet.

## Searching

One search is a single request — about 0.1 MB, the same order as the metadata
extraction `nibbles` already runs, so it is not asked about separately. Nothing is
downloaded until you press the button on a video's sheet.

```
 20 results · ~ dates approx
   Crust of Rust: Lifetime Annotations
   Jon Gjengset · ~5y · 90m34s · 312K
 ✓ Rust Lifetimes Finally Explained
   Let's Get Rusty · ~2y · 26m01s · 1.4M
```

- **The age is approximate, and says so.** YouTube's search page gives a
  rounded phrase ("4 months ago"), not a date, so `nibbles` shows `~4mo` rather
  than inventing a day. `<1d` is anything posted today; `?` means the answer
  came back with no date at all, which happens.
- **The views are shortened the way YouTube does it**: `842`, `1.2K`, `34M`,
  `1.1B` — one decimal under ten, truncated rather than rounded, so a count is
  never shown as more than it is. A result that came back without one shows
  nothing there rather than a `?`.
- A grey line too long for its row ends in `…`; the views are last on it, so
  they are the first to go on a narrow phone.
- `✓` marks what the queue already holds, and what this session queued.
- Getting the words wrong costs the search again, so the field keeps what you
  typed: tap it (or `/`) and fixing a typo is an edit, not a retype. Esc from
  the results goes back to **Recent** — this session's searches and feeds —
  and repeating one of those is free.
- While a search runs, a spinner and `x stop` sit under the field; `x` (or a
  tap on it) cancels it.
- No paging. Asking for the next twenty re-fetches the first twenty to get
  there, so better words are always cheaper than a second page.

Searches go through your `~/.config/yt-dlp/config` like everything else, which
matters — see the bot-check section below.

## Your subscription feed

The Feed tab — or `subs` in the field — reads the
newest 30 videos from the accounts you follow. It reads itself the first time
you open the tab in a session. The rows are a search's rows, so a video out of
the feed is picked, sized, marked and queued exactly as a search hit is.

```
 30 videos                 ╭───────────╮
 read 3m ago · 0.2 MB      │ r Re-read │
                           ╰───────────╯
   Crust of Rust: Subtyping and Variance
   Jon Gjengset · ~3d · 90m34s
 ✓ Making a Case for Rust
   Some Channel · ~1w · 12m40s
 ╭──────────────────────────────────────╮
 │      ↓ 30 more · 0.4 MB in all       │
 ╰──────────────────────────────────────╯
```

- **The button at the foot goes further back**, thirty at a time, up to 150.
  The figure on it is the price of the next look before you take it — and it
  is the **total**, not the extra thirty, because YouTube's pages are
  sequential: there is no asking for videos 31–60 without walking 1–30 to
  reach them, so going deeper re-buys what is already on screen. Five looks is
  0.2 + 0.4 + 0.6 + 0.8 + 1.0 MB, so going deep is worth doing in one decision
  rather than five idle taps.
- **Only a deliberate act reads it**: a tap on that button, ↓ on the last row,
  or a *fresh* drag down after the list has rested at its end for about half a
  second. **A fling's momentum never does** — it arrives as one unbroken stream
  of scrolling, which never rests and then pulls again — so a flick that
  carries the list to its end stops there.
- **Going deeper keeps your place.** The videos already on screen keep their
  positions when the list grows underneath them, so a deeper look carries on
  from where you were reading. After one asked for with ↓, the cursor steps
  onto the first video that just arrived. ←→ jump a screenful, which is what
  150 rows needs.
- **The deeper look switches itself off at the bottom of the feed.** If
  YouTube hands back fewer videos than were asked for, that is everything it
  has, and the foot says `that is the whole feed` instead of a price. At 150
  it says `at the 150 cap`, which is the different sentence: there *is* more
  and ytq will not spend it. A deeper look that fails changes nothing — the
  count and the price go back to what is actually on screen — and says why,
  on a notice over the rows you were reading, as a Re-read that fails or
  comes back empty does. (One that lands while you are on another tab is said
  when you come back.)
- **The selected title scrolls when it does not fit.** Only the one under the
  cursor, slowly, and only when it is genuinely too long for the room; every
  other row keeps its `…` and stays still, because a list where every line
  slides is a list nothing can be read off. Moving the cursor starts the new
  title from its beginning. A screen with nothing to scroll writes nothing to
  the terminal and costs no wakeups at all.
- **It needs the stored cookie**, and the Feed and Later tabs are the only
  ones that do. The feed is a signed-in page; the jar is the same
  `~/.config/yt-dlp/cookies.txt` the bot-check section below is about, wired in
  by the `--cookies` line in `~/.config/yt-dlp/config`. `nibbles` reads that config
  itself — the one yt-dlp reads, which is the first of its config files that
  exists, with `~` and `$HOME` in the jar's path expanded as yt-dlp expands
  them — and refuses **before** spending anything if there is no cookie line,
  or the file it names is not there — the tab says which, in place of the list.
  A `--cookies` line in a config file yt-dlp never gets to is pointed out
  rather than trusted.
- **An empty feed is never reported as "nothing new."** YouTube answers a
  logged-out feed with no entries rather than with an error, so an empty answer
  means the cookies have expired. The tab says exactly that, and how old the
  jar is.
- **One page is about 0.2 MB.** Bounded on purpose: yt-dlp will follow every
  continuation YouTube offers, which for a few years of subscriptions is
  hundreds of pages on the mobile radio. `SUBS_RESULTS` in `ytq.py` is the
  first bound and `SUBS_MAX` is the last one; the 0.2 MB is an estimate by
  analogy with the search page and has not been measured on the vessel's link.
- **It is kept for the session**, so leaving the tab and coming back costs
  nothing — and because it is, the line beside `r Re-read` says how old what
  you are looking at is. Re-read reads it again at the depth you have reached,
  for the figure on that line.
- The dates are approximate exactly as the search's are, and `✓` marks what the
  queue already holds before anything is probed — which on a feed is worth more
  than on a search, because the feed shows you the same videos every day until
  you do something about them.
- `nibbles --list subs` prints the first page and writes nothing, for a pipe or
  an ssh session with no terminal. Going deeper is a screen thing: it is a
  decision with a price on it, and a price belongs on a screen somebody is
  looking at.

## Your Watch Later playlist

The Later tab — or `wl` in the field, `watch later`, or the playlist's own
URL (in the field or as `nibbles <url>`), `youtube.com/playlist?list=WL` — reads the first 30
videos of your Watch Later playlist. Everything in the feed section above
holds for it too, on the same cookie, the same bound and the same prices: the
foot goes deeper, thirty at a time to 150, and says the total first; Re-read
reads it again; it is kept for the session; `✓` marks what the queue already
holds. The two lists are read to their own depths, so going deeper in one does
not re-buy the other.

```
 3 videos                  ╭───────────╮
 read just now · 0.2 MB    │ r Re-read │
                           ╰───────────╯
   Saved For Tonight
   Jon Gjengset · ~1d · 10m00s
   that is the whole list
```

- **The order is YouTube's.** Whatever the playlist is sorted by there
  (manual, date added, …) is the order here; ytq does not re-sort it.
- **The dates are the videos' upload dates**, approximate as everywhere else —
  not when you added them.
- **An empty Watch Later says both things it can mean.** Unlike the feed, it
  can really be empty — but a signed-out session reads the same way, so the
  tab says both, and how old the jar is.
- **A video opened *from* Watch Later is that video.** Its URL carries
  `&list=WL`, and pasting it opens that one video's sheet; only the
  `/playlist?list=WL` page itself is read as the list.
- **Queueing from it does not remove anything from it.** ytq only reads.
- The 0.2 MB a look is the feed's estimate carried over, not a measurement;
  a playlist page holds more rows than a feed page, so it may well be less.
- `nibbles --list wl` prints the first 30 and writes nothing.

## The video sheet and the Formats sheet

The sheet opens on the tap, with the title and byline the row already had,
and the format fetch starts at once: `asking YouTube for formats`, `~0.3 MB`,
with the button drawn but doing nothing until the answer lands. Closing the
sheet does not cancel the fetch — the answer is kept for the session, so the
same video opens again at once and for nothing; `x` is what stops it, and the
sheet closes with it.

```
 Crust of Rust: Subtyping an…  esc ×
 Jon Gjengset · ~3d · 90m34s · 41K
 Quality ─────────── 480p · 3 formats
 [ 240p ][ 480p ][ 720p ][ audio ]
 [◉ Smallest ][○ Largest ][ Formats ]
 92 MiB · mp4 · avc1+mp4a
 [   ◉ At 03:00   ][     ○ Now      ]
 [    ⏎ Queue for 03:00 · 92 MiB    ]
```

(On the phone each button is a three-row box; here it is one row.)

- **The quality buttons are the heights you use**: the three you have picked
  most (240p, 480p and 720p until you have picked anything), or the ones set
  by hand under `quality chips` on the More tab — plus `audio`. A height this
  video does not offer is grey; other heights are under Formats. Set more by
  hand than the row has room for and it shows the one you are on and those
  around it, never narrower buttons; the rest are under Formats. `audio`
  turns the row into bitrates, with `← video` first to go back.
- **Smallest | Largest** picks within that height. Which one you used is
  remembered, separately for video and audio, along with the format you chose
  last, so the sheet opens on your usual and most videos take no taps but the
  button. With nothing remembered it opens at the height nearest 480p.
- **Skip codecs** on the More tab names codec families Smallest and Largest
  pass over (nothing, until you set it). They never empty a height: with
  nothing else left, a skipped one is offered after all. `skipped vp9` in grey
  says when one was passed over that would otherwise have won.
- **The size is the one figure**, with the container and the codecs beside
  it, and it is on the button. It is coloured by how many nights it will
  take — green fits inside one window comfortably, amber is most of one, red
  spans several, and a red one also says how many in words (`(3 nights)`). `~` marks a size yt-dlp only estimates; the cap takes a 12%
  margin instead of 3% to cover it.
- **At 03:00 | Now** — the time is when the next window opens, on your
  phone's clock (`the window` until the queue's reading is in). Now is
  [below](#downloading-it-now).
- Keys: `s` and `l` for Smallest and Largest, ←→ step the height, `f` opens
  Formats, `n` switches between At and Now, enter is the button. **`c` copies
  the video's page URL** to the Android clipboard (needs the Termux:API app),
  and says so on the sheet.
  The page URL, not a stream URL — streams are signed and expire in hours.

**Formats** is a sheet over the video sheet with every format the video
offers, grouped by height (audio last, by bitrate), smallest first in each, and
opened at the height you were on:

```
 Formats · 480p ╱╱╱╱╱╱╱╱╱╱╱╱╱  esc ×
 smallest first · ~ an estimate
 480p ──────────────────────────── 3
      71 MiB~  480p webm
    vp9 + opus · skipped
  ●    92 MiB  480p mp4
    avc1.4d401e + mp4a.40.2
      104 MiB  480p mp4
    av01.0.04M.08 · skipped
```

- A tap on a row picks it and goes back to the video sheet; ↑↓ move the pick
  through the list and enter goes back with it.
- **The selected row (`●`) says its codecs in full** — `avc1.4d401e +
  mp4a.40.2`, exactly as yt-dlp reported them. The other rows carry only the
  family (`avc1`, `vp9`), and which av01 profile a stream is decides whether
  the player on the other end can play it.
- A row in a skipped codec is dimmed and marked `skipped`, but can still be
  picked.
- `merged` rows download video and audio separately and merge locally — the
  size shown is both together.
- Formats yt-dlp states **no size** for are left out, and counted on the top
  line (`· 2 unsized`): the queue needs a measured cap, not a guess. A video with no sized format at all says so on a
  sheet of its own.
- **A list holding nothing but 360p says why.** If YouTube sent only the legacy
  progressive stream, that is the bot check and not a video that only exists in
  360p — the video sheet says `bot check` on a line of its own, and the first
  time it happens in a session you get the whole explanation and the one
  command that diagnoses it. It is told apart from the case above by the
  *absence of adaptive streams*, not by the symptom: both end up as one 360p
  row, and they have different fixes.

## Without the picker

```
nibbles --list <url>            # print the table, write nothing
nibbles --list subs           # print the subscription feed, write nothing
nibbles --list wl             # print Watch Later, write nothing
nibbles --from-json dump.json   # reuse a saved 'yt-dlp -J' dump —
                            # changing your mind costs no data
```

`--from-json` takes a saved search too — a `yt-dlp -J --flat-playlist
'ytsearch20:…'` dump opens as results on the Search tab instead of a video
sheet, and `--list` prints those rows rather than formats. That is how the
screens can be worked on without spending anything.

## Downloading it now

Choose **Now** on the video sheet (or press `n`), or pass `--now`. The button
becomes `⏎ Start now · 92 MiB` in the spend style, and one grey line under
At/Now says what differs: `today's allowance, no reserve kept`. That button is
the one yes — there is no second question.

**On the vessel's wifi the window and Now come out of the same allowance**;
what Now changes is that no reserve is kept and nothing waits for the window.
Off the vessel's wifi — zwana not answering — the line says `on mobile data,
charged` and the button turns red, because that is ordinary mobile data,
charged normally, with nothing counting it.

It runs **detached**, so choosing it does not end the session: the sheet
closes, the status bar along the foot shows `↓ 18%` and the download's name,
and you can carry on queueing. Leaving the app leaves the download running.
On the Queue tab, a tap on its row opens the running download's sheet, where
**Pause** (`x`) stops it — what has downloaded stays on disk and the item
stays queued, so the next window carries on from where you stopped.

That sheet also has **Open it when done** (`o`), for a download this session
started: ticked, the file is handed to Android with `termux-open` the moment
this run delivers it. The ask lives in the app and nowhere else: quit and it is
gone, and a download that is paused or stops short never opens anything, not
even when a later run finishes it.

**Opening needs one line of Termux setup**: `allow-external-apps = true` in
`~/.termux/termux.properties`, then `termux-reload-settings` ([the
README](../README.md#termux-once-first) has the commands). Since termux-app
0.118, Termux shares no file with another app without it, and `termux-open`
still says it worked — so nibbles asks first. Open it when done, and Open it
on a finished download's sheet, say what they came to, and refuse aloud,
before anything is handed over, what Termux would refuse in silence:

- the file is no longer where it was delivered (`it is not in
  ~/storage/downloads any more`);
- Termux may not read it (`run termux-setup-storage`);
- it is outside Termux's own folders and internal storage — an SD card
  (`move it to internal storage, or set its destination there in More`);
- Termux has not been told it may share files (the line, the file, and
  `termux-reload-settings`; the value must be exactly `true`).

Otherwise the answer is `opened film.mp4` — which means Android was handed
it; what the app it went to made of it is not told — or `could not open
film.mp4`.

Only one at a time: the queue takes an exclusive lock, so asking for a second
while one is going says so and leaves the second queued. It still writes the
queue item first either way, so it shows up in `nibbles list`, and
`nibbles path <name>` says where it landed.

## When YouTube says "Sign in to confirm you're not a bot"

Nothing to do with the video — YouTube is refusing the extraction. Two causes,
both handled in `~/.config/yt-dlp/config` rather than in `nibbles`:

- **No JavaScript runtime.** YouTube's "n" challenge has to be solved or the
  formats are withheld. yt-dlp only enables `deno` by default and this device
  has `node`, hence `--js-runtimes node` in the config, plus the solver scripts
  from `pip install yt-dlp-ejs` (~53 KiB, one-off). Without both you get
  storyboards and nothing else.
- **The vessel's IP is rate-limited.** The watch page comes back HTTP 429, so
  there is no visitor data and so no PO token. Cookies from a logged-in session
  get past it — `~/.config/yt-dlp/cookies.txt`, wired in by the `--cookies` line
  in the config. Without them the same URL either fails outright or lists a
  fraction of the formats it really has (one 320p entry, on the video this was
  first debugged with, against thirty up to 960p60 with them).

  **Check the version first.** YouTube breaks yt-dlp faster than anything else
  here, and a stale copy produces exactly this symptom with a perfectly correct
  config — that is what happened on 2026-08-28, where 2026.7.4's authenticated
  default client had stopped working and the fix had been released nine days
  earlier. `nibbles`'s own notice leads with the version and the right upgrade
  command for how it is installed; by hand it is:

  ```
  head -1 $(command -v yt-dlp)     # which python owns it
  uv tool list                     # or whether uv does
  ```

  A shebang under `uv/tools/` means `uv tool install yt-dlp --with yt-dlp-ejs
  --force` — **not** `uv tool upgrade`, which answers "Nothing to upgrade" and
  does nothing if the tool carries any version constraint. (`nibbles` reads
  uv's own record of the install and keeps what it says: the tool's extras,
  such as `'yt-dlp[default]'`, and every `--with` with its own extras and pin;
  only yt-dlp's own pin is left behind.) yt-dlp's own release — the
  single-file zipapp, or the built binary with no shebang at all — updates
  itself: `yt-dlp -U`. Anything else means `<that python> -m pip install -U
  yt-dlp`, `<that python>` being the one the shebang names, or the one an
  `env` shebang finds. Do not read the `(pip)` marker in `yt-dlp -v` as an
  answer: it says `(pip)` under a uv tool too.

  **Checking the other two halves takes one command, no URL and no data:**

  ```
  yt-dlp -v 2>&1 | grep -i 'js runtimes\|optional lib'
  ```

  ```
  [debug] Optional libraries: sqlite3-3.45.1, yt_dlp_ejs-0.8.0
  [debug] JS runtimes: node-22.22.2
  ```

  That is what working looks like. `JS runtimes: none` means the challenge
  cannot be solved; a missing `yt_dlp_ejs` means the solver scripts are not
  installed **for the yt-dlp that actually runs**. That last part is the trap:
  `nibbles` is a `uv` tool whose venv does not carry yt-dlp, on purpose, so it
  falls back to the `yt-dlp` binary on `PATH` — and `yt-dlp-ejs` has to be
  installed alongside *that* one, not alongside `nibbles`. `yt-dlp -v` reports for
  whichever it is, which is why the check is that rather than a `pip list`.

  Where to install it depends on where that yt-dlp came from — the same
  `-v` output says, on its version line: `(pip)` means
  `pip install yt-dlp-ejs` into the python owning `$(command -v yt-dlp)`, and
  a `uv tool` install takes `uv tool install yt-dlp --with yt-dlp-ejs`.

  The cookies expire. When the bot-check message comes back, re-export
  `cookies.txt` from the phone browser in Netscape format and overwrite that
  file — mode 600, and never in the repo: it holds live Google session tokens,
  and yt-dlp rewrites it in place as they refresh.

  The same jar is what the **subscription feed** (and **Watch Later**) signs in with, and it is the
  louder alarm of the two: a search with stale cookies still returns something,
  where the feed returns nothing at all. So an empty feed and a short format
  list are the same fault, and `nibbles` says so on both rather than leaving
  "no new videos" to be believed.

## Notes

- One video at a time; playlist URLs are refused — and refused off the
  list's first page, so a channel or a playlist pasted by mistake costs one
  page rather than a full look at every video in it. A *search* naturally
  comes back as a list of them, which is a different thing and is what the
  results list is.
- What you chose last is remembered, in the queue's own `config.json` beside
  the destinations: the format, Smallest or Largest for video and for audio,
  and how often you pick each height. It only decides what the sheet opens on
  and which quality buttons it shows. If the video does not offer the format
  you chose last, the closest resolution wins.
- A plain file URL (not a video page) is queued as a file by `nibbles <url>`
  rather than through yt-dlp — it slices more precisely and skips the
  per-night metadata overhead. Pasted into the app's field it is still a
  video sheet's question.
- Large videos span nights. Each nightly firing re-runs yt-dlp (media URLs
  expire in hours, so they must be re-resolved) at ~0.1–0.5 MB per firing;
  that overhead is already inside the declared cap.
