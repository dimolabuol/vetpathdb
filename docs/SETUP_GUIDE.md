# VetPathDB Setup Guide

Complete installation and configuration guide for VetPathDB.

## System Requirements

### Hardware

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB+ recommended for embedding models
- **Storage**: 10GB+ for application and vector store
- **GPU**: Optional, improves embedding generation speed

### Software

- Python 3.11 or higher
- MongoDB 6.0 or higher
- poppler-utils (for pdftotext)
- tesseract-ocr (optional, for scanned PDFs)

## Installation

### 1. Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip \
  mongodb-org poppler-utils tesseract-ocr
```

**macOS:**
```bash
brew install python@3.11 mongodb-community poppler tesseract
```

**Fedora/RHEL:**
```bash
sudo dnf install python3.11 mongodb-org poppler-utils tesseract
```

### 2. Clone the Repository

```bash
git clone https://github.com/dimolabuol/vetpathdb.git
cd vetpathdb
```

### 3. Create Python Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -e ".[pdf]"   # [pdf] adds PDF→text ingestion deps (marker-pdf,
                          # pytesseract, …); omit for a search-only install.
                          # Add ,mcp to also enable the MCP server: ".[pdf,mcp]"
```

### 4. Start MongoDB

```bash
# Start MongoDB service
sudo systemctl start mongod
sudo systemctl enable mongod

# Verify connection
mongosh --eval "db.serverStatus()"
```

### 5. Configure Environment

Create a `.env` file (optional):

```bash
# LLM Configuration
AI_LLM_BASE_URL=http://localhost:8080/v1
AI_LLM_MODEL=your-model-name
AI_LLM_TIMEOUT=300

# MongoDB
MONGODB_URI=mongodb://localhost:27017

# Embedding Model
AI_EMBEDDING_MODEL=Alibaba-NLP/gte-Qwen2-1.5B-instruct
```

### 6. Start the Server

```bash
./run.sh
```

Or manually:
```bash
python -m vetpathdb serve
```

The server starts on (HTTP; ports become 9443/9444 when TLS certs are present):
- Production: <http://localhost:8080>
- Demo mode: <http://localhost:8081>

### Optional: HTTPS

The server uses HTTPS automatically if `certs/key.pem` and `certs/cert.pem`
exist in the working directory. Drop your own certs in (or generate a
self-signed pair with `openssl req -x509 -newkey rsa:4096 -keyout
certs/key.pem -out certs/cert.pem -days 365 -nodes -subj /CN=localhost`)
and restart. With no certs present the server runs plain HTTP.

## LLM Setup

VetPathDB requires an LLM for document extraction. Any OpenAI-compatible API works.

### Option 1: Local LLM (vLLM)

```bash
# Install vLLM
pip install vllm

# Start server
python -m vllm.entrypoints.openai.api_server \
  --model mistralai/Mistral-7B-Instruct-v0.2 \
  --port 8080
```

### Option 2: Local LLM (llama.cpp)

```bash
# Build llama.cpp with server
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make

# Download a model
./models/download-model.sh mistral-7b-instruct-v0.2.Q4_K_M.gguf

# Start server
./server -m models/mistral-7b-instruct-v0.2.Q4_K_M.gguf --port 8080
```

### Option 3: OpenAI API

Set your API key and endpoint:

```bash
AI_LLM_BASE_URL=https://api.openai.com/v1
AI_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

### Option 4: Azure OpenAI

```bash
AI_LLM_BASE_URL=https://your-resource.openai.azure.com
AI_LLM_MODEL=your-deployment-name
AZURE_OPENAI_API_KEY=...
```

## First-Time Configuration

Configure your LLM endpoint and MongoDB connection via environment variables
or a `.env` file (see step 5 above). Then start the server and open
<http://localhost:8080> in your browser.

## Running Modes

### Production Mode

```bash
./run.sh
# or
python -m vetpathdb serve
```

- Database: `cases`
- Port: 8080 (HTTP) / 9443 (HTTPS when certs present)
- Full AI model loading

### Demo Mode

```bash
./run.sh --demo-db
# or
python -m vetpathdb serve --demo-db
```

- Database: `cases_demo`
- Port: 8081 (HTTP) / 9444 (HTTPS when certs present)
- Separate data from production

### Skip Models (Fast Start)

```bash
./run.sh --skip-models
```

Skips loading embedding models for faster startup. Semantic search won't work.

### MCP Server

```bash
./run.sh --mcp
```

Enables the MCP server at `/mcp/` for AI agent integration.

## Directory Structure

```
vetpathdb/              # Main Python package
├── app.py              # FastAPI application
├── cli.py              # Unified CLI
├── config.py           # AI configuration
├── models.py           # Data models
├── search/             # Search pipeline
├── storage/            # Data access layer
├── api/                # API routes
├── mcp/                # MCP server integration
├── pipeline/           # PDF -> JSON ingestion pipeline
└── prompts/            # Schema YAMLs + prompt assembler
scripts/                # Admin utilities (demo, backup)
static/                 # Web UI assets
tests/                  # Test suite
docs/                   # Documentation
```

## Updating

### Pull Latest Changes

```bash
git pull origin main
pip install -e .
```

### Database Migrations

VetPathDB uses MongoDB and handles schema evolution automatically. Existing documents remain compatible.

## Backup and Restore

### MongoDB Backup

```bash
# Backup
mongodump --db cases --out ./backup/

