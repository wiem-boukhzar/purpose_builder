"""Streamlit-only helpers that drive refinement controls."""
from __future__ import annotations

from typing import Dict

import streamlit as st

from .common import fresh_structured_data, run_disease_validation
from .state_manager import get_session_state


def _state():
    """Reuse the configured purpose_app session state (Streamlit or backend)."""
    return get_session_state()


def _apply_generic_selection(parent_iri: str, suggestion: Dict[str, str]) -> None:
    """Replace a generic disease with the selected specific suggestion."""
    structured = _state().get("structured_data", fresh_structured_data())
    diseases = list(structured.get("diseases", []))

    parent_label = None
    for record in _state().get("ontology_linked_diseases", []):
        if record["iri"] == parent_iri:
            parent_label = record["label"]
            break

    if parent_label:
        diseases = [suggestion["label"] if d == parent_label else d for d in diseases]
    if suggestion["label"] not in diseases:
        diseases.append(suggestion["label"])

    structured["diseases"] = diseases
    _state().structured_data = structured
    _state().ontology_generic_diseases = [
        issue for issue in _state().get("ontology_generic_diseases", []) if issue["iri"] != parent_iri
    ]
    run_disease_validation(diseases)
    st.rerun()


def _apply_unknown_selection(source_text: str, suggestion_label: str) -> None:
    """Fill in an unknown disease with whichever suggestion the user clicks."""
    structured = _state().get("structured_data", fresh_structured_data())
    diseases = list(structured.get("diseases", []))

    if suggestion_label not in diseases:
        diseases.append(suggestion_label)

    structured["diseases"] = diseases
    _state().structured_data = structured
    _state().ontology_unknown_diseases = [
        issue for issue in _state().get("ontology_unknown_diseases", []) if issue["input"] != source_text
    ]
    run_disease_validation(diseases)
    st.rerun()


def render_refinement_controls() -> None:
    """Render the Streamlit UI widgets for refining generic/unknown diseases."""
    generic_issues = _state().get("ontology_generic_diseases", [])
    unknown_diseases = _state().get("ontology_unknown_diseases", [])

    if not generic_issues and not unknown_diseases:
        return

    st.markdown("#### 🔍 Disease Refinement")

    for issue in generic_issues:
        st.markdown(f"**{issue['label']}** requires a more specific subtype.")
        for idx, suggestion in enumerate(issue.get("suggestions", []), start=1):
            label = suggestion["label"]
            button_label = f"{idx}. {label}"
            key = f"generic_{issue['iri']}_{suggestion['iri']}"
            if st.button(button_label, key=key):
                _apply_generic_selection(issue["iri"], suggestion)

    for issue in unknown_diseases:
        st.markdown(f"**{issue['input']}** was not matched in the MONDO ontology.")
        suggestions = issue.get("suggestions", [])
        if suggestions:
            for idx, suggestion_label in enumerate(suggestions, start=1):
                key = f"unknown_{issue['input']}_{idx}"
                if st.button(f"{idx}. {suggestion_label}", key=key):
                    _apply_unknown_selection(issue["input"], suggestion_label)
        else:
            st.info("No close ontology labels were found. Please provide the official disease name.")
