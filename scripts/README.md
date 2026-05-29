# Admin Scripts

Utility scripts for database administration. These are **not** part of
the main ingestion pipeline (which lives in `vetpathdb/pipeline/` and is
accessed via `vetpathdb` CLI commands).

| Script | Purpose |
|--------|---------|
| `backup_restore.py` | MongoDB + vector-store backup and restore |

To load the bundled 20-case demo into a fresh install, use the CLI
instead of any script here:

```bash
vetpathdb load-examples
```
