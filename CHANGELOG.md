# Changelog

## v1.0.0

Initial public release.

### Features

- Schema-driven case-type system with four reference schemas (surgical
  pathology, immunohistochemistry, post-mortem, cytopathology); add new
  types by dropping a YAML into `vetpathdb/prompts/schemas/`.
- LLM extraction pipeline with three deployment tiers documented in
  `docs/LLM_SETUP.md` (Ollama for laptops, llama-server for single-GPU
  labs, vLLM/SGLang for production).
- ChromaDB-backed semantic search with optional LLM re-ranking and an
  11-point relevance rubric (`vetpathdb/prompts/fragments/relevance_scale.txt`).
- Model Context Protocol (MCP) server exposing eleven search/aggregation
  tools for AI-agent integration.
- Docker Compose deployment with optional bundled-Ollama profile
  (`docker compose --profile with-llm up -d`).
- Plain HTTP on port 8080 by default (demo 8081); HTTPS on 9443/9444 is
  opt-in (drop `certs/key.pem` + `certs/cert.pem`). `VETPATHDB_PORT` overrides.
- All LLM prompts externalized under `vetpathdb/prompts/` and loaded via
  `prompts.loader.render_prompt` (the relevance rubric is a single shared
  fragment).
- `vetpathdb doctor` self-check for Python, sqlite3, MongoDB, LLM
  endpoint, vector store, and FastMCP.
- 20 fully synthetic demo cases auto-loaded on first boot.
