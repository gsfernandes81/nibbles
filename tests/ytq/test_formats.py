"""The format list: what is offered, at what cap, and what a thin answer means.

The cap is the number the runner holds an item to, so a format offered without
a measured size is an item either refused every night for being too big or
killed by the watchdog for being bigger than it claimed. And a list holding
nothing but 360p has two completely different causes with two completely
different fixes, which is the one thing this half must not conflate.
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

import ytq
from conftest import fmt, video_info

MiB = 1024 * 1024


def test_a_format_with_no_stated_size_is_hidden_and_counted():
    """The queue needs a measured cap, not a guess — and a short list has to
    explain itself or it reads as a video that only exists in 360p."""
    info = video_info(formats=[
        fmt("137", vcodec="avc1", ext="mp4", height=1080, filesize=100 * MiB),
        fmt("299", vcodec="avc1", ext="mp4", height=1080),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=5 * MiB),
    ])
    options, unsized = ytq.choices(info)
    assert unsized == 1
    assert all(option.size > 0 for option in options)


def test_storyboards_are_not_downloads():
    info = video_info(formats=[
        fmt("sb0", ext="mhtml", filesize=1000),
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", height=360,
            filesize=10 * MiB),
    ])
    options, unsized = ytq.choices(info)
    assert [option.fmt for option in options] == ["18"]
    assert unsized == 0


def test_a_merge_costs_both_streams_together():
    info = video_info(formats=[
        fmt("137", vcodec="avc1.640028", ext="mp4", height=1080,
            filesize=400 * MiB),
        fmt("140", acodec="mp4a.40.2", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    options, _ = ytq.choices(info)
    merged = next(o for o in options if o.kind == "merge")
    assert merged.fmt == "137+140"
    assert merged.size == 410 * MiB
    # Same container family both sides, so no transcode and no fallback to mkv.
    assert merged.merge_ext == "mp4"


def test_a_mixed_pair_is_merged_into_matroska():
    info = video_info(formats=[
        fmt("248", vcodec="vp9", ext="webm", height=1080, filesize=300 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    merged = next(o for o in ytq.choices(info)[0] if o.kind == "merge")
    assert merged.merge_ext == "mkv"


def test_audio_only_rows_sort_to_the_bottom():
    options, _ = ytq.choices(video_info())
    kinds = [option.kind for option in options]
    assert kinds == sorted(kinds, key=lambda kind: kind == "audio")
    assert "audio" in kinds


def test_video_rows_are_largest_first():
    """Row 0 is always the biggest file, which is why the cursor does not
    open there when a format was chosen last time."""
    videos = [o.size for o in ytq.choices(video_info())[0] if o.kind != "audio"]
    assert videos == sorted(videos, reverse=True)


def test_a_measured_size_takes_a_smaller_margin_than_an_estimated_one():
    """``~`` on the row and 12% instead of 3% are the same fact twice."""
    exact = ytq.Choice("single", "18", 100 * MiB, True, "mp4", "360p", "")
    approx = ytq.Choice("single", "18", 100 * MiB, False, "mp4", "360p", "")
    assert approx.expect_bytes > exact.expect_bytes > 100 * MiB


@given(
    size=st.integers(min_value=1, max_value=8 * 1024**3),
    exact=st.booleans(),
)
def test_the_cap_is_always_more_than_the_measurement(size, exact):
    """Payload bytes are not wire bytes, and the item pays for one metadata
    extraction per firing on top."""
    choice = ytq.Choice("single", "18", size, exact, "mp4", "360p", "")
    assert choice.expect_bytes >= size + ytq.OVERHEAD_FIXED
    assert isinstance(choice.expect_bytes, int)
    assert choice.expect_bytes == math.ceil(
        size * (ytq.OVERHEAD_EXACT if exact else ytq.OVERHEAD_APPROX)
    ) + ytq.OVERHEAD_FIXED


# --------------------------------------------------------------------------- #
# The bot check, told apart from a video that really is 360p only
# --------------------------------------------------------------------------- #


def test_a_youtube_answer_with_no_adaptive_stream_is_a_refusal():
    """A youtube video always has adaptive streams, so none at all is not a
    video that only exists in 360p — it is an extraction that was refused."""
    assert ytq.withheld(video_info(formats=[
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=10 * MiB),
        fmt("sb0", ext="mhtml"),
    ]))


def test_an_answer_holding_adaptive_streams_is_not_a_refusal():
    assert not ytq.withheld(video_info())


def test_only_youtube_is_accused_of_a_bot_check():
    """The claim is specific to youtube; a plain .mp4 URL legitimately serves
    one progressive file."""
    info = video_info(extractor="generic", formats=[
        fmt("0", vcodec="h264", acodec="aac", ext="mp4", filesize=10 * MiB),
    ])
    assert not ytq.withheld(info)


def test_the_two_ways_of_seeing_one_row_are_not_conflated():
    """``withheld`` reads the RAW formats and ``choices`` reports what it had
    to drop; the same symptom, two different fixes."""
    info = video_info(formats=[
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=10 * MiB),
        fmt("137", vcodec="avc1", ext="mp4", height=1080),  # adaptive, unsized
        fmt("140", acodec="mp4a", ext="m4a", abr=129),      # adaptive, unsized
    ])
    options, unsized = ytq.choices(info)
    assert len(options) == 1 and unsized == 2
    assert not ytq.withheld(info)


def test_an_answer_with_no_formats_at_all_is_not_accused():
    assert not ytq.withheld(video_info(formats=[]))


def test_the_notice_leads_with_the_version_and_carries_a_real_command():
    """It used to lead with the cookies, and sent somebody down two dead ends
    with a correct config and a six-week-old yt-dlp."""
    said = ytq.withheld_advice(
        "the jar, written today", version="2026.7.4",
        upgrade="uv tool install yt-dlp --with yt-dlp-ejs --force",
        mine="git -C ~/ytq pull",
    )
    assert "2026.7.4" in said[1]
    assert said[2] == "uv tool install yt-dlp --with yt-dlp-ejs --force"
    assert any("the jar, written today" in line for line in said)


def test_the_upgrade_line_is_read_off_the_machine(tmp_path, monkeypatch):
    """A uv tool and a pip install take different commands and neither works
    on the other, and a reinstall that drops a --with package is silent."""
    venv = tmp_path / "tools" / "yt-dlp"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.write_text("")
    (venv / ytq.UV_RECEIPT).write_text(
        'requirements = [{ name = "yt-dlp" }, { name = "yt-dlp-ejs" }]\n'
        'entrypoints = [{ name = "yt-dlp" }]\n'
    )
    binary = tmp_path / "yt-dlp"
    binary.write_text(f"#!{python}\n")
    monkeypatch.setattr(ytq.shutil, "which", lambda name: str(binary))
    said = ytq.upgrade_command("yt-dlp")
    assert said.startswith("uv tool install yt-dlp")
    # The --with packages a reinstall would otherwise drop, and never the
    # tool's own name a second time.
    assert "--with yt-dlp-ejs" in said
    assert "--with yt-dlp " not in said
    assert "--force" in said


def test_a_pip_install_gets_a_pip_line(tmp_path, monkeypatch):
    binary = tmp_path / "yt-dlp"
    binary.write_text("#!/usr/bin/python3\n")
    monkeypatch.setattr(ytq.shutil, "which", lambda name: str(binary))
    assert "pip install -U yt-dlp" in ytq.upgrade_command("yt-dlp")


def test_a_missing_yt_dlp_says_so_rather_than_offering_a_command(monkeypatch):
    monkeypatch.setattr(ytq.shutil, "which", lambda name: None)
    assert "PATH" in ytq.upgrade_command("yt-dlp")


def test_the_interpreter_is_shortened_only_when_it_means_the_same_file(
    monkeypatch,
):
    """A venv's python3 is a symlink to the system one, and `python3 -m pip`
    under the system python installs somewhere else entirely."""
    monkeypatch.setattr(ytq.shutil, "which", lambda name: "/usr/bin/python3")
    assert ytq.short_python("/usr/bin/python3") == "python3"
    assert ytq.short_python("/home/me/venv/bin/python3") == "/home/me/venv/bin/python3"
    assert ytq.short_python("") == "python3"


# --------------------------------------------------------------------------- #
# What a size means on this connection
# --------------------------------------------------------------------------- #


@given(size=st.integers(min_value=0, max_value=20 * 1024**3))
def test_the_colour_and_the_words_agree_about_a_long_download(size):
    """A terminal without colours must not be the one that loses the warning."""
    band, note = ytq.cost_band(size), ytq.nights_note(size)
    assert bool(note) == (ytq.nights(size) > 1)
    if note:
        assert band == "nights"


def test_the_bands_are_where_a_night_actually_is():
    assert ytq.cost_band(ytq.NIGHT_BYTES // 3) == "fits"
    assert ytq.cost_band(ytq.NIGHT_BYTES // 3 + 1) == "night"
    assert ytq.cost_band(ytq.NIGHT_BYTES) == "night"
    assert ytq.cost_band(ytq.NIGHT_BYTES + 1) == "nights"
    assert ytq.nights(1) == 1


# --------------------------------------------------------------------------- #
# Where the cursor opens, and where the file goes
# --------------------------------------------------------------------------- #


def options_for(labels):
    return [
        ytq.Choice("audio" if label.startswith("audio") else "merge",
                   f"f{index}", 10 * MiB, True, "mp4", label, "")
        for index, label in enumerate(labels)
    ]


def test_no_memory_opens_at_the_top():
    assert ytq.preferred_index(options_for(["1080p mp4", "720p mp4"]), None) == 0
    assert ytq.preferred_index(options_for(["1080p mp4"]), {}) == 0


def test_the_exact_row_wins_when_it_is_there():
    options = options_for(["2160p mp4", "1080p mp4", "720p mp4"])
    picked = ytq.preferred_index(options, {"label": "1080p mp4", "kind": "merge"})
    assert options[picked].label == "1080p mp4"


def test_the_resolution_is_what_is_actually_remembered():
    """The exact format a video offers varies with the video; the useful
    memory is "1080p, merged" and not the string."""
    options = options_for(["2160p webm", "1080p webm", "audio 129k m4a"])
    picked = ytq.preferred_index(options, {"label": "1080p mp4", "kind": "merge"})
    assert options[picked].label == "1080p webm"


def test_a_memory_that_matches_nothing_changes_nothing():
    options = options_for(["2160p mp4", "1080p mp4"])
    assert ytq.preferred_index(options, {"label": "144p ogg", "kind": "single"}) == 0


def test_a_remembered_kind_is_the_last_thing_tried():
    options = options_for(["2160p mp4", "audio 129k m4a"])
    picked = ytq.preferred_index(options, {"label": "audio 320k opus", "kind": "audio"})
    assert options[picked].kind == "audio"


@given(
    labels=st.lists(st.sampled_from(
        ["2160p mp4", "1080p mp4", "720p webm", "audio 129k m4a"]
    ), min_size=1, max_size=6),
    remembered=st.one_of(
        st.none(),
        st.fixed_dictionaries({
            "label": st.sampled_from(["1080p mp4", "nonsense", ""]),
            "kind": st.sampled_from(["merge", "audio", "single", ""]),
        }),
    ),
)
def test_the_cursor_always_opens_on_a_row_that_exists(labels, remembered):
    options = options_for(labels)
    assert 0 <= ytq.preferred_index(options, remembered) < len(options)


def test_an_audio_pick_does_not_land_among_the_films():
    """The music player and the video player look in different places."""
    audio = ytq.Choice("audio", "140", 1, True, "m4a", "audio 129k m4a", "")
    video = ytq.Choice("merge", "137+140", 1, True, "mp4", "1080p mp4", "")
    assert ytq.dest_for(audio) == ytq.AUDIO_DEST
    assert ytq.dest_for(video) == ytq.VIDEO_DEST
    # --dest names a directory and wins over both.
    assert ytq.dest_for(audio, "/sdcard/Movies") == "/sdcard/Movies"


def test_the_destination_is_the_row_chosen_and_never_the_extension():
    """At queue time there is no file to have an extension."""
    audio_in_mp4 = ytq.Choice("audio", "140", 1, True, "mp4", "audio 129k mp4", "")
    assert ytq.dest_for(audio_in_mp4) == ytq.AUDIO_DEST


def test_the_selected_row_keeps_the_codec_profile_in_full():
    """Which av01 profile a stream is decides whether a player can play it."""
    info = video_info(formats=[
        fmt("137", vcodec="av01.0.08M.08", ext="mp4", height=1080,
            filesize=100 * MiB),
        fmt("140", acodec="mp4a.40.2", ext="m4a", abr=129, filesize=5 * MiB),
    ])
    merged = next(o for o in ytq.choices(info)[0] if o.kind == "merge")
    assert "av01.0.08M.08" in merged.codecs
    assert "mp4a.40.2" in merged.codecs
    # The columns carry only the family, because a column has a width budget.
    assert "av01.0.08M.08" not in merged.detail


def test_a_size_is_written_the_way_this_repo_writes_sizes():
    assert ytq.human(0) == "0 B"
    assert ytq.human(1536) == "2 KiB"
    assert ytq.human(3 * 1024**3).endswith("GiB")


@given(size=st.integers(min_value=0, max_value=10 * 1024**4))
def test_every_size_says_what_unit_it_is_in(size):
    assert ytq.human(size).split()[-1] in ("B", "KiB", "MiB", "GiB")


def test_a_size_changes_unit_where_the_unit_changes():
    assert ytq.human(1023) == "1,023 B"
    assert ytq.human(1024) == "1 KiB"
    assert ytq.human(1024**2 - 1) == "1,024 KiB"
    assert ytq.human(1024**3) == "1.00 GiB"


def test_an_estimated_size_is_carried_as_an_estimate():
    """The ``~`` on the row and the wider margin are the same fact, and both
    come off whether yt-dlp said filesize or filesize_approx."""
    info = video_info(formats=[
        fmt("137", vcodec="avc1", ext="mp4", height=1080, approx=400 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    merged = next(o for o in ytq.choices(info)[0] if o.kind == "merge")
    # One estimated half makes the pair an estimate.
    assert merged.exact is False
    assert "~" in ytq.format_row(merged, 40)


def test_a_high_frame_rate_is_part_of_the_label():
    """60fps and 30fps at the same height are not the same download."""
    info = video_info(formats=[
        fmt("299", vcodec="avc1", ext="mp4", height=1080, fps=60,
            filesize=700 * MiB),
        fmt("137", vcodec="avc1", ext="mp4", height=1080, fps=30,
            filesize=400 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    labels = [option.label for option in ytq.choices(info)[0]]
    assert "1080p60 mp4" in labels
    assert "1080p mp4" in labels


def test_a_format_with_no_height_still_has_something_to_say():
    info = video_info(formats=[
        fmt("hls", vcodec="avc1", acodec="mp4a", ext="mp4",
            filesize=10 * MiB),
    ])
    assert ytq.choices(info)[0][0].label.strip()


# --------------------------------------------------------------------------- #
# Which audio a merge takes, and what is not offered at all
# --------------------------------------------------------------------------- #


def test_a_format_yt_dlp_did_not_name_is_not_offered():
    """Without a format id there is nothing to ask yt-dlp for."""
    info = video_info(formats=[
        {"ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "filesize": 10 * MiB},
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=10 * MiB),
    ])
    assert [option.fmt for option in ytq.choices(info)[0]] == ["18"]


def test_a_merge_takes_the_best_audio_of_its_own_family():
    """One best audio per container family, so a merge does not have to
    transcode or fall back to Matroska when it does not need to."""
    info = video_info(formats=[
        fmt("137", vcodec="avc1", ext="mp4", height=1080, filesize=400 * MiB),
        fmt("139", acodec="mp4a", ext="m4a", abr=48, filesize=4 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    merged = next(o for o in ytq.choices(info)[0] if o.kind == "merge")
    assert merged.fmt == "137+140"
    assert merged.size == 410 * MiB


def test_a_video_with_no_audio_of_its_own_family_takes_the_best_there_is():
    info = video_info(formats=[
        fmt("248", vcodec="vp9", ext="webm", height=1080, filesize=300 * MiB),
        fmt("139", acodec="mp4a", ext="m4a", abr=48, filesize=4 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    merged = next(o for o in ytq.choices(info)[0] if o.kind == "merge")
    assert merged.fmt == "248+140"
    assert merged.merge_ext == "mkv"


def test_a_video_with_no_audio_at_all_is_not_offered_as_a_merge():
    """There is nothing to merge it with, and half a video is not a download."""
    info = video_info(formats=[
        fmt("137", vcodec="avc1", ext="mp4", height=1080, filesize=400 * MiB),
    ])
    options, _ = ytq.choices(info)
    assert options == []


def test_the_bot_check_verdict_is_a_yes_or_no_and_not_an_absence():
    """A screen that says nothing is a screen that said no."""
    storyboards_first = video_info(formats=[
        fmt("sb0", ext="mhtml"),
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=10 * MiB),
        fmt("22", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=20 * MiB),
    ])
    assert ytq.withheld(storyboards_first) is True
    with_adaptive = video_info(formats=[
        fmt("sb0", ext="mhtml"),
        fmt("18", vcodec="avc1", acodec="mp4a", ext="mp4", filesize=10 * MiB),
        fmt("137", vcodec="avc1", ext="mp4", height=1080, filesize=400 * MiB),
        fmt("140", acodec="mp4a", ext="m4a", abr=129, filesize=10 * MiB),
    ])
    assert ytq.withheld(with_adaptive) is False
    assert ytq.withheld(video_info(extractor="generic", formats=[
        fmt("0", vcodec="h264", acodec="aac", ext="mp4", filesize=1),
    ])) is False
