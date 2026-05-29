# LLM Setup Guide

VetPathDB needs an OpenAI-compatible `/v1/chat/completions` endpoint to
extract structured data from PDF reports. This guide walks through the
three supported tiers, from "laptop demo in one command" to
"production-grade extraction over thousands of PDFs". Pick the tier
that matches your hardware and scale; the app itself is identical in
all three — only the inference server differs.

## Which tier should I use?

| Tier | Use case | Hardware | Inference server | Model | ~Throughput |
|------|----------|----------|------------------|-------|-------------|
| **A** | Demo / laptop | CPU, 8–16GB RAM | **Ollama** | Qwen3-4B Q4 | ~5–15 tok/s (CPU), 60+ tok/s (GPU) |
| **B** | Lab workstation | Single consumer GPU (≥24GB) | **llama.cpp (`llama-server`)** | Qwen3-30B-A3B Q4 / Llama-3.3-70B 4-bit | 40–120 tok/s |
| **C** | Production / many PDFs | Multi-GPU or H100 | **vLLM** or **SGLang** | Llama-3.3-70B / Qwen3.5-122B-A10B / Gemma-4-31B | 500–15,000 tok/s |

Rough rules of thumb (extracting ~2000 output tokens per report):
- Tier A on CPU: 2–5 minutes per report — OK for trying 10 PDFs, painful for 500.
- Tier A on GPU: ~30 seconds per report — fine for 100s.
- Tier B: 5–15 seconds per report — comfortable for 1000s.
- Tier C: sub-second per report at batch, suitable for any scale.

---

## Tier A — Bundled Ollama (easiest)

The repo ships with a ready-to-go Ollama sidecar as a Docker Compose profile.
This is the fastest way from `git clone` to a working extraction.

### Option 1 — Docker Compose (recommended)

```bash
git clone https://github.com/dimolabuol/vetpathdb.git
cd vetpathdb
docker compose --profile with-llm up -d
```

That's it. The compose file brings up MongoDB, Ollama, and VetPathDB, wires
them together, and on first boot Ollama downloads the default model
(`qwen3:4b-instruct-q4_K_M`, ~2.5GB). The entrypoint auto-detects the
sidecar and sets `AI_LLM_BASE_URL` for you.

Open <http://localhost:8080>. Drop PDFs into `./pdf/` on the host and
run the extraction pipeline:

```bash
docker compose exec vetpathdb \
  vetpathdb pipeline --pdf-dir /app/pdf \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint http://ollama:11434/v1 \
  --model qwen3:4b-instruct-q4_K_M
```

### Enabling GPU acceleration

By default the bundled Ollama runs on CPU. To get real throughput you need
nvidia-container-toolkit installed on the host, then uncomment the GPU
block in `docker-compose.yml`:

```yaml
  ollama:
    # ... existing config ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Restart: `docker compose --profile with-llm up -d`. Ollama will pick up
the GPU automatically; no model config change needed.

### Using a bigger model

Qwen3-4B is a deliberately small default so the bundle works on laptops.
If you have a 24GB+ GPU, switch to Qwen3-30B-A3B (MoE, 3B active) for
much higher extraction quality with similar throughput:

```bash
# Override the model via environment variable
AI_LLM_MODEL=qwen3:30b-a3b-instruct-q4_K_M docker compose --profile with-llm up -d
```

The entrypoint pulls whichever model you set. Other good choices on
Ollama: `llama3.3:70b-instruct-q4_K_M` (48GB GPU),
`qwen3:14b-instruct-q4_K_M` (single 16GB GPU).

### Option 2 — Bare-metal Ollama (no Docker)

If you don't want Docker:

```bash
# Install
curl -fsSL https://ollama.com/install.sh | sh

# Pull and run a model
ollama pull qwen3:4b-instruct-q4_K_M
ollama serve &   # runs on :11434 by default

# Point VetPathDB at it
export AI_LLM_BASE_URL=http://localhost:11434/v1
export AI_LLM_MODEL=qwen3:4b-instruct-q4_K_M

