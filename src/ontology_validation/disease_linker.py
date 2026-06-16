# Fuzzy MONDO linker that consumes normalization helpers and the indexes built in
# ontology_loader so purpose_app and demos can convert user text into canonical IRIs.
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from rapidfuzz import fuzz, process
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS

from .normalization import normalize

_LABEL_CACHE: Dict[Tuple[str, str], str] = {}


@dataclass(slots=True)
class LinkedDisease:
    iri: str
    label: str
    score: float
    source_text: str


@dataclass(slots=True)
class UnknownDisease:
    source_text: str
    suggestions: List[str]


def label_for(
    iri: str,
    g: Graph | None = None,
    labels: Mapping[str, str] | None = None,
    lang: str = "en",
) -> str:
    """Cache-friendly helper to fetch the preferred label for a MONDO concept."""
    cache_key = (iri, lang.lower())
    cached = _LABEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if labels is not None:
        mapped = labels.get(iri)
        if mapped:
            _LABEL_CACHE[cache_key] = mapped
            return mapped

    if g is None:
        iri_str = str(iri)
        fragment = iri_str.split("#")[-1].split("/")[-1]
        result = fragment.replace("_", " ") if fragment else iri_str
        _LABEL_CACHE[cache_key] = result
        return result

    uri = URIRef(iri)
    preferred: Optional[str] = None
    fallback: Optional[str] = None

    for literal in g.objects(uri, RDFS.label):
        if not isinstance(literal, Literal):
            continue
        value = str(literal)
        if literal.language:
            if literal.language.lower().startswith(lang.lower()):
                preferred = value
                break
        elif fallback is None:
            fallback = value

    if preferred:
        _LABEL_CACHE[cache_key] = preferred
        return preferred
    if fallback:
        _LABEL_CACHE[cache_key] = fallback
        return fallback

    iri_str = str(iri)
    fragment = iri_str.split("#")[-1].split("/")[-1]
    result = fragment.replace("_", " ") if fragment else iri_str
    _LABEL_CACHE[cache_key] = result
    return result


def _pick_best_normalized_match(
    normalized_term: str,
    candidates: List[Tuple[str, float, object]],
) -> Optional[Tuple[str, float]]:
    """Tie-break multiple fuzzy matches by weighing score, position, and obsolescence."""
    if not candidates:
        return None

    term_tokens = normalized_term.split()
    term_token_count = len(term_tokens)

    def sort_key(item: Tuple[str, float, object]) -> Tuple[int, int, int, int, int]:
        label, score, _ = item
        label_tokens = label.split()
        label_token_count = len(label_tokens)
        # Prefer higher scores, direct substring matches, fewer extra tokens,
        # and prioritize non-obsolete labels that mention the query up front.
        contains_penalty = 0 if normalized_term == label else (0 if normalized_term in label else 1)
        extra_tokens = max(label_token_count - term_token_count, 0)
        try:
            position_penalty = label_tokens.index(term_tokens[0])
        except ValueError:
            position_penalty = len(label_tokens)
        obsolete_penalty = 1 if any(token in {"obsolete"} for token in label_tokens) else 0
        return (
            -int(score),
            contains_penalty,
            position_penalty,
            extra_tokens,
            obsolete_penalty,
            len(label),
        )

    label, score, _ = min(candidates, key=sort_key)
    return label, float(score)


def link_best(
    term: str,
    index: Mapping[str, Sequence[str]],
    g: Graph | None = None,
    labels: Mapping[str, str] | None = None,
    threshold: int = 80,
) -> Optional[LinkedDisease]:
    """Return the highest-confidence MONDO concept for a user-supplied disease."""
    normalized_term = normalize(term)
    if not normalized_term or not index:
        return None

    matched_label: Optional[str] = None
    score: float = 0.0

    if normalized_term in index:
        # Perfect normalized match; skip the fuzzy machinery.
        matched_label = normalized_term
        score = 100.0
    else:
        # Fall back to fuzzy scoring, then re-rank ties with heuristics that
        # penalize obsolete concepts or partial overlaps.
        best_match = process.extractOne(
            normalized_term,
            index.keys(),
            scorer=fuzz.token_set_ratio,
        )
        if not best_match:
            return None
        top_label, top_score, _ = best_match
        if top_score < threshold:
            return None

        all_top_matches = process.extract(
            normalized_term,
            index.keys(),
            scorer=fuzz.token_set_ratio,
            limit=None,
            score_cutoff=top_score,
        )
        best = _pick_best_normalized_match(normalized_term, all_top_matches)
        if best is None:
            return None
        matched_label, score = best

    candidates = index.get(matched_label, set())
    if not candidates:
        return None

    chosen_iri = None
    chosen_label = None

    for iri in candidates:
        label = label_for(iri, g=g, labels=labels)
        if normalize(label) == matched_label:
            chosen_iri = iri
            chosen_label = label
            break

    if chosen_iri is None:
        # As a last resort grab whatever MONDO label sits under the normalized key.
        chosen_iri = next(iter(candidates))
        chosen_label = label_for(chosen_iri, g=g, labels=labels)

    return LinkedDisease(
        iri=chosen_iri,
        label=chosen_label,
        score=float(score),
        source_text=term,
    )


def _top_label_suggestions(
    term: str,
    index: Mapping[str, Sequence[str]],
    g: Graph | None = None,
    labels: Mapping[str, str] | None = None,
    limit: int = 3,
    score_cutoff: int = 60,
) -> List[str]:
    """Surface the best human-readable suggestions when we cannot auto-link."""
    normalized_term = normalize(term)
    if not normalized_term or not index:
        return []

    matches = process.extract(
        normalized_term,
        index.keys(),
        limit=max(limit * 4, limit),
        scorer=fuzz.token_set_ratio,
        score_cutoff=score_cutoff,
    )

    suggestions: List[str] = []
    seen: Set[str] = set()

    for normalized_label, score, _ in matches:
        if score < score_cutoff:
            continue
        for iri in index.get(normalized_label, set()):
            label = label_for(iri, g=g, labels=labels)
            if label not in seen:
                suggestions.append(label)
                seen.add(label)
            if len(suggestions) >= limit:
                break
        if len(suggestions) >= limit:
            break

    return suggestions


def link_many(
    terms: Sequence[str],
    index: Mapping[str, Sequence[str]],
    g: Graph | None = None,
    labels: Mapping[str, str] | None = None,
    threshold: int = 80,
) -> List[Union[LinkedDisease, UnknownDisease]]:
    """Vectorised helper that returns either linked diseases or suggestion payloads."""
    results: List[Union[LinkedDisease, UnknownDisease]] = []

    for term in terms:
        linked = link_best(term, index, g=g, labels=labels, threshold=threshold)
        if linked is not None:
            results.append(linked)
            continue

        suggestions = _top_label_suggestions(term, index, g=g, labels=labels)
        results.append(UnknownDisease(source_text=term, suggestions=suggestions))

    return results
