# Package facade that lazily loads the MONDO graph and exposes shared indexes for the
# linker, validator, Streamlit apps, and smoke tests.
from __future__ import annotations

import os

from rdflib import Graph

from .ontology_loader import build_child_index, build_child_map, build_label_index, load_graph
from .precomputed import load_precomputed

_MONDO_GRAPH: Graph | None = None
_MONDO_VERSION: str | None = None
_LABELS = None
_LABEL_INDEX = None
_HAS_CHILDREN = None
_CHILDREN_INDEX = None


def _ensure_loaded() -> None:
    """Load the MONDO graph + indexes once and cache them for future imports."""
    global _MONDO_GRAPH, _MONDO_VERSION, _LABELS, _LABEL_INDEX, _HAS_CHILDREN, _CHILDREN_INDEX
    if _MONDO_VERSION is not None and _LABEL_INDEX is not None and _CHILDREN_INDEX is not None:
        return

    force_graph = os.getenv("MONDO_FORCE_GRAPH", "").strip() in {"1", "true", "TRUE", "yes", "YES"}
    disable_precomputed = os.getenv("MONDO_DISABLE_PRECOMPUTED", "").strip() in {"1", "true", "TRUE", "yes", "YES"}

    if not force_graph and not disable_precomputed:
        precomputed = load_precomputed(os.getenv("MONDO_PRECOMPUTED_PATH") or None)
        if precomputed is not None:
            _MONDO_GRAPH = None
            _MONDO_VERSION = precomputed.mondo_version
            _LABELS = precomputed.labels
            _LABEL_INDEX = precomputed.label_index
            _CHILDREN_INDEX = precomputed.children_index
            _HAS_CHILDREN = {iri: bool(children) for iri, children in _CHILDREN_INDEX.items()}

            globals().update(
                {
                    "MONDO_GRAPH": _MONDO_GRAPH,
                    "MONDO_VERSION": _MONDO_VERSION,
                    "LABELS": _LABELS,
                    "LABEL_INDEX": _LABEL_INDEX,
                    "HAS_CHILDREN": _HAS_CHILDREN,
                    "CHILDREN_INDEX": _CHILDREN_INDEX,
                }
            )
            return

    graph, version = load_graph()
    _MONDO_GRAPH = graph
    _MONDO_VERSION = version
    _LABELS = {}
    _LABEL_INDEX = build_label_index(graph)
    _HAS_CHILDREN = build_child_map(graph)
    _CHILDREN_INDEX = build_child_index(graph)

    globals().update(
        {
            "MONDO_GRAPH": graph,
            "MONDO_VERSION": version,
            "LABELS": _LABELS,
            "LABEL_INDEX": _LABEL_INDEX,
            "HAS_CHILDREN": _HAS_CHILDREN,
            "CHILDREN_INDEX": _CHILDREN_INDEX,
        }
    )


def __getattr__(name: str):
    """Expose lazy globals so `from ontology_validation import MONDO_GRAPH` still works."""
    if name in {"MONDO_GRAPH", "MONDO_VERSION", "LABELS", "LABEL_INDEX", "HAS_CHILDREN", "CHILDREN_INDEX"}:
        _ensure_loaded()
        return globals()[name]
    raise AttributeError(name)


__all__ = [
    "MONDO_GRAPH",
    "MONDO_VERSION",
    "LABELS",
    "LABEL_INDEX",
    "HAS_CHILDREN",
    "CHILDREN_INDEX",
    "build_label_index",
    "build_child_map",
    "build_child_index",
    "load_graph",
]
