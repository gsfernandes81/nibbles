"""What ytq asks the internet for, and what it says before it asks.

Every function here is on the road to spending metered data, so what is pinned
is the *cost shape*: one request per search, one page per look at the feed, the
cookie question asked before the request rather than after the empty answer,
and a price on screen before the key that spends it.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import zipfile

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nibbles import ytq


def after(argv: list[str], flag: str) -> str:
    assert flag in argv, f"{flag} is not in {argv}"
    return argv[argv.index(flag) + 1]


# --------------------------------------------------------------------------- #
# One request, not twenty
# --------------------------------------------------------------------------- #


@given(count=st.integers(min_value=1, max_value=200))
def test_a_search_is_one_flat_request_for_a_stated_number(count):
    """``--flat-playlist`` is the difference between ~0.1 MB and twenty
    extractions, and the expensive shape looks almost identical."""
    argv = ytq.search_argv("crust of rust", count)
    assert "--flat-playlist" in argv
    assert "-J" in argv
    assert f"ytsearch{count}:crust of rust" in argv
    # The dates it prints are only approximate because of this, so the two
    # travel together or the `~` on every row is a lie.
    for token in ytq.APPROX_DATE_ARGS:
        assert token in argv


@given(count=st.integers(min_value=1, max_value=ytq.SUBS_MAX))
def test_a_look_at_the_feed_is_bounded_to_what_was_asked_for(count):
    """Unbounded, yt-dlp follows every continuation youtube offers — which for
    a few years of subscriptions is hundreds of pages on a metered radio."""
    argv = ytq.subs_argv(count)
    assert after(argv, "--playlist-end") == str(count)
    assert "--flat-playlist" in argv
    assert ytq.SUBS_URL in argv


@given(count=st.integers(min_value=1, max_value=ytq.SUBS_MAX))
def test_a_look_at_watch_later_is_bounded_the_same_way(count):
    """A Watch Later kept as a to-do list for years is thousands long, so the
    bound is the same whole cost argument as the feed's."""
    argv = ytq.later_argv(count)
    assert after(argv, "--playlist-end") == str(count)
    assert "--flat-playlist" in argv
    assert ytq.WL_URL in argv
    assert ytq.SUBS_URL not in argv


def test_each_list_reads_its_own_page(monkeypatch):
    """One road for both lists, and the road carries which one it is."""
    seen = []
    monkeypatch.setattr(ytq, "ask", lambda argv, timeout: seen.append(argv) or {})
    ytq.read_feed(ytq.WATCH_LATER, 30)
    ytq.subscriptions(30)
    assert ytq.WL_URL in seen[0] and ytq.SUBS_URL not in seen[0]
    assert ytq.SUBS_URL in seen[1] and ytq.WL_URL not in seen[1]


def test_neither_request_disables_the_user_config():
    """The cookies and the JS runtime live there; without them youtube
    answers with a fraction of what it has, or refuses."""
    for argv in (ytq.search_argv("x"), ytq.subs_argv(), ytq.later_argv()):
        assert not any(token.startswith("--ignore-config") for token in argv)
        assert "--no-config-locations" not in argv


def test_the_search_and_the_feed_start_with_the_same_yt_dlp():
    head = ytq.ytdl_item.ytdl_argv()
    assert ytq.search_argv("x")[: len(head)] == head
    assert ytq.subs_argv()[: len(head)] == head


# --------------------------------------------------------------------------- #
# Reading the answer
# --------------------------------------------------------------------------- #


def fake_run(stdout="", stderr="", code=0, blow_up=None):
    def run(argv, capture_output, text, timeout):
        if blow_up is not None:
            raise blow_up
        return subprocess.CompletedProcess(argv, code, stdout, stderr)
    return run


def test_every_way_yt_dlp_can_fail_comes_back_as_one_error(monkeypatch):
    """One door, because three copies of "yt-dlp is not installed" drift."""
    cases = [
        fake_run(blow_up=FileNotFoundError()),
        fake_run(blow_up=subprocess.TimeoutExpired("yt-dlp", 5)),
        fake_run(code=1, stderr="ERROR: Video unavailable"),
        fake_run(stdout="not json at all"),
        fake_run(stdout="[1, 2, 3]"),
    ]
    for run in cases:
        monkeypatch.setattr(ytq.subprocess, "run", run)
        with pytest.raises(ytq.ProbeError):
            ytq.ask(["yt-dlp"], 5)


def test_a_playlist_url_is_refused_rather_than_queued(monkeypatch):
    monkeypatch.setattr(
        ytq.subprocess, "run",
        fake_run(stdout=json.dumps({"_type": "playlist", "entries": []})),
    )
    with pytest.raises(ytq.ProbeError):
        ytq.probe("https://youtube.com/playlist?list=x")


