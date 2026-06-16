# Runs SHACL validation over user-selected diseases to flag generic concepts; purpose_app
# calls it after disease_linker suggestions while tests ensure the shapes stay consistent.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pyshacl import validate
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SH


SHAPES_PATH = Path(__file__).resolve().parent / "shapes.ttl"


@dataclass(slots=True)
class ValidationReport:
    conforms: bool
    generic_concepts: List[str]
    report_text: str
    field_messages: List[str]


def _build_data_graph(concepts: Iterable[str], metadata: Optional[Dict[str, Any]] = None) -> Graph:
    """Create a minimal RDF graph describing the selected diseases and form fields."""
    ex = Namespace("http://example.org/schema#")
    graph = Graph()
    graph.bind("ex", ex)

    intent = BNode()
    graph.add((intent, RDF.type, ex.ResearchIntent))

    for iri in concepts:
        graph.add((intent, ex.diseaseConcept, URIRef(iri)))

    if metadata:
        medication_value = metadata.get("medication")
        if medication_value:
            graph.add((intent, ex.hasMedication, Literal(str(medication_value))))

        collaborator_value = metadata.get("collaborator")
        if collaborator_value:
            graph.add((intent, ex.collaboratorStatus, Literal(str(collaborator_value))))

        product_dev = metadata.get("product_development")
        if product_dev:
            graph.add((intent, ex.productDevelopment, Literal(str(product_dev))))

        ta_value = metadata.get("TA")
        if ta_value:
            graph.add((intent, ex.therapeuticArea, Literal(str(ta_value))))

    return graph


def _load_shapes(shapes_path: str | None) -> Graph:
    """Load the SHACL shapes that encode MONDO's 'must be leaf' constraints."""
    path = Path(shapes_path) if shapes_path else SHAPES_PATH
    if not path.is_absolute():
        path = (SHAPES_PATH.parent / path).resolve()
    shapes_graph = Graph()
    shapes_graph.parse(str(path), format="turtle")
    return shapes_graph


def _extract_generic_from_report(report_graph: Graph) -> List[str]:
    """Pull the IRIs of offending diseases out of the SHACL result graph."""
    generics: List[str] = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        focus = report_graph.value(result, SH.focusNode)
        if isinstance(focus, URIRef):
            iri = str(focus)
            if iri not in generics:
                generics.append(iri)
    return generics


def _fallback_generic_check(
    concepts: Iterable[str],
    do_graph: Optional[Graph],
    children_index: Optional[Dict[str, List[str]]],
) -> List[str]:
    """Best-effort backup when SHACL fails to emit focus nodes (rare)."""
    generic: List[str] = []
    if children_index is not None:
        # When we already computed a children index, just check whether each concept
        # has known descendants rather than issuing SPARQL queries.
        for iri in concepts:
            if children_index.get(iri):
                generic.append(str(iri))
        return generic
    if do_graph is None:
        return generic
    for iri in concepts:
        ask = do_graph.query(
            f"ASK {{ ?child rdfs:subClassOf <{iri}> . }}",
            initNs={"rdfs": RDFS},
        )
        if bool(ask):
            generic.append(str(iri))
    return generic


def _extract_field_messages(report_graph: Graph) -> List[str]:
    """Collect SHACL validation messages that point to non-disease form fields."""
    messages: List[str] = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        focus = report_graph.value(result, SH.focusNode)
        if isinstance(focus, URIRef):
            # These are handled separately as generic disease issues.
            continue
        message = report_graph.value(result, SH.resultMessage)
        if message:
            text = str(message).strip()
            if text:
                messages.append(text)
    return messages


def _build_subclass_graph(concepts: Iterable[str], children_index: Dict[str, List[str]]) -> Graph:
    """Recreate a tiny ontology graph using only the selected nodes and their children."""
    graph = Graph()
    for parent in concepts:
        for child in children_index.get(parent, []):
            graph.add((URIRef(child), RDFS.subClassOf, URIRef(parent)))
    return graph


def validate_diseases(
    concepts: List[str],
    do_graph: Optional[Graph],
    shapes_path: str | None = None,
    children_index: Optional[Dict[str, List[str]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ValidationReport:
    """Run SHACL over the selected MONDO IRIs and enforce additional form rules."""
    data_graph = _build_data_graph(concepts, metadata=metadata)
    shapes_graph = _load_shapes(shapes_path)

    if do_graph is None:
        if children_index is None:
            raise ValueError("Either an ontology graph or a children index must be provided.")
        # In the Streamlit app we only pass the children index, so we reconstruct
        # a tiny subclass graph containing just the selected concepts.
        ont_graph = _build_subclass_graph(concepts, children_index)
    else:
        ont_graph = do_graph

    conforms, report_graph, report_text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ont_graph,
        inference="rdfs",
        advanced=True,
        meta_shacl=False,
        abort_on_first=False,
        js=False,
    )

    generics = _extract_generic_from_report(report_graph)
    if not generics and not conforms:
        # SHACL sometimes reports only human-readable text; run a best-effort check
        # so the UI can still highlight generic selections.
        generics = _fallback_generic_check(concepts, ont_graph, children_index)

    field_messages = _extract_field_messages(report_graph)

    return ValidationReport(
        conforms=bool(conforms),
        generic_concepts=generics,
        report_text=report_text,
        field_messages=field_messages,
    )
