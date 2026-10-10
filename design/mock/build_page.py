import html
import json
import re
import sys

screens = json.load(open(sys.argv[1])) + json.load(open(sys.argv[3])) + json.load(open(sys.argv[4]))
by = {s["key"]: s for s in screens}


def md(s: str) -> str:
    s = html.escape(s)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def pair(s):
    notes = "".join(f"<li>{md(n)}</li>" for n in s["notes"])
    full = s["full"]
    frames = []
    for shot in s["shots"]:
        up = shot["rows"] < full
        kb = ""
        if up:
            kb = f'<div class="kbd" style="height:calc({full - shot["rows"]} * var(--lh))">phone keyboard</div>'
        label = f'{"keyboard up" if up else "keyboard down"} · {s["width"]}×{shot["rows"]}'
        frames.append(f"""<div class="frame"><div class="cap">{label}</div>
  <div class="phone" style="--cols:{s['width']}"><pre class="term">{shot['html']}</pre>{kb}</div></div>""")
    return f"""
<figure class="shot2" id="{s['key']}">
  <div class="frames">{''.join(frames)}</div>
  <figcaption>
    <h3>{html.escape(s['title'])}</h3>
    <ul>{notes}</ul>
  </figcaption>
</figure>"""


def phone(s):
    kb = ""
    if s["keyboard_from"] is not None:
        kb = f'<div class="kb" style="top:calc({s["keyboard_from"]} * var(--lh) + var(--pad) + 10px)">phone keyboard</div>'
    notes = "".join(f"<li>{md(n)}</li>" for n in s["notes"])
    return f"""
<figure class="shot" id="{s['key']}">
  <div class="phone" style="--cols:{s['width']}">
    <pre class="term">{s['html']}</pre>{kb}
  </div>
  <figcaption>
    <h3>{html.escape(s['title'])}</h3>
    <ul>{notes}</ul>
  </figcaption>
</figure>"""


def chips_frames():
    q = by.get("q-chips")
    if not q:
        return ""
    out = []
    for sh in q["shots_free"]:
        out.append(f"""<div class="frame"><div class="cap">{sh['label']}</div>
  <div class="phone" style="--cols:40"><pre class="term">{sh['html']}</pre><div class="kbd" style="height:calc(10 * var(--lh))">phone keyboard</div></div></div>""")
    return "".join(out)


def group(keys):
    return "\n".join(pair(by[k]) if "shots" in by[k] else phone(by[k]) for k in keys)


YTQ = ["k-search", "k-results", "k-sheet-loading", "k-sheet", "k-sheet-audio", "k-sheet-now", "k-sheet-dup", "k-formats", "k-feed"]
DLQ = ["k-queue", "k-item", "k-place", "k-download", "k-run", "k-more", "k-setting", "k-narrow"]

