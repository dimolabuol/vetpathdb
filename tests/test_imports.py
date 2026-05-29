"""Smoke test: top-level production modules import cleanly.

Catches the class of regression where a deleted module is still
referenced via a from-import. The rest of the test suite uses small
stub fixtures and never transitively imports `vetpathdb.app` or
`vetpathdb.mcp.server`, so a stale `from vetpathdb.utils import …` would
ship green through `pytest tests/` but crash the server at startup.

Each test uses ``pytest.importorskip`` to allow running in environments
where the heavier optional dependencies (chromadb, sentence-transformers,
fastmcp) are not installed. CI installs ``.[dev,mcp]`` so all of these
are available there and the smoke test actually runs.
"""
from __future__ import annotations

import pytest


def test_app_module_loads():
    pytest.importorskip("chromadb")
    pytest.importorskip("sentence_transformers")
    import vetpathdb.app  # noqa: F401


def test_mcp_server_module_loads():
    pytest.importorskip("fastmcp")
    pytest.importorskip("chromadb")
    pytest.importorskip("sentence_transformers")
    import vetpathdb.mcp.server  # noqa: F401


def test_search_modules_load():
    pytest.importorskip("chromadb")
    pytest.importorskip("sentence_transformers")
    import vetpathdb.search.semantic  # noqa: F401
    import vetpathdb.search.vectordb  # noqa: F401


def test_pipeline_modules_load():
    # extract_text optionally pulls in pytesseract for OCR; skip if absent.
    pytest.importorskip("pytesseract")
    import vetpathdb.pipeline.extract_text  # noqa: F401


def test_pipeline_core_modules_load():
    # These have no heavy optional deps and must always import cleanly.
    import vetpathdb.pipeline.extract_data  # noqa: F401
    import vetpathdb.pipeline.load  # noqa: F401
    import vetpathdb.pipeline._utils  # noqa: F401


def test_storage_and_api_modules_load():
    import vetpathdb.storage.cases  # noqa: F401
    import vetpathdb.storage.analysis  # noqa: F401
    import vetpathdb.api.analysis  # noqa: F401


