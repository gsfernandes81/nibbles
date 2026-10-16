#!/data/data/com.termux/files/usr/bin/python3
"""Queue any direct file URL for the expiring-quota runner.

ytq covers pages yt-dlp understands; this covers everything else. It sizes the
file from its response headers (headers only, no payload — costs nothing
meaningful), writes a queue item that downloads through :mod:`expire_dl`'s
bounded-Range machinery, and the nightly runner does the rest.

The queue contract says "unknown" is not a valid ``EXPECT_BYTES``, so when the
server will not state a size you must pass ``--expect-bytes`` yourself: it is
the cap enforced against the item, i.e. the most you are willing to let it
cost.

Usage::

    nibbles <url>                    # probe the size, queue it
    nibbles <url> --name x.iso       # choose the saved file name
    nibbles <url> --probe            # print size and resume support only
    nibbles <url> --expect-bytes N   # server states no size: set the cap
"""

from __future__ import annotations

import argparse
import email.utils
import http.client
import json
import math
import mimetypes
import re
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

from nibbles import expire_dl
from nibbles import ytq

BASE_HEADERS = {
    # Sizes are meaningless if the server gzips, and expire_dl will ask for
    # identity too — probe what will actually be fetched.
    "Accept-Encoding": "identity",
    "User-Agent": "dlq/1",
}

TIMEOUT = 30


class ProbeError(RuntimeError):
    """The URL could not be sized."""


class Look(NamedTuple):
    """One answer's status and headers, and where it came from after any
    redirect."""

    code: int
    headers: object
    url: str


