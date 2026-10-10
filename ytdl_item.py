#!/data/data/com.termux/files/usr/bin/python3
"""``nibbles/ytdl_item.py``, by the path it had before nibbles was a package.

nibbles became a package on 2026-10-10. A video queued before then imports
``ytdl_item`` off the checkout root when it fires. So the old path is kept as a
door: imported, this file *is* ``nibbles.ytdl_item``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nibbles import ytdl_item as _module  # noqa: E402

sys.modules[__name__] = _module