def test_a_probe_answers_a_list_from_its_first_page(monkeypatch):
    """``-J`` alone extracts every entry of a playlist or a channel in full —
    a watch page and player calls each — before the refusal arrives; the
    sheet's ~0.3 MB was a price for one video. Bounded the way the search and
    the feed are, a list is refused off its first page, and a video still
    comes back whole."""
    asked = []
    answers = iter([
        {"_type": "playlist", "entries": [{"id": "a"}]},
        {"_type": "multi_video", "entries": [{"id": "a"}]},
        {"id": "a", "formats": [{"format_id": "18"}]},
    ])
    monkeypatch.setattr(ytq, "ask", lambda argv, timeout: asked.append(argv) or next(answers))
    for url in ("https://www.youtube.com/playlist?list=PLx", "https://example.org/parts"):
        with pytest.raises(ytq.ProbeError):
            ytq.probe(url)
    video = ytq.probe("https://youtu.be/a")
    assert video["formats"]
    for argv in asked:
        assert "--flat-playlist" in argv
        assert int(after(argv, "--playlist-end")) <= 1
        assert "--no-playlist" in argv and "-J" in argv
        assert argv[: len(ytq.ytdl_item.ytdl_argv())] == ytq.ytdl_item.ytdl_argv()
        assert not any(token.startswith("--ignore-config") for token in argv)


def test_channels_and_playlists_are_dropped_from_a_search(monkeypatch):
    info = {
        "entries": [
            {"id": "a", "title": "a video", "ie_key": "Youtube"},
            {"_type": "channel", "id": "c", "title": "a channel"},
            {"_type": "playlist", "id": "p", "title": "a playlist"},
            "not even a dict",
            {"title": "no id and no url"},
        ]
    }
    found = ytq.entries(info)
    assert [hit.title for hit in found] == ["a video"]
    # No url in the entry, so one was made from the id — the row is still
    # pickable, which is the point of tolerating the field being absent.
    assert "a" in found[0].url


def test_an_entry_carries_its_view_count_when_there_is_one():
    found = ytq.entries({"entries": [
        {"id": "a", "title": "a", "view_count": 1234},
        {"id": "b", "title": "b", "view_count": 5.0},
        {"id": "c", "title": "c"},
        {"id": "d", "title": "d", "view_count": "many"},
        {"id": "e", "title": "e", "view_count": True},
        {"id": "f", "title": "f", "view_count": float("nan")},
    ]})
    assert [hit.views for hit in found] == [1234, 5, None, None, None, None]


@pytest.mark.parametrize("count, shown", [
    (0, "0"),
    (7, "7"),
    (999, "999"),
    (1_000, "1.0K"),
    (1_234, "1.2K"),
    (1_299, "1.2K"),
    (9_999, "9.9K"),
    (10_000, "10K"),
    (12_345, "12K"),
    (999_999, "999K"),
    (1_000_000, "1.0M"),
    (1_950_000, "1.9M"),
    (34_567_890, "34M"),
    (1_100_000_000, "1.1B"),
    (15_000_000_000, "15B"),
])
def test_a_view_count_is_shortened_the_way_youtube_does(count, shown):
    """Truncated and not rounded: ``999_999`` rounded is ``1000K``, a unit the
    list never uses, and a rounded count is a count shown as more than it is."""
    assert ytq.views(count) == shown


@pytest.mark.parametrize("count", [None, -1, True, "12"])
def test_no_view_count_is_shown_as_nothing(count):
    assert ytq.views(count) == ""


def test_an_entry_keeps_what_the_duplicate_check_recognises_it_by():
    hit = ytq.entries({"entries": [{"id": "xyz", "ie_key": "Youtube", "title": "t"}]})[0]
    assert hit.key == ytq.source_key({"id": "xyz", "ie_key": "Youtube"})


# --------------------------------------------------------------------------- #
# The price of the next look
# --------------------------------------------------------------------------- #


def test_a_deeper_look_re_buys_the_whole_listing():
    """Youtube's continuations are sequential: there is no asking for 31-60
    without walking 1-30, so the figure is the total and never the increment."""
    one = float(ytq.feed_cost(ytq.SUBS_RESULTS).strip("~ MB"))
    two = float(ytq.feed_cost(ytq.SUBS_RESULTS * 2).strip("~ MB"))
    assert two == pytest.approx(one * 2, rel=0.05)


def test_the_end_of_the_feed_and_the_cap_are_different_sentences():
    # Fewer back than asked for: there is nothing further to reach.
    assert ytq.next_page(28, 30) == (None, False)
    # At the cap: there IS more and ytq will not spend it.
    assert ytq.next_page(ytq.SUBS_MAX, ytq.SUBS_MAX) == (None, True)


