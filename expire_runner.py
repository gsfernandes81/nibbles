#!/data/data/com.termux/files/usr/bin/python3
"""``nibbles/expire_runner.py``, by the path it had before nibbles was a package.

nibbles became a package on 2026-10-10. A phone armed before then has the job
scheduler starting this file every night; an installed copy's queue root gets a
launcher like it (``home.launcher``). So the old path is kept as a door:
imported, this file *is* ``nibbles.expire_runner``; run, it does what running
that module did.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if __name__ == "__main__":
    # The runner works out of the directory it sits in, as it always has; said
    # before the import, because the runner spells its root when imported.
    os.environ["EXPIRE_HOME"] = str(Path(__file__).resolve().parent)

from nibbles import expire_runner as _module  # noqa: E402

if __name__ == "__main__":
    sys.exit(_module.main())

sys.modules[__name__] = _module
