#!/data/data/com.termux/files/usr/bin/python3
"""``nibbles/expire_sched.py``, by the path it had before nibbles was a package.

nibbles became a package on 2026-10-10. ``python3 expire_sched.py`` in the
checkout has always been the queue's command line, with nothing installed. So
the old path is kept as a door: imported, this file *is*
``nibbles.expire_sched``; run, it does what running that module did.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nibbles import expire_sched as _module  # noqa: E402

if __name__ == "__main__":
    sys.exit(_module.main())

sys.modules[__name__] = _module