chips_q = chips_frames()
page = f"""<title>ytq and dlq, buttons first</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Instrument+Sans:wght@400;500;600;700&display=swap">
<style>
/* Layout: one reading column of decisions, then phone frames beside their notes. */
:root {{
  --bg: #F6F5FA; --fg: #22202B; --muted: #5E5A6E; --faint: #8C879C;
  --rule: #DEDBE8; --panel: #FFFFFF; --accent: #6B50FF; --warn: #B07A00;
  --term-bg: #201F26; --frame: #2D2C35;
  --display: "Instrument Sans", "Segoe UI", system-ui, sans-serif;
  --body: "Instrument Sans", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
  --pad: 12px;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #16151B; --fg: #E9E7F2; --muted: #A9A4BA; --faint: #77728A;
  --rule: #2C2A36; --panel: #1D1C24; --accent: #9C8AFF; --warn: #E8B33A;
  --frame: #3A3845; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #16151B; --fg: #E9E7F2; --muted: #A9A4BA; --faint: #77728A;
  --rule: #2C2A36; --panel: #1D1C24; --accent: #9C8AFF; --warn: #E8B33A;
  --frame: #3A3845; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--fg); font: 16px/1.55 var(--body); }}
main {{ max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 40px 80px; }}
h1, h2, h3 {{ font-family: var(--display); text-wrap: balance; line-height: 1.2; }}
h1 {{ font-size: clamp(30px, 5vw, 44px); margin: 0 0 8px; letter-spacing: -0.01em; }}
h2 {{ font-size: 24px; margin: 56px 0 12px; padding-top: 20px; border-top: 1px solid var(--rule); }}
h3 {{ font-size: 17px; margin: 0 0 8px; }}
p, li {{ max-width: 68ch; }}
.lede {{ color: var(--muted); font-size: 18px; max-width: 62ch; }}
.eyebrow {{ font: 600 12px/1 var(--body); letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }}
code {{ font-family: var(--mono); font-size: 0.86em; background: color-mix(in srgb, var(--accent) 10%, transparent); padding: 1px 4px; border-radius: 3px; }}
.rules {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin: 18px 0; }}
.rule {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 14px 16px; min-width: 0; }}
.rule b {{ display: block; margin-bottom: 4px; }}
.rule p {{ margin: 0; color: var(--muted); font-size: 15px; }}
.shot {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 28px; align-items: start; margin: 28px 0; }}
.shot figcaption ul {{ margin: 0; padding-left: 18px; color: var(--muted); }}
.shot figcaption li {{ margin-bottom: 6px; }}
.phone {{ --lh: 16px; position: relative; background: var(--frame); padding: 10px; border-radius: 18px; overflow-x: auto; max-width: 100%; }}
.term {{ margin: 0; background: var(--term-bg); color: #DFDBDD; font: 13px/var(--lh) var(--mono);
         padding: var(--pad); border-radius: 8px; width: calc(var(--cols) * 1ch); box-sizing: content-box;
         font-variant-ligatures: none; }}
.term {{ line-height: var(--lh); }}
.term .c {{ display: inline-block; width: 1ch; height: var(--lh); text-align: center; vertical-align: top; position: relative; overflow: visible; }}
.term .r {{ display: inline-block; height: var(--lh); vertical-align: top; white-space: pre; }}
.term .b::before {{ content: ""; position: absolute; box-sizing: border-box; }}
.term .h::before {{ left: 0; right: 0; top: 50%; border-top: 1px solid currentColor; }}
.term .v::before {{ top: 0; bottom: 0; left: 50%; border-left: 1px solid currentColor; }}
.term .thumb::before {{ top: 0; bottom: 0; left: calc(50% - 1.5px); border-left: 3px solid currentColor; }}
.term .full::before {{ inset: 0; background: currentColor; }}
.term .tl::before {{ left: 50%; top: 50%; right: 0; bottom: 0; border-left: 1px solid currentColor; border-top: 1px solid currentColor; border-top-left-radius: 5px; }}
.term .tr::before {{ left: 0; top: 50%; width: calc(50% + 1px); bottom: 0; border-right: 1px solid currentColor; border-top: 1px solid currentColor; border-top-right-radius: 5px; }}
.term .bl::before {{ left: 50%; top: 0; right: 0; height: calc(50% + 1px); border-left: 1px solid currentColor; border-bottom: 1px solid currentColor; border-bottom-left-radius: 5px; }}
.term .br::before {{ left: 0; top: 0; width: calc(50% + 1px); height: calc(50% + 1px); border-right: 1px solid currentColor; border-bottom: 1px solid currentColor; border-bottom-right-radius: 5px; }}
.shot2 {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 28px; align-items: start; margin: 32px 0; }}
.shot2 figcaption ul {{ margin: 0; padding-left: 18px; color: var(--muted); }}
.shot2 figcaption li {{ margin-bottom: 6px; }}
.frames {{ display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-start; }}
.frame {{ display: flex; flex-direction: column; gap: 6px; min-width: 0; max-width: 100%; }}
.cap {{ font: 600 11px/1 var(--body); letter-spacing: 0.08em; text-transform: uppercase; color: var(--faint); }}
.phone .kbd {{ margin-top: 0; border-radius: 0 0 8px 8px; background: repeating-linear-gradient(135deg, #2b2a33 0 6px, #26252d 6px 12px);
       color: #8C879C; font: 600 11px/1 var(--body); letter-spacing: 0.08em; text-transform: uppercase;
       display: flex; align-items: center; justify-content: center; }}
@media (max-width: 1080px) {{ .shot2 {{ grid-template-columns: minmax(0, 1fr); gap: 14px; }} }}
.kb {{ position: absolute; left: 10px; right: 10px; bottom: 10px; border-radius: 0 0 8px 8px;
       background: repeating-linear-gradient(135deg, #2b2a33 0 6px, #26252d 6px 12px);
       color: #8C879C; font: 600 12px/1 var(--body); letter-spacing: 0.08em; text-transform: uppercase;
       display: flex; align-items: center; justify-content: center; font-size: 12px; }}
.phone .kb {{ font-size: 12px; }}
.term + .kb {{ margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 15px; }}
.tablewrap {{ overflow-x: auto; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; }}
th {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--faint); font-weight: 600; }}
ol.q {{ padding-left: 22px; }}
ol.q li {{ margin-bottom: 12px; max-width: none; }}
ol.q b {{ color: var(--fg); }}
.rec {{ color: var(--accent); font-weight: 600; }}
@media (max-width: 760px) {{
  .shot {{ grid-template-columns: minmax(0, 1fr); gap: 14px; }}
  .phone {{ --lh: 13px; }}
  .term {{ font-size: 10.5px; }}
}}
</style>
<main>
<div class="eyebrow">Design proposal · 2026-10-10 · for review before any code</div>
<h1>ytq and dlq, buttons first</h1>
<p class="lede">The second draft. The first kept today's screens and added buttons to them. This one reshapes both apps around a phone: one shell with tabs along the bottom, sheets that rise from the bottom instead of pages, and two taps from a search result to a queued video. Every mockup is drawn with bewitch's own recipes at the real terminal size.</p>

<h2>The shape</h2>
<div class="rules">
  <div class="rule"><b>One app, five tabs</b><p>Search, Feed, Later, Queue and More, along the bottom where the thumb is. <code>ytq</code> opens on Search, <code>ytq subs</code> on Feed and <code>dlq</code> on Queue. dlq's listing already ran inside ytq's session; now it is simply a tab.</p></div>
  <div class="rule"><b>Sheets, not pages</b><p>A video, a download, a confirm and a setting each open as a sheet from the bottom over the screen they came from, which stays visible and dimmed above it. Esc, or a tap on the dimmed part, closes the sheet.</p></div>
  <div class="rule"><b>Two taps to queue</b><p>Tap a result and its sheet opens at once while the formats load. Tap Queue. Quality is a tier (a height, or an audio bitrate) plus Smallest or Largest, and the full table is a button away, opened at that tier.</p></div>
  <div class="rule"><b>Keyboard up or down</b><p>Termux shrinks the terminal when the phone keyboard opens, so every screen is laid out by how many rows it gets, shown below side by side. Below 16 rows: the window card becomes one line, and a sheet takes the full height with its main button pinned and the rest scrolling. Tabs and buttons never shrink. The 24 and 14 rows here are estimates, to be measured on your phone.</p></div>
  <div class="rule"><b>Your clock, not UTC</b><p>The window is named by when it opens on the phone's own clock: “at 03:00”, “tomorrow 03:00”, “today 14:00”, whichever 00:00 UTC minus the window turns into where you are. The reset reads the same way (“before the 04:00 reset”). There is no UTC and no “tonight” on any screen, and nothing is called free or paid unless it really is. The mockups assume a phone at UTC+4.</p></div>
  <div class="rule"><b>No Back buttons</b><p>Tabs replace the stack of screens. The only depth left is a sheet, and a sheet closes. Quit sits in More, and <code>q</code> still quits from anywhere.</p></div>
</div>
<div class="tablewrap"><table>
<tr><th>Today</th><th>Becomes</th></tr>
<tr><td>ytq entry field, <code>subs</code>, <code>wl</code></td><td>The Search tab's bar, plus the Feed and Later tabs</td></tr>
<tr><td>ytq results</td><td>Under the search bar on the Search tab, with no page of their own</td></tr>
<tr><td>ytq formats + confirm + duplicate screen</td><td>One video sheet: quality chips, the window or Now, one button</td></tr>
<tr><td>ytq download screen, the running line</td><td>The status rule above the tabs, on every tab, and a sheet behind it</td></tr>
<tr><td>dlq listing with three stacked groups</td><td>The Queue tab: a window card, then Queued, Failed or Done one at a time</td></tr>
<tr><td>slugs (<code>40-some-talk.py</code>, <code>some-talk.mp4</code>)</td><td>One name: the title, cleaned for Android. <code>40-Some Talk.py</code> in the queue, <code>Some Talk.mp4</code> in Downloads</td></tr>
<tr><td>dlq item screen</td><td>A sheet over the queue, with its actions as a button grid</td></tr>
<tr><td>dlq settings, destinations, runner log</td><td>The More tab</td></tr>
<tr><td><code>p spot</code> (pick_place)</td><td>Gone. ytq queues last; reordering is Move in the Queue tab</td></tr>
</table></div>

<h2>How touch works</h2>
<div class="rules">
  <div class="rule"><b>A tap is a tap, a drag is a scroll</b><p>Termux decides this before the app hears anything (checked in its <code>TerminalView</code> source). A tap reaches the app as press and release together, the moment the finger lifts, and only if the finger did not move. A drag never sends a press; it arrives as wheel events, one per row moved, followed by a fling's momentum. So a drag can never press a button, and a button acts as soon as Termux reports the tap. It fills with the primary colour for one frame so you see what you hit. A long press is Termux's own text selection and never reaches the app.</p></div>
  <div class="rule"><b>A short guard against double taps</b><p>For 100 ms after a screen or dialog appears, taps are ignored, which is under the ~100 ms at which a response starts to feel slow. For a further 200 ms (Android's own double-tap window is 300 ms in total), only a tap on the same cell as the one that opened the screen is dropped. A deliberate tap anywhere else acts at once, so the second half of a double tap cannot land on a dialog's yes.</p></div>
  <div class="rule"><b>One tap opens</b><p>Tapping a row opens its sheet in the same tap. In ytq that also starts the format fetch (~0.3 MB), and the sheet fills in when it lands. The selection bar still shows which row the keys act on.</p></div>
  <div class="rule"><b>The price is on the button</b><p>A button that spends data names the amount on its face, or on the line directly above it. Anything that spends data nothing is counting (mobile data, with the portal out of reach) still goes through exactly one yes.</p></div>
  <div class="rule"><b>Swiping scrolls, and a deliberate pull can spend</b><p>Termux turns a swipe into wheel events. A swipe scrolls the list. On Feed and Later, the end of the list carries the next page's total price; once the list has rested there, a fresh drag down reads it. A fling's momentum stops at the end and never fetches, because flicks on Termux are not reliable enough to spend on.</p></div>
  <div class="rule"><b>Draggable scrollbars</b><p>The last three columns of a list are the scrollbar's zone. A tap there jumps to that point. Termux stamps every wheel event of a drag with the cell where the drag began, so a drag that starts on the bar moves the thumb a row per row of finger travel, a page at a time through the list, while a drag anywhere else scrolls the list a row at a time.</p></div>
  <div class="rule"><b>Fetches run in the background</b><p>Search, format probes and the deeper look run on worker threads. The screen stays live, a spinner shows what is running, and Stop (x) cancels it.</p></div>
  <div class="rule"><b>Keys still work</b><p>Every key still works. Each button shows its key in grey, so the button row is the hint line. The two hint sets become two label sets: full words at 38 columns and up, short ones at 30.</p></div>
  <div class="rule"><b>Thumb zone and keyboard</b><p>Tabs, sheets and their buttons sit at the bottom. Anything you type into (the search bar, a setting, a rename) sits at the top, above the phone keyboard.</p></div>
  <div class="rule"><b>An idle screen is still silent</b><p>Everything is drawn through <code>bewitch.screen.Frame</code>. With nothing running, the loop blocks on <code>inkey()</code> and writes nothing. Only spinners, the selected title's marquee and a running download animate.</p></div>
</div>

<h2>The pieces</h2>
{group(["kit"])}

<h2>Finding and queueing (ytq's half)</h2>
<p><code>write_item</code> is still the one door, and duplicates are still refused on the extractor and id.</p>
{group(YTQ)}

<h2>The queue (dlq's half)</h2>
<p>Every button calls the same function as its key and its command (<code>do_arm</code>, <code>do_cancel</code>, <code>set_dest</code>, <code>queue_run_argv</code>, <code>do_reorder</code>). The cut line, gate() and admit() stay exactly as they are.</p>
{group(DLQ)}

<h2>How it would be built</h2>
<div class="tablewrap"><table>
<tr><th>Piece</th><th>Where</th><th>What it does</th></tr>
<tr><td><code>tui.py</code></td><td>ytq, imported by dlq</td><td>The one blessed <code>Terminal</code> and session: fullscreen, cbreak, hidden cursor, click and wheel reporting (SGR). It turns SIGWINCH into a resize event, restores the terminal on Ctrl-Z, on resume and on any exception, and drops mouse bytes nobody asked for. <code>read_event()</code> returns a Key, Tap(x, y), Scroll(dy, x, y), Resize or Done(fetch). dlq never opens a second Terminal: its tabs draw into ytq's session.</td></tr>
<tr><td>The shell</td><td>ytq, with dlq's tab imported</td><td>Tab bar with its status rule, and the sheet stack. The Queue and More tabs come from dlq's <code>expire_ui</code>, imported when the tab is first opened and never at module top, which keeps the circular import rule.</td></tr>
<tr><td><code>widgets.py</code></td><td>ytq, depends on bewitch only</td><td><code>button</code>, <code>dock</code>, <code>segmented</code>, <code>field</code>, <code>chips</code>, <code>tabbar</code>, <code>sheet</code>, <code>dim</code>, plus <code>HitMap</code>: ids on composed rectangles, last composed wins, hit lookup by cell. It is Lip Gloss v2's Layer and Compositor model, kept separate so it can move into bewitch if you want it there.</td></tr>
<tr><td><code>Fetch</code></td><td>in <code>tui.py</code></td><td>A thread per fetch, holding its yt-dlp subprocess so Stop can kill it. While one runs, the loop wakes at the spinner's 10 fps. When none run, it blocks.</td></tr>
<tr><td>Screens</td><td>both apps</td><td>Each screen becomes <code>draw(state, w, h) -&gt; (Block, HitMap)</code>, a pure function, plus <code>handle(state, event)</code>. The layout tests sweep widths over <code>draw</code> without a pty. The pty tests keep checking structure only.</td></tr>
<tr><td>Goes away</td><td></td><td><code>curses</code>, <code>enable_touch_scroll</code>, <code>read_wheel</code> and <code>wheel_step</code> (replaced by Scroll events), <code>HINTS</code> and <code>TIGHT_HINTS</code> (replaced by label sets), and <code>text_input</code> (replaced by <code>field</code>).</td></tr>
<tr><td>Test pumps</td><td>ytq <code>conftest.py</code>, dlq <code>_pty.py</code></td><td>They answer CPR and DECRQM as Termux does, so blessed starts in 0.1 s and decodes mouse reports. New pty tests: a tap on a button acts, a tap outside every button does nothing, and a swipe never presses a key.</td></tr>
</table></div>
<p>Already settled in your comments: a tap acts as soon as Termux reports it, a 100 ms guard plus a same-spot double-tap guard, one tap opens a row, one tap spends when the price is showing, and uncounted data needs exactly one yes. Buttons stay three rows tall (about 11 mm) at every height; lists give up rows first. A swipe moves the view; the selection stays on its row until it comes within one item of the edge and then rides along one item in, as Helix's scrolloff does, and ↑ ↓ keep the same margin (none below three visible items). Feed and Later read themselves the first time their tab opens in a session (~0.2 MB each). blessed is a runtime dependency of both apps (<code>pip install blessed</code> on the phone).</p>
<p>The work would be done on <code>ccr-4926f911-fmw0a0</code> in both repos, starting from <code>main</code> as you chose. The <code>bewitched</code> branches are used only as a reference for the look. Nothing gets merged into any <code>main</code>. Both repos' CLAUDE.md files would be updated where these decisions replace old ones, such as “a flick scrolls; only a keypress spends” and the two hint sets.</p>

<h2>Questions for you</h2>
<ol class="q">
  <li><b>One shell for both commands?</b> <span class="rec">Proposed:</span> <code>ytq</code> and <code>dlq</code> open the same five-tab app on different tabs. The code stays in the two repos, and dlq supplies the Queue and More tabs. The alternative is two apps that look alike.</li>
</ol>
</main>
"""
open(sys.argv[2], "w").write(page)
print(len(page))
