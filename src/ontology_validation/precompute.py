# CLI helper to precompute lightweight MONDO indexes (labels, synonyms, subclasses)
# from the RDF/XML mondo.owl file without holding a full rdflib Graph in memory.
from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET

from .normalization import normalize
from .precomputed import default_precomputed_path

NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_OWL = "http://www.w3.org/2002/07/owl#"
NS_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
NS_SKOS = "http://www.w3.org/2004/02/skos/core#"
NS_OBOINOWL = "http://www.geneontology.org/formats/oboInOwl#"
NS_XML = "http://www.w3.org/XML/1998/namespace"

TAG_RDF = f"{{{NS_RDF}}}RDF"
TAG_OWL_ONTOLOGY = f"{{{NS_OWL}}}Ontology"
TAG_OWL_CLASS = f"{{{NS_OWL}}}Class"
TAG_OWL_VERSION_INFO = f"{{{NS_OWL}}}versionInfo"

TAG_RDFS_LABEL = f"{{{NS_RDFS}}}label"
TAG_RDFS_SUBCLASS_OF = f"{{{NS_RDFS}}}subClassOf"
TAG_SKOS_ALT_LABEL = f"{{{NS_SKOS}}}altLabel"
TAG_OBO_EXACT_SYNONYM = f"{{{NS_OBOINOWL}}}hasExactSynonym"

ATTR_RDF_ABOUT = f"{{{NS_RDF}}}about"
ATTR_RDF_ID = f"{{{NS_RDF}}}ID"
ATTR_RDF_RESOURCE = f"{{{NS_RDF}}}resource"
ATTR_XML_LANG = f"{{{NS_XML}}}lang"
ATTR_XML_BASE = f"{{{NS_XML}}}base"


def _accept_lang(lang_value: Optional[str], desired: str = "en") -> bool:
    if lang_value is None or lang_value == "":
        return desired.lower() in ("", "en")
    return lang_value.lower().startswith(desired.lower())


def _iter_label_literals(elem: ET.Element) -> Iterable[str]:
    """Yield accepted labels/synonyms for a class element."""
    for child in elem:
        if child.tag not in {TAG_RDFS_LABEL, TAG_SKOS_ALT_LABEL, TAG_OBO_EXACT_SYNONYM}:
            continue
        lang = child.attrib.get(ATTR_XML_LANG)
        if not _accept_lang(lang, "en"):
            continue
        text = (child.text or "").strip()
        if text:
            yield text


def _pick_preferred_label(elem: ET.Element) -> Optional[str]:
    """Pick an English preferred label (rdfs:label) if possible, otherwise any rdfs:label."""
    fallback: Optional[str] = None
    for child in elem:
        if child.tag != TAG_RDFS_LABEL:
            continue
        text = (child.text or "").strip()
        if not text:
            continue
        lang = child.attrib.get(ATTR_XML_LANG)
        if _accept_lang(lang, "en"):
            return text
        if fallback is None:
            fallback = text
    return fallback


def build_indexes_from_rdfxml(path: Path) -> Tuple[str, Dict[str, str], Dict[str, List[str]], Dict[str, List[str]]]:
    """Return mondo_version, labels, label_index, children_index parsed from mondo.owl RDF/XML."""
    base_uri: Optional[str] = None
    mondo_version: Optional[str] = None

    labels: Dict[str, str] = {}
    label_index: DefaultDict[str, Set[str]] = defaultdict(set)
    children_index: DefaultDict[str, Set[str]] = defaultdict(set)

    # iterparse emits (event, element); we clear processed elements to keep memory bounded.
    context = ET.iterparse(path, events=("start", "end"))
    for event, elem in context:
        if event == "start" and elem.tag == TAG_RDF and base_uri is None:
            base_uri = elem.attrib.get(ATTR_XML_BASE)

        if event != "end":
            continue

        if elem.tag == TAG_OWL_ONTOLOGY and mondo_version is None:
            for child in elem:
                if child.tag == TAG_OWL_VERSION_INFO:
                    candidate = (child.text or "").strip()
                    if candidate:
                        mondo_version = candidate
                        break
            elem.clear()
            continue

        if elem.tag != TAG_OWL_CLASS:
            continue

        iri = elem.attrib.get(ATTR_RDF_ABOUT)
        if not iri:
            rdf_id = elem.attrib.get(ATTR_RDF_ID)
            if rdf_id and base_uri:
                iri = f"{base_uri}#{rdf_id}"
        if not iri:
            elem.clear()
            continue

        preferred_label = _pick_preferred_label(elem)
        if preferred_label and iri not in labels:
            labels[iri] = preferred_label

        for literal in _iter_label_literals(elem):
            key = normalize(literal)
            if key:
                label_index[key].add(iri)

        for child in elem:
            if child.tag != TAG_RDFS_SUBCLASS_OF:
                continue
            parent = child.attrib.get(ATTR_RDF_RESOURCE)
            if parent:
                children_index[parent].add(iri)

        elem.clear()

    if mondo_version is None:
        # Stable fallback that doesn't require hashing the full file.
        mondo_version = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    label_index_out = {k: sorted(v) for k, v in label_index.items() if v}
    children_index_out = {k: sorted(v) for k, v in children_index.items() if v}

    return mondo_version, labels, label_index_out, children_index_out


def write_precomputed(
    mondo_version: str,
    labels: Dict[str, str],
    label_index: Dict[str, List[str]],
    children_index: Dict[str, List[str]],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": mondo_version,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "labels": labels,
        "label_index": label_index,
        "children_index": children_index,
    }
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute MONDO indexes for low-memory runtime loading.")
    parser.add_argument(
        "--in",
        dest="in_path",
        default="data/ontology/mondo.owl",
        help="Path to mondo.owl (RDF/XML).",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        default=str(default_precomputed_path()),
        help="Path to write mondo_precomputed.json.gz.",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    if not in_path.is_absolute():
        base_dir = Path(__file__).resolve().parents[2]
        in_path = (base_dir / in_path).resolve()
    out_path = Path(args.out_path)

    mondo_version, labels, label_index, children_index = build_indexes_from_rdfxml(in_path)
    write_precomputed(mondo_version, labels, label_index, children_index, out_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

