"""Shared utilities for the VetPathDB ingestion pipeline."""

import os
import re
from datetime import datetime

try:
    from colorama import Fore, Style
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


# ---------------------------------------------------------------------------
# Logging helpers (coloured when colorama is available)
# ---------------------------------------------------------------------------

def get_timestamp():
    return datetime.now().strftime("%H:%M:%S")

def print_info(message, debug=False, debug_mode=False):
    if debug and not debug_mode:
        return
    if _HAS_COLOR:
        print(f"{Fore.WHITE}[{get_timestamp()}]{Style.RESET_ALL} {Fore.CYAN}[INFO]{Style.RESET_ALL} {message}")
    else:
        print(f"[{get_timestamp()}] [INFO] {message}")

def print_success(message, debug=False, debug_mode=False):
    if debug and not debug_mode:
        return
    if _HAS_COLOR:
        print(f"{Fore.WHITE}[{get_timestamp()}]{Style.RESET_ALL} {Fore.GREEN}[SUCCESS]{Style.RESET_ALL} {message}")
    else:
        print(f"[{get_timestamp()}] [SUCCESS] {message}")

def print_error(message, debug=False, debug_mode=False):
    if debug and not debug_mode:
        return
    if _HAS_COLOR:
        print(f"{Fore.WHITE}[{get_timestamp()}]{Style.RESET_ALL} {Fore.RED}[ERROR]{Style.RESET_ALL} {message}")
    else:
        print(f"[{get_timestamp()}] [ERROR] {message}")

def print_debug(message, debug_mode=False):
    if debug_mode:
        if _HAS_COLOR:
            print(f"{Fore.WHITE}[{get_timestamp()}]{Style.RESET_ALL} {Fore.MAGENTA}[DEBUG]{Style.RESET_ALL} {message}")
        else:
            print(f"[{get_timestamp()}] [DEBUG] {message}")


# ---------------------------------------------------------------------------
# Case ID extraction — configurable via case_id_patterns.yaml
# ---------------------------------------------------------------------------

def _configured_patterns():
    """Load configured patterns from the registry. Returns an empty list by
    default — the extractor then falls back to using the filename stem as
    the case ID. Labs with real archival schemes set
    ``VETPATHDB_CASE_ID_PATTERNS`` to point at their pattern file.
    """
    try:
        from vetpathdb.prompts.loader import load_case_id_patterns
        return load_case_id_patterns()
    except Exception:
        return []


_SANITIZE_RE = re.compile(r"[^\w\-]+")


def _sanitize_to_id(text: str) -> str:
    """Collapse any non-word characters to underscores so the result is safe
    as a filename/directory fragment. Empty input becomes ``unknown``."""
    cleaned = _SANITIZE_RE.sub("_", text).strip("_")
    return cleaned or "unknown"


def _apply_standardize(text: str, pattern: dict) -> str:
    if "_standardize_compiled" in pattern:
        text = text.replace(" ", "")
        src_re, repl = pattern["_standardize_compiled"]
        return src_re.sub(repl, text)
    return text


def _match_pattern(text: str, pattern: dict) -> str | None:
    """Try a single pattern against text. Returns the matched ID or None."""
    candidate = _apply_standardize(text, pattern)
    if "_skip_compiled" in pattern and pattern["_skip_compiled"].search(candidate):
        return None
    for match in pattern["_compiled"].finditer(candidate):
        hit = match.group(0)
        # Reject nested IDs (an ID with an extra trailing segment) when an exclude regex is set.
        if "_exclude_compiled" in pattern and pattern["_exclude_compiled"].search(candidate):
            continue
        return hit
    return None


def extract_case_id_from_name_or_path(file_path: str) -> str:
    """Extract a case ID from a file path.

    Tries each configured regex pattern (from
    ``vetpathdb/prompts/case_id_patterns.yaml`` or a file named by the
    ``VETPATHDB_CASE_ID_PATTERNS`` env var) against the filename first,
    then each parent directory in reverse. The first pattern to match wins.

    If no pattern matches *or* no patterns are configured (the default),
    falls back to the sanitized filename stem. This means every PDF always
    produces a usable case ID; the pipeline never silently skips files for
    want of a matching filename convention.

    Args:
        file_path: Full path to a file.

    Returns:
        Extracted case ID string. Never returns ``None``.
    """
    path_parts = file_path.split(os.path.sep)
    patterns = _configured_patterns()

    if patterns:
        candidates = [path_parts[-1]] + list(reversed(path_parts[:-1]))
        for part in candidates:
            for pattern in patterns:
                hit = _match_pattern(part, pattern)
                if hit:
                    return hit

    # Fallback: use the filename stem, sanitized to be filesystem-safe.
    stem = os.path.splitext(path_parts[-1])[0] if path_parts else ""
    return _sanitize_to_id(stem)


def is_valid_case_id(case_id) -> bool:
    """Return True if ``case_id`` is non-empty and either matches a
    configured pattern or is a well-formed sanitized identifier.

    With no patterns configured, any non-empty sanitized string is valid —
    this matches the new default behaviour where filename stems are
    accepted as case IDs.
    """
    if case_id is None:
        return False
    text = str(case_id)
    if not text:
        return False
    patterns = _configured_patterns()
    if patterns:
        for pattern in patterns:
            candidate = _apply_standardize(text, pattern)
            if pattern["_compiled"].fullmatch(candidate):
                return True
        return False
    # Permissive mode: non-empty sanitized ID is valid.
    return _sanitize_to_id(text) == text


def detect_case_id_format(case_id) -> str:
    """Return the configured pattern name that matches, or 'filename' when
    no patterns are configured, or 'unknown' when patterns are configured
    but none match.
    """
    if case_id is None:
        return "unknown"
    text = str(case_id)
    patterns = _configured_patterns()
    if not patterns:
        return "filename"
    for pattern in patterns:
        candidate = _apply_standardize(text, pattern)
        if pattern["_compiled"].fullmatch(candidate):
            return pattern["name"]
    return "unknown"
