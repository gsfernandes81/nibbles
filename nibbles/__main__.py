"""``python -m nibbles`` is ``nibbles``: what a detached ``nibbles now`` runs,
under the interpreter that is running this, wherever the package is."""

import sys

from nibbles import main

sys.exit(main())
