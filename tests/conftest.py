"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `src` importable from tests without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """A throwaway directory usable as an Obsidian vault."""
    (tmp_path / "Research" / "Incoming").mkdir(parents=True)
    return tmp_path
