"""Exception hierarchy for Darwin.

All internal errors inherit from ``DarwinError``. MCP tools catch at the
boundary and serialize to structured error dicts so the agent still gets
a usable response instead of a stack trace.
"""


class DarwinError(Exception):
    """Base class for all Darwin errors."""


class ConfigError(DarwinError):
    """Missing or invalid configuration."""


class ArxivError(DarwinError):
    """arXiv API error (base)."""


class ArxivRateLimitError(ArxivError):
    """arXiv throttled us — retry with backoff."""


class ArxivEmptyResultError(ArxivError):
    """No results for the given query."""


class PDFParseError(DarwinError):
    """Failed to read or parse a PDF."""


class ObsidianError(DarwinError):
    """Obsidian vault operation failed (base)."""


class VaultNotConfiguredError(ObsidianError):
    """OBSIDIAN_VAULT_PATH is unset or invalid."""


class NoteNotFoundError(ObsidianError):
    """Requested note does not exist in the vault."""
