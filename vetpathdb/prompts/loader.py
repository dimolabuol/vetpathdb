"""Load and assemble prompts from schema definitions.

The template system separates the shared extraction rules (base_template.txt)
from the per-document-type JSON schemas (schemas/*.yaml). This module
assembles the two at runtime.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent
BASE_TEMPLATE_PATH = PROMPTS_DIR / "base_template.txt"
SCHEMAS_DIR = PROMPTS_DIR / "schemas"
CASE_ID_PATTERNS_PATH = PROMPTS_DIR / "case_id_patterns.yaml"


def load_schema(schema_path: str) -> dict:
    """Load and return a schema YAML definition."""
    with open(schema_path) as f:
        return yaml.safe_load(f)


def list_schemas() -> list[dict]:
    """List all available schema definitions.

    Returns a list of dicts with keys: path, name, code, description, ui.
    """
    schemas = []
    for p in sorted(SCHEMAS_DIR.glob("*.yaml")):
        defn = load_schema(p)
        schemas.append({
            "path": str(p),
            "name": defn.get("name", p.stem),
            "code": defn.get("code", ""),
            "description": defn.get("description", ""),
            "ui": defn.get("ui", {}),
        })
    return schemas


def find_schema_by_code(code: str) -> dict | None:
    """Find a schema by its 2+ letter code. Returns None if not registered."""
    code = code.upper()
    for p in sorted(SCHEMAS_DIR.glob("*.yaml")):
        defn = load_schema(p)
        if defn.get("code", "").upper() == code:
            defn["_path"] = str(p)
            return defn
    return None


def assemble_extraction_prompt(schema_path: str) -> str:
    """Assemble a full extraction prompt from base template + schema YAML.

    Reads the shared base template and substitutes the ``{schema}``
    placeholder with the JSON schema from the given YAML file.
    """
    with open(BASE_TEMPLATE_PATH) as f:
        template = f.read()
    defn = load_schema(schema_path)
    return template.replace("{schema}", defn["schema"])


# ---------------------------------------------------------------------------
# Generic prompt rendering (retrieval / chat / extraction prompts)
# ---------------------------------------------------------------------------

# Reusable fragments composed into prompt templates via {token} -> file
# contents, applied BEFORE str.format so the fragment bodies are never treated
# as format fields. Mirrors the {schema} substitution in
# assemble_extraction_prompt above.
_PROMPT_FRAGMENTS = {
    "scale": "fragments/relevance_scale.txt",
    "reasoning": "fragments/relevance_reasoning.txt",
    "json_guard": "fragments/json_guard.txt",
}


@lru_cache(maxsize=None)
def _read_prompt_file(rel_path: str) -> str:
    """Read a prompt template/fragment relative to the prompts dir (cached)."""
    return (PROMPTS_DIR / rel_path).read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs) -> str:
    """Render a prompt template by path relative to the prompts dir.

    Example::

        render_prompt("search/relevance_batch.txt", query=q, cases=c)

    Any ``{scale}`` / ``{reasoning}`` / ``{json_guard}`` tokens are first
    replaced with the corresponding shared fragment (single source of truth),
    then ``str.format(**kwargs)`` fills the remaining placeholders. Literal
    JSON braces in templates must be doubled (``{{ }}``). Raises ``KeyError``
    if the template needs a placeholder that ``kwargs`` does not supply (a
    developer error — fail loud).
    """
    template = _read_prompt_file(name)
    for token, frag_path in _PROMPT_FRAGMENTS.items():
        placeholder = "{" + token + "}"
        if placeholder in template:
            template = template.replace(placeholder, _read_prompt_file(frag_path).strip())
    return template.format(**kwargs)




# ---------------------------------------------------------------------------
# Form schema expansion
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Case-ID pattern configuration
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_case_id_patterns() -> list[dict]:
    """Return the list of case-ID regex patterns to try, in priority order.

    Reads from the path given by VETPATHDB_CASE_ID_PATTERNS if set, else
    from the bundled case_id_patterns.yaml. Returns an empty list if
    nothing is configured — callers should fall back to hardcoded defaults.
    """
    override = os.environ.get("VETPATHDB_CASE_ID_PATTERNS")
    path = Path(override) if override else CASE_ID_PATTERNS_PATH
    if not path.exists():
        return []
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    patterns = doc.get("patterns", [])
    # Pre-compile regexes for speed
    for p in patterns:
        p["_compiled"] = re.compile(p["regex"])
        if "exclude" in p:
            p["_exclude_compiled"] = re.compile(p["exclude"])
        if "skip_if_matches" in p:
            p["_skip_compiled"] = re.compile(p["skip_if_matches"])
        if "standardize" in p:
            src, dst = p["standardize"].split("->", 1)
            p["_standardize_compiled"] = (re.compile(src), dst)
    return patterns
