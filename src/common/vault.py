"""Obsidian vault I/O.

Every read/write/search against the vault goes through the ``Vault`` class so
that path resolution, frontmatter parsing, and vault-containment checks live
in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

from .exceptions import NoteNotFoundError, ObsidianError, VaultNotConfiguredError

_FRONTMATTER_DELIM = "---"


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter_dict, body)``.

    If no YAML frontmatter is present, returns ``({}, content)``. Invalid YAML
    is treated as "no frontmatter" — we'd rather preserve the file than raise.
    Tolerates BOM and CRLF.
    """
    if not content:
        return {}, ""
    stripped = content.lstrip("﻿")
    if not stripped.startswith(_FRONTMATTER_DELIM):
        return {}, content

    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != _FRONTMATTER_DELIM:
        return {}, content

    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == _FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        return {}, content

    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1:])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, content
    if not isinstance(fm, dict):
        return {}, content
    return fm, body


def compose_note(frontmatter: dict[str, Any], body: str) -> str:
    """Render a note string from a frontmatter dict and body text."""
    if not frontmatter:
        return body
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"{_FRONTMATTER_DELIM}\n{fm_text}\n{_FRONTMATTER_DELIM}\n{body}"


class Vault:
    """Filesystem-backed wrapper around an Obsidian vault directory."""

    def __init__(self, root: str | Path | None):
        if not root:
            raise VaultNotConfiguredError("OBSIDIAN_VAULT_PATH is not set")
        root_path = Path(str(root)).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise VaultNotConfiguredError(f"Vault directory does not exist: {root_path}")
        self.root = root_path

    # --- Path resolution -------------------------------------------------

    def _resolve(self, note_path: str) -> Path:
        """Resolve a vault-relative note path to an absolute file path.

        Strips a trailing ``.md`` if present. Rejects paths that escape the
        vault root (directory traversal defence).
        """
        note_path = note_path.strip().lstrip("/\\")
        if note_path.lower().endswith(".md"):
            note_path = note_path[:-3]
        if not note_path:
            raise ObsidianError("Empty note path")
        candidate = (self.root / f"{note_path}.md").resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as e:
            raise ObsidianError(f"Note path escapes vault root: {note_path}") from e
        return candidate

    def relative(self, path: Path) -> str:
        """Return a vault-relative path string (no ``.md`` suffix)."""
        rel = path.relative_to(self.root).as_posix()
        return rel[:-3] if rel.lower().endswith(".md") else rel

    # --- Writes ----------------------------------------------------------

    def write_note(self, note_path: str, content: str) -> Path:
        """Write ``content`` to ``note_path``; creates parent directories."""
        full = self._resolve(note_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return full

    def append_note(self, note_path: str, text: str, separator: str = "\n\n") -> Path:
        """Append ``text`` to an existing note's body (after any frontmatter)."""
        full = self._resolve(note_path)
        if not full.exists():
            raise NoteNotFoundError(f"Note not found: {note_path}")
        existing = full.read_text(encoding="utf-8")
        fm, body = split_frontmatter(existing)
        new_body = body.rstrip() + separator + text + "\n"
        full.write_text(compose_note(fm, new_body), encoding="utf-8")
        return full

    def update_frontmatter(
        self,
        note_path: str,
        tags: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> Path:
        """Merge ``tags`` and ``properties`` into the note's YAML frontmatter.

        Existing tags are preserved; new tags are appended. ``properties`` keys
        overwrite any existing keys of the same name. If the note has no
        frontmatter yet, one is created.
        """
        full = self._resolve(note_path)
        if not full.exists():
            raise NoteNotFoundError(f"Note not found: {note_path}")
        content = full.read_text(encoding="utf-8")
        fm, body = split_frontmatter(content)
        fm = dict(fm)

        if tags is not None:
            existing = fm.get("tags") or []
            if not isinstance(existing, list):
                existing = [existing]
            fm["tags"] = list(dict.fromkeys([*existing, *tags]))
        if properties:
            fm.update(properties)

        full.write_text(compose_note(fm, body), encoding="utf-8")
        return full

    # --- Reads -----------------------------------------------------------

    def read_note(self, note_path: str) -> str:
        full = self._resolve(note_path)
        if not full.exists():
            raise NoteNotFoundError(f"Note not found: {note_path}")
        return full.read_text(encoding="utf-8")

    def iter_notes(self) -> Iterator[Path]:
        """Yield every ``.md`` file under the vault (excluding ``.obsidian/``)."""
        for path in self.root.rglob("*.md"):
            if ".obsidian" in path.parts:
                continue
            yield path

    def search(
        self,
        query: str,
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> list[dict[str, str]]:
        """Substring search across note contents.

        Returns a list of ``{name, path, snippet}`` dicts, one per matching
        note, with a ~240-char snippet centred on the first hit.
        """
        if not query:
            return []
        q = query if case_sensitive else query.lower()
        hits: list[dict[str, str]] = []
        for path in self.iter_notes():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hay = content if case_sensitive else content.lower()
            idx = hay.find(q)
            if idx == -1:
                continue
            start = max(0, idx - 60)
            end = min(len(content), idx + 180)
            snippet = content[start:end].replace("\n", " ").strip()
            hits.append(
                {
                    "name": path.stem,
                    "path": self.relative(path),
                    "snippet": snippet,
                }
            )
            if len(hits) >= max_results:
                break
        return hits
