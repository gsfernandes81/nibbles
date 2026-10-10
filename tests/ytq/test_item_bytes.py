"""The metering, which is the one thing in a queue item that can be silently
wrong every night for ever.

The bytes an item reports are what the runner spends its allowance against, so
a count that is too high stops a download that had budget left — and the merge
case does exactly that, for ever, because a merge writes a file the size of
both its inputs and every firing re-reaches the same point and stops again.
These pin the three rules :class:`ytdl_item.Meter` is shaped by, and nothing
about how it is spelled.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

import ytdl_item


def wrote(folder, name: str, size: int):
    """A file of *size* bytes, directories made as needed."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_a_finished_stream_is_not_counted_a_second_time(tmp_path):
    """yt-dlp renames ``x.mp4.part`` to ``x.mp4``; that is not new bytes."""
    meter = ytdl_item.Meter(tmp_path)
    part = wrote(tmp_path, "talk.f137.mp4.part", 1000)
    assert meter.taken() == 1000
    part.rename(tmp_path / "talk.f137.mp4")
    assert meter.taken() == 1000


def test_fragments_and_their_part_belong_to_one_stream(tmp_path):
    """``x.mp4.part-Frag7`` is the same stream as ``x.mp4.part``."""
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.mp4.part", 400)
    wrote(tmp_path, "talk.mp4.part-Frag7", 900)
    # One stream at its high-water mark, not the sum of two names for it.
    assert meter.taken() == 900


def test_two_streams_of_a_merge_are_counted_once_each(tmp_path):
    """The video and the audio are both payload; their merge is not."""
    meter = ytdl_item.Meter(tmp_path)
    video = wrote(tmp_path, "talk.f137.mp4.part", 1000)
    audio = wrote(tmp_path, "talk.f140.m4a.part", 200)
    video.rename(tmp_path / "talk.f137.mp4")
    audio.rename(tmp_path / "talk.f140.m4a")
    downloaded = meter.taken()
    assert downloaded == 1200

    # ffmpeg announces itself, the item freezes the meter, and the merged file
    # — as big as both inputs together — lands. Without the freeze this reads
    # as the whole video being downloaded a second time, which is what stops
    # the item mid-merge every night for ever.
    meter.freeze()
    wrote(tmp_path, "talk.mp4", 1200)
    assert meter.taken() == downloaded


def test_a_merge_in_progress_is_never_payload(tmp_path):
    """ffmpeg's own target is a ``.temp.`` name, and the index is not payload."""
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.f137.mp4.part", 500)
    wrote(tmp_path, "talk.temp.mp4", 5000)
    wrote(tmp_path, "talk.f137.mp4.ytdl", 300)
    assert meter.taken() == 500
    assert ytdl_item.fetched_bytes(tmp_path) == 500


def test_bytes_already_on_disk_are_not_this_slice(tmp_path):
    """A resumed download starts the slice at zero, not at what it resumed."""
    wrote(tmp_path, "talk.f137.mp4.part", 700)
    meter = ytdl_item.Meter(tmp_path)
    assert meter.taken() == 0
    wrote(tmp_path, "talk.f137.mp4.part", 900)
    assert meter.taken() == 200


def test_fetched_bytes_is_everything_downloaded_so_far(tmp_path):
    """What the *next* firing resumes from: finished streams and partial ones."""
    wrote(tmp_path, "talk.f137.mp4", 1000)
    wrote(tmp_path, "talk.f140.m4a.part", 200)
    wrote(tmp_path, "nested/talk.f251.webm.part", 50)
    assert ytdl_item.fetched_bytes(tmp_path) == 1250


def test_fetched_bytes_survives_a_directory_that_is_not_there(tmp_path):
    assert ytdl_item.fetched_bytes(tmp_path / "never-made") == 0


@given(
    steps=st.lists(
        st.tuples(
            st.sampled_from(["grow", "rename", "delete"]),
            st.integers(min_value=0, max_value=2),
            st.integers(min_value=1, max_value=4096),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_the_meter_never_hands_bytes_back(tmp_path_factory, steps):
    """However the files move about, what has been spent cannot go down.

    A file disappearing — renamed away, or eaten by a merge — must never read
    as bytes being returned, because the runner subtracts this from a budget
    and a figure that fell would buy the same bytes twice.
    """
    root = tmp_path_factory.mktemp("meter")
    meter = ytdl_item.Meter(root)
    seen = 0
    for what, which, size in steps:
        part = root / f"stream{which}.mp4.part"
        done = root / f"stream{which}.mp4"
        if what == "grow":
            wrote(root, part.name, size)
        elif what == "rename" and part.is_file():
            part.replace(done)
        elif what == "delete":
            part.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
        now = meter.taken()
        assert now >= seen
        seen = now


def test_freezing_holds_the_last_figure_and_not_a_fresh_one(tmp_path):
    """Freezing re-reading the directory would be the double count itself."""
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.f137.mp4.part", 100)
    assert meter.taken() == 100
    wrote(tmp_path, "talk.mp4", 999_999)  # the merge, already on disk
    meter.freeze()
    assert meter.taken() == 100
