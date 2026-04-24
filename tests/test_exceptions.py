"""Unit tests for src.common.exceptions."""

from __future__ import annotations

from src.common.exceptions import (
    ArxivEmptyResultError,
    ArxivError,
    ArxivRateLimitError,
    ConfigError,
    DarwinError,
    NoteNotFoundError,
    ObsidianError,
    PDFParseError,
    VaultNotConfiguredError,
)


def test_hierarchy():
    # Every Darwin-specific exception should descend from DarwinError so
    # callers can catch the base class and get everything.
    for cls in (
        ArxivError,
        ArxivRateLimitError,
        ArxivEmptyResultError,
        ConfigError,
        ObsidianError,
        VaultNotConfiguredError,
        NoteNotFoundError,
        PDFParseError,
    ):
        assert issubclass(cls, DarwinError)

    # Sub-families keep their parent relationship
    assert issubclass(ArxivRateLimitError, ArxivError)
    assert issubclass(ArxivEmptyResultError, ArxivError)
    assert issubclass(VaultNotConfiguredError, ObsidianError)
    assert issubclass(NoteNotFoundError, ObsidianError)
