"""Render the design mockups: ``python3 design/mock/render.py``.

Writes, under ``design/mockups/``:

- ``<screen>.<rows>.txt``: the screen as plain text, one file per height;
- ``<screen>.<rows>.ans``: the same with its colours, as bewitch's ANSI adapter
  writes them (24-bit). ``cat`` one in Termux to see it on the phone itself;
- ``index.html``: the review page, every screen keyboard down and up beside its
  notes, plus the decisions. The published copy of this page is the one the
  owner commented on.

The mockups are drawn with bewitch's own recipes and the proposed ones in
``kit.py``, at the terminal's real size, so what they show is what a terminal
can draw. ``screens3.py`` is the authoritative set; ``screens.py`` (round one)
and ``screens2.py`` (round two) are kept because ``screens3.py`` reuses their
helpers and ``screens.py`` draws the pieces gallery.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "mockups"
sys.path.insert(0, str(HERE))

import screens  # noqa: E402
import screens3  # noqa: E402


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    for old in OUT.glob("*.ans"):
        old.unlink()
    pieces = [s for s in screens.build() if s["key"] == "kit"]
    final = screens3.build()
    final.append({"key": "q-chips", "shots_free": screens3.chips_question()})
    for s in final:
        for shot in s.get("shots", []):
            stem = f"{s['key']}.{s['width']}x{shot['rows']}"
            (OUT / f"{stem}.txt").write_text(shot["plain"] + "\n", encoding="utf-8")
            (OUT / f"{stem}.ans").write_text(shot["ansi"] + "\n", encoding="utf-8")
    (OUT / "kit.txt").write_text(pieces[0]["plain"] + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "a.json").write_text(json.dumps(pieces), encoding="utf-8")
        (tmp / "b.json").write_text("[]", encoding="utf-8")
        (tmp / "c.json").write_text(json.dumps(final), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(HERE / "build_page.py"), str(tmp / "a.json"),
             str(OUT / "index.html"), str(tmp / "b.json"), str(tmp / "c.json")],
            check=True, stdout=subprocess.DEVNULL,
        )
    print(f"wrote {len(list(OUT.glob('*.txt')))} text mockups and index.html to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