def _look(url: str, timeout: int, ranged: bool) -> Look | None:
    """One look at *url*'s headers: HEAD, or (*ranged*) a GET for
    ``bytes=0-0`` closed unread, which costs at most one byte of payload.

    The one place the two questions ``nibbles <url>`` asks — :func:`kind_of`
    and :func:`probe` — decide what an answer that is not an answer means, so
    the two cannot drift apart on it: a refused HEAD is ``None`` (plenty of
    servers refuse it, and the ranged GET settles it), a refused GET is a
    :class:`ProbeError` naming the status, and a server that cannot be reached
    — or does not talk HTTP, or is not a URL at all — is a :class:`ProbeError`
    too. An unreachable server is an error, never a guess.
    """
    try:
        if ranged:
            request = urllib.request.Request(
                url, headers={**BASE_HEADERS, "Range": "bytes=0-0"}
            )
        else:
            request = urllib.request.Request(url, method="HEAD", headers=BASE_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Look(response.getcode(), response.headers, response.geturl())
    except urllib.error.HTTPError as exc:
        if not ranged:
            return None
        raise ProbeError(f"HTTP {exc.code} {exc.reason}") from exc
    except (
        urllib.error.URLError,
        OSError,
        TimeoutError,
        http.client.HTTPException,
        ValueError,
    ) as exc:
        raise ProbeError(f"cannot reach {url}: {exc}") from exc


def _from_head(headers) -> tuple[int, bool | None]:
    """``(bytes, resumable)`` from a HEAD response. ``None`` = server not saying."""
    length = headers.get("Content-Length", "")
    size = int(length) if str(length).isdigit() else 0
    ranges = (headers.get("Accept-Ranges") or "").strip().lower()
    resumable = True if ranges == "bytes" else (False if ranges == "none" else None)
    return size, resumable


def _from_ranged(code: int, headers) -> tuple[int, bool | None]:
    """``(bytes, resumable)`` from a ``Range: bytes=0-0`` response.

    A 206 proves the server honours Range and names the total after the slash;
    a 200 proves it does not, and its Content-Length is the whole file.
    """
    if code == 206:
        content_range = headers.get("Content-Range", "")
        total = content_range.rsplit("/", 1)[-1].strip()
        return (int(total) if total.isdigit() else 0), True
    if code == 200:
        length = headers.get("Content-Length", "")
        return (int(length) if str(length).isdigit() else 0), False
    return 0, None


class Probe(NamedTuple):
    """What a header look found out about a file before any of it is fetched.

    The first two are the size and the resume verdict; the rest is what the
    same answer said about the file, which is what names it.
    """

    size: int
    resumable: bool | None
    #: The name the server gives it (Content-Disposition), or "".
    name: str = ""
    #: The media type it says it is, or "".
    kind: str = ""
    #: Where the answer came from after any redirect, or "".
    url: str = ""
    #: Whether the answer was a web page rather than a file.
    page: bool = False


def _disposition_name(headers) -> str:
    """The file name a Content-Disposition gives, ``filename*`` first.

    The starred form (RFC 5987, ``UTF-8''…``) is the one that can spell a
    name that is not ASCII, and a server sending both means it. Any directory
    in it is dropped, as a browser drops it.
    """
    try:
        params = headers.get_params(header="content-disposition") or []
    except AttributeError:  # a plain mapping, not a message
        return ""
    plain = ""
    for key, value in params[1:]:
        if key.lower() != "filename":
            continue
        if isinstance(value, tuple):
            plain = email.utils.collapse_rfc2231_value(value)
            break
        plain = plain or value
    return re.split(r"[/\\]", plain)[-1]


def _media_type(headers) -> str:
    return (headers.get("Content-Type") or "").split(";")[0].strip().lower()


def _described(look: Look | None) -> tuple[str, str, str, bool]:
    """``(name, kind, url, page)``: what *look* said about the file."""
    if look is None:
        return "", "", "", False
    headers = look.headers
    return (
        _disposition_name(headers),
        _media_type(headers),
        look.url or "",
        expire_dl.is_page(headers),
    )


def probe(url: str, timeout: int = TIMEOUT) -> Probe:
    """Size the file and test resume support without downloading it.

    HEAD first; if that answers with both a length and an Accept-Ranges verdict
    we are done. Otherwise a GET for ``bytes=0-0``, closed unread, settles both
    at the cost of headers plus at most one payload byte.
    """
    size, resumable = 0, None
    seen = _look(url, timeout, ranged=False)
    if seen is not None:
        size, resumable = _from_head(seen.headers)

    if not (size and resumable is not None):
        try:
            ranged = _look(url, timeout, ranged=True)
        except ProbeError:
            # Half an answer is still an answer: what HEAD said stands.
            if not size:
                raise
        else:
            ranged_size, ranged_resumable = _from_ranged(ranged.code, ranged.headers)
            size = ranged_size or size
            if ranged_resumable is not None:
                resumable = ranged_resumable
            seen = ranged
    return Probe(size, resumable, *_described(seen))


#: What a page is, as opposed to a file: these go to yt-dlp, which reads
#: the page for the video in it; anything else is fetched as it is, by Range.
#: The download itself refuses the same answers (``expire_dl.is_page``).
PAGE_TYPES = expire_dl.PAGE_TYPES

#: Hosts that are only ever pages, so asking them costs nothing at all.
PAGE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


def kind_of(url: str, timeout: int = TIMEOUT) -> str:
    """``"page"`` for a page yt-dlp reads, ``"file"`` for a file to fetch.

    ``nibbles <url>`` is one door for both (2026-10-10), so this is the
    question it asks: YouTube's hosts are pages without asking, and anything
    else is asked by its headers — HEAD, or where that is refused a GET for
    ``bytes=0-0`` closed unread, the same two looks :func:`probe` takes — and
    is a page only when :func:`expire_dl.is_page` says so, the test the
    download itself puts every answer to. A file that names no type is still
    a file: what is not a page has nothing in it for yt-dlp to find.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(host == known or host.endswith(f".{known}") for known in PAGE_HOSTS):
        return "page"
    look = _look(url, timeout, ranged=False) or _look(url, timeout, ranged=True)
    return "page" if expire_dl.is_page(look.headers) else "file"


#: What :func:`normal_url` leaves as it is: the characters a URL is built
#: of, and ``%``, so an escape already there stays one.
_URL_SAFE = "/:?#[]@!$&'()*+,;=%~"


def normal_url(url: str) -> str:
    """A link as ``nibbles <url>`` hands it on, so the headers asked, the
    item written and the duplicate check all see one spelling of it.

    Its scheme added (``https://``) when it was typed without one, the way
    yt-dlp adds it; and whatever is not ASCII in its path, query and fragment
    percent-encoded, which is what a server is sent — http.client will not
    send it as typed, and a Cyrillic file name was a traceback. Idempotent:
    an escape already there is kept. The host is left as it is, because
    the resolver and http.client IDNA-encode a host themselves.
    """
    text = url.strip()
    if "://" not in text:
        text = f"https://{text}"
    parts = urllib.parse.urlsplit(text)
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        *(urllib.parse.quote(part, safe=_URL_SAFE)
          for part in (parts.path, parts.query, parts.fragment)),
    ))


#: A suffix kept as one: what Android reads a file's type from, and nothing
#: else. Longer, or anything but letters and digits, is part of the name.
SUFFIX = re.compile(r"[A-Za-z0-9]{1,10}")

#: Media types that say nothing about what a file is, so no suffix is made
#: from them.
UNTYPED = (
    "application/octet-stream",
    "binary/octet-stream",
    "application/download",
    "application/force-download",
    "application/x-download",
)


def _named(text: str) -> bool:
    """Whether anything of *text* is left once it is cleaned for a name."""
    kept = "".join(ch for ch in ytq.REFUSED.sub(" ", text) if ch.isprintable())
    return bool(kept.strip(" -."))


def _suffix(name: str) -> str:
    stem, dot, suffix = name.rpartition(".")
    return suffix if dot and SUFFIX.fullmatch(suffix) and _named(stem) else ""


def file_name(raw: str, kind: str = "") -> str:
    """The name a download is saved under: *raw*, cleaned as a video's title
    is (:func:`ytq.title_name`: only what Android's shared storage refuses,
    capped well under 255 bytes) with its suffix kept whole — or, where it
    has none, one made from the media type *kind*, because Android's opener
    reads a file's type from its suffix and nothing else.

    One rule for every name a file download gets, ``--name`` included: a name
    with a ``/`` in it failed every firing after the request was paid for, one
    with a ``:`` or ``?`` downloaded and then could not be handed to shared
    storage, and one long enough that ``.part.meta.json`` passed 255 bytes was
    downloaded, delivered, struck and downloaded again. A name with nothing
    left in it is ``download``.
    """
    raw = (raw or "").strip()
    suffix = _suffix(raw)
    stem = raw[: -len(suffix) - 1] if suffix else raw
    if not suffix and kind and kind not in UNTYPED:
        suffix = (mimetypes.guess_extension(kind) or "").lstrip(".")
    stem = ytq.title_name(stem) if _named(stem) else "download"
    return f"{stem}.{suffix}" if suffix else stem


def _segment(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    return path.rstrip("/").rpartition("/")[2]


def name_from_url(url: str, final: str = "", kind: str = "") -> str:
    """A safe file name from the URL's last path segment (:func:`file_name`).

    The link's own segment, unless it names no type of file and *final* —
    where the link redirected to — does: ``/latest/download`` and
    ``get.php?id=`` say nothing, the release they land on does.
    """
    asked, landed = _segment(url), _segment(final) if final else ""
    if landed and ((_suffix(landed) and not _suffix(asked)) or not _named(asked)):
        asked = landed
    return file_name(asked, kind)


def expect_bytes(size: int) -> int:
    """The cap to declare: the measurement plus the same margin ytq uses."""
    return int(math.ceil(size * ytq.OVERHEAD_EXACT)) + ytq.OVERHEAD_FIXED


def _line(text: str) -> str:
    """*text* on one line: what a header comment can hold. Anything that is
    not printable (a line break above all) would end the comment early."""
    return "".join(ch if ch.isprintable() else " " for ch in str(text))


def _doc(text: str) -> str:
    """*text* as the item's docstring may hold it: on one line, with no
    backslash to start an escape (``\\N``, ``\\U`` and ``\\x`` are errors in a
    plain string) and no ``\"\"\"`` to end it. The docstring is for a person
    reading the item; what is fetched and saved is the json.dumps'd copy."""
    return _line(text).replace("\\", "/").replace('"""', "'''")


def _literal(text: str) -> str:
    """*text* as a Python string literal that reads back as exactly *text*.

    json.dumps, but never ``ensure_ascii``: that spells a character outside
    the Basic Multilingual Plane — an emoji, most of all — as a UTF-16
    surrogate pair, which JSON reads back as the character and *Python* reads
    back as two lone surrogates, a name no file can be opened under. Written
    as itself, it is read as itself: the item is UTF-8, as Python reads it.
    """
    return json.dumps(text, ensure_ascii=False)


def render(
    url: str,
    name: str,
    cap: int,
    size: int,
    sha256: str | None,
    probed: str,
    dest: str = "file",
    partial: bool = True,
) -> str:
    """The queue item source. The strings it runs with go through
    :func:`_literal` and the copies a person reads through :func:`_doc` and
    :func:`_line`, so no URL or name can produce a file that does not parse.

    *partial* is whether the server resumes: ``PARTIAL: no`` when the probe
    saw it ignore Range, so the runner gives it a firing that can take the
    whole of it rather than a slice it would have to throw away.
    """
    if size:
        note = (
            f"Sized {size:,} bytes by a header probe on {probed}; "
            f"EXPECT_BYTES adds a 3% + {ytq.human(ytq.OVERHEAD_FIXED)} "
            f"margin for wire overhead and retries."
        )
        shown = ytq.human(size)
    else:
        note = (
            "The server would not state a size, so EXPECT_BYTES is a "
            "declared spending cap rather than a measurement."
        )
        shown = "size unstated"
    if not partial:
        note += (
            " The server ignores Range, so it is fetched in one piece, in a "
            "firing that can take all of it."
        )
    return f'''{ytq.SHEBANG}
# EXPIRE: v1
# EXPECT_BYTES: {cap}
# PARTIAL: {"yes" if partial else "no"}
# DEST: {_line(dest)}
# SOURCE: url:{_line(url)}
# DESC: {_line(f"{name} ({shown}, direct download)")[:160]}
"""{_doc(name)}

{_doc(url)}

{textwrap.fill(note, 78)}
"""

import sys

sys.path.insert(0, {json.dumps(str(ytq.MODULE_DIR))})
from nibbles import expire_dl  # noqa: E402

sys.exit(expire_dl.run(
    {_literal(url)},
    {_literal(name)},
    expect_sha256={ytq.literal(sha256)},
    total_hint={size},
))
'''


def _priority(text: str) -> int:
    """``--number``: a place in the queue, 0 to :data:`ytq.MAX_PRIORITY`.

    The runner sorts item *names*, so ``100`` would run before ``20``, and a
    negative number writes an item nothing lists or runs — reported as
    queued. Refused rather than clamped: 99 for 100 shares a key with
    whatever is already there.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0 <= value <= ytq.MAX_PRIORITY:
        raise argparse.ArgumentTypeError(
            f"{value} is not 0 to {ytq.MAX_PRIORITY}: the queue runs in name "
            f"order, so {value} would not run where it looks like it should"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nibbles",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              nibbles https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso
              nibbles https://x.example/build --name build.tar.gz --sha256 <hex>
              nibbles https://x.example/feed --expect-bytes 50000000

            a video page at the same command goes to its video sheet; the
            queue itself is nibbles queue, or nibbles status.
            docs: ~/nibbles/docs/download-queue.md"""),
    )
    parser.add_argument("url", nargs="?", help="the file to download")
    parser.add_argument(
        "--name", help="saved file name (default: what the server or the URL calls it)"
    )
    parser.add_argument(
        "--number",
        type=_priority,
        metavar="NN",
        help=f"queue priority prefix, 0 to {ytq.MAX_PRIORITY} (default: after the last)",
    )
    parser.add_argument(
        "--sha256", metavar="HEX", help="verify the finished file before delivery"
    )
    parser.add_argument(
        "--dest",
        metavar="DIR",
        help="put this one somewhere other than the configured file directory "
        "(nibbles dest sets that)",
    )
    parser.add_argument(
        "--expect-bytes",
        type=int,
        metavar="N",
        help="spending cap when the server states no size",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="print the size and resume support, write nothing",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the item instead of writing it"
    )
    parser.add_argument(
        "--again",
        action="store_true",
        help="queue it even though this URL is already in the queue or done",
    )
    args = parser.parse_args(argv)

    if not args.url:
        parser.error("a URL is required")
    sha256 = None
    if args.sha256:
        # Cleaned here, before anything is asked or written: an upper-case or
        # prefixed digest is the same digest, and one that is not a SHA-256
        # at all would fail a correct file once per strike.
        try:
            sha256 = expire_dl.sha256_digest(args.sha256)
        except ValueError as exc:
            parser.error(str(exc))

    try:
        found = probe(args.url)
    except ProbeError as exc:
        if args.expect_bytes and not args.probe:
            print(f"probe failed ({exc}); trusting --expect-bytes", file=sys.stderr)
            found = Probe(0, None)
        else:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    size, resumable = found.size, found.resumable

    # Named after the probe, from what it was told: the name asked for, else
    # the one the server gives the file, else the link's (or where it led).
    if args.name:
        name = file_name(args.name)
    elif found.name:
        name = file_name(found.name, found.kind)
    else:
        name = name_from_url(args.url, found.url, found.kind)

    resume_note = {
        True: "server supports resume (Range honoured)",
        False: "server IGNORES Range - cannot resume across slices",
        None: "resume support unknown",
    }[resumable]
    if args.probe:
        print(
            f"{name}: "
            f"{f'{ytq.human(size)} ({size:,} bytes)' if size else 'size not stated'}"
            f"  ·  {resume_note}"
        )
        if found.page:
            print("it answers with a web page, not a file")
        if size:
            print(
                f"would declare EXPECT_BYTES {expect_bytes(size):,} "
                f"({ytq.human(expect_bytes(size))})"
            )
        return 0

    if found.page:
        # What the download would be handed is a page — a sign-in or error
        # page, or a page and not a file at all — and it refuses pages, so an
        # item queued now could only fail. Said now instead.
        print(
            f"error: {args.url} answers with a web page, not a file; nothing "
            "queued (nibbles <url> alone opens a page)",
            file=sys.stderr,
        )
        return 1

    if args.expect_bytes:
        cap = args.expect_bytes
        if size and cap < size:
            print(
                f"error: --expect-bytes {cap:,} is below the measured {size:,} bytes",
                file=sys.stderr,
            )
            return 1
    elif size:
        cap = expect_bytes(size)
    else:
        print(
            "error: the server would not state a size; pass --expect-bytes "
            "with the most you are willing to let it cost",
            file=sys.stderr,
        )
        return 1

    number = args.number if args.number is not None else ytq.next_number()
    slug = ytq.slugify(Path(name).stem)
    source = render(
        args.url,
        name,
        cap,
        size,
        sha256,
        time.strftime("%Y-%m-%d", time.gmtime()),
        dest=str(Path(args.dest).expanduser()) if args.dest else "file",
        # Unknown is not "no": the first firing finds out, and expire_dl
        # stops a server that turns out not to resume before it spends.
        partial=resumable is not False,
    )
    if args.dry_run:
        print(source, end="")
        return 0

    try:
        path = ytq.write_item(number, slug, source, again=args.again)
    except ytq.Duplicate as clash:
        # The same door ytq queues through, so the same answer: say what it
        # already is and how to mean it anyway. Re-buying a file that is
        # already on the disk is the whole thing this queue exists to avoid.
        print(f"error: {clash.says()} — {clash.stem}", file=sys.stderr)
        if clash.how == "name":
            print(
                "       matched by name, not by URL; it may be another file",
                file=sys.stderr,
            )
        print("       nibbles URL --again queues it a second time", file=sys.stderr)
        return 1
    problem = ytq.validate(path)
    if problem:
        print(f"warning: the runner would reject this item: {problem}")
        print(f"written anyway at {path}")
        return 1
    print(
        f"queued {path.name} — {ytq.human(size) if size else 'size unstated'}, "
        f"cap {ytq.human(cap)}"
    )
    where = ytq.landing(args.dest or "file")
    print(f"lands in {where} as {name} once the nightly window has worked through it")
    if resumable is False and size > ytq.SLICE_MIN_BYTES:
        print(
            "warning: this server ignores Range requests, so it waits for a "
            "firing whose budget can take the whole file at once"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
