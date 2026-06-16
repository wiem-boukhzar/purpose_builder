# Lightweight loader for precomputed MONDO indexes.
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True, slots=True)
class PrecomputedIndex:
    mondo_version: str
    labels: Dict[str, str]
    label_index: Dict[str, List[str]]
    children_index: Dict[str, List[str]]


def default_precomputed_path() -> Path:
    """Return the default path for the precomputed MONDO index inside the repo/image."""
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "data/ontology/mondo_precomputed.json.gz"


def load_precomputed(path: str | os.PathLike[str] | None = None) -> Optional[PrecomputedIndex]:
    """Load the precomputed index file if present; return None when unavailable/invalid."""
    resolved = Path(path) if path else default_precomputed_path()
    if not resolved.exists():
        return None

    try:
        with gzip.open(resolved, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        return None
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    mondo_version = data.get("version")
    labels = data.get("labels")
    label_index = data.get("label_index")
    children_index = data.get("children_index")

    if not isinstance(mondo_version, str) or not mondo_version.strip():
        return None
    if not isinstance(labels, dict) or not isinstance(label_index, dict) or not isinstance(children_index, dict):
        return None

    # Shallow validation to avoid crashing on malformed files.
    try:
        labels_out = {str(k): str(v) for k, v in labels.items() if k and v}
        label_index_out: Dict[str, List[str]] = {
            str(k): [str(iri) for iri in v if iri] for k, v in label_index.items() if k and isinstance(v, list)
        }
        children_index_out: Dict[str, List[str]] = {
            str(k): [str(child) for child in v if child] for k, v in children_index.items() if k and isinstance(v, list)
        }
    except Exception:
        return None

    if not labels_out or not label_index_out:
        return None

    return PrecomputedIndex(
        mondo_version=mondo_version.strip(),
        labels=labels_out,
        label_index=label_index_out,
        children_index=children_index_out,
    )

