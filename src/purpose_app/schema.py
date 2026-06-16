"""Shared field schema loader used by both the backend and frontend."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ENV_SCHEMA_PATH = "PURPOSE_FIELD_SCHEMA"


def _default_schema_path() -> Path:
    """Use the schema file shipped with the package unless overridden."""
    return Path(__file__).with_name("field_schema.json")


def _resolve_schema_path() -> Path:
    """Allow deployments to point at custom schema files via env var."""
    override = os.getenv(_ENV_SCHEMA_PATH)
    if override:
        return Path(override)
    return _default_schema_path()


@lru_cache(maxsize=1)
def _load_schema() -> Dict[str, Any]:
    path = _resolve_schema_path()
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_field_schema() -> Dict[str, Any]:
    """Return the raw schema dictionary."""
    return _load_schema()


def get_field_config() -> List[Tuple[str, str, str]]:
    """Expose `(key, label, prompt)` triples for display prompts."""
    schema = _load_schema()
    return [(field["key"], field["label"], field["prompt"]) for field in schema.get("fields", [])]


def get_display_specs() -> Dict[str, Dict[str, Any]]:
    """Map field keys to their display options (type, empty text, etc.)."""
    schema = _load_schema()
    return {field["key"]: field.get("display", {}) for field in schema.get("fields", [])}


FIELD_CONFIG = get_field_config()
OPTIONAL_FIELDS = set(_load_schema().get("optional_fields", []))
_DISPLAY_SPECS = get_display_specs()


def format_field_value(key: str, value: Any) -> str:
    """Apply backend-controlled display rules (lists, yes/no coercion, etc.)."""
    spec = _DISPLAY_SPECS.get(key, {})
    empty_text = spec.get("empty_text", "Not provided")
    dtype = spec.get("type", "text")

    if dtype == "list":
        if not value:
            return empty_text
        return ", ".join(value)

    if dtype == "yes_no":
        if value in {"yes", "no"}:
            return str(value).capitalize()
        return empty_text

    if spec.get("treat_no_as_missing") and value == "no":
        return empty_text

    return value if value else empty_text
