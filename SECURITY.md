# Security Policy

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue.
Use GitHub's **"Report a vulnerability"** (Security → Advisories) on
<https://github.com/dimolabuol/vetpathdb>, or email the corresponding author
(see `CITATION.cff`). We aim to acknowledge reports within a few working days.

## Deployment security model

VetPathDB is research software intended to run on **trusted, local
infrastructure**. Please be aware:

- **No built-in authentication or authorization.** Every endpoint (web UI,
  REST API, and the optional `/mcp` server) is unauthenticated. Anyone who can
  reach the port has full read access to the database.
- **Bind to loopback by default.** The server binds to `127.0.0.1` unless you
  set `VETPATHDB_HOST`; the Docker image publishes only to `127.0.0.1`. Do not
  expose it directly to a network.
- **For multi-user or networked deployments,** place VetPathDB behind a reverse
  proxy that enforces authentication and TLS. The `docs/SETUP_GUIDE.md` proxy
  recipe is a starting point, not a complete hardening guide.
- **Bring-your-own-data responsibility.** Real pathology reports may contain
  personal data subject to GDPR or equivalent regulation. You are responsible
  for the legal basis, access controls, and data protection of any real data
  you ingest. The shipped demo dataset is fully synthetic.
- **Untrusted input.** Content extracted from PDFs by the LLM is rendered in
  the web UI; treat ingested documents as untrusted and review the source
  report (linked in the UI) before relying on any extracted field.