@given(asked=st.integers(min_value=1, max_value=400))
def test_a_deeper_look_never_asks_past_the_cap(asked):
    more, at_cap = ytq.next_page(asked, asked)
    assert more is None or ytq.SUBS_MAX >= more > asked
    assert not (more and at_cap)


def test_the_down_arrow_completes_onto_the_first_new_row():
    """↓ at the last row is what asked for the deeper look, and that key's
    motion finishes when the fetch does."""
    assert ytq.bumped_place((29, 10), 30) == (30, 10)
    assert ytq.bumped_place((5, 0), 30) == (5, 0)
    assert ytq.bumped_place((0, 0), 0) == (0, 0)


def test_the_feed_line_carries_the_price_at_every_width():
    for width in range(32, 100):
        line = ytq.feed_meta(30, "just now", 60, False, width)
        assert len(line) <= width
        # The price is the fact this line exists for; the age is the comfort.
        assert "0.4" in line and "60" in line
    at_end = ytq.feed_meta(28, "just now", None, False, 80)
    at_cap = ytq.feed_meta(150, "just now", None, True, 80)
    assert at_end != at_cap


# --------------------------------------------------------------------------- #
# Which of the three things the one field was handed
# --------------------------------------------------------------------------- #


def test_the_feed_is_asked_about_before_the_url_test():
    """The feed's own URL passes ``looks_like_url`` too, so a router that
    asked that first would probe it and get the playlist refusal."""
    assert ytq.looks_like_feed(ytq.SUBS_URL)
    assert ytq.looks_like_url(ytq.SUBS_URL)


def test_watch_later_is_asked_about_before_the_url_test_too():
    """Its page is a playlist URL, which the probe would refuse as one."""
    assert ytq.which_feed(ytq.WL_URL) is ytq.WATCH_LATER
    assert ytq.which_feed("youtube.com/playlist?list=WL&pp=x") is ytq.WATCH_LATER
    assert ytq.looks_like_url(ytq.WL_URL)
    assert ytq.which_feed(ytq.SUBS_URL) is ytq.SUBS


def test_a_video_played_out_of_watch_later_is_that_video():
    """``&list=WL`` rides along on every video opened from the list, and a
    pasted one of those is asking for the video, not the list."""
    for link in ("https://www.youtube.com/watch?v=abc&list=WL&index=3",
                 "https://www.youtube.com/playlist?list=WLx",
                 "https://www.youtube.com/playlist?list=PLabc"):
        assert ytq.which_feed(link) is None, link


@given(word=st.sampled_from(ytq.WL_WORDS))
def test_every_spelling_of_watch_later_is_taken_however_it_is_typed(word):
    assert ytq.which_feed(f"  {word.upper()} ") is ytq.WATCH_LATER


def test_the_two_lists_are_told_apart():
    assert not set(ytq.FEED_WORDS) & set(ytq.WL_WORDS)
    assert set(ytq.FEEDS) == {ytq.SUBS_KEY, ytq.WL_KEY}
    # Cached beside searches under keys nobody can type as a search.
    assert all(key.startswith(":") for key in ytq.FEEDS)
    assert ytq.which_feed("later") is None


@given(word=st.sampled_from(ytq.FEED_WORDS))
def test_every_spelling_of_the_feed_is_taken_however_it_is_typed(word):
    assert ytq.looks_like_feed(f"  {word.upper()} ")


def test_words_are_words_and_links_are_links():
    assert not ytq.looks_like_url("crust of rust")
    assert not ytq.looks_like_url("")
    assert not ytq.looks_like_feed("subs of rust")
    for link in ("https://youtu.be/x", "www.youtube.com/watch?v=x",
                 "youtu.be/x", "youtube.com/watch?v=x"):
        assert ytq.looks_like_url(link)


# --------------------------------------------------------------------------- #
# The cookie, asked about before anything is spent
# --------------------------------------------------------------------------- #


def test_no_config_at_all_is_a_refusal(tmp_path):
    state, detail = ytq.cookie_state([tmp_path / "nothing"])
    assert state == "none"
    assert ytq.CONFIG_SUGGESTION in detail


def test_a_config_with_no_cookie_line_names_the_file_it_is_missing_from(tmp_path):
    config = tmp_path / "config"
    config.write_text("--js-runtimes node\n# --cookies is only a comment here\n")
    state, detail = ytq.cookie_state([config])
    assert state == "none"
    assert str(config) in detail or ytq.tilde(config) in detail


