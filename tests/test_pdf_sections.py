"""Unit tests for src.common.pdf_sections."""

from __future__ import annotations

from src.common.pdf_sections import PER_SECTION_LIMIT, canonicalize, split_sections


class TestCanonicalize:
    def test_methods_variants(self):
        assert canonicalize("Methods") == "methods"
        assert canonicalize("METHOD") == "methods"
        assert canonicalize("Methodology") == "methods"
        assert canonicalize("Approach") == "methods"

    def test_results_variants(self):
        assert canonicalize("Results") == "results"
        assert canonicalize("Results and Discussion") == "results"

    def test_background_maps_to_related_work(self):
        assert canonicalize("Background") == "related_work"
        assert canonicalize("Related Work") == "related_work"

    def test_acknowledgments_skipped(self):
        assert canonicalize("Acknowledgments") is None
        assert canonicalize("Acknowledgements") is None

    def test_unknown_returns_none(self):
        assert canonicalize("Totally Made Up Section") is None


class TestSplitSections:
    def test_basic_split(self):
        text = (
            "Abstract\n"
            "This paper introduces a new method.\n"
            "1. Introduction\n"
            "We motivate the problem here.\n"
            "2. Methods\n"
            "Our approach is simple.\n"
            "3. Results\n"
            "It works well.\n"
            "4. Conclusion\n"
            "Done.\n"
        )
        sections = split_sections(text)
        assert "abstract" in sections
        assert "introduction" in sections
        assert "methods" in sections
        assert "results" in sections
        assert "conclusion" in sections
        assert "new method" in sections["abstract"]
        assert "motivate" in sections["introduction"]
        assert "simple" in sections["methods"]

    def test_missing_abstract_uses_positional_fallback(self):
        # No "Abstract" header line at column 0, but the word appears in text
        text = "Abstract: this is the abstract body.\nIntroduction\nBody here."
        sections = split_sections(text)
        # The positional fallback finds "abstract" somewhere in the text
        assert "abstract" in sections
        assert len(sections["abstract"]) > 0

    def test_section_truncation(self):
        long_body = "x" * (PER_SECTION_LIMIT + 500)
        text = f"Abstract\n{long_body}\nIntroduction\nshort\n"
        sections = split_sections(text)
        assert "abstract" in sections
        assert len(sections["abstract"]) <= PER_SECTION_LIMIT + len("\n[... truncated]")
        assert sections["abstract"].endswith("[... truncated]")

    def test_numbered_and_roman_headers(self):
        text = "1. Introduction\nfoo\nII. Methods\nbar\n"
        sections = split_sections(text)
        assert sections.get("introduction") == "foo"
        assert sections.get("methods") == "bar"

    def test_empty_text(self):
        assert split_sections("") == {}

    def test_skipped_sections_not_included(self):
        text = "Introduction\nfoo\nAcknowledgments\nThanks to mom.\n"
        sections = split_sections(text)
        assert "introduction" in sections
        # Acknowledgments is canonicalized to None → should not appear
        assert not any("mom" in v for v in sections.values())
