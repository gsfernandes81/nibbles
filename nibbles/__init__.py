"""nibbles: queue YouTube videos and files, fetch them before the data expires.

The package is the whole app; ``nibbles`` (:func:`main`) is its one command.
Nothing is imported here: the runner, the queue items and the job scheduler
import ``nibbles.<module>`` with Termux's own interpreter, and must not pay
for — or need — the screens' terminal library on the way.
"""

from __future__ import annotations

__version__ = "0.5.0"


def main(argv: list[str] | None = None) -> int:
    """``nibbles``: the one command (:func:`nibbles.app.main`)."""
    from nibbles.app import main as door

    return door(argv)
