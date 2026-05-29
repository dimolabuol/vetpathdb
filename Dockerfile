FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for the app
RUN useradd --create-home --shell /bin/bash --uid 1000 vetpathdb

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY vetpathdb/ vetpathdb/
COPY static/ static/
COPY docker-entrypoint.sh ./

# [pdf] enables the in-container ingestion pipeline (vetpathdb pipeline /
# extract-text); [mcp] enables the /mcp server. Both are documented features
# of the shipped image.
RUN pip install --no-cache-dir ".[pdf,mcp]" && \
    chmod +x docker-entrypoint.sh

# Ensure app-writable directories and transfer ownership to non-root user.
# certs/ exists so users can bind-mount their own key.pem + cert.pem to
# opt into HTTPS; with no certs present the server runs plain HTTP.
RUN mkdir -p /app/cases_vectorstore /app/pdf /app/certs && \
    chown -R vetpathdb:vetpathdb /app

USER vetpathdb

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fs http://localhost:8080/ || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