def test_a_jar_that_is_named_but_not_there_is_told_from_one_that_is(tmp_path):
    jar = tmp_path / "cookies.txt"
    config = tmp_path / "config"
    config.write_text(f"--cookies {jar}\n")
    assert ytq.cookie_state([config])[0] == "missing"
    jar.write_text("")
    assert ytq.cookie_state([config])[0] == "missing"  # empty is not a session
    jar.write_text("# Netscape HTTP Cookie File\n")
    state, detail = ytq.cookie_state([config])
    assert state == "file"
    # How old the jar is, which is what turns "the feed is empty" into a
    # sentence somebody can act on.
    assert "today" in detail


def test_a_quoted_path_reads_the_way_yt_dlp_reads_it(tmp_path):
    """Parsed with shlex per line, the way yt-dlp parses these files: a path
    with a space in it has to read the same here as it does there."""
    spaced = tmp_path / "my cookies.txt"
    spaced.write_text("x")
    config = tmp_path / "config"
    config.write_text(f'--cookies "{spaced}"\n')
    assert ytq.cookie_state([config])[0] == "file"
    plain = tmp_path / "cookies.txt"
    plain.write_text("x")
    config.write_text(f"--cookies={plain}\n")
    assert ytq.cookie_state([config])[0] == "file"


def test_a_browser_jar_is_a_declaration_and_counts(tmp_path):
    config = tmp_path / "config"
    config.write_text("--cookies-from-browser firefox\n")
    state, detail = ytq.cookie_state([config])
    assert state == "browser"
    assert "firefox" in detail


@pytest.mark.parametrize("spelled", [
    "~/my jars/cookies.txt",
    "$HOME/my jars/cookies.txt",
    "${HOME}/my jars/cookies.txt",
    "$JARDIR/cookies.txt",
    "{absolute}",
])
def test_every_spelling_yt_dlp_expands_names_the_same_jar(monkeypatch, tmp_path, spelled):
    """yt-dlp expands the user and then the variables (``expand_path``) before
    it loads the jar, so ``$HOME/…`` is a working setup there — and a refusal
    here, sending somebody to re-export cookies that are fine."""
    jar = ytq.Path.home() / "my jars" / "cookies.txt"
    jar.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JARDIR", str(jar.parent))
    config = tmp_path / "config"
    spelled = str(jar) if spelled == "{absolute}" else spelled
    config.write_text(f"--cookies {shlex.quote(spelled)}\n")
    jar.write_text("# Netscape HTTP Cookie File\n")
    assert ytq.cookie_state([config])[0] == "file"
    jar.unlink()
    assert ytq.cookie_state([config])[0] == "missing"


def test_yt_dlp_s_user_config_candidates_are_all_there_in_its_order():
    """yt-dlp reads the first of these it can open; a list missing one gets
    wrong which file that is (``get_user_config_dirs`` and
    ``_load_from_config_dirs``)."""
    home = ytq.Path.home()
    xdg = home / ".config"
    assert ytq.config_paths() == [
        xdg / "yt-dlp.conf",
        xdg / "yt-dlp" / "config",
        xdg / "yt-dlp" / "config.txt",
        home / "yt-dlp.conf",
        home / "yt-dlp.conf.txt",
        home / ".yt-dlp" / "config",
        home / ".yt-dlp" / "config.txt",
    ]


#: What one candidate config can be: not there, a directory (which yt-dlp
#: cannot open, so passes over), empty (which it opens, and stops at), a
#: config with no cookies, or one with them.
_CONFIG_STATES = ("absent", "directory", "empty", "other", "cookies")


@given(states=st.lists(st.sampled_from(_CONFIG_STATES), min_size=7, max_size=7))
def test_the_cookies_are_read_from_the_one_config_yt_dlp_reads(states):
    """yt-dlp opens the first candidate it can and reads no other, so a
    ``--cookies`` line behind an earlier file — even an empty one — is never
    read: calling it a go spends a feed read to be told to sign in."""
    home = ytq.Path.home()
    for leftover in (home / ".config", home / ".yt-dlp", home / "yt-dlp.conf",
                     home / "yt-dlp.conf.txt"):
        if leftover.is_dir():
            shutil.rmtree(leftover)
        leftover.unlink(missing_ok=True)
    jar = home / "jar" / "cookies.txt"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_text("# Netscape HTTP Cookie File\n")
    paths = ytq.config_paths()
    for path, state in zip(paths, states, strict=True):
        if state == "directory":
            path.mkdir(parents=True, exist_ok=True)
        elif state != "absent":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text({"empty": "", "other": "--no-mtime\n",
                             "cookies": f"--cookies {jar}\n"}[state])
    opened = [p for p, s in zip(paths, states, strict=True) if s not in ("absent", "directory")]
    read = opened[0] if opened else None
    state, detail = ytq.cookie_state()
    assert ytq.user_config() == read
    assert (state == "file") == (read is not None and states[paths.index(read)] == "cookies")
    declared = ytq.declared_cookies()
    assert (declared[2] if declared else None) == (read if state == "file" else None)
    if state != "file" and read is not None:
        # The file that is read is the one named, and a line it hides is
        # pointed at rather than left for somebody to find.
        assert ytq.tilde(read) in detail
        later = paths[paths.index(read) + 1:]
        hidden = [p for p in later if states[paths.index(p)] == "cookies"]
        if hidden:
            assert ytq.tilde(hidden[0]) in detail


