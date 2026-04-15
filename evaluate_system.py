#!/usr/bin/env python3
"""
Darwin System Evaluation
=========================
End-to-end evaluation of the Darwin research agent pipeline.

Sections
--------
  1. Search Quality       — structured engine vs raw-keyword baseline
  2. Download Pipeline    — success rate, deduplication, file integrity, latency
  3. PDF Extraction       — text yield, section detection, truncation behaviour
  4. Note Creation        — file creation, frontmatter, required sections
  5. End-to-End Pipeline  — search → download → read → note, completion rate
  6. Error Handling       — bad inputs handled gracefully without crashing

Usage
-----
  python evaluate_system.py              # full evaluation (all sections)
  python evaluate_system.py --section search
  python evaluate_system.py --section download
  python evaluate_system.py --section pdf
  python evaluate_system.py --section notes
  python evaluate_system.py --section e2e
  python evaluate_system.py --section errors
  python evaluate_system.py --no-save   # skip CSV output
"""

import argparse
import csv
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import arxiv
import pymupdf

# Set vault path to a temp directory so note-creation tests don't require
# Obsidian to be installed. The eval creates real files we can inspect.
_EVAL_VAULT = os.path.join(PROJECT_ROOT, "_eval_vault")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", _EVAL_VAULT)
os.makedirs(_EVAL_VAULT, exist_ok=True)

from src.arxiv_server.server import (
    search_papers,
    download_paper,
    read_paper,
    list_papers,
    confirm_download,
    _key_terms,
)
from src.pdf_parser.server import extract_pdf_sections
from src.obsidian_server.server import obsidian_create_note, obsidian_create_paper_note

PAPER_STORAGE = os.environ.get("PAPER_STORAGE", os.path.join(PROJECT_ROOT, "papers"))

# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _ok(condition: bool) -> str:
    return "✓" if condition else "✗"


def _section_header(title: str) -> None:
    print(f"\n{'═' * 66}")
    print(f"  {title}")
    print(f"{'═' * 66}")


def _row(label: str, passed: bool, detail: str = "") -> dict:
    print(f"  {_ok(passed)}  {label:<40} {detail}")
    return {"label": label, "passed": passed, "detail": detail}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Search Quality
# ═══════════════════════════════════════════════════════════════════════════════

SEARCH_QUERIES = [
    {"query": "reward hacking reinforcement learning",      "cats": {"cs.AI", "cs.LG"}},
    {"query": "attention mechanism transformer",            "cats": {"cs.LG", "cs.CL"}},
    {"query": "federated learning privacy",                 "cats": {"cs.LG", "cs.CR"}},
    {"query": "diffusion models image generation",          "cats": {"cs.CV", "cs.LG"}},
    {"query": "large language model hallucination",         "cats": {"cs.CL", "cs.AI"}},
    {"query": "graph neural network node classification",   "cats": {"cs.LG"}},
    {"query": "contrastive learning self-supervised",       "cats": {"cs.LG", "cs.CV"}},
    {"query": "adversarial robustness deep learning",       "cats": {"cs.LG", "cs.CR"}},
]


def _baseline_search(query: str, max_results: int = 8) -> list[dict]:
    """Raw arXiv keyword search with no field scoping (the old approach)."""
    client = arxiv.Client()
    results = []
    try:
        for r in client.results(arxiv.Search(query=query, max_results=max_results,
                                             sort_by=arxiv.SortCriterion.Relevance)):
            results.append({
                "id": r.get_short_id(),
                "title": r.title,
                "categories": r.categories,
                "summary": r.summary.replace("\n", " "),
            })
    except Exception:
        pass
    return results


def _kw_precision(results: list[dict], query: str) -> float:
    if not results:
        return 0.0
    terms = _key_terms(query)
    if not terms:
        return 1.0
    hits = sum(
        1 for r in results
        if any(t in (r.get("title", "") + " " + r.get("summary", "")).lower() for t in terms)
    )
    return hits / len(results)


def _cat_precision(results: list[dict], expected: set) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if set(r.get("categories", [])) & expected) / len(results)


