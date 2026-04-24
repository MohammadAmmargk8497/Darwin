"""Unit tests for arXiv query construction in src.arxiv_server.server."""

from __future__ import annotations

from src.arxiv_server.server import (
    _build_fallback_query,
    _build_structured_query,
    _has_field_prefix,
    _key_terms,
)


class TestKeyTerms:
    def test_drops_stopwords(self):
        assert _key_terms("the quick brown fox") == ["quick", "brown", "fox"]

    def test_drops_short_tokens(self):
        assert _key_terms("a bb ccc dddd") == ["ccc", "dddd"]

    def test_lowercases(self):
        assert _key_terms("Reward Alignment") == ["reward", "alignment"]

    def test_empty(self):
        assert _key_terms("") == []


class TestHasFieldPrefix:
    def test_detects_ti_prefix(self):
        assert _has_field_prefix('ti:"attention is all"')

    def test_detects_cat_prefix(self):
        assert _has_field_prefix("cat:cs.AI attention")

    def test_no_prefix(self):
        assert not _has_field_prefix("reward alignment")

    def test_empty(self):
        assert not _has_field_prefix("")


class TestStructuredQuery:
    def test_short_query_uses_exact_phrase(self):
        q = _build_structured_query("reward alignment")
        assert 'ti:"reward alignment"' in q
        assert 'abs:"reward alignment"' in q

    def test_long_query_uses_and_of_terms(self):
        # "large language model training efficiency" has 5 key terms
        q = _build_structured_query("large language model training efficiency")
        # AND-of-terms form: should contain every term in both ti: and abs:
        for term in ("large", "language", "model", "training", "efficiency"):
            assert f"ti:{term}" in q
            assert f"abs:{term}" in q
        assert " AND " in q

    def test_categories_appended_when_provided(self):
        q = _build_structured_query("reward hacking", categories=["cs.AI", "cs.LG"])
        assert "cat:cs.AI" in q
        assert "cat:cs.LG" in q
        assert " AND " in q

    def test_categories_omitted_when_none(self):
        q = _build_structured_query("reward hacking")
        assert "cat:" not in q


class TestFallbackQuery:
    def test_or_of_terms(self):
        q = _build_fallback_query("reward alignment policy")
        assert " OR " in q
        for term in ("reward", "alignment", "policy"):
            assert f"ti:{term}" in q
            assert f"abs:{term}" in q

    def test_empty_returns_raw(self):
        # Only stopwords → no key terms → returns raw query
        assert _build_fallback_query("the a an") == "the a an"
