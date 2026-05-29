# Document Type Schemas

Each YAML file defines a document type for VetPathDB extraction.

## Included Examples (Veterinary Pathology)

| File | Code | Description |
|------|------|-------------|
| `surgical_pathology.yaml` | SP | Surgical biopsy and excision reports |
| `postmortem.yaml` | PM | Post-mortem / necropsy reports |
| `cytopathology.yaml` | CY | Cytology and fine-needle aspirate reports |
| `immunohistochemistry.yaml` | IH | IHC panel and staining reports |

### Report-metadata field naming

The bundled schemas use generic metadata field names — `accession_id` for
the internal tissue/block reference and `external_reference` for any
outside case number (submitting organisation, insurance claim, court
exhibit, etc.). Labs with specific conventions (e.g. forensic
pathology "exhibit number", hospital "MRN") can rename these via
their own schema YAML; the pipeline reads whatever the `schema:`
block defines.

## Creating Your Own

Copy an existing schema and modify it:

```bash
cp surgical_pathology.yaml my_document_type.yaml
```

A schema YAML has five top-level sections. The first four are required, `ui` is optional but needed if you want the dropdown to light up automatically for the new type:

```yaml
name: My Document Type          # Human-readable name
code: MT                        # Short code; surfaced as case_type on every ingested doc
description: What this type is  # Brief description

ui:                             # Optional — drives /api/schemas and the frontend
  icon: fa-notes-medical        #   Font Awesome class rendered in dropdowns
  label_plural: "MT Reports"    #   Plural label for the filter menu

detection_patterns:             # How to auto-detect this type
  filename: ["_MT_", "_MT."]    #   Case-insensitive substring match
  content: ["my document"]      #   Plain keyword match
  content_regex:                #   Optional — Python regex scored by create_type_matcher()
    - 'my\s*document\s*report'

schema: |                       # JSON schema for extraction (embedded as string)
  {
    "summary": "",
    "report_metadata": { ... },
    ...your fields here...
    "comment": "",
    "case_keywords": [],
    "rag_summary": ""
  }

enrichment:                     # Fields for search index enrichment
  fields:
    case_keywords:
      type: array
      description: "..."
    rag_summary:
      type: string
      description: "..."
  exclude_from_keywords:        # Metadata sections to exclude from keywords
    - report_metadata
```

### Case-ID formats

By default the pipeline uses the sanitized filename stem as the case ID
(`patient_smith.pdf` → `patient_smith`). This means any folder of PDFs
works out of the box.

Labs with structured archival IDs can point the pipeline at a regex
patterns file via `VETPATHDB_CASE_ID_PATTERNS=path/to/patterns.yaml`.
See `docs/examples/case_id_patterns_example.yaml` for a worked example
with a sample numbering scheme. The file format is documented in the
comments of `vetpathdb/prompts/case_id_patterns.yaml`.

Then run extraction:

```bash
vetpathdb extract-data --input-dir ./text \
  --schema vetpathdb/prompts/schemas/my_document_type.yaml \
  --endpoint http://localhost:8080/v1 --model your-model
```