def evaluate_search() -> dict:
    _section_header("Section 1 — Search Quality (Structured vs Baseline)")
    results = []

    for label, searcher in [
        ("Baseline (raw keyword)", lambda q: _baseline_search(q)),
        ("Structured (Darwin)",    lambda q: [r for r in search_papers(q, max_results=8,
                                               categories=["cs.AI","cs.LG","stat.ML"])
                                              if not r.get("error")]),
    ]:
        print(f"\n  [{label}]")
        per = []
        for item in SEARCH_QUERIES:
            q, cats = item["query"], item["cats"]
            t0 = time.perf_counter()
            papers = searcher(q)
            ms = (time.perf_counter() - t0) * 1000
            kw = _kw_precision(papers, q)
            cat = _cat_precision(papers, cats)
            success = len(papers) >= 3
            print(f"    {_ok(success)} [{len(papers):2d} | kw={kw:.2f} | cat={cat:.2f} | {ms:.0f}ms]  {q}")
            per.append({"query": q, "n": len(papers), "kw": kw, "cat": cat, "ms": ms, "ok": success})

        n = len(per)
        agg = {
            "label": label,
            "keyword_precision": sum(r["kw"] for r in per) / n,
            "category_precision": sum(r["cat"] for r in per) / n,
            "success_rate": sum(r["ok"] for r in per) / n,
            "zero_result_rate": sum(1 for r in per if r["n"] == 0) / n,
            "avg_latency_ms": sum(r["ms"] for r in per) / n,
            "per_query": per,
        }
        results.append(agg)

    base, struct = results

    print(f"\n  {'Metric':<28} {'Baseline':>9} {'Structured':>11} {'Δ':>8}")
    print(f"  {'─' * 58}")
    comparisons = [
        ("Keyword Precision",  "keyword_precision",  "{:.3f}", True),
        ("Category Precision", "category_precision", "{:.3f}", True),
        ("Success Rate",       "success_rate",       "{:.3f}", True),
        ("Zero-Result Rate",   "zero_result_rate",   "{:.3f}", False),
        ("Avg Latency (ms)",   "avg_latency_ms",     "{:.0f}", False),
    ]
    wins = 0
    for label, key, fmt, hib in comparisons:
        b, s = base[key], struct[key]
        delta = s - b
        arrow = ("↑" if delta > 0 else "↓") if hib else ("↑" if delta < 0 else "↓")
        if (delta > 0) == hib:
            wins += 1
        print(f"  {label:<28} {fmt.format(b):>9} {fmt.format(s):>11} {arrow} {fmt.format(abs(delta)):>6}")

    print(f"\n  Structured wins {wins}/{len(comparisons)} metrics vs baseline.")
    return {"section": "search", "baseline": base, "structured": struct, "wins": wins}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Download Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_download() -> dict:
    _section_header("Section 2 — Download Pipeline")
    rows = []

    # Find existing papers to test dedup + file integrity
    existing = [f.replace(".pdf", "") for f in os.listdir(PAPER_STORAGE) if f.endswith(".pdf")]
    if not existing:
        print("  ⚠  No papers in papers/ — skipping download dedup tests")
        return {"section": "download", "rows": []}

    test_id = existing[0]

    # 2a. Deduplication: calling download_paper on an existing paper should
    #     return the path immediately without hitting the network
    t0 = time.perf_counter()
    result = download_paper(test_id)
    ms = (time.perf_counter() - t0) * 1000
    is_cached = ms < 500  # should be near-instant, not a network call
    rows.append(_row("Deduplication (cache hit < 500 ms)", is_cached, f"{ms:.0f} ms"))

    # 2b. Return value is a valid path
    path_exists = os.path.isfile(result) if isinstance(result, str) else False
    rows.append(_row("download_paper returns valid file path", path_exists, str(result)[:60]))

    # 2c. File is a valid PDF (starts with %PDF magic bytes)
    if path_exists:
        with open(result, "rb") as f:
            header = f.read(4)
        is_pdf = header == b"%PDF"
        rows.append(_row("Downloaded file is a valid PDF", is_pdf, f"header={header}"))
    else:
        rows.append(_row("Downloaded file is a valid PDF", False, "no file to check"))

    # 2d. list_papers() returns the expected files
    listed = list_papers()
    lists_correctly = test_id + ".pdf" in listed or any(test_id in f for f in listed)
    rows.append(_row("list_papers() lists downloaded papers", lists_correctly,
                     f"{len(listed)} files found"))

    # 2e. confirm_download returns expected structure
    conf = confirm_download("Test Paper", test_id, "2024-01-01", "This is a test abstract.")
    has_status = conf.get("status") == "awaiting_confirmation"
    has_message = "message" in conf and "PAPER DOWNLOAD CONFIRMATION" in conf["message"]
    rows.append(_row("confirm_download returns correct status", has_status,
                     f"status={conf.get('status')}"))
    rows.append(_row("confirm_download message contains required fields", has_message))

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} download checks.")
    return {"section": "download", "rows": rows, "passed": passed, "total": len(rows)}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — PDF Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_pdf() -> dict:
    _section_header("Section 3 — PDF Extraction")
    rows = []

    existing = [f.replace(".pdf", "") for f in os.listdir(PAPER_STORAGE) if f.endswith(".pdf")]
    if not existing:
        print("  ⚠  No papers in papers/ — skipping PDF extraction tests")
        return {"section": "pdf", "rows": []}

    # Test on up to 3 papers for breadth
    test_ids = existing[:3]

    for paper_id in test_ids:
        print(f"\n  Paper: {paper_id}")

        # 3a. read_paper returns text (not error string)
        text = read_paper(paper_id, max_chars=5000)
        is_text = isinstance(text, str) and not text.startswith("Error:")
        rows.append(_row(f"read_paper({paper_id}) returns text", is_text,
                         f"{len(text)} chars" if is_text else text[:60]))

        # 3b. Extracted text is substantial (more than a few hundred chars)
        substantial = is_text and len(text) > 500
        rows.append(_row("  Extracted text > 500 chars", substantial,
                         f"{len(text)} chars" if is_text else "—"))

        # 3c. Truncation marker appears when max_chars is hit
        short_text = read_paper(paper_id, max_chars=500)
        truncated = "[... Content truncated" in short_text
        rows.append(_row("  Truncation marker present at max_chars", truncated))

        # 3d. extract_pdf_sections finds an abstract
        pdf_path = os.path.join(PAPER_STORAGE, f"{paper_id}.pdf")
        sections = extract_pdf_sections(pdf_path, max_chars=5000)
        has_abstract = "abstract" in sections and len(sections.get("abstract", "")) > 50
        rows.append(_row("  extract_pdf_sections finds abstract", has_abstract,
                         f"abstract={len(sections.get('abstract',''))} chars"))

        # 3e. Full text preview key present
        has_preview = "full_text_preview" in sections
        rows.append(_row("  extract_pdf_sections returns full_text_preview", has_preview))

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} PDF extraction checks.")
    return {"section": "pdf", "rows": rows, "passed": passed, "total": len(rows)}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — Note Creation
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_notes() -> dict:
    _section_header("Section 4 — Note Creation (Obsidian)")
    rows = []
    vault = os.environ.get("OBSIDIAN_VAULT_PATH", _EVAL_VAULT)

    # 4a. obsidian_create_note
    result = obsidian_create_note(
        title="Eval Test Note",
        content="This is test content for the evaluation module.",
        tags=["eval", "test"],
    )
    created = result.get("success", False)
    rows.append(_row("obsidian_create_note reports success", created,
                     f"status={result.get('status')}"))

    if created:
        note_path = result.get("file_location", "")
        file_exists = os.path.isfile(note_path)
        rows.append(_row("Note file actually written to disk", file_exists, note_path[-60:]))

        if file_exists:
            content = Path(note_path).read_text(encoding="utf-8")
            rows.append(_row("Note has YAML frontmatter", "---" in content))
            rows.append(_row("Note has title field in frontmatter",
                             "title: Eval Test Note" in content))
            rows.append(_row("Note has tags in frontmatter", "tags:" in content))
            rows.append(_row("Note has ## Key Points section", "## Key Points" in content))
            rows.append(_row("Note has ## References section", "## References" in content))

    # 4b. obsidian_create_paper_note
    paper_result = obsidian_create_paper_note(
        paper_id="eval-test-001",
        title="Evaluation Test Paper",
        authors=["Alice Smith", "Bob Jones"],
        abstract="This is a synthetic abstract for evaluation purposes.",
        methods="Synthetic methods section.",
        findings="Key findings from the evaluation.",
        keywords=["evaluation", "testing"],
    )
    paper_created = paper_result.get("success", False)
    rows.append(_row("obsidian_create_paper_note reports success", paper_created,
                     f"status={paper_result.get('status')}"))

    if paper_created:
        paper_path = paper_result.get("file_location", "")
        paper_file_exists = os.path.isfile(paper_path)
        rows.append(_row("Paper note file written to disk", paper_file_exists))

        if paper_file_exists:
            content = Path(paper_path).read_text(encoding="utf-8")
            rows.append(_row("Paper note has paper_id in frontmatter",
                             "paper_id: eval-test-001" in content))
            rows.append(_row("Paper note has ## Abstract section", "## Abstract" in content))
            rows.append(_row("Paper note has ## Key Findings section",
                             "## Key Findings" in content))
            rows.append(_row("Paper note has ## Methods section", "## Methods" in content))

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} note creation checks.")
    return {"section": "notes", "rows": rows, "passed": passed, "total": len(rows)}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — End-to-End Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_e2e() -> dict:
    _section_header("Section 5 — End-to-End Pipeline (Search → Download → Read → Note)")
    rows = []

    pipeline_query = "attention mechanism transformer"
    print(f"\n  Query: '{pipeline_query}'")

    # Step 1: Search
    t0 = time.perf_counter()
    results = search_papers(pipeline_query, max_results=5, categories=["cs.AI", "cs.LG"])
    search_ms = (time.perf_counter() - t0) * 1000
    papers = [r for r in results if not r.get("error")]
    search_ok = len(papers) >= 1
    rows.append(_row("Step 1: search_papers returns results", search_ok,
                     f"{len(papers)} papers in {search_ms:.0f}ms"))

    if not search_ok:
        print("  ✗  Search returned nothing — cannot continue pipeline test.")
        return {"section": "e2e", "rows": rows, "passed": 0, "total": 1}

    paper = papers[0]
    paper_id = paper["id"].split("v")[0]  # strip version suffix
    print(f"  Using paper: {paper_id} — {paper.get('title', '')[:60]}")

    # Step 2: Download (uses dedup if already present)
    t0 = time.perf_counter()
    dl_result = download_paper(paper_id)
    dl_ms = (time.perf_counter() - t0) * 1000
    dl_ok = isinstance(dl_result, str) and os.path.isfile(dl_result)
    rows.append(_row("Step 2: download_paper succeeds", dl_ok,
                     f"{dl_ms:.0f}ms  path={'ok' if dl_ok else dl_result[:50]}"))

    # Step 3: Read paper
    if dl_ok:
        t0 = time.perf_counter()
        text = read_paper(paper_id, max_chars=3000)
        read_ms = (time.perf_counter() - t0) * 1000
        read_ok = isinstance(text, str) and not text.startswith("Error:") and len(text) > 200
        rows.append(_row("Step 3: read_paper extracts text", read_ok,
                         f"{len(text)} chars in {read_ms:.0f}ms"))
    else:
        rows.append(_row("Step 3: read_paper extracts text", False, "skipped — download failed"))
        text = ""
        read_ok = False

    # Step 4: Create Obsidian note from paper data
    t0 = time.perf_counter()
    note_result = obsidian_create_paper_note(
        paper_id=paper_id,
        title=paper.get("title", "Unknown"),
        authors=paper.get("authors", "").split(", "),
        abstract=paper.get("summary", ""),
        findings="To be extracted from full text.",
        keywords=["pipeline-test"],
    )
    note_ms = (time.perf_counter() - t0) * 1000
    note_ok = note_result.get("success", False)
    rows.append(_row("Step 4: obsidian_create_paper_note succeeds", note_ok,
                     f"{note_ms:.0f}ms"))

    # Overall pipeline
    all_steps_ok = search_ok and dl_ok and read_ok and note_ok
    rows.append(_row("Full pipeline completes without errors", all_steps_ok))

    total_ms = search_ms + dl_ms + (read_ms if read_ok else 0) + note_ms
    print(f"\n  Total pipeline latency: {total_ms:.0f} ms")

    passed = sum(1 for r in rows if r["passed"])
    print(f"  Passed {passed}/{len(rows)} end-to-end checks.")
    return {"section": "e2e", "rows": rows, "passed": passed, "total": len(rows),
            "total_latency_ms": total_ms}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — Error Handling Robustness
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_errors() -> dict:
    _section_header("Section 6 — Error Handling Robustness")
    rows = []

    # 6a. Empty query
    result = search_papers("", max_results=5)
    graceful = isinstance(result, list) and result and "error" in result[0]
    rows.append(_row("Empty query returns error dict (no crash)", graceful,
                     result[0].get("error", "")[:60] if graceful else str(result)[:60]))

    # 6b. Nonsense query (no real papers)
    result = search_papers("xyzzy foobar qwerty 99999 zzzz", max_results=5)
    graceful = isinstance(result, list)
    no_crash = True  # if we reached here, it didn't crash
    rows.append(_row("Nonsense query returns list (no crash)", graceful and no_crash,
                     f"{len(result)} items returned"))

    # 6c. Non-existent paper ID for read_paper (not downloaded)
    result = read_paper("9999-nonexistent-paper", max_chars=1000)
    graceful = isinstance(result, str) and "Error" in result
    rows.append(_row("read_paper on missing file returns error string", graceful,
                     result[:70]))

    # 6d. extract_pdf_sections on missing file
    result = extract_pdf_sections("/nonexistent/path/paper.pdf")
    graceful = isinstance(result, dict) and "error" in result
    rows.append(_row("extract_pdf_sections on missing path returns error dict", graceful,
                     str(result.get("error", ""))[:60]))

    # 6e. confirm_download returns structured dict (never raises)
    try:
        result = confirm_download("", "", "", "")
        graceful = isinstance(result, dict) and "status" in result
    except Exception as e:
        graceful = False
    rows.append(_row("confirm_download with empty args returns dict (no crash)", graceful))

    # 6f. search_papers with invalid max_results falls back gracefully
    result = search_papers("machine learning", max_results=-1)
    graceful = isinstance(result, list)
    rows.append(_row("search_papers with max_results=-1 handles gracefully", graceful,
                     f"{len(result)} results (clamped to 1)"))

    # 6g. obsidian_create_note with missing vault path
    orig = os.environ.get("OBSIDIAN_VAULT_PATH")
    os.environ["OBSIDIAN_VAULT_PATH"] = ""
    try:
        from src.obsidian_server import server as obs_srv
        obs_srv.OBSIDIAN_VAULT_PATH = ""
        result = obs_srv.obsidian_create_note("Crash Test", "content", [])
        graceful = isinstance(result, dict) and result.get("success") is False
    except Exception:
        graceful = False
    finally:
        os.environ["OBSIDIAN_VAULT_PATH"] = orig or _EVAL_VAULT
        obs_srv.OBSIDIAN_VAULT_PATH = orig or _EVAL_VAULT
    rows.append(_row("obsidian_create_note with no vault path fails gracefully", graceful))

    passed = sum(1 for r in rows if r["passed"])
    print(f"\n  Passed {passed}/{len(rows)} error handling checks.")
    return {"section": "errors", "rows": rows, "passed": passed, "total": len(rows)}


