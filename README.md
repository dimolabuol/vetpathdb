# VetPathDB

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://github.com/dimolabuol/vetpathdb/actions/workflows/tests.yml/badge.svg)](https://github.com/dimolabuol/vetpathdb/actions)

An open-source platform for extracting structured data from veterinary pathology PDF reports using large language models, with AI-powered semantic search for case retrieval.

## Overview

VetPathDB combines LLM-based information extraction with vector similarity search to transform unstructured pathology reports into a searchable, structured database. Case types are driven entirely by schema YAML files under `vetpathdb/prompts/schemas/`; the repo ships four reference schemas (surgical pathology, immunohistochemistry, post-mortem, cytopathology), and each lab can add, rename, or replace these with its own type codes, case-ID formats, and form layouts.

**Key capabilities:**

- **LLM Extraction** -- Extracts 40+ structured fields from PDF reports using customisable prompts
- **Semantic Search** -- Natural language case retrieval via sentence-transformer embeddings (ChromaDB)
- **AI-Enhanced Search** -- Optional LLM re-ranking of retrieval results for clinical relevance
- **Web Interface** -- Browser-based search, case viewer, and analytics dashboard
- **MCP Integration** -- Model Context Protocol server for AI agent workflows

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/dimolabuol/vetpathdb.git
cd vetpathdb
docker compose up -d
```

20 example cases load automatically on first boot. Open <http://localhost:8080>.

Basic keyword search works out of the box. For semantic / AI-enhanced search, you need an LLM endpoint — see [docs/LLM_SETUP.md](docs/LLM_SETUP.md).

### With your own data, bundled LLM (no setup)

```bash
docker compose --profile with-llm up -d
```

Brings up MongoDB, VetPathDB, **and** an Ollama container preconfigured with Qwen3-4B. The model (~2.5 GB) downloads on first boot. Drop PDFs into `./pdf/` and extract via `docker compose exec vetpathdb vetpathdb pipeline …`. For GPU acceleration, larger models, or production throughput, see [docs/LLM_SETUP.md](docs/LLM_SETUP.md).

### Local Python install

```bash
git clone https://github.com/dimolabuol/vetpathdb.git
cd vetpathdb
pip install -e ".[pdf]"   # [pdf] adds the PDF→text extraction deps; drop it
                          # for a search-only install with no ingestion

vetpathdb doctor          # check dependencies
vetpathdb load-examples   # load 20 demo cases
vetpathdb serve
```

Open <http://localhost:8080>.

> **TLS:** the server runs plain HTTP by default. To enable HTTPS, drop your own `certs/key.pem` + `certs/cert.pem` into the repo root (or bind-mount them into `/app/certs/` in the container) — the server picks them up automatically at startup.

### Prerequisites

- Python 3.11+
- MongoDB 6.0+
- poppler-utils and tesseract-ocr (for PDF extraction; install the `[pdf]` extra for the Python deps)
- An OpenAI-compatible LLM endpoint (for data extraction and semantic search; not needed for keyword-search demo)

## Architecture

```
vetpathdb/                     Python package
  app.py                       FastAPI application server
  config.py                    AI/ML configuration (env var overrides)
  models.py                    Pydantic data models
  search/
    semantic.py                Embedding + LLM search pipeline
    vectordb.py                ChromaDB vector store management
    query.py                   MongoDB query builder
  storage/
    cases.py                   Case data access layer
    analysis.py                Statistical analysis
  api/
    analysis.py                Analysis API endpoints
  mcp/
    server.py                  MCP tool server (FastMCP)
  pipeline/                    Data ingestion pipeline
    extract_text.py            PDF to text conversion
    extract_data.py            LLM structured extraction
    load.py                    MongoDB data loading
  prompts/
    base_template.txt          Shared extraction rules
    schemas/                   Document type definitions (YAML)
    case_id_patterns.yaml      Default case-ID regex registry
    loader.py                  YAML schema loader / prompt assembler
  cli.py                       Unified command-line interface

scripts/                       Admin utilities (demo, backup)
static/                        Frontend (HTML/JS/CSS)
```

## Configuration

All settings can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `AI_LLM_BASE_URL` | `http://localhost:8080/v1` | LLM API endpoint |
| `AI_LLM_MODEL` | `local-model` | LLM model name |
| `AI_EMBEDDING_MODEL` | `Alibaba-NLP/gte-Qwen2-1.5B-instruct` | Embedding model |

## Data Pipeline

The extraction pipeline converts PDFs to structured JSON via LLM.

### Full pipeline (one command)

```bash
vetpathdb pipeline \
  --pdf-dir /path/to/pdfs \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint http://localhost:8080/v1 \
  --model llama-3.3-70b
```

### Step by step

```bash
# 1. Extract text from PDFs
vetpathdb extract-text --pdf-dir /path/to/pdfs --output-dir /path/to/text

# 2. Extract structured data via LLM
vetpathdb extract-data --input-dir /path/to/text \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint http://localhost:8080/v1 --model llama-3.3-70b

# 3. Load into database
vetpathdb load --input-dir /path/to/text

# 4. Build search index
vetpathdb index
```

### Custom document types

Define your own extraction schema — see
[`vetpathdb/prompts/schemas/`](vetpathdb/prompts/schemas/) for examples and
instructions.

## MCP Integration

VetPathDB exposes an MCP server for AI agent integration:

```json
{
  "mcpServers": {
    "vetpathdb": {
      "command": "mcp-client-http",
      "args": ["http://localhost:8080/mcp/"]
    }
  }
}
```

Eleven tools are exposed: `semantic_search`, `search_cases`,
`get_case_details`, `list_cases_by_criteria`, `custom_aggregation`,
`get_basic_stats`, `get_yearly_stats`, `get_date_range_info`,
`get_database_schema`, `get_field_values`, `explore_field_relationships`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

VetPathDB has **no built-in authentication** and is intended to run on
trusted, local infrastructure (it binds to `127.0.0.1` by default). See
[SECURITY.md](SECURITY.md) for the deployment security model and how to
report a vulnerability.

## License

- **Code** — [MIT License](LICENSE).
- **Synthetic demo dataset** (`vetpathdb/examples/demo_cases.json`) —
  [Creative Commons Attribution 4.0 (CC BY 4.0)](LICENSE-DATA). The demo cases
  are fully synthetic and contain no real patient or personnel information.

## Citation

If you use VetPathDB in your research, please cite the project — see
[CITATION.cff](CITATION.cff). A pinned, Zenodo-archived release accompanies the
associated publication.

## Ethics & data

This repository ships only synthetic demo data and contains no real cases.
Users bringing their own data are responsible for obtaining any ethics
approvals and meeting any data-protection obligations that apply in their
jurisdiction.
