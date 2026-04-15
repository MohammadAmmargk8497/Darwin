#!/usr/bin/env python3
"""
Full pipeline test for Darwin research agent
Tests: Search → Download → Read → Extract → Summarize
"""
import asyncio
import sys
import os

print("=" * 80)
print("DARWIN FULL PIPELINE TEST")
print("=" * 80)
print("\nThis will test the complete workflow:")
print("  1. Search papers on ArXiv")
print("  2. Download a paper")
print("  3. Read paper content")
print("  4. Extract PDF sections")
print("  5. Summarize findings")
print("\n" + "=" * 80)
print("\nStarting agent...\n")

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from src.agent.main import run_agent

if __name__ == "__main__":
    asyncio.run(run_agent())
