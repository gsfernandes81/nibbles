"""What ytq asks the internet for, and what it says before it asks.

Every function here is on the road to spending metered data, so what is pinned
is the *cost shape*: one request per search, one page per look at the feed, the
cookie question asked before the request rather than after the empty answer,
and a price on screen before the key that spends it.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from hypothesis import given
from hypothesis import strategies as st

import ytq


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
