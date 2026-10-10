#!/data/data/com.termux/files/usr/bin/python3
"""``nibbles/expire_dl.py``, by the path it had before nibbles was a package.

nibbles became a package on 2026-10-10. A file download queued before then
imports ``expire_dl`` off the checkout root when it fires. So the old path is
kept as a door: imported, this file *is* ``nibbles.expire_dl``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nibbles import expire_dl as _module  # noqa: E402

sys.modules[__name__] = _module