# Run extraction normally
vetpathdb pipeline --pdf-dir /path/to/pdfs \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint $AI_LLM_BASE_URL --model $AI_LLM_MODEL
```

### Caveats for Tier A

- **Throughput is the catch.** Ollama serialises requests per model by
  default. For bulk extraction over hundreds of PDFs, consider Tier B.
- **JSON reliability.** Small models (4B) sometimes emit malformed JSON
  that triggers the repair loop in `extract_data.py`. If you see frequent
  `.malformed` files, either drop to a smaller field set or move to Tier
  B with a larger model.

---

## Tier B — Single consumer GPU with llama-server

For a lab running extractions on their own 3090/4090/A6000, `llama-server`
from the llama.cpp project is the sweet spot: single binary, explicit
tuning knobs, reproducible (you can pin the exact GGUF blob by SHA), and
exposes an OpenAI-compatible `/v1` endpoint. This matches the closest
medical-domain precedent: the LLM-AIx oncology extraction pipeline
([Nature npj Precision Oncology, 2025](https://www.nature.com/articles/s41698-025-01103-4))
runs Llama-3.1 70B 4-bit GGUF on an A6000 at ~100 reports/hour.

### Install

Download a release binary from
[github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases),
or build from source. Most modern Linux/macOS hosts can use the
pre-built CUDA binaries directly.

### Recommended models

| GPU VRAM | Model | Expected quality |
|----------|-------|-----------------|
| 24GB (3090/4090) | **Qwen3-30B-A3B-Instruct Q4_K_M** (~18.6GB) | Very good; MoE with only 3B active parameters → fast |
| 24GB | Qwen3-14B-Instruct Q6_K (~12GB) | Good; dense, safer on smaller contexts |
| 48GB (A6000/A100) | **Llama-3.3-70B-Instruct Q4_K_M** (~43GB) | Matches LLM-AIx precedent |
| 48GB | Qwen3.5-122B-A10B AWQ (~55GB) | Leading open-weight extraction |

Pull a GGUF from HuggingFace (e.g. `bartowski/Qwen3-30B-A3B-Instruct-GGUF`)
and **record the SHA256** for reproducibility — this is essential if you
intend to publish or re-run later.

### Run

```bash
./llama-server \
    -m /path/to/Qwen3-30B-A3B-Instruct-Q4_K_M.gguf \
    --host 0.0.0.0 \
    --port 8080 \
    --ctx-size 16384 \
    --parallel 4 \
    --cont-batching \
    --n-gpu-layers 99 \
    --jinja
```

Flag explanations:
- `--ctx-size 16384`: enough for most pathology reports plus the ~3k-token
  prompt template. Raise if your reports are very long.
- `--parallel 4`: number of concurrent slots. Match to VetPathDB's
  `AI_MAX_BATCH_CONCURRENCY` (default 25) divided by expected queue depth.
- `--cont-batching`: continuous batching across slots for higher throughput.
- `--n-gpu-layers 99`: push all layers to GPU (use lower value if not all fit).
- `--jinja`: enable Jinja chat templating (required for recent Qwen/Llama models).

### Point VetPathDB at it

```bash
export AI_LLM_BASE_URL=http://localhost:8080/v1
export AI_LLM_MODEL=qwen3-30b-a3b-instruct  # whatever llama-server reports at /v1/models

vetpathdb pipeline --pdf-dir /path/to/pdfs \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint $AI_LLM_BASE_URL --model $AI_LLM_MODEL
```

### Reproducibility checklist

For publication-grade runs, record all of:
- `llama-server --version` (pins the llama.cpp build)
- GGUF file SHA256
- Exact command line (ctx-size, parallel, etc.)
- `vetpathdb --version` and the git SHA of the schema YAML used

---

## Tier C — Production (vLLM or SGLang)

For extracting thousands of PDFs, or running continuously in a clinical
deployment, a purpose-built inference engine is the right answer. Both
vLLM and SGLang are drop-in OpenAI-compatible servers with continuous
batching and constrained-decoding support (XGrammar); SGLang additionally
has RadixAttention for shared-prefix workloads, giving it a measurable
advantage on repeated-schema extraction like this pipeline.

### Reproducing the paper with vLLM

Four open-weight models cover the paper's benchmark set. Pick the one
that fits your hardware — VetPathDB doesn't care which, the
`/v1/chat/completions` API is identical.

| Model | Hugging Face | Typical fit |
|---|---|---|
| Llama-3.3-70B-Instruct (Meta, dense, 70B) | `meta-llama/Llama-3.3-70B-Instruct` | 2× 80 GB bf16; 1× 80 GB FP8 |
| Gemma-4-31B-it (Google, dense, 31B) | `google/gemma-4-31B-it` | 1× 80 GB bf16; 1× 48 GB FP8 |
| Qwen3.5-122B-A10B (Alibaba, MoE 122B / 10B active) | `Qwen/Qwen3.5-122B-A10B-FP8` | 1× 80 GB FP8 |
| Qwen3.6-27B (Alibaba, dense, 27B + vision) | `Qwen/Qwen3.6-27B-FP8` | 1× 48 GB FP8 |

Minimal `vllm serve` (only the model id changes between rows):

```bash
pip install vllm

