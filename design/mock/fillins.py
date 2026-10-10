"""Render what the build filled in where no mockup drew it, from the real app.

``python3 design/mock/fillins.py`` writes ``design/mockups/fillins.html``: the
review page for the "filled in where the spec is silent" half of
``design/divergences.md``. Unlike ``screens3.py`` nothing here is drawn by
hand: every frame is the real ``nibbles.App`` composed headless, on a
throwaway queue root, with the phone at UTC+4 as the mockups assume.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MiB = 1024 * 1024

# The phone the mockups assume, and a queue root that is not the real one.
os.environ["TZ"] = "Asia/Dubai"
time.tzset()
ROOT = Path(tempfile.mkdtemp(prefix="nibbles-fillins-"))
HOME = ROOT / "home"
HOME.mkdir()
shutil.copytree(REPO / "nibbles", ROOT / "nibbles",
                ignore=shutil.ignore_patterns("__pycache__"))
for sub in ("queue", "done", "failed", "work", "out", "logs"):
    (ROOT / sub).mkdir()
shutil.copy(REPO / "queue" / "README.md", ROOT / "queue" / "README.md")
os.environ.update(EXPIRE_HOME=str(ROOT), HOME=str(HOME))
os.environ.setdefault("ZWANA_HOME", str(REPO.parent / "zwana-quota"))
os.environ.setdefault("BEWITCH_HOME", str(REPO.parent / "bewitch"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(HERE))

import kit  # noqa: E402  (bewitch on the path, and the HTML cells)
from nibbles import app as nibbles  # noqa: E402
from nibbles import queue_screens as qs  # noqa: E402
from nibbles import shell  # noqa: E402
from nibbles import tui  # noqa: E402
from nibbles import yt_screens as ys  # noqa: E402
from nibbles import ytq  # noqa: E402

runner = qs.runner()


def item(name, cap, where="queue", desc="", stated=0):
    path = ROOT / where / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n# EXPIRE: v1\n# EXPECT_BYTES: {cap}\n# PARTIAL: yes\n"
                    f"# DESC: {desc or name} [1080p mp4]\n\"\"\"x\"\"\"\n")
    return path


item("10-ubuntu-24.04-desktop-amd64.iso.py", 5745 * MiB)
item("20-Some Talk About Rust.py", 505 * MiB)
item("30-big.iso.py", 8192 * MiB)
item("40-An Old Talk.py", 300 * MiB, where="failed")
item("50-Crust of Rust - Lifetimes.py", 92 * MiB, where="done/2026-10-09")
(ROOT / "state.json").write_text(json.dumps({"items": {
    "40-An Old Talk.py": {"attempts": 3, "last": "yt-dlp: HTTP Error 403"}}}))
(ROOT / "logs" / "runner.log").write_text(
    "2026-10-09 23:00:04Z firing: window open, 480 MiB to spend\n"
    "2026-10-09 23:00:05Z 20-Some Talk About Rust.py: admitted, 46 MiB this slice\n"
    "2026-10-09 23:14:51Z 20-Some Talk About Rust.py: slice done, 46 MiB\n")


def reading(free=763 * MiB, spent=283 * MiB):
    doc = runner.qw.derive({
        "ts": time.time(), "credits": 4.0, "per_credit": 1_000_000,
        "remainder": free, "pool": free + spent, "grant": free + spent,
        "drawn_today": 0, "allocated": 0, "online": True,
    }, 0.0, True)
    return doc


def facts(portal=True, **changes):
    doc = reading() if portal else None
    real = runner.portal_now
    runner.portal_now = lambda: (doc, "" if doc else "no credentials")
    try:
        got = runner.snapshot(force=False, blind=not portal)
    finally:
        runner.portal_now = real
    got.update(changes)
    return got


def app_at(tab, h, fx=None, w=40):
    app = nibbles.App(None, tab, size=(w, h))
    app.queue.facts = fx if fx is not None else facts()
    app.queue.reached, app.queue.reached_at = True, time.monotonic()
    app.guard.opened = -10.0
    for job, _ in list(app.jobs):
        job.cancelled = True
    app.jobs.clear()
    if hasattr(app.tabs[4], "job_rows"):
        app.tabs[4].job_rows = [("job", f"{qs.sched.ARMED}, fires every 15m", "32")]
    return app


def shot(app):
    block = app.compose()
    return {"rows": app.height, "html": kit.to_html(block), "plain": block.plain()}


SCREENS: list[dict] = []


def add(key, title, notes, make, heights=(24, 14), width=40):
    shots = [shot(make(h)) for h in heights]
    SCREENS.append({"key": key, "title": title, "notes": notes, "width": width,
                    "shots": shots, "full": heights[0]})


# --- the status bar for every verdict -------------------------------------

def status_strip(_h):
    lines = []
    model = app_at(3, 24).queue
    cases = [("before a reading", None, ""), ("a reading that failed", None, "no route to host")]
    for verdict in ("early", "go", "late", "empty", "off", "spent", "blind", "no-portal", "stale"):
        cases.append((verdict, facts(verdict=verdict), ""))
    for label, fx, note in cases:
        model.facts, model.note = fx, note
        lines.append((label, kit.status_bar(model.status(40), 40) if hasattr(kit, "status_bar")
                      else None, model.status(40)))
    return lines


def status_page():
    model = app_at(3, 24).queue
    from nibbles import widgets as w

    rows = []
    cases = [("before a reading", None, ""), ("a reading that failed", None, "no route to host")]
    for verdict in ("early", "go", "late", "empty", "off", "spent", "blind", "no-portal", "stale"):
        cases.append((f"verdict {verdict}", facts(verdict=verdict), ""))
    for label, fx, note in cases:
        model.facts, model.note = fx, note
        rows.append((label, kit.to_html(w.status_bar(model.status(40), 40))))
    model.facts = facts()
    model.live = "10-ubuntu-24.04-desktop-amd64.iso.py"
    rows.append(("a download in flight", kit.to_html(w.status_bar(model.status(40), 40))))
    model.live = ""
    model.firing.child = type("Alive", (), {"poll": lambda self: None, "pid": 0})()
    rows.append(("the whole queue starting", kit.to_html(w.status_bar(model.status(40), 40))))
    return rows


# --- Stop on a running fetch -----------------------------------------------

def searching(h):
    app = app_at(0, h)
    tab = app.tabs[0]
    tab.value = "crust of rust"
    tab.job = tui.Job(lambda: None, "searching", key="crust of rust")
    return app


def reading_feed(h):
    app = app_at(1, h)
    app.tabs[1].read_once = True
    app.tabs[1].problem = []  # a cookie on disk, as a read needs
    app.tabs[1].job = tui.Job(lambda: None, "reading", key=(30, "", False))
    return app


# --- notices -----------------------------------------------------------------

RESULTS = ytq.entries({"entries": [
    {"id": f"v{i}", "ie_key": "Youtube", "title": t, "channel": "Jon Gjengset",
     "url": f"https://www.youtube.com/watch?v=v{i}", "duration": 5434,
     "timestamp": int(time.time()) - 86400 * 3, "view_count": 41000}
    for i, t in enumerate(["Crust of Rust: Subtyping and Variance",
                           "Making a Case for Rust in the Kernel", "lofi hip hop radio",
                           "Rust Lifetimes Finally Explained", "The Async Book",
                           "Why my Termux setup is ridiculous", "Building a TUI with blessed"])]})


def with_results(app):
    app.yt.landed("crust of rust", RESULTS)
    app.tabs[0].show("crust of rust")
    return app


def notice_failed(h):
    app = with_results(app_at(0, h))
    app.sheets[:] = [shell.Notice("Could not read it", [
        "could not read that URL",
        "ERROR: [youtube] abc: Video unavailable. This video is private"],
        border=kit.T.error)]
    return app


def notice_withheld(h):
    app = with_results(app_at(0, h))
    app.sheets[:] = [shell.Notice("Only 360p", ytq.withheld_advice(ytq.cookie_state()[1]))]
    return app


# --- Download now and Run now ---------------------------------------------

def queue_rows():
    return qs.sched.items()


def download_now(counted):
    def make(h):
        app = app_at(3, h)
        row = next(r for r in app.queue.rows if r["name"].startswith("20-"))
        item_sheet = qs.ItemSheet(row)
        if counted is None:
            app.queue.reached = None
            app.queue.reach_job = tui.Job(lambda: None, "reach")
        else:
            app.queue.reached = counted
        sheet = qs.NowSheet.__new__(qs.NowSheet)
        shell.Confirm.__init__(sheet, "Download now", "", [])
        sheet.row, sheet.item = row, item_sheet
        app.sheets[:] = [sheet]
        return app
    return make


def run_counted(h):
    app = app_at(3, h)
    offer = facts()
    app.sheets[:] = [qs.run_sheet(app, dict(offer, verdict="go", blind=False))]
    return app


# --- More and its sheets -------------------------------------------------------

def more(h):
    return app_at(4, h)


def more_sheet(factory):
    def make(h):
        app = app_at(4, h)
        app.sheets[:] = [factory(app)]
        return app
    return make


def job_confirm(app):
    tab = app.tabs[4]
    tab.act(app, ("job",))
    return app.sheets[-1]


# --- words ---------------------------------------------------------------------

def group(index):
    def make(h):
        app = app_at(3, h)
        app.tabs[3].group = index
        return app
    return make


def empty_queue(h):
    for p in (ROOT / "queue").glob("*.py"):
        p.rename(ROOT / "work" / (p.name + ".hidden"))
    try:
        app = app_at(3, h)
        app.compose()
        return app
    finally:
        for p in (ROOT / "work").glob("*.hidden"):
            p.rename(ROOT / "queue" / p.name.removesuffix(".hidden"))


def before_reading(h):
    app = with_results(app_at(0, h))
    app.queue.facts = None
    info = {"id": "v0", "title": "Crust of Rust: Subtyping and Variance", "duration": 5434,
            "extractor_key": "Youtube", "channel": "Jon Gjengset",
            "webpage_url": RESULTS[0].url, "formats": [
                {"format_id": "135", "vcodec": "avc1.4d401e", "acodec": "none", "ext": "mp4",
                 "height": 480, "filesize": 80 * MiB},
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a",
                 "abr": 129, "filesize": 10 * MiB}]}
    app.yt.probed[RESULTS[0].url] = (info, *ytq.choices(info))
    sheet = ys.VideoSheet(app, RESULTS[0].url, info["title"], "Jon Gjengset · ~3d · 90m34s")
    app.sheets[:] = [sheet]
    sheet.shown(app)
    return app


def narrow(h):
    return app_at(3, h, w=32)


def rename(h):
    app = app_at(3, h)
    row = next(r for r in app.queue.rows if r["name"].startswith("20-"))
    app.sheets[:] = [qs.ItemSheet(row), qs.RenameSheet(row)]
    return app


def said(h):
    app = with_results(app_at(0, h))
    app.say("queued Crust of Rust - Subtyping and Variance · 92 MiB")
    return app


def nightly_download(h):
    name = "10-ubuntu-24.04-desktop-amd64.iso.py"
    work = ROOT / "work" / name
    work.mkdir(parents=True, exist_ok=True)
    (work / ".status.json").write_text(json.dumps(
        {"part_bytes": int(1.02 * 1024 * MiB), "total_bytes": int(5.61 * 1024 * MiB)}))
    app = app_at(3, h)
    app.queue.live = name
    app.sheets[:] = [qs.DownloadSheet("10-ubuntu-24.04-desktop-amd64.iso.py")]
    return app


# ---------------------------------------------------------------------------------

def build() -> list[dict]:
    add("f-stop", "Stop on a running fetch: the search", [
        "While a search runs, the grey line under the bar is its spinner and price, ending in `x stop`, a tap target. `x` anywhere stops the newest fetch and kills the yt-dlp it holds.",
    ], searching)
    add("f-stop-feed", "Stop on a running fetch: the feed's first read", [
        "The read's line sits where `60 videos` will be, `x stop` at its end (a key here, not a target); Re-read is drawn off until it lands.",
    ], reading_feed)
    add("f-notice", "Notices are sheets: a probe that failed", [
        "What the old full-page messages said is a sheet: the title, the lines wrapped, a pinned `esc OK`. Its body scrolls and its OK never does.",
    ], notice_failed)
    add("f-notice-withheld", "Notices are sheets: the once-a-session 360p notice", [
        "Opened over the video sheet it is about; the sheet itself carries `bot check — one format only` on every list it applies to.",
    ], notice_withheld)
    add("f-now-counted", "Download now: zwana answers", [
        "A download's Download now asks once, with what is left to fetch on the yes. Counted: the window's own sentence, `today's allowance, no reserve kept`.",
    ], download_now(True))
    add("f-now-blind", "Download now: zwana does not answer", [
        "Run now's sentence, `on mobile data, charged`, the warning border and the yes in red.",
    ], download_now(False))
    add("f-now-asking", "Download now: asking", [
        "For the second or so the connect takes, the question says so and the yes is drawn but does nothing.",
    ], download_now(None))
    add("f-run-counted", "Run now when zwana answers (design §9's proposal)", [
        "The same sheet as the blind one: `n Run now · 480 MiB`, `out of the 03:00 window's allowance` in grey, the primary border.",
    ], run_counted)
    add("f-more", "More: every setting the runner has", [
        "Every row in `expire_runner.SETTINGS` order, so `reserve when paid` and `notify blocked` are rows too (`paid-min` only while the waiver is on). Skip codecs reads `none` until it is set.",
    ], more)
    add("f-skip", "More: skip codecs", [
        "The setting sheet's shape: the field, its rule, presets, `esc Cancel` and `⏎ Set` pinned.",
    ], more_sheet(lambda app: qs.SkipSheet()))
    add("f-chips", "More: quality chips", [
        "`learned` (the default) or heights set by hand.",
    ], more_sheet(lambda app: qs.ChipsSheet()))
    add("f-dests", "More: destinations", [
        "Video, audio and file with where each goes; a tap on one opens its path in the same field sheet, with a `default` preset.",
    ], more_sheet(lambda app: qs.DestSheet()))
    add("f-path", "More: one destination's path", [], more_sheet(lambda app: qs.PathSheet("video")))
    add("f-job", "More: stopping the nightly job", [
        "Arming is one tap on the row; stopping asks first, the stop in the danger style, No last.",
    ], more_sheet(job_confirm))
    add("f-log", "More: the runner log", [
        "The file's last lines, scrolled to the end. An item's own log is the same sheet.",
    ], more_sheet(lambda app: qs.LogSheet("Runner log", ROOT / "logs" / "runner.log")))
    add("f-failed", "Words: the Failed group", [
        "A failed download's second line is its last error; the mark is `×`.",
    ], group(1))
    add("f-done", "Words: the Done group", [
        "A finished one's is its size and the file it delivered (or `deleted`); the mark is `✓`.",
    ], group(2))
    add("f-before", "Words: before the first reading", [
        "The window is `the window` until the queue's reading lands, never a made-up time.",
    ], before_reading)
    add("f-narrow", "Words: the cut line at 32 columns", [
        "The lead-in shortens to `window`, as `k-narrow` draws it, and the figure stays.",
    ], narrow, heights=(20, 11), width=32)
    add("f-rename", "Words: Rename", [
        "A field sheet titled Rename, prefilled with the name; the title is cleaned the way a new download's is.",
    ], rename)
    add("f-said", "Words: what queueing did", [
        "Said on the line above the tabs, as More's changes are.",
    ], said)
    add("f-pause", "Pause only on a download this session can stop", [
        "A nightly firing's download (or a `dlq now` elsewhere) gets `esc Back` alone: this app holds no handle on it, and a Pause that says paused over a download that carries on would be worse than none.",
    ], nightly_download)
    empty_rows = add("f-empty", "Words: an empty group", [
        "`nothing queued — Search or Feed adds something`, `nothing has failed`, `nothing finished yet`.",
    ], empty_queue)
    del empty_rows
    return SCREENS


def page(screens: list[dict], statuses: list[tuple[str, str]]) -> str:
    base = (REPO / "design" / "mockups" / "index.html").read_text(encoding="utf-8")
    head = base[: base.index("<main>")]
    head = re.sub(r"<title>.*?</title>", "<title>nibbles fill-ins</title>", head)

    def md(s: str) -> str:
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(s))

    def figure(s):
        frames = []
        for sh in s["shots"]:
            up = sh["rows"] < s["full"]
            kb = (f'<div class="kbd" style="height:calc({s["full"] - sh["rows"]} * var(--lh))">'
                  "phone keyboard</div>") if up else ""
            label = f'{"keyboard up" if up else "keyboard down"} · {s["width"]}×{sh["rows"]}'
            frames.append(f'<div class="frame"><div class="cap">{label}</div><div class="phone" '
                          f'style="--cols:{s["width"]}"><pre class="term">{sh["html"]}</pre>{kb}</div></div>')
        notes = "".join(f"<li>{md(n)}</li>" for n in s["notes"])
        return (f'<figure class="shot2" id="{s["key"]}"><div class="frames">{"".join(frames)}</div>'
                f'<figcaption><h3>{html.escape(s["title"])}</h3><ul>{notes}</ul></figcaption></figure>')

    by = {s["key"]: s for s in screens}

    def section(keys):
        return "\n".join(figure(by[k]) for k in keys)

    status_rows = "".join(
        f'<tr><td>{html.escape(label)}</td><td><div class="phone" style="--cols:40;padding:6px">'
        f'<pre class="term" style="padding:4px 8px">{bar}</pre></div></td></tr>'
        for label, bar in statuses)
    keys = [
        ("Tab, Shift-Tab", "anywhere", "the next or the previous tab"),
        ("s, l", "Queue", "More, and the runner log, as on dlq's listing"),
        ("n", "video sheet", "At ↔ Now"),
        ("f", "video sheet", "Formats"),
        ("s, l", "video sheet", "Smallest, Largest"),
        ("← →", "video sheet", "step the height (or bitrate)"),
        ("c", "video sheet", "copy the page URL (said on the sheet)"),
        ("/", "Search, Feed, Later", "focus the search field"),
        ("↑ ↓ ⏎", "Formats", "move the pick; take it back to the video sheet"),
    ]
    key_rows = "".join(f"<tr><td><code>{html.escape(k)}</code></td><td>{html.escape(w)}</td>"
                       f"<td>{html.escape(d)}</td></tr>" for k, w, d in keys)
    return head + f"""<main>
