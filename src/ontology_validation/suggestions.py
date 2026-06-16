# Suggests concrete child diseases for generic selections, complementing
# disease_linker outputs and feeding validator/purpose_app refinement flows.
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

from .disease_linker import label_for


@dataclass(slots=True)
class Suggestion:
    iri: str
    label: str


def suggest_children(
    concept_iri: str,
    g: Graph | None = None,
    children_index: Optional[Dict[str, List[str]]] = None,
    labels: Mapping[str, str] | None = None,
    lang: str = "en",
) -> List[Suggestion]:
    """Return sorted child disease suggestions for a generic MONDO concept."""
    parent = URIRef(concept_iri)
    suggestions: List[Suggestion] = []
    seen: set[tuple[str, str]] = set()

    if children_index is not None:
        candidate_children = children_index.get(concept_iri, [])
    elif g is not None:
        candidate_children = [
            str(child)
            for child in g.subjects(RDFS.subClassOf, parent)
            if isinstance(child, URIRef)
        ]
    else:
        candidate_children = []

    for child_iri in candidate_children:
        label = label_for(child_iri, g=g, labels=labels, lang=lang)
        if not label:
            continue
        key = (child_iri, label)
        if key in seen:
            continue
        suggestions.append(Suggestion(iri=child_iri, label=label))
        seen.add(key)

    suggestions.sort(key=lambda item: item.label.lower())
    if not suggestions and children_index is None and g is not None:
        # Index may not be available in some contexts; scan the graph as a backup.
        for child in g.subjects(RDFS.subClassOf, parent):
            if not isinstance(child, URIRef):
                continue
            child_iri = str(child)
            label = label_for(child_iri, g=g, labels=labels, lang=lang)
            if not label:
                continue
            key = (child_iri, label)
            if key in seen:
                continue
            suggestions.append(Suggestion(iri=child_iri, label=label))
            seen.add(key)
        suggestions.sort(key=lambda item: item.label.lower())

    return suggestions