vllm serve <MODEL_ID> \
    --port 8080 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.90
```

For multi-GPU setups add `--tensor-parallel-size N`. FP8/AWQ are inferred
from `-FP8`/`-AWQ` repo suffixes; pass `--quantization` explicitly only
when loading a base bf16 repo with on-the-fly quantisation.

### SGLang (fastest for repeated-schema extraction)

SGLang shares vLLM's API, so swap in `python -m sglang.launch_server
--model-path <MODEL_ID> --port 8080 --context-length 16384` and the rest
of the pipeline is unchanged.

### Point VetPathDB at it

Same as Tier B — set `AI_LLM_BASE_URL` and `AI_LLM_MODEL`, run the
pipeline. The extraction code is endpoint-agnostic.

### XGrammar constrained decoding (not wired yet)

vLLM and SGLang both support `response_format={"type": "json_schema", ...}`
which guarantees the model cannot emit malformed JSON, eliminating the
repair loop in `extract_data.py`. VetPathDB does not yet send this
parameter — adding it is a planned follow-up that requires the
per-schema `json_schema:` block to be authored in each YAML. Until then,
Tier C deployments get all the throughput benefit but still rely on
retry-on-malformed.

---

## Using a different embedding model

The semantic-search index is built with a sentence-transformer embedding
model (separate from the LLM used for extraction). The shipped default is
`Alibaba-NLP/gte-Qwen2-1.5B-instruct`, which expects a specific
instruction-prefixed query format. To swap it you must both (a) change
the model and (b) set the correct prompt convention for the new family,
then rebuild the Chroma index.

Common embedding families and their expected query prompt:

| Family | Example model | `AI_EMBEDDING_QUERY_PROMPT` |
|--------|---------------|----------------------------|
| Qwen `gte` (default) | `Alibaba-NLP/gte-Qwen2-1.5B-instruct` | `"Instruct: Given a vet pathology cases search query, retrieve relevant cases that match the query\nQuery: "` |
| BGE | `BAAI/bge-large-en-v1.5` | `""` (empty — BGE uses no prefix) |
| E5 | `intfloat/e5-large-v2` | `"query: "` |
| MiniLM / generic | `sentence-transformers/all-MiniLM-L6-v2` | `""` |
| Nomic embed | `nomic-ai/nomic-embed-text-v1.5` | `"search_query: "` |

Example: switching to BGE-large:

```bash
export AI_EMBEDDING_MODEL="BAAI/bge-large-en-v1.5"
export AI_EMBEDDING_QUERY_PROMPT=""     # BGE needs no query-instruction prefix
rm -rf cases_vectorstore                # old index is dimension-mismatched
vetpathdb index                         # rebuild from scratch
```

Embedding dimension and max-sequence-length may also differ; set
`AI_MAX_SEQ_LENGTH` accordingly (8192 for Qwen gte, 512 for BGE/MiniLM,
1024 for E5).

**You must reindex after switching** — Chroma stores vectors of a fixed
dimension, and mixing models is a silent quality failure rather than a
loud error.

---

## Verifying your setup

### 1. The LLM endpoint responds

```bash
curl http://localhost:8080/v1/models
```

Should return a JSON list including the model you started. If this fails,
the rest won't work — fix connectivity first.

### 2. `vetpathdb doctor`

```bash
vetpathdb doctor
```

Reports status of every required service, including the LLM endpoint. A
green "LLM endpoint: ok" means the app can reach it. (The doctor does
not yet detect *which* server flavour or which features are supported
— that's a planned improvement.)

### 3. One-PDF smoke test

Drop a single PDF into a test directory and run the pipeline against it.
This catches "everything is reachable but the model emits garbage" cases
before you commit hours to a batch run.

```bash
mkdir -p /tmp/smoke && cp /path/to/one.pdf /tmp/smoke/
vetpathdb pipeline --pdf-dir /tmp/smoke \
  --schema vetpathdb/prompts/schemas/surgical_pathology.yaml \
  --endpoint $AI_LLM_BASE_URL --model $AI_LLM_MODEL