<div class="eyebrow">For approval · 2026-10-10 · drawn by the real app</div>
<h1>Filled in where the spec is silent</h1>
<p class="lede">The second half of <code>design/divergences.md</code>: the places the build had to decide something no mockup draws. Every frame below is the real app composed headless on a throwaway queue, with the phone at UTC+4 as the mockups assume, so this is exactly what the branch draws. Approve them together, or send back the ones you want changed.</p>

<h2>The status bar, for every verdict</h2>
<p>The spec draws <code>WAITING</code> and <code>↓ 18%</code>. Every other verdict gets one label word too, never only a colour, and the right segment is the countdown only where there is one.</p>
<div class="tablewrap"><table><tr><th>When</th><th>The last row</th></tr>{status_rows}</table></div>

<h2>Stop, and notices</h2>
{section(["f-stop", "f-stop-feed", "f-notice", "f-notice-withheld"])}

<h2>Download now and Run now</h2>
{section(["f-now-counted", "f-now-blind", "f-now-asking", "f-run-counted"])}

<h2>More, and the sheets it opens</h2>
{section(["f-more", "f-skip", "f-chips", "f-dests", "f-path", "f-job", "f-log"])}

<h2>The running download</h2>
{section(["f-pause"])}

<h2>Words where no mockup had any</h2>
{section(["f-failed", "f-done", "f-empty", "f-before", "f-narrow", "f-rename", "f-said"])}

<h2>Keys the spec does not list</h2>
<p>Nothing on screen changes for these; every button still shows its own key.</p>
<div class="tablewrap"><table><tr><th>Key</th><th>Where</th><th>Does</th></tr>{key_rows}</table></div>

<h2>And one that needs no picture</h2>
<p>A bare <code>nibbles</code> opens on Search, as design §9 proposed; <code>nibbles queue</code>, <code>feed</code>, <code>later</code> or <code>more</code> open another tab.</p>
</main>
"""


def main() -> int:
    statuses = status_page()
    screens = build()
    out = REPO / "design" / "mockups" / "fillins.html"
    out.write_text(page(screens, statuses), encoding="utf-8")
    for s in screens:
        for sh in s["shots"]:
            (REPO / "design" / "mockups" / f"{s['key']}.{s['width']}x{sh['rows']}.txt").write_text(
                sh["plain"] + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(screens)} screens)")
    shutil.rmtree(ROOT, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