def test_how_old_a_jar_is_said_in_words():
    assert ytq.written(1000.0, now=1000.0) == "today"
    assert ytq.written(1000.0, now=1000.0 + 86400) == "yesterday"
    assert ytq.written(1000.0, now=1000.0 + 86400 * 9).startswith("9 ")
    # A clock that went backwards is not a file written in the future.
    assert ytq.written(2000.0, now=1000.0) == "today"


def test_an_empty_feed_is_never_reported_as_nothing_new():
    """Youtube answers a logged-out feed with no entries rather than an error,
    so the honest-looking reading is the one it cannot have."""
    detail = "~/.config/yt-dlp/cookies.txt, written 30 days ago"
    said = ytq.empty_feed_advice(detail)
    joined = " ".join(said).lower()
    assert "cookie" in joined
    assert "nothing new" not in joined
    assert "up to date" not in joined
    # The fix is one spelling appended to every screen that cannot read the
    # feed, so a refusal and an empty answer cannot go stale apart.
    assert said[-len(ytq.cookie_fix(detail)):] == ytq.cookie_fix(detail)


def test_an_empty_watch_later_says_both_things_it_can_mean():
    """An empty Watch Later can be real, unlike an empty feed — but a
    signed-out session reads the same, so both are said and the fix is on it."""
    detail = "~/.config/yt-dlp/cookies.txt, written 30 days ago"
    said = ytq.empty_later_advice(detail)
    joined = " ".join(said).lower()
    assert "watch later" in joined
    assert "cookie" in joined
    assert said[-len(ytq.cookie_fix(detail)):] == ytq.cookie_fix(detail)
    assert ytq.WATCH_LATER.empty is ytq.empty_later_advice
    assert ytq.SUBS.empty is ytq.empty_feed_advice


def test_the_end_of_each_list_says_which_list_it_is_the_end_of():
    for feed in ytq.FEEDS.values():
        line = ytq.feed_meta(12, "just now", None, False, 80, feed.whole)
        assert feed.whole in line


def test_the_refusal_carries_the_same_fix_and_says_which_it_is():
    detail = "there is no yt-dlp config"
    none = ytq.cookie_advice("none", detail)
    missing = ytq.cookie_advice("missing", detail)
    assert none[0] != missing[0]
    for said in (none, missing):
        assert said[-len(ytq.cookie_fix(detail)):] == ytq.cookie_fix(detail)


# --------------------------------------------------------------------------- #
# Saying how old and how long, roughly and honestly
# --------------------------------------------------------------------------- #


def test_an_age_that_is_not_known_is_never_invented():
    assert ytq.age(None) == "?"
    assert ytq.age(0) == "?"
    assert ytq.age("yesterday") == "?"


@given(days=st.integers(min_value=0, max_value=40 * 365))
def test_every_age_but_today_says_it_is_approximate(days):
    now = 2_000_000_000.0
    said = ytq.age(int(now - days * 86400), now=now)
    assert said.startswith("~") or said == "<1d"


@given(
    older=st.integers(min_value=1, max_value=40 * 365),
    newer=st.integers(min_value=0, max_value=40 * 365),
)
def test_older_never_reads_as_newer(older, newer):
    """The one thing a rounded age has to get right is the order of two."""
    units = {"d": 1, "w": 2, "mo": 3, "y": 4}

    def rank(days):
        said = ytq.age(int(2e9 - days * 86400), now=2e9)
        if said == "<1d":
            return (0, 0)
        found = re.fullmatch(r"~(\d+)(d|w|mo|y)", said)
        assert found, said
        return units[found.group(2)], int(found.group(1))

    if older > newer:
        assert rank(older) >= rank(newer)


def test_a_length_is_minutes_and_seconds_or_what_it_is_instead():
    assert ytq.clock(90) == "1m30s"
    assert ytq.clock(None) == "?"
    assert ytq.clock(0) == "?"
    assert ytq.clock(90, live=True) == "live"


