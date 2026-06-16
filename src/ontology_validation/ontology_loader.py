# MONDO loading + indexing utilities shared by the disease_linker, suggestions, and
# validator modules so they operate on the same cached graph/state.
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS
from rdflib import Namespace
from rdflib.util import guess_format

from .normalization import normalize

OBOINOWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")
BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ONTOLOGY_PATH = BASE_DIR / "data/ontology/mondo.owl"


def _resolve_version(graph: Graph, path: Path) -> str:
    """Prefer OWL version info, otherwise fall back to file timestamp/hash."""
    for ontology in graph.subjects(RDF.type, OWL.Ontology):
        version_literal = graph.value(ontology, OWL.versionInfo)
        if isinstance(version_literal, Literal):
            version_text = str(version_literal).strip()
            if version_text:
                return version_text

    try:
        mtime = path.stat().st_mtime
    except OSError:
        file_bytes = path.read_bytes()
        return hashlib.sha256(file_bytes).hexdigest()

    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


@lru_cache(maxsize=1)
def load_graph(path: str = "data/ontology/mondo.owl") -> Tuple[Graph, str]:
    """Parse MONDO once, returning both the RDF graph and a version identifier."""
    graph = Graph()
    ontology_path = Path(path)
    if not ontology_path.is_absolute():
        ontology_path = (BASE_DIR / ontology_path).resolve()

    fmt = guess_format(str(ontology_path))

    if fmt is not None:
        graph.parse(ontology_path, format=fmt)
    else:
        graph.parse(ontology_path)

    version = _resolve_version(graph, ontology_path)
    return graph, version


def build_label_index(g: Graph, lang: str = "en") -> Dict[str, Set[str]]:
    """Build normalized label -> set of IRIs index for fast fuzzy lookups."""
    index: Dict[str, Set[str]] = defaultdict(set)
    lang_normalized = (lang or "").lower()

    def _accept(literal: Literal) -> bool:
        if not isinstance(literal, Literal):
            return False
        if literal.language is None or literal.language == "":
            return lang_normalized in ("", "en")
        return literal.language.lower().startswith(lang_normalized) if lang_normalized else False

    predicates = [RDFS.label, SKOS.altLabel, OBOINOWL.hasExactSynonym]

    for predicate in predicates:
        for subject, label in g.subject_objects(predicate):
            if _accept(label):
                key = normalize(str(label))
                if key:
                    index[key].add(str(subject))

    return dict(index)


def build_child_map(g: Graph) -> Dict[str, bool]:
    """Return a map of class IRI -> True if it has at least one direct subclass."""
    has_child: Dict[str, bool] = defaultdict(bool)
    for child, parent in g.subject_objects(RDFS.subClassOf):
        has_child[str(parent)] = True
        # ensure child exists in map even if False for consistency
        has_child.setdefault(str(child), False)
    return dict(has_child)


def build_child_index(g: Graph) -> Dict[str, List[str]]:
    """Return a map of class IRI -> list of direct subclass IRIs."""
    child_index: Dict[str, List[str]] = defaultdict(list)
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if not isinstance(child, URIRef) or not isinstance(parent, URIRef):
            continue
        child_index[str(parent)].append(str(child))
    return dict(child_index)
