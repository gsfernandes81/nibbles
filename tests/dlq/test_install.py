"""An installed copy makes its own queue root, and never anybody else's.

Installed from PyPI, nibbles is a package in site-packages, and the queue it
manages is ``~/nibbles`` (:func:`home.root`). The first run makes that root —
the item contract that marks it, and the launcher the nightly job is armed with
— and every run after keeps the launcher pointing at wherever an upgrade put
the package; a checkout gets the launcher too, gitignored. What is pinned here
is the other half as much as that one: a checkout's tracked files, a root
``EXPIRE_HOME`` names and a folder of somebody's own are never made into
anything, and a launcher nibbles did not write is never written over.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(dlq, monkeypatch):
    """The copy's ``nibbles.home``, with no ``EXPIRE_HOME`` to defer to."""
    monkeypatch.delenv("EXPIRE_HOME")
    return dlq.ytq.home


def test_the_first_run_makes_the_root_and_later_runs_change_nothing(home, tmp_path):
    root = tmp_path / "nibbles"
    assert home.ensure(root)
    marker = root / home.CONTRACT
    launcher = root / home.LAUNCHER
    assert marker.read_text(encoding="utf-8") == home.contract()
    assert launcher.read_text(encoding="utf-8") == home.launcher()
    assert os.access(launcher, os.X_OK)
    made = {path: path.stat().st_mtime_ns for path in (marker, launcher)}
    assert home.ensure(root) == []
    assert {path: path.stat().st_mtime_ns for path in made} == made


def test_the_contract_an_installed_copy_writes_is_the_checkout_s(home):
    assert home.contract() == (REPO / "queue" / "README.md").read_text(encoding="utf-8")


def test_the_wheel_ships_the_contract_where_the_package_looks_for_it(home):
    hatch = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["hatch"]
    shipped = hatch["build"]["targets"]["wheel"]["force-include"]["queue/README.md"]
    assert shipped == f"nibbles/{home.SHIPPED_CONTRACT.name}"


def test_a_folder_of_somebody_s_own_is_never_filled(home, tmp_path):
    root = tmp_path / "nibbles"
    root.mkdir()
    (root / "notes.txt").write_text("mine")
    assert home.ensure(root) == []
    assert sorted(path.name for path in root.iterdir()) == ["notes.txt"]


def test_a_checkout_gets_the_launcher_and_nothing_else(home, dlq):
    # The test root is shaped like a checkout: the package and the contract.
    assert home.is_checkout(dlq.root)
    (dlq.root / home.LAUNCHER).unlink()
    tracked = {path: path.read_bytes() for path in dlq.root.rglob("*") if path.is_file()}
    assert home.ensure(dlq.root) == []
    launcher = dlq.root / home.LAUNCHER
    assert launcher.read_text(encoding="utf-8") == home.launcher()
    after = {path: path.read_bytes() for path in dlq.root.rglob("*") if path.is_file()}
    assert after.pop(launcher)
    assert after == tracked


def test_the_launcher_is_gitignored_in_a_checkout(home):
    ignored = (REPO / ".gitignore").read_text().splitlines()
    assert f"/{home.LAUNCHER}" in ignored


def test_a_root_expire_home_names_is_never_made(dlq, tmp_path, monkeypatch):
    chosen = tmp_path / "chosen"
    monkeypatch.setenv("EXPIRE_HOME", str(chosen))
    assert dlq.ytq.home.ensure() == []
    assert not chosen.exists()


def test_only_a_launcher_of_ours_is_ever_rewritten(home, tmp_path):
    root = tmp_path / "nibbles"
    home.ensure(root)
    launcher = root / home.LAUNCHER
    stale = home.launcher().replace(str(home.SOURCE), "/where/the/package/was")
    launcher.write_text(stale, encoding="utf-8")
    home.ensure(root)
    assert launcher.read_text(encoding="utf-8") == home.launcher()

    theirs = "#!/bin/sh\necho a runner somebody wrote\n"
    launcher.write_text(theirs, encoding="utf-8")
    home.ensure(root)
    assert launcher.read_text(encoding="utf-8") == theirs


def test_the_launcher_runs_the_runner_in_the_root_it_sits_in(home, dlq, tmp_path):
    root = tmp_path / "nibbles"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home.ensure(root)
    env = {**os.environ, "EXPIRE_HOME": str(elsewhere), "HOME": str(dlq.home)}
    done = subprocess.run(
        [sys.executable, str(root / home.LAUNCHER)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert (root / "heartbeat").is_file()
    assert list(elsewhere.iterdir()) == []


def test_the_package_says_the_version_pyproject_releases(dlq):
    import importlib

    package = importlib.import_module("nibbles")
    released = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    assert package.__version__ == released
