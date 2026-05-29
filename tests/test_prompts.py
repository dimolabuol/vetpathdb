"""Tests for the externalized prompt system (vetpathdb/prompts/loader.render_prompt).

These lock the canonical relevance-scoring prompts against drift: the rubric
text used to be copy-pasted in three places and had diverged. The goldens below
are the historical `semantic.py` (validated-path) wording, which is now the
single source of truth shared by the batch and single-case templates.
"""
from __future__ import annotations

import pytest

from vetpathdb.prompts.loader import render_prompt, _read_prompt_file

# --- Golden canonical prompts (the validated semantic.py wording) ---

_BATCH_GOLDEN = '''You are a veterinary pathology case search assistant. Given a search query and a set of case details, analyze which cases are most relevant to the query.

Search Query: {query}

Case Details:
{cases}

Rate each case's relevance to the query using this scoring system:
- 0.0 – Case unrelated to query intent
- 0.1 – Shares only generic terms
- 0.2 – Same broad category, different context
- 0.3 – Addresses part of query, misses main intent
- 0.4 – Related topic but different focus
- 0.5 – Partially addresses query intent
- 0.6 – Addresses main query intent, lacks some specifics
- 0.7 – Matches query intent, minor contextual differences
- 0.8 – Strongly matches query intent and context
- 0.9 – Near-complete match, one minor detail differs
- 1.0 – All query criteria exactly match

Return your analysis as a JSON array of objects, with structure as follows:
[
  {{
    "case_id": "ID_HERE",
    "score": 0.0,
    "reasoning": "REASON_HERE"
  }}
]

Reasoning must be brief (one line) and cite specific details from the case that match or don't match the query (e.g., "Canine lymphoma but B-cell not T-cell" or "Same breed and tumor type, different age"). Never describe the match quality abstractly - only state what specifically matched and what didn't.
Output just valid json, NEVER use ```json markdown tag

IMPORTANT: Your response MUST be valid JSON. Double-check your output format.
Sort by score in descending order.'''

_SINGLE_GOLDEN = '''You are a veterinary pathology case search assistant. Given a search query and a single case, analyze how relevant the case is to the query.

Search Query: {query}

Case Details:
{case}

Rate this case's relevance to the query using this scoring system:
- 0.0 – Case unrelated to query intent
- 0.1 – Shares only generic terms
- 0.2 – Same broad category, different context
- 0.3 – Addresses part of query, misses main intent
- 0.4 – Related topic but different focus
- 0.5 – Partially addresses query intent
- 0.6 – Addresses main query intent, lacks some specifics
- 0.7 – Matches query intent, minor contextual differences
- 0.8 – Strongly matches query intent and context
- 0.9 – Near-complete match, one minor detail differs
- 1.0 – All query criteria exactly match

Return your analysis as a JSON object with the following structure:
{{
  "score": 0.0,
  "reasoning": "REASON_HERE"
}}

Reasoning must be brief (one line) and cite specific details from the case that match or don't match the query (e.g., "Canine lymphoma but B-cell not T-cell" or "Same breed and tumor type, different age"). Never describe the match quality abstractly - only state what specifically matched and what didn't.
Output just valid json, NEVER use ```json markdown tag

IMPORTANT: Your response MUST be valid JSON. Double-check your output format.'''


def test_batch_prompt_matches_golden():
    got = render_prompt("search/relevance_batch.txt", query="QQ", cases="CC")
    assert got == _BATCH_GOLDEN.format(query="QQ", cases="CC")


def test_single_prompt_matches_golden():
    got = render_prompt("search/relevance_single.txt", query="QQ", case="CC")
    assert got == _SINGLE_GOLDEN.format(query="QQ", case="CC")


def test_substitution_happened():
    got = render_prompt("search/relevance_batch.txt", query="MAST-CELL-Q", cases="CASE-XYZ")
    assert "MAST-CELL-Q" in got and "CASE-XYZ" in got
    assert "{query}" not in got and "{cases}" not in got and "{scale}" not in got


def test_json_braces_survived():
    got = render_prompt("search/relevance_batch.txt", query="q", cases="c")
    # Doubled braces in the template must collapse to a single literal JSON example.
    assert '"case_id": "ID_HERE"' in got
    assert "{{" not in got and "}}" not in got


def test_scale_is_single_source_of_truth():
    batch = render_prompt("search/relevance_batch.txt", query="q", cases="c")
    single = render_prompt("search/relevance_single.txt", query="q", case="c")
    scale = _read_prompt_file("fragments/relevance_scale.txt").strip()
    assert scale in batch
    assert scale in single


def test_missing_placeholder_raises():
    # A template needs {query}/{cases}; omitting them is a developer error → fail loud.
    with pytest.raises(KeyError):
        render_prompt("search/relevance_batch.txt")


def test_chat_prompt_injects_case_text():
    got = render_prompt("chat/consultant_system.txt", case_text="SENTINEL-CASE-TEXT")
    assert "SENTINEL-CASE-TEXT" in got
    assert "senior veterinary pathologist consultant" in got


def test_json_repair_prompt_loads():
    repair = render_prompt("extraction/json_repair_user.txt", error_msg="E", content="C")
    assert "E" in repair and "C" in repair and "{error_msg}" not in repair
