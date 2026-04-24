"""Unit tests for src.common.vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.exceptions import (
    NoteNotFoundError,
    ObsidianError,
    VaultNotConfiguredError,
)
from src.common.vault import Vault, compose_note, split_frontmatter


# ---------------------------------------------------------------------------
# Frontmatter round-tripping
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    def test_standard_note(self):
        content = "---\ntitle: Foo\ntags: [a, b]\n---\n\n# Body\n\nText."
        fm, body = split_frontmatter(content)
        assert fm == {"title": "Foo", "tags": ["a", "b"]}
        assert body.startswith("\n# Body")

    def test_no_frontmatter(self):
        content = "# Just a body\n\nText."
        fm, body = split_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_empty(self):
        assert split_frontmatter("") == ({}, "")

    def test_unclosed_frontmatter(self):
        content = "---\ntitle: Foo\n# Body"
        fm, body = split_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_invalid_yaml_is_graceful(self):
        content = "---\n: : : bad yaml\n---\nbody"
        fm, body = split_frontmatter(content)
        assert fm == {}

    def test_roundtrip(self):
        original_fm = {"title": "X", "tags": ["a"]}
        body = "\n# Body\n"
        out = compose_note(original_fm, body)
        fm, body_out = split_frontmatter(out)
        assert fm == original_fm
        assert body_out.strip() == "# Body"


# ---------------------------------------------------------------------------
# Vault ops
# ---------------------------------------------------------------------------


class TestVault:
    def test_unconfigured_raises(self):
        with pytest.raises(VaultNotConfiguredError):
            Vault(None)
        with pytest.raises(VaultNotConfiguredError):
            Vault("")

    def test_nonexistent_raises(self, tmp_path: Path):
        with pytest.raises(VaultNotConfiguredError):
            Vault(tmp_path / "does-not-exist")

    def test_write_and_read(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("Research/Incoming/foo", "# Hello")
        assert vault.read_note("Research/Incoming/foo") == "# Hello"

    def test_write_accepts_trailing_md(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("notes/bar.md", "# Bar")
        assert (tmp_vault / "notes" / "bar.md").exists()
        assert vault.read_note("notes/bar") == "# Bar"

    def test_read_missing_raises(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        with pytest.raises(NoteNotFoundError):
            vault.read_note("nope")

    def test_traversal_rejected(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        with pytest.raises(ObsidianError):
            vault.write_note("../outside", "nope")

    def test_empty_path_rejected(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        with pytest.raises(ObsidianError):
            vault.write_note("", "nope")

    def test_append_preserves_frontmatter(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        content = "---\ntitle: Foo\n---\n\n# Body\n\nLine 1."
        vault.write_note("Research/Incoming/foo", content)
        vault.append_note("Research/Incoming/foo", "Line 2.")
        result = vault.read_note("Research/Incoming/foo")
        fm, body = split_frontmatter(result)
        assert fm == {"title": "Foo"}
        assert "Line 1" in body
        assert "Line 2" in body

    def test_append_missing_raises(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        with pytest.raises(NoteNotFoundError):
            vault.append_note("missing", "hi")

    def test_update_frontmatter_adds_tags(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("n", "---\ntitle: X\ntags: [a]\n---\n\nbody")
        vault.update_frontmatter("n", tags=["b", "a", "c"])
        fm, _ = split_frontmatter(vault.read_note("n"))
        # 'a' already present, dedup preserves order
        assert fm["tags"] == ["a", "b", "c"]

    def test_update_frontmatter_sets_properties(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("n", "---\ntitle: X\n---\n\nbody")
        vault.update_frontmatter("n", properties={"status": "reviewed", "score": 5})
        fm, _ = split_frontmatter(vault.read_note("n"))
        assert fm["status"] == "reviewed"
        assert fm["score"] == 5

    def test_update_frontmatter_missing_raises(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        with pytest.raises(NoteNotFoundError):
            vault.update_frontmatter("nope", tags=["x"])

    def test_search_finds_content(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("a", "reward hacking in RL")
        vault.write_note("b", "diffusion model architectures")
        vault.write_note("c", "another note mentioning reward hacking again")
        hits = vault.search("reward hacking")
        assert len(hits) == 2
        paths = {h["path"] for h in hits}
        assert paths == {"a", "c"}
        assert all("reward hacking" in h["snippet"].lower() for h in hits)

    def test_search_empty_query(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        assert vault.search("") == []

    def test_search_no_hits(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("a", "some content")
        assert vault.search("needle") == []

    def test_search_case_insensitive_by_default(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("a", "Transformer Architecture")
        hits = vault.search("transformer")
        assert len(hits) == 1

    def test_iter_notes_skips_dot_obsidian(self, tmp_vault: Path):
        vault = Vault(tmp_vault)
        vault.write_note("real", "visible")
        # Simulate Obsidian's internal workspace.md
        hidden = tmp_vault / ".obsidian" / "workspace.md"
        hidden.parent.mkdir(parents=True)
        hidden.write_text("hidden")
        names = {p.stem for p in vault.iter_notes()}
        assert "real" in names
        assert "workspace" not in names