# Restore
mongorestore --db cases ./backup/cases/
```

### Vector Store Backup

```bash
# Backup ChromaDB
cp -r cases_vectorstore/ ./backup/vectorstore/

# Restore
cp -r ./backup/vectorstore/ cases_vectorstore/
```

## Production Deployment

### Using systemd

Create `/etc/systemd/system/vetpathdb.service`:

```ini
[Unit]
Description=VetPathDB
After=network.target mongodb.service

[Service]
Type=simple
User=vetpathdb
WorkingDirectory=/opt/vetpathdb
ExecStart=/opt/vetpathdb/venv/bin/python -m vetpathdb serve
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable vetpathdb
sudo systemctl start vetpathdb
```

### Using PM2

```bash
npm install -g pm2
pm2 start "python -m vetpathdb" --name vetpathdb
pm2 save
pm2 startup
```

### Reverse Proxy (nginx)

> **⚠️ VetPathDB has no built-in authentication.** Exposing it on a network
> without an auth layer gives anyone who can reach it full read access to your
> database. The recipe below adds HTTP Basic auth as a minimum; use your
> institution's SSO/OAuth proxy where available. Keep the app bound to
> loopback (the default) so it is reachable *only* through the proxy.

```nginx
server {
    listen 443 ssl;
    server_name vetpathdb.example.com;

    ssl_certificate /etc/letsencrypt/live/vetpathdb.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vetpathdb.example.com/privkey.pem;

    location / {
        # Minimum bar: HTTP Basic auth. Create the file with:
        #   htpasswd -c /etc/nginx/.htpasswd <username>
        auth_basic           "VetPathDB";
        auth_basic_user_file /etc/nginx/.htpasswd;

        # Default app is plain HTTP on 8080. If you enabled TLS certs, use
        # proxy_pass https://127.0.0.1:9443; and add proxy_ssl_verify off;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Troubleshooting

### Server Won't Start

1. Check Python version: `python --version` (need 3.11+)
2. Check MongoDB: `mongosh --eval "db.serverStatus()"`
3. Check port availability: `netstat -tlnp | grep 8080`

Run `vetpathdb doctor` to check all dependencies in one go.

### ChromaDB sqlite3 Version Error

If you see `RuntimeError: Your system has an unsupported version of sqlite3. Chroma requires sqlite3 >= 3.35.0`, the system sqlite3 library is too old. This affects Ubuntu 20.04, RHEL 8, and other older distributions.

**Fix — install pysqlite3-binary and shim it:**

```bash
pip install pysqlite3-binary
```

Then add this to the top of your entry point (or set via `PYTHONSTARTUP`):

```python
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
```

**Or upgrade the system library:**

- Ubuntu 22.04+ / Debian 12+: already ships sqlite3 >= 3.37
- Ubuntu 20.04: `sudo apt install sqlite3 libsqlite3-dev` from a newer repo, or upgrade Python to a build with newer sqlite3 bundled (pyenv, conda, uv)
- Docker: the bundled `python:3.11-slim` image in this project already has a supported sqlite3 version

### LLM Connection Issues

1. Test endpoint manually:
   ```bash
   curl http://localhost:8080/v1/models
   ```
2. Check firewall settings
3. Verify model name is correct

### Slow Embedding Generation

1. Consider using GPU if available
2. Use a smaller embedding model
3. Use `--skip-models` for testing without search

### Memory Issues

1. Reduce embedding batch size
2. Use a smaller embedding model
3. Increase system swap space