# ═══════════════════════════════════════════════════════════════════════════════
# Final summary + CSV output
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(section_results: list[dict]) -> None:
    print(f"\n{'═' * 66}")
    print("  OVERALL SYSTEM EVALUATION SUMMARY")
    print(f"{'═' * 66}")

    total_passed = 0
    total_checks = 0

    for res in section_results:
        section = res.get("section", "?")
        if section == "search":
            wins = res.get("wins", 0)
            out_of = 5
            label = "Search Quality (structured wins vs baseline)"
            detail = f"{wins}/{out_of} metrics"
            pct = wins / out_of
        else:
            p = res.get("passed", 0)
            t = res.get("total", 0)
            label = {
                "download": "Download Pipeline",
                "pdf":      "PDF Extraction",
                "notes":    "Note Creation",
                "e2e":      "End-to-End Pipeline",
                "errors":   "Error Handling",
            }.get(section, section)
            detail = f"{p}/{t} checks passed"
            pct = (p / t) if t else 0
            total_passed += p
            total_checks += t

        bar_filled = int(pct * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        print(f"  {_ok(pct >= 0.8)}  {label:<36} [{bar}] {pct*100:.0f}%  {detail}")

    if total_checks:
        overall = total_passed / total_checks
        print(f"\n  Overall (excl. search comparison): {total_passed}/{total_checks} "
              f"checks passed ({overall*100:.0f}%)")
    print(f"{'═' * 66}\n")


def save_csv(section_results: list[dict]) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"eval_results_{timestamp}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["section", "check", "passed", "detail"])
        for res in section_results:
            section = res.get("section", "?")
            if section == "search":
                for system in ["baseline", "structured"]:
                    d = res.get(system, {})
                    for row in d.get("per_query", []):
                        writer.writerow([
                            f"search_{system}",
                            row["query"],
                            row["ok"],
                            f"n={row['n']} kw={row['kw']:.2f} cat={row['cat']:.2f} ms={row['ms']:.0f}",
                        ])
            else:
                for row in res.get("rows", []):
                    writer.writerow([section, row["label"], row["passed"], row.get("detail", "")])
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

SECTION_MAP = {
    "search":   evaluate_search,
    "download": evaluate_download,
    "pdf":      evaluate_pdf,
    "notes":    evaluate_notes,
    "e2e":      evaluate_e2e,
    "errors":   evaluate_errors,
}

def main():
    parser = argparse.ArgumentParser(description="Darwin full system evaluation")
    parser.add_argument("--section", choices=list(SECTION_MAP), default=None,
                        help="Run only one section")
    parser.add_argument("--no-save", action="store_true", help="Skip CSV output")
    args = parser.parse_args()

    print("=" * 66)
    print("  Darwin Research Agent — System Evaluation")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 66)

    if args.section:
        result = SECTION_MAP[args.section]()
        section_results = [result]
    else:
        section_results = [fn() for fn in SECTION_MAP.values()]

    print_summary(section_results)

    if not args.no_save:
        path = save_csv(section_results)
        print(f"  Per-check results saved to: {path}\n")


if __name__ == "__main__":
    main()
