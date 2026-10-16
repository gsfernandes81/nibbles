"""The metering, which is the one thing in a queue item that can be silently
wrong every night for ever.

The bytes an item reports are what the runner spends its allowance against, so
a count that is too high stops a download that had budget left — and the merge
case does exactly that, for ever, because a merge writes a file the size of
both its inputs and every firing re-reaches the same point and stops again.
These pin the rules :class:`ytdl_item.Meter` is shaped by, and nothing about
how it is spelled. A count that is too *low* is the worse of the two: on a
phone the runner charges the item's own report, so bytes the meter missed are
bytes that move with no guard and no ledger behind them.
"""

from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st

from nibbles import ytdl_item, ytq


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
    """``x.mp4.part-Frag7`` is the same stream as ``x.mp4.part``, and so is the
    fragment while it is still being fetched, ``x.mp4.part-Frag7.part``."""
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.mp4.part", 400)
    fragment = wrote(tmp_path, "talk.mp4.part-Frag7.part", 900)
    # A fragment not yet appended is bytes the part does not hold yet.
    assert meter.taken() == 1300
    fragment = fragment.rename(tmp_path / "talk.mp4.part-Frag7")
    assert meter.taken() == 1300
    with (tmp_path / "talk.mp4.part").open("ab") as part:
        part.write(fragment.read_bytes())
    fragment.unlink()
    # Appended and gone: the same 1300 bytes, under one name now.
    assert meter.taken() == 1300


def test_a_fragment_a_stop_left_behind_is_counted(tmp_path):
    """Stopped mid-fragment, the partial fragment was fetched this slice; the
    runner charges this figure on a phone, so missing it is the wrong way."""
    wrote(tmp_path, "talk.mp4.part", 2000)
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.mp4.part-Frag3.part", 700)
    assert meter.taken() == 700


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


@given(title=st.text(max_size=80), size=st.integers(min_value=1, max_value=4096))
@example(title="Clearing the .temp. cache: a 4K tour", size=5000)
@example(title="Notes.temp", size=10)
@example(title="x.temp.mp4", size=10)
@example(title="x.ytdl", size=10)
def test_no_title_hides_its_own_bytes(tmp_path_factory, title, size):
    """A partial named after its title is payload whatever the title says.

    Items queued before the stem still hold ``<title>.f137.mp4.part``. A title
    with ``.temp.`` in it once read as a merge in progress: nought taken, so
    the slice was never stopped and nothing was charged. A merge beside it, or
    the fragment index, still adds nothing.
    """
    name = ytq.title_name(title)
    root = tmp_path_factory.mktemp("titled")
    meter = ytdl_item.Meter(root)
    wrote(root, f"{name}.f137.mp4.part", size)
    assert meter.taken() == size
    assert ytdl_item.fetched_bytes(root) == size
    wrote(root, f"{name}.temp.mp4", 3 * size)
    wrote(root, f"{name}.f137.mp4.ytdl", 7)
    assert meter.taken() == size
    assert ytdl_item.fetched_bytes(root) == size


def test_bytes_already_on_disk_are_not_this_slice(tmp_path):
    """A resumed download starts the slice at zero, not at what it resumed."""
    wrote(tmp_path, "talk.f137.mp4.part", 700)
    meter = ytdl_item.Meter(tmp_path)
    assert meter.taken() == 0
    wrote(tmp_path, "talk.f137.mp4.part", 900)
    assert meter.taken() == 200