```

Expected output: one `.json` file in `/tmp/smoke/<case_id>/`, parseable,
with `report_metadata.report_type == "SP"`.

---

## Environment variables

The app reads these at startup (see `vetpathdb/config.py` for defaults):

| Variable | Default | What it does |
|----------|---------|--------------|
| `AI_LLM_BASE_URL` | `http://localhost:8080/v1` | OpenAI-compatible endpoint |
| `AI_LLM_MODEL` | `local-model` | Model name sent in the `model:` field of chat requests |
| `AI_LLM_TIMEOUT` | `300` | Per-request timeout in seconds |
| `AI_MAX_BATCH_CONCURRENCY` | `25` | Max concurrent LLM calls per task |
| `AI_MAX_RETRIES` | `3` | Retries on transient failures (429, 5xx) |
| `AI_GLOBAL_MAX_LLM_REQUESTS` | `50` | Global LLM concurrency cap across all tasks |
| `AI_CIRCUIT_BREAKER_THRESHOLD` | `10` | Consecutive errors before pausing |
| `AI_CIRCUIT_BREAKER_COOLDOWN` | `5.0` | Pause duration in seconds |
| `AI_PDF_ROOT_PATH` | `./pdf` | On-disk root where PDFs are organised as `<root>/<case_id>/<file>.pdf`. Point at NFS / shared storage if needed. |
| `AI_MONGO_DB` | `cases` | MongoDB database name for all collections |
| `AI_COLLECTION_CASES` | `processed_cases` | Name of the main extracted-cases collection |
| `AI_EMBEDDING_QUERY_PROMPT` | *(Qwen-gte prefix)* | Instruction prefix for the embedding model — see "Using a different embedding model" above |

Inside Docker with the `with-llm` profile, the entrypoint auto-sets
`AI_LLM_BASE_URL=http://ollama:11434/v1` and picks a sensible default
`AI_LLM_MODEL`. Any value you set explicitly via environment wins over
the autodetection.

---

## Troubleshooting

### "LLM endpoint: not reachable" in `vetpathdb doctor`

- Check the server is actually listening: `ss -tlnp | grep 8080` (or
  whichever port).
- Check firewall / Docker network: from inside the app container, `curl
  $AI_LLM_BASE_URL/models`.
- Ollama listens on `:11434` by default, not `:8080` — make sure the
  port matches your endpoint variable.

### Many `.malformed` files during extraction

The LLM is emitting syntactically invalid JSON. Usually means the model
is too small for the schema complexity.

- Tier A with Qwen3-4B: try Qwen3-14B or switch to Tier B.
- Cut schema size: disable fields you don't need.
- Raise temperature → 0 and retry. Many serving stacks default to 0.8,
  which hurts structured extraction. The app sends `temperature: 0`
  already, but some frontends (LM Studio, webui) override this.

### Out of memory / CUDA OOM

- Pick a higher quantisation tier (Q4_K_M → Q3_K_M).
- Lower `--ctx-size` (but make sure it's still > prompt + max report size).
- Lower `--parallel` / `--n-gpu-layers`.
- Drop to a smaller model.

### Extraction runs forever

- Check Ollama didn't finish downloading: `docker compose logs ollama`.
- Drop `AI_MAX_BATCH_CONCURRENCY` — if the server can't handle 25 in-flight
  requests, they queue and time out in bursts.
- On CPU, 40-field extraction over a long pathology report genuinely takes
  2–5 minutes per case. This is normal for Tier A; it's a reason to move
  to Tier B.

### `docker compose --profile with-llm` hangs on first boot

Ollama is pulling the model. First pull is ~2.5GB for Qwen3-4B and
~18GB for Qwen3-30B-A3B. Follow progress: `docker compose logs -f ollama`.

---

## Further reading

- Inference engine landscape, 2026: [vLLM vs SGLang benchmarks (Spheron)](https://www.spheron.network/blog/vllm-vs-tensorrt-llm-vs-sglang-benchmarks/),
  [vLLM vs Ollama (Red Hat)](https://developers.redhat.com/articles/2025/08/08/ollama-vs-vllm-deep-dive-performance-benchmarking).
- Open-weight model rankings: [BenchLM 2026](https://benchlm.ai/blog/posts/best-open-source-llm).
- Structured output / constrained decoding: [XGrammar](https://github.com/mlc-ai/xgrammar),
  [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/).
- Closest medical precedent: [LLM-AIx oncology pipeline](https://pmc.ncbi.nlm.nih.gov/articles/PMC12443949/).