def test_how_old_the_listing_on_screen_is():
    assert ytq.freshness(None) == ""
    assert ytq.freshness(1000.0, now=1000.0) == "just now"
    assert ytq.freshness(1000.0, now=1000.0 + 600).endswith("m ago")
    assert ytq.freshness(1000.0, now=1000.0 + 7200).endswith("h ago")


# --------------------------------------------------------------------------- #
# Where each phrase changes, which is what makes it a rounded answer
# --------------------------------------------------------------------------- #


def test_the_age_changes_unit_where_the_precision_does():
    """``~3w`` and ``~4mo`` are different claims about how much is known."""
    now = 2_000_000_000.0

    def said(days):
        return ytq.age(int(now - days * 86400), now=now)

    assert said(0) == "<1d"
    assert said(1) == "~1d"
    assert said(13) == "~13d"
    assert said(14) == "~2w"
    assert said(55) == "~7w"
    assert said(56) == "~1mo"
    assert said(729) == "~24mo"
    assert said(730) == "~2y"


def test_the_listing_s_age_changes_unit_too():
    read = 1_000.0
    assert ytq.freshness(read, now=read + 89) == "just now"
    assert ytq.freshness(read, now=read + 90) == "1m ago"
    assert ytq.freshness(read, now=read + 5399) == "89m ago"
    assert ytq.freshness(read, now=read + 5400) == "1h ago"


# --------------------------------------------------------------------------- #
# Tolerating every field being absent, without losing the row
# --------------------------------------------------------------------------- #


def test_a_row_is_kept_however_the_answer_spells_it():
    """yt-dlp's flat entries carry different keys on different days; a row
    dropped here is a video somebody cannot pick."""
    found = ytq.entries({"entries": [
        {"id": "a", "ie_key": "Youtube", "title": "first",
         "webpage_url": "https://www.youtube.com/watch?v=a"},
        {"_type": "channel", "id": "c"},
        "not even a dict",
        {"id": "b", "ie_key": "Youtube", "title": "  ",
         "uploader": "An Uploader", "release_timestamp": 1_700_000_000,
         "live_status": "is_live"},
    ]})
    # Everything after a skipped entry is still there: the skips are a
    # `continue`, not the end of the list.
    assert len(found) == 2
    assert found[0].url == "https://www.youtube.com/watch?v=a"
    # A title that is only spaces is not a title.
    assert found[1].title == "(untitled)"
    # The channel comes from whichever key carried it.
    assert found[1].channel == "An Uploader"
    # And the date from whichever key carried that.
    assert ytq.age(found[1].timestamp) != "?"
    assert found[1].live is True
    assert ytq.clock(found[1].duration, found[1].live) == "live"


def test_a_video_that_is_not_live_is_not_marked_live():
    hit = ytq.entries({"entries": [
        {"id": "a", "ie_key": "Youtube", "title": "t", "live_status": "not_live",
         "duration": 90}
    ]})[0]
    assert hit.live is False
    assert ytq.clock(hit.duration, hit.live) == "1m30s"


# --------------------------------------------------------------------------- #
# What `nibbles <x>` takes: what yt-dlp would
# --------------------------------------------------------------------------- #


def test_what_yt_dlp_would_take_is_taken(monkeypatch):
    monkeypatch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: text == "dQw4w9WgXcQ")
    assert ytq.read_input("https://vimeo.com/76979871") == ("url", "https://vimeo.com/76979871")
    assert ytq.read_input("youtu.be/dQw4w9WgXcQ") == ("url", "youtu.be/dQw4w9WgXcQ")
    # A link typed without its scheme gets one, the way yt-dlp fixes it up.
    assert ytq.read_input("example.com/a.iso") == ("url", "https://example.com/a.iso")
    # yt-dlp's YouTube search keys are the app's own search.
    assert ytq.read_input("ytsearch:crust of rust") == ("search", "crust of rust")
    assert ytq.read_input("ytsearch5:rust") == ("search", "rust")
    assert ytq.read_input("ytsearchdate:rust") == ("search", "rust")
    # What only an extractor knows is a link: asked of yt-dlp.
    assert ytq.read_input("dQw4w9WgXcQ") == ("url", "dQw4w9WgXcQ")


def test_what_yt_dlp_would_not_take_is_not(monkeypatch):
    monkeypatch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: False)
    for text in ("", "   ", "ytsearch:", "crust of rust", "stauts", "subs"):
        assert ytq.read_input(text) is None, text
    # And with no yt-dlp to ask, an extractor's word is not guessed at.
    monkeypatch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: None)
    assert ytq.read_input("dQw4w9WgXcQ") is None