def test_a_partial_started_over_counts_from_nought(tmp_path):
    """"Unable to resume": yt-dlp opens the ``.part`` ``wb`` and fetches from
    byte 0. Every byte it holds afterwards is new, though it is smaller than
    what was there — the high-water mark alone read nothing until it passed
    the old size, and the slice stop let a whole slice through on top."""
    wrote(tmp_path, "talk.f137.mp4.part", 6000)
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.f137.mp4.part", 5000)
    assert meter.taken() == 5000
    with (tmp_path / "talk.f137.mp4.part").open("ab") as part:
        part.write(b"x" * 2000)
    assert meter.taken() == 7000


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
            st.sampled_from(["grow", "restart", "fragment", "rename", "delete"]),
            st.integers(min_value=0, max_value=2),
            st.integers(min_value=1, max_value=4096),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_the_meter_never_hands_bytes_back(tmp_path_factory, steps):
    """However the files move about, what has been spent cannot go down.

    A file disappearing — renamed away, eaten by a merge, a fragment appended
    and deleted — or a partial started over must never read as bytes being
    returned, because the runner subtracts this from a budget and a figure
    that fell would buy the same bytes twice.
    """
    root = tmp_path_factory.mktemp("meter")
    meter = ytdl_item.Meter(root)
    seen = 0
    for number, (what, which, size) in enumerate(steps):
        part = root / f"stream{which}.mp4.part"
        done = root / f"stream{which}.mp4"
        if what == "grow":
            wrote(root, part.name, size)
        elif what == "restart" and part.is_file():
            part.write_bytes(b"x" * (part.stat().st_size // 2))
        elif what == "fragment":
            fragment = wrote(root, f"{part.name}-Frag{number}.part", size)
            fragment = fragment.rename(root / f"{part.name}-Frag{number}")
            with part.open("ab") as stream:
                stream.write(fragment.read_bytes())
            fragment.unlink()
        elif what == "rename" and part.is_file():
            part.replace(done)
        elif what == "delete":
            part.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
        now = meter.taken()
        assert now >= seen
        seen = now


#: Two streams of one download, as a merge fetches them.
STREAMS = ("talk.f137.mp4", "talk.f140.m4a")


def fed(path, pieces) -> int:
    """yt-dlp writing *pieces* into a partial; what that fetched.

    A piece of ``n >= 0`` is ``n`` bytes appended — a resume. A negative one
    is the partial opened ``wb`` and ``-n - 1`` bytes written from byte 0 —
    "Unable to resume" — taken only where that is smaller than what was there,
    since a restart that has already passed the old size between two looks is
    growth to anyone watching.
    """
    if pieces >= 0:
        with path.open("ab") as partial:
            partial.write(b"x" * pieces)
        return pieces
    again = -pieces - 1
    if not path.is_file() or again >= path.stat().st_size:
        return 0
    path.write_bytes(b"x" * again)
    return again


@given(
    start=st.tuples(st.integers(0, 4096), st.integers(0, 4096)),
    steps=st.lists(
        st.tuples(
            st.sampled_from(["fetch", "fragment", "leave", "finish"]),
            st.integers(min_value=0, max_value=1),
            st.lists(st.integers(-2049, 2048), min_size=1, max_size=4),
            st.booleans(),
        ),
        max_size=20,
    ),
)
def test_the_meter_counts_what_was_fetched(tmp_path_factory, start, steps):
    """Neither less than was fetched this slice, nor more but for a fragment.

    yt-dlp's own ways with a download, in any order: a partial resumed, a
    partial started over from byte 0, a fragment fetched (and perhaps started
    over), renamed, appended to its stream and deleted, a fragment a stop left
    behind, and a finished stream renamed out of its ``.part``. The one moment
    the files say more than was fetched is a fragment appended and not yet
    deleted (*peek* looks then), and by one fragment a stream at most.
    """
    root = tmp_path_factory.mktemp("fetched")
    for stream, size in zip(STREAMS, start, strict=True):
        if size:
            wrote(root, f"{stream}.part", size)
    meter = ytdl_item.Meter(root)
    fetched = seen = 0
    over: dict[str, int] = {}
    finished: set[str] = set()

    def look() -> None:
        nonlocal seen
        now = meter.taken()
        assert fetched <= now <= fetched + sum(over.values())
        assert now >= seen
        seen = now

    for number, (what, which, pieces, peek) in enumerate(steps):
        stream = STREAMS[which]
        if stream in finished:
            continue
        part = root / f"{stream}.part"
        if what == "finish":
            if part.is_file():
                part.rename(root / stream)
                finished.add(stream)
                look()
            continue
        target = part if what == "fetch" else root / f"{part.name}-Frag{number}.part"
        for piece in pieces:
            fetched += fed(target, piece)
            look()
        if what != "fragment" or not target.is_file():
            continue
        fragment = target.rename(root / f"{part.name}-Frag{number}")
        look()
        with part.open("ab") as partial:
            partial.write(fragment.read_bytes())
        if peek:
            over[stream] = max(over.get(stream, 0), fragment.stat().st_size)
            look()
        fragment.unlink()
        look()


def test_freezing_holds_the_last_figure_and_not_a_fresh_one(tmp_path):
    """Freezing re-reading the directory would be the double count itself."""
    meter = ytdl_item.Meter(tmp_path)
    wrote(tmp_path, "talk.f137.mp4.part", 100)
    assert meter.taken() == 100
    wrote(tmp_path, "talk.mp4", 999_999)  # the merge, already on disk
    meter.freeze()
    assert meter.taken() == 100