@given(text=st.from_regex(r"[A-Za-z][a-z]{0,10}(-[a-z]{1,11}){0,3}", fullmatch=True))
def test_a_word_is_never_asked_of_yt_dlp(text):
    """``programming`` is eleven of YouTube's id characters, and yt-dlp would
    take it as one: a word is refused before yt-dlp is asked, so typing one
    never spends a probe."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: pytest.fail(text))
        assert ytq.read_input(text) is None


@given(ident=st.from_regex(r"[A-Za-z0-9_-]{11}", fullmatch=True)
       .filter(lambda text: re.search(r"[0-9_]|.[A-Z]|^-|-$|--", text)))
def test_what_is_shaped_like_an_id_is_still_asked(ident):
    """A digit, an underscore, a capital past the first letter, a stray
    hyphen: not a word, so yt-dlp is asked, and a yes is a link."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ytq, "yt_dlp_takes", lambda text, timeout=30: True)
        assert ytq.read_input(ident) == ("url", ident)


def test_yt_dlp_itself_is_asked_offline(monkeypatch, tmp_path):
    """Against a stand-in ``yt_dlp`` whose one extractor takes eleven-letter
    ids, and whose catch-all takes everything: the catch-all is not asked."""
    package = tmp_path / "yt_dlp"
    (package / "extractor").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "extractor" / "__init__.py").write_text(
        "import re\n"
        "class Youtube:\n"
        "    @staticmethod\n"
        "    def ie_key(): return 'Youtube'\n"
        "    @staticmethod\n"
        "    def suitable(text): return re.fullmatch(r'[0-9A-Za-z_-]{11}', text) is not None\n"
        "class Generic:\n"
        "    @staticmethod\n"
        "    def ie_key(): return 'Generic'\n"
        "    @staticmethod\n"
        "    def suitable(text): return True\n"
        "def gen_extractor_classes(): return [Youtube, Generic]\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    assert ytq.yt_dlp_takes("dQw4w9WgXcQ") is True
    assert ytq.yt_dlp_takes("stauts") is False


def test_a_link_only_yt_dlp_knows_opens_its_sheet_not_a_search(monkeypatch, capsys):
    """``--link`` (nibbles' own, hidden) hands the app a link the field would
    search for, marked as one."""
    from nibbles import app as nibbles

    seen = {}
    monkeypatch.setattr(ytq.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(nibbles, "run", lambda tab, first, *a, **k: seen.update(first=first) or [])
    assert ytq.main(["--link", "dQw4w9WgXcQ"]) == 0
    assert seen["first"] == ytq.LINK_KEY + "dQw4w9WgXcQ"


def test_stop_kills_the_yt_dlp_a_fetch_is_waiting_on():
    """Inside a fetch, ``ask`` hands its child to the job, so ``x`` ends it
    rather than leaving it spending until it answers."""
    import sys
    import time

    from nibbles import tui

    job = tui.Job(lambda: ytq.ask([sys.executable, "-c", "import time; time.sleep(30)"], 60),
                  "asking")
    job.run(lambda: None)
    end = time.monotonic() + 10
    while job._child is None and time.monotonic() < end:
        time.sleep(0.01)
    assert job._child is not None
    job.cancel()
    while not job.finished and time.monotonic() < end:
        time.sleep(0.01)
    assert job.finished
    assert isinstance(job.error, tui.Cancelled)


def test_a_fetch_that_ignores_its_timeout_still_comes_back():
    """A child that shrugs off SIGTERM is not waited on past its timeout."""
    import sys
    import time

    from nibbles import tui

    stubborn = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('', flush=True); time.sleep(30)")
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        tui.run_child([sys.executable, "-c", stubborn], 1)
    assert time.monotonic() - began < 10


# --------------------------------------------------------------------------- #
# The upgrade line, read off the machine
# --------------------------------------------------------------------------- #


def _uv_tool(folder, patch, receipt: str):
    """A uv tool venv holding *receipt*, and a ``yt-dlp`` on PATH run by it."""
    venv = folder / "tools" / "yt-dlp"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    python = venv / "bin" / "python"
    python.write_text("")
    (venv / ytq.UV_RECEIPT).write_text(receipt)
    binary = folder / "yt-dlp"
    binary.write_text(f"#!{python}\n")
    patch.setattr(ytq.shutil, "which", lambda name: str(binary))


def _operands(line: str) -> tuple[str, list[str]]:
    """``uv tool install TOOL --with A --with B --force`` → ``(TOOL, [A, B])``."""
    words = shlex.split(line)
    assert words[:3] == ["uv", "tool", "install"] and words[-1] == "--force"
    middle = words[4:-1]
    assert middle[::2] == ["--with"] * (len(middle) // 2)
    return words[3], middle[1::2]


def _spec(entry: dict, pinned: bool = True) -> str:
    extras = entry.get("extras") or []
    return (entry["name"] + (f"[{','.join(extras)}]" if extras else "")
            + (entry.get("specifier", "") if pinned else ""))


def test_the_line_for_an_install_with_extras_keeps_them_and_every_with(tmp_path, monkeypatch):
    """What uv writes for ``uv tool install "yt-dlp[default]" --with yt-dlp-ejs``.
    The ``]`` closing the extras once ended the list, so the line dropped them
    and every ``--with`` after them — and following it uninstalled the very
    solver the same notice says ``yt-dlp -v`` must show."""
    _uv_tool(tmp_path, monkeypatch, (
        "[tool]\n"
        "requirements = [\n"
        '    { name = "yt-dlp", extras = ["default"] },\n'
        '    { name = "yt-dlp-ejs" },\n'
        "]\n"
        "entrypoints = [\n"
        '    { name = "yt-dlp", install-path = "/x/bin/yt-dlp", from = "yt-dlp" },\n'
        "]\n"
    ))
    tool, withs = _operands(ytq.upgrade_command("yt-dlp"))
    assert tool == "yt-dlp[default]"
    assert withs == ["yt-dlp-ejs"]


_NAMES = st.from_regex(r"[a-z][a-z0-9]{0,5}(-[a-z0-9]{1,3})?", fullmatch=True).filter(
    lambda name: name != "yt-dlp")
_EXTRAS = st.lists(st.from_regex(r"[a-z]{1,6}", fullmatch=True), max_size=2, unique=True)
_PINS = st.sampled_from(["", ">=1.10", "==2026.9.1", ">=1.0,<3", "~=0.3"])


def _toml(entry: dict) -> str:
    parts = [f'name = "{entry["name"]}"']
    if entry["extras"]:
        parts.append("extras = [" + ", ".join(f'"{e}"' for e in entry["extras"]) + "]")
    if entry["specifier"]:
        parts.append(f'specifier = "{entry["specifier"]}"')
    return "    { " + ", ".join(parts) + " },\n"


@given(
    own=st.fixed_dictionaries({"extras": _EXTRAS, "specifier": _PINS}),
    withs=st.lists(st.fixed_dictionaries({"name": _NAMES, "extras": _EXTRAS,
                                          "specifier": _PINS}),
                   max_size=4, unique_by=lambda e: e["name"]),
)
def test_the_upgrade_line_reinstalls_exactly_what_uv_recorded(own, withs):
    """Every ``--with`` comes back with its extras and its pin, the tool with
    its extras, and the one thing left behind is the tool's own pin — moving
    past it is the point of ``install --force``."""
    import tempfile

    own = {"name": "yt-dlp", **own}
    receipt = "[tool]\nrequirements = [\n" + "".join(map(_toml, [own, *withs])) + "]\n"
    with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
        _uv_tool(ytq.Path(folder), patch, receipt)
        tool, said = _operands(ytq.upgrade_command("yt-dlp"))
    assert tool == _spec(own, pinned=False)
    assert said == [_spec(entry) for entry in withs]


def _zipapp(path) -> None:
    """yt-dlp's single-file release: an ``env`` shebang in front of a zip."""
    import io

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("__main__.py", "print('yt-dlp')\n")
    path.write_bytes(b"#!/usr/bin/env python3\n" + archive.getvalue())


@pytest.mark.parametrize("install, first", [
    ("zipapp", "yt-dlp"),
    ("built binary", "yt-dlp"),
    ("pip script", "python3"),
    ("env script", "python3"),
])
def test_the_upgrade_line_is_one_that_runs(tmp_path, monkeypatch, install, first):
    """The release updates itself; a pip install is upgraded by the python it
    names — and the ``env`` in front of either is never that python."""
    binary = tmp_path / "yt-dlp"
    if install == "zipapp":
        _zipapp(binary)
    elif install == "built binary":
        binary.write_bytes(b"\x7fELF\x02\x01\x01" + bytes(64))
    elif install == "pip script":
        binary.write_text("#!/usr/bin/python3\nimport yt_dlp\n")
    else:
        binary.write_text("#!/usr/bin/env python3\nimport yt_dlp\n")
    found = {"yt-dlp": str(binary), "python3": "/usr/bin/python3"}
    monkeypatch.setattr(ytq.shutil, "which", found.get)
    words = ytq.upgrade_command("yt-dlp").split()
    assert words[0] == first
    assert ytq.Path(words[0]).name != "env"
    assert ("-m pip" in " ".join(words)) == (first == "python3")
