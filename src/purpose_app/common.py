# Core conversation + validation helpers used by both Streamlit entry points; this is
# where ontology_validation services, LangGraph wiring, and logging utilities converge.
from __future__ import annotations

import csv
import gzip
import html
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

import ontology_validation as ontology_validation
from ontology_validation.disease_linker import (
    LinkedDisease,
    UnknownDisease,
    label_for,
    link_many,
)
from ontology_validation.validator import ValidationReport, validate_diseases
from .logging_utils import log_event
from .schema import FIELD_CONFIG, OPTIONAL_FIELDS, format_field_value
from .state_manager import get_session_state


def _state():
    """Shortcut accessor so we don't repeat get_session_state everywhere."""
    return get_session_state()

MAX_GENERIC_SUGGESTIONS = 10
MAX_LEAF_PATHS_PER_DISEASE = 500
_OPTION_PATTERN = re.compile(r"^\s*(?:option\s*)?(\d+)(?:\D.*)?$", re.IGNORECASE)

SYSTEM_INSTRUCTIONS = (
    "You are a pharmaceutical research assistant who extracts structured information from conversations. "
    "You will see a conversation between the assistant and user. The assistant asks questions, and the user responds.\n"
    "\nExtract the following fields for a pharma research purpose JSON payload:\n"
    "- diseases: array of disease names (strings) explicitly provided or unambiguously implied; use an empty array if unknown.\n"
    "- medication: string; if the user explicitly says they don't have medication (e.g., 'no', 'I do not have', 'none'), "
    "use the string \"no\". If they provide a medication name, use that name. If unknown/not mentioned, use null.\n"
    "- collaborator: \"yes\" or \"no\" only; use null if unknown.\n"
    "- product_development: \"yes\" or \"no\" only; use null if unknown.\n"
    "- product_development_scope: string describing the scope if product_development is yes; use null if unknown or not applicable.\n"
    "- TA: string representing the therapeutic area; select exactly ONE from the list below. "
    "Infer from diseases when possible. Use null only if the therapeutic area cannot be reasonably inferred.\n"
    "\nTherapeutic area choices (return the exact label):\n"
    "- Infections\n"
    "- Neoplasms\n"
    "- Musculoskeletal Diseases\n"
    "- Digestive System Diseases\n"
    "- Stomatognathic Diseases\n"
    "- Respiratory Tract Diseases\n"
    "- Otorhinolaryngologic Diseases\n"
    "- Nervous System Diseases\n"
    "- Eye Diseases\n"
    "- Male Urogenital Diseases\n"
    "- Female Urogenital Diseases & Pregnancy Complications\n"
    "- Cardiovascular Diseases\n"
    "- Hemic and Lymphatic Diseases\n"
    "- Congenital, Hereditary & Neonatal Diseases & Abnormalities\n"
    "- Skin & Connective Tissue Diseases\n"
    "- Nutritional & Metabolic Diseases\n"
    "- Endocrine System Diseases\n"
    "- Immune System Diseases\n"
    "- Disorders of Environmental Origin\n"
    "- Animal Diseases\n"
    "- Pathological Conditions, Signs & Symptoms\n"
    "- Occupational Diseases\n"
    "- Chemically-Induced Disorders\n"
    "- Wounds & Injuries\n"
    "\nIMPORTANT RULES:\n"
    "1. Match each user answer to the MOST RECENT assistant question.\n"
    "2. If the assistant asks 'Do you have a collaborator (yes or no)?', the user's answer applies to 'collaborator'.\n"
    "3. If the assistant asks 'Are you pursuing product development (yes or no)?', the user's answer applies to 'product_development'.\n"
    "4. If the assistant asks about medication, the user's answer applies to 'medication'.\n"
    "5. Only update a field when there's a clear question-answer pair for it.\n"
    "\nRespond with a single JSON object only, no prose. Only include fields listed above."
)

EXPECTED_KEYS = {"diseases", "medication", "collaborator", "product_development", "product_development_scope", "TA"}
KEY_NORMALISATION = {
    "ta": "TA",
    "therapeutic_area": "TA",
    "therapeuticarea": "TA",
    "therapeutic-area": "TA",
    "disease": "diseases",
    "diseases": "diseases",
    "drug": "medication",
    "medication": "medication",
    "medicine": "medication",
    "sponsor": "collaborator",
    "collaborator": "collaborator",
    "collaboration": "collaborator",
    "productdevelopment": "product_development",
    "product_development": "product_development",
    "product_development_scope": "product_development_scope",
    "productdevelopment_scope": "product_development_scope",
    "productdevelopment scope": "product_development_scope",
    "product development scope": "product_development_scope",
    "development_scope": "product_development_scope",
}
THERAPEUTIC_AREAS = [
    "Infections",
    "Neoplasms",
    "Musculoskeletal Diseases",
    "Digestive System Diseases",
    "Stomatognathic Diseases",
    "Respiratory Tract Diseases",
    "Otorhinolaryngologic Diseases",
    "Nervous System Diseases",
    "Eye Diseases",
    "Male Urogenital Diseases",
    "Female Urogenital Diseases & Pregnancy Complications",
    "Cardiovascular Diseases",
    "Hemic and Lymphatic Diseases",
    "Congenital, Hereditary & Neonatal Diseases & Abnormalities",
    "Skin & Connective Tissue Diseases",
    "Nutritional & Metabolic Diseases",
    "Endocrine System Diseases",
    "Immune System Diseases",
    "Disorders of Environmental Origin",
    "Animal Diseases",
    "Pathological Conditions, Signs & Symptoms",
    "Occupational Diseases",
    "Chemically-Induced Disorders",
    "Wounds & Injuries",
]
THERAPEUTIC_AREA_CODES = {
    "C01": "Infections",
    "C04": "Neoplasms",
    "C05": "Musculoskeletal Diseases",
    "C06": "Digestive System Diseases",
    "C07": "Stomatognathic Diseases",
    "C08": "Respiratory Tract Diseases",
    "C09": "Otorhinolaryngologic Diseases",
    "C10": "Nervous System Diseases",
    "C11": "Eye Diseases",
    "C12": "Male Urogenital Diseases",
    "C13": "Female Urogenital Diseases & Pregnancy Complications",
    "C14": "Cardiovascular Diseases",
    "C15": "Hemic and Lymphatic Diseases",
    "C16": "Congenital, Hereditary & Neonatal Diseases & Abnormalities",
    "C17": "Skin & Connective Tissue Diseases",
    "C18": "Nutritional & Metabolic Diseases",
    "C19": "Endocrine System Diseases",
    "C20": "Immune System Diseases",
    "C21": "Disorders of Environmental Origin",
    "C22": "Animal Diseases",
    "C23": "Pathological Conditions, Signs & Symptoms",
    "C24": "Occupational Diseases",
    "C25": "Chemically-Induced Disorders",
    "C26": "Wounds & Injuries",
}
THERAPEUTIC_AREA_SYNONYMS = {
    "oncology": "Neoplasms",
    "cancer": "Neoplasms",
    "cardiology": "Cardiovascular Diseases",
    "neurology": "Nervous System Diseases",
    "immunology": "Immune System Diseases",
    "autoimmune": "Immune System Diseases",
    "pulmonology": "Respiratory Tract Diseases",
    "respiratory": "Respiratory Tract Diseases",
    "infectious": "Infections",
    "infection": "Infections",
    "hematology": "Hemic and Lymphatic Diseases",
    "haematology": "Hemic and Lymphatic Diseases",
    "dermatology": "Skin & Connective Tissue Diseases",
    "gastroenterology": "Digestive System Diseases",
    "gastrointestinal": "Digestive System Diseases",
    "rheumatology": "Musculoskeletal Diseases",
    "orthopedic": "Musculoskeletal Diseases",
    "endocrinology": "Endocrine System Diseases",
    "metabolic": "Nutritional & Metabolic Diseases",
    "congenital": "Congenital, Hereditary & Neonatal Diseases & Abnormalities",
    "neonatal": "Congenital, Hereditary & Neonatal Diseases & Abnormalities",
    "pregnancy": "Female Urogenital Diseases & Pregnancy Complications",
    "obgyn": "Female Urogenital Diseases & Pregnancy Complications",
    "otolaryngology": "Otorhinolaryngologic Diseases",
    "ent": "Otorhinolaryngologic Diseases",
    "ophthalmology": "Eye Diseases",
    "dental": "Stomatognathic Diseases",
    "oral": "Stomatognathic Diseases",
    "environmental": "Disorders of Environmental Origin",
    "occupational": "Occupational Diseases",
    "toxicology": "Chemically-Induced Disorders",
    "injury": "Wounds & Injuries",
}
THERAPEUTIC_AREA_CODE_PATTERN = re.compile(r"\bC\d{2}\b", re.IGNORECASE)


class ResearchState(TypedDict, total=False):
    user_messages: List[str]
    raw_response: str
    structured: Dict[str, Any]
    validation_result: Optional["ValidationOutcome"]


class GenericIssue(TypedDict):
    iri: str
    label: str
    suggestions: List[Dict[str, str]]


class ValidationOutcome(TypedDict, total=False):
    conforms: bool
    linked: List[LinkedDisease]
    unknown: List[UnknownDisease]
    generic_parents: List[GenericIssue]
    report_text: str
    field_messages: List[str]


def format_numbered_list(labels: Sequence[str]) -> str:
    """Render enumerated Markdown/plan text for suggestion prompts."""
    return "\n".join(f"{idx}. {label}" for idx, label in enumerate(labels, start=1))


def unique_preserve_order(labels: Sequence[str]) -> List[str]:
    """Deduplicate while preserving the first-seen order."""
    seen = set()
    ordered: List[str] = []
    for label in labels:
        if label not in seen:
            ordered.append(label)
            seen.add(label)
    return ordered


def iri_to_doid(iri: str) -> str:
    """Convert MONDO IRIs to human-friendly DOID strings when possible."""
    prefix = "http://purl.obolibrary.org/obo/DOID_"
    if iri.startswith(prefix):
        return f"DOID:{iri.rsplit('_', 1)[-1]}"
    return iri


def fresh_structured_data() -> Dict[str, Any]:
    """Baseline shape for the form-like structured data we maintain."""
    return {
        "diseases": [],
        "medication": None,
        "collaborator": None,
        "product_development": None,
        "product_development_scope": None,
        "TA": None,
    }


def init_session_state() -> None:
    """Initialise every key the workflow relies on inside the current session state."""
    if "messages" not in _state():
        _state().messages = []
    if "structured_data" not in _state():
        _state().structured_data = fresh_structured_data()
    if "thinking" not in _state():
        _state().thinking = False
    if "acknowledged_diseases" not in _state():
        _state().acknowledged_diseases = False
    if "asked_medication" not in _state():
        _state().asked_medication = False
    if "ontology_unknown_diseases" not in _state():
        _state().ontology_unknown_diseases = []
    if "ontology_generic_diseases" not in _state():
        _state().ontology_generic_diseases = []
    if "ontology_linked_diseases" not in _state():
        _state().ontology_linked_diseases = []
    if "ontology_validation_report" not in _state():
        _state().ontology_validation_report = ""
    if "ontology_validation_error" not in _state():
        _state().ontology_validation_error = ""
    if "ontology_conforms" not in _state():
        _state().ontology_conforms = False
    if "final_purpose_payload" not in _state():
        _state().final_purpose_payload = None
    if "validation_report_payload" not in _state():
        _state().validation_report_payload = None
    if "final_validation_result" not in _state():
        _state().final_validation_result = None
    if "final_validation_error" not in _state():
        _state().final_validation_error = ""
    if "final_validation_candidates" not in _state():
        _state().final_validation_candidates = []
    if "final_selected_leaves" not in _state():
        _state().final_selected_leaves = {}
    if "final_leaf_option_lookup" not in _state():
        _state().final_leaf_option_lookup = {}
    if "final_dropdown_state" not in _state():
        _state().final_dropdown_state = {}
    if "selected_purpose" not in _state():
        _state().selected_purpose = ""
    if "validation_locked" not in _state():
        _state().validation_locked = False
    if "validation_cached" not in _state():
        _state().validation_cached = None
    if "recorded_use_cases" not in _state():
        _state().recorded_use_cases = []
    if "last_intent" not in _state():
        _state().last_intent = None
    if "validated_diseases_key" not in _state():
        _state().validated_diseases_key = ()
    if "validation_locked" not in _state():
        _state().validation_locked = False
    if "validation_cached" not in _state():
        _state().validation_cached = None


def _message_context() -> Dict[str, Any]:
    structured = _state().get("structured_data", {}) or {}
    return {
        "diseases": list(structured.get("diseases") or []),
        "therapeutic_area": structured.get("TA"),
        "purpose_category": _state().get("selected_purpose") or None,
    }


def add_message(role: str, content: str, display_content: Optional[str] = None) -> None:
    """Persist a chat turn and mirror it into the telemetry stream."""
    entry = {"role": role, "content": content, "context": _message_context()}
    if display_content is not None:
        entry["display"] = display_content
    _state().messages.append(entry)
    log_payload = {
        "role": role,
        "content": content,
    }
    if display_content is not None and display_content != content:
        log_payload["display"] = display_content
    log_event("chat_message", **log_payload)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def detect_intent(message: str) -> str:
    """Route a user message to support/purpose_tuner/optimizer/reviewer."""
    lowered = _normalize_text(message)

    reviewer_hints = (
        "validate",
        "validation",
        "review",
        "approval",
        "conform",
        "shacl",
        "check",
    )
    optimizer_hints = (
        "use case",
        "use-case",
        "existing",
        "duplicate",
        "redundan",
        "match",
        "optimiz",
        "scope",
    )
    support_hints = (
        "how",
        "what is",
        "help",
        "documentation",
        "doc",
        "guide",
        "where can i",
        "faq",
        "explain",
    )

    if any(hint in lowered for hint in reviewer_hints):
        return "reviewer"
    if any(hint in lowered for hint in optimizer_hints):
        return "optimizer"
    if any(hint in lowered for hint in support_hints):
        return "support"
    return "purpose_tuner"


def _purpose_signature(structured: Dict[str, Any]) -> str:
    diseases = structured.get("diseases") or []
    ta = structured.get("TA") or ""
    purpose = _state().get("selected_purpose") or ""
    key = "|".join([
        ",".join(sorted({str(item).strip().lower() for item in diseases if item})),
        str(ta).strip().lower(),
        str(purpose).strip().lower(),
    ])
    return key


def _summarize_use_case(structured: Dict[str, Any]) -> str:
    diseases = structured.get("diseases") or []
    ta = structured.get("TA") or ""
    purpose = _state().get("selected_purpose") or ""
    pieces = []
    if purpose:
        pieces.append(f"Purpose: {purpose}")
    if diseases:
        pieces.append(f"Diseases: {', '.join(diseases)}")
    if ta:
        pieces.append(f"Therapeutic area: {ta}")
    return " | ".join(pieces) if pieces else "Unspecified purpose"


def build_optimizer_reply(structured: Dict[str, Any]) -> str:
    """Provide a lightweight, in-session use-case match and store result."""
    if not purpose_complete(structured):
        missing = [label for key, label, _ in FIELD_CONFIG if key in missing_fields(structured)]
        missing_text = ", ".join(missing) if missing else "required fields"
        return f"To match against existing use cases, I still need: {missing_text}."

    signature = _purpose_signature(structured)
    use_cases = _state().get("recorded_use_cases", [])
    existing = next((item for item in use_cases if item.get("signature") == signature), None)
    summary = _summarize_use_case(structured)

    if existing:
        return (
            "I found a similar use case already recorded in this session. "
            f"Summary: {existing.get('summary')}"
        )

    use_case = {
        "id": f"uc_{len(use_cases) + 1}",
        "signature": signature,
        "summary": summary,
        "status": "draft",
    }
    use_cases.append(use_case)
    _state().recorded_use_cases = use_cases

    tips: List[str] = []
    diseases = structured.get("diseases") or []
    if len(diseases) > 2:
        tips.append("Consider narrowing to fewer diseases for a clearer scope.")
    if not structured.get("TA"):
        tips.append("Add a therapeutic area to improve matching precision.")

    tip_text = " " + " ".join(tips) if tips else ""
    return f"No similar use case found. I stored this as a draft in session memory. Summary: {summary}.{tip_text}"


def build_reviewer_reply(structured: Dict[str, Any]) -> str:
    """Validate the purpose against required fields and prior SHACL results."""
    if not purpose_complete(structured):
        missing = [label for key, label, _ in FIELD_CONFIG if key in missing_fields(structured)]
        missing_text = ", ".join(missing) if missing else "required fields"
        return f"Review needs more detail. Missing: {missing_text}."

    final_result = _state().get("final_validation_result")
    final_error = _state().get("final_validation_error")
    if final_result:
        if final_result.get("conforms"):
            return "Review outcome: approved. The purpose conforms to the preferred descriptors."
        error_text = final_error or "Validation failed. Please adjust the selected diseases."
        return f"Review outcome: needs changes. {error_text}"

    return (
        "Review ready. Please run validation to confirm descriptor alignment, "
        "then I can finalize the decision."
    )


def clear_option_shortcuts() -> None:
    _state().pop("option_shortcuts", None)


def set_option_shortcuts(kind: str, target: str, suggestions: List[Dict[str, str]]) -> None:
    """Remember the numeric shortcuts currently surfaced to the user."""
    _state().option_shortcuts = {
        "kind": kind,
        "target": target,
        "suggestions": suggestions,
    }


def reset_final_validation() -> None:
    _state().final_validation_result = None
    _state().final_validation_error = ""
    _state().validation_report_payload = None
    _state().final_purpose_payload = None
    _state().final_validation_candidates = []
    _state().final_selected_leaves = {}
    _state().final_leaf_option_lookup = {}
    _state().final_dropdown_state = {}


def resolve_option_shortcut(message: str) -> str:
    """Translate `option 1` style replies into the suggestion they point at."""
    data = _state().get("option_shortcuts")
    if not data:
        return message
    match = _OPTION_PATTERN.match(message.strip())
    if not match:
        return message
    idx = int(match.group(1)) - 1
    suggestions = data.get("suggestions") or []
    if 0 <= idx < len(suggestions):
        return suggestions[idx]["label"]
    return message


def update_structured_data(data: Optional[Dict[str, Any]]) -> None:
    """Merge new structured fields into the conversation state and reset validation."""
    if not data:
        return

    current = _state().get("structured_data", fresh_structured_data())
    merged = fresh_structured_data()
    merged.update(current)

    for key, value in data.items():
        if key not in merged:
            continue
        if key == "diseases":
            merged[key] = list(value) if value else []
        else:
            if value not in (None, "", []):
                merged[key] = value

    changed = current != merged
    _state().structured_data = merged
    if changed:
        reset_final_validation()


def run_disease_validation(raw_diseases: Optional[List[str]]) -> Optional[ValidationOutcome]:
    """Cheap validation stub that defers heavy ontology work until final export."""
    state = _state()
    diseases_key = tuple(d.strip().lower() for d in (raw_diseases or []) if d)

    # We track the raw inputs but avoid expensive ontology work until the user
    # reaches the final validation flow, keeping the chat loop snappy.
    state.ontology_unknown_diseases = []
    state.ontology_generic_diseases = []
    state.ontology_linked_diseases = []
    state.ontology_validation_report = ""
    state.ontology_validation_error = ""
    state.validation_cached = None
    state.validation_locked = False
    state.validated_diseases_key = diseases_key
    state.ontology_conforms = False
    if raw_diseases:
        log_event(
            "validation_deferred",
            diseases=raw_diseases,
            message="Ontology linking deferred to final validation stage.",
        )
    return None


@lru_cache(maxsize=4096)
def _cached_leaf_paths(
    root_iri: str,
    limit: int = MAX_LEAF_PATHS_PER_DISEASE,
) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """DFS the MONDO graph and cache up to `limit` leaf paths under a root IRI."""
    if not root_iri or limit <= 0:
        return ()

    # Depth-first traversal so we can reuse the same leaf paths across reruns.
    stack: List[Tuple[str, Tuple[str, ...]]] = [(root_iri, (root_iri,))]
    visited: set[str] = set()
    leaves: List[Tuple[str, Tuple[str, ...]]] = []

    while stack:
        current, path = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        children = ontology_validation.CHILDREN_INDEX.get(current, [])
        if not children:
            leaves.append((current, path))
            if len(leaves) >= limit:
                break
            continue
        for child in reversed(children):
            stack.append((child, path + (child,)))

    if not leaves:
        leaves.append((root_iri, (root_iri,)))
    return tuple(leaves)


def _collect_leaf_nodes(root_iri: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return cached leaf paths as small dicts (and optionally limit the count)."""
    effective_limit = limit if limit is not None else MAX_LEAF_PATHS_PER_DISEASE
    cached = _cached_leaf_paths(root_iri, effective_limit)
    return [{"iri": iri, "path": list(path)} for iri, path in cached]


def _build_tree_structure(leaf_options: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert the flat list of leaf paths into a nested tree for the UI."""
    if not leaf_options:
        return None

    root_iris = leaf_options[0]["path_iris"]
    root_labels = leaf_options[0]["path_labels"]
    root: Dict[str, Any] = {
        "iri": root_iris[0],
        "label": root_labels[0],
        "path_iris": [root_iris[0]],
        "path_labels": [root_labels[0]],
        "children": {},
        "is_leaf": False,
    }

    for option in leaf_options:
        path_iris = option["path_iris"]
        path_labels = option["path_labels"]
        current = root

        for idx in range(1, len(path_iris)):
            iri = path_iris[idx]
            label = path_labels[idx]
            children = current.setdefault("children", {})
            if iri not in children:
                children[iri] = {
                    "iri": iri,
                    "label": label,
                    "path_iris": current["path_iris"] + [iri],
                    "path_labels": current["path_labels"] + [label],
                    "children": {},
                    "is_leaf": False,
                }
            current = children[iri]

        current["is_leaf"] = True
        current["leaf_display"] = option["display"]
        current["meddra"] = option.get("meddra")
        current.setdefault("children", {})

    _finalise_tree_children(root)
    return root


def _finalise_tree_children(node: Dict[str, Any]) -> None:
    """Prune empty child containers and sort children alphabetically."""
    children_map: Dict[str, Dict[str, Any]] = node.get("children", {})
    ordered = sorted(children_map.values(), key=lambda item: item["label"].lower())
    node["children"] = ordered
    for child in ordered:
        _finalise_tree_children(child)


def prepare_final_validation(structured: Optional[Dict[str, Any]]) -> bool:
    """Link high-level diseases to concrete leaves so the UI can prompt for selections."""
    state = _state()
    if not structured:
        state.final_validation_error = "Structured data is empty; complete the form before validation."
        state.final_validation_candidates = []
        return False

    raw_diseases = structured.get("diseases") or []
    if not raw_diseases:
        state.final_validation_error = "No diseases were captured; add at least one before validating."
        state.final_validation_candidates = []
        return False

    previous_selection = dict(state.get("final_selected_leaves", {}))
    reset_final_validation()

    candidates: List[Dict[str, Any]] = []
    lookup_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for raw in raw_diseases:
        trimmed = raw.strip()
        if not trimmed:
            continue
        candidate: Dict[str, Any] = {"raw": trimmed, "leaf_options": [], "tree": None, "error": None}
        # Link each free-text disease to MONDO so we can present leaf choices in the UI.
        try:
            result = link_many(
                [trimmed],
                ontology_validation.LABEL_INDEX,
                g=ontology_validation.MONDO_GRAPH,
                labels=ontology_validation.LABELS,
            )[0]
        except Exception as exc:  # pragma: no cover - defensive
            candidate["error"] = f"Linking failed: {exc}"
            candidates.append(candidate)
            continue

        if isinstance(result, UnknownDisease):
            suggestions = ", ".join(result.suggestions[:MAX_GENERIC_SUGGESTIONS]) or "no close matches found"
            candidate["error"] = f"Could not match '{trimmed}' in MONDO. Suggestions: {suggestions}"
            candidates.append(candidate)
            continue

        candidate["match"] = {
            "iri": result.iri,
            "label": result.label,
            "score": result.score,
            "source_text": result.source_text,
        }
        leaves = _collect_leaf_nodes(result.iri)
        leaf_options: List[Dict[str, Any]] = []
        for leaf in leaves:
            path_labels = [
                label_for(iri, g=ontology_validation.MONDO_GRAPH, labels=ontology_validation.LABELS)
                for iri in leaf["path"]
            ]
            display = " > ".join(path_labels)
            leaf_options.append(
                {
                    "iri": leaf["iri"],
                    "label": path_labels[-1],
                    "display": display,
                    "path_labels": path_labels,
                    "path_iris": leaf["path"],
                    "meddra": MEDDRA_LLT_MAP.get(leaf["iri"]),
                }
            )

        candidate["leaf_options"] = leaf_options
        option_lookup = {opt["display"]: opt for opt in leaf_options}
        lookup_map[trimmed] = option_lookup

        tree = _build_tree_structure(leaf_options)
        candidate["tree"] = tree

        default_selection: List[str] = []
        for display in previous_selection.get(trimmed, []):
            option = option_lookup.get(display)
            if not option:
                continue
            default_selection.append(display)

        _state().final_selected_leaves[trimmed] = default_selection
        state.final_dropdown_state.setdefault(trimmed, {"path": []})
        candidates.append(candidate)

    state.final_validation_candidates = candidates
    state.final_leaf_option_lookup = lookup_map
    state.final_validation_error = ""
    state.final_validation_result = None
    state.validation_report_payload = None
    state.final_purpose_payload = None

    log_event(
        "final_validation_prepare",
        diseases=raw_diseases,
        candidate_count=len(candidates),
        unmatched=sum(1 for item in candidates if item.get("error")),
    )
    return True


def current_selected_leaf_iris() -> Dict[str, List[str]]:
    """Translate display strings back into MONDO IRIs for final validation."""
    selections: Dict[str, List[str]] = {}
    lookup_map: Dict[str, Dict[str, Dict[str, Any]]] = _state().get("final_leaf_option_lookup", {})
    for raw, displays in _state().get("final_selected_leaves", {}).items():
        lookup = lookup_map.get(raw, {})
        iris = [lookup[display]["iri"] for display in displays if display in lookup]
        selections[raw] = iris
    return selections


def run_final_pyshacl_validation(
    structured: Optional[Dict[str, Any]],
    selected_map: Dict[str, List[str]],
) -> Optional[ValidationReport]:
    """Run the expensive SHACL validation once the user locks in specific leaves."""
    state = _state()
    if not structured:
        state.final_validation_error = "Structured data is empty; complete the form before final validation."
        state.final_validation_result = None
        state.final_purpose_payload = None
        return None

    if not state.final_validation_candidates:
        state.final_validation_error = "There are no validation candidates. Click Validate first."
        return None

    unresolved = [
        candidate["raw"]
        for candidate in state.final_validation_candidates
        if not candidate.get("error") and not selected_map.get(candidate["raw"])
    ]
    # Force the user to pick at least one leaf per disease before we commit to SHACL.
    if unresolved:
        state.final_validation_error = (
            "Select at least one lowest-level term for: " + ", ".join(unresolved)
        )
        state.final_validation_result = None
        state.final_purpose_payload = None
        return None

    leaf_records: List[Dict[str, Any]] = []
    lookup_map: Dict[str, Dict[str, Dict[str, Any]]] = state.get("final_leaf_option_lookup", {})

    # Convert UI selections back into MONDO IRIs with MedDRA metadata for logging/export.
    for raw, displays in state.final_selected_leaves.items():
        lookup = lookup_map.get(raw, {})
        for display in displays:
            option = lookup.get(display)
            if not option:
                continue
            leaf_records.append(
                {
                    "raw_input": raw,
                    "iri": option["iri"],
                    "label": option["label"],
                    "path_labels": option["path_labels"],
                    "path_iris": option["path_iris"],
                    "meddra": option.get("meddra"),
                    "id": iri_to_doid(option["iri"]),
                }
            )

    if not leaf_records:
        state.final_validation_error = "No lowest-level terms were selected."
        state.final_validation_result = None
        state.final_purpose_payload = None
        return None

    # SHACL needs unique IRIs; dedupe in case the user selects redundant leaves.
    unique_iris = list({record["iri"] for record in leaf_records})

    try:
        report = validate_diseases(
            unique_iris,
            None,
            children_index=ontology_validation.CHILDREN_INDEX,
            metadata=structured or {},
        )
    except Exception as exc:  # pragma: no cover - defensive
        state.final_validation_error = str(exc)
        state.final_validation_result = None
        state.final_purpose_payload = None
        return None

    state.ontology_validation_report = report.report_text
    state.ontology_conforms = bool(report.conforms)
    state.ontology_linked_diseases = [
        {
            "id": record["id"],
            "iri": record["iri"],
            "label": record["label"],
            "score": 1.0,
            "source_text": record["raw_input"],
            "path": record["path_labels"],
            "meddra": record.get("meddra"),
        }
        for record in leaf_records
    ]

    summary = {
        "conforms": bool(report.conforms),
        "selected_terms": [
            {
                "raw_input": record["raw_input"],
                "label": record["label"],
                "iri": record["iri"],
                "path": record["path_labels"],
                "meddra": record.get("meddra"),
            }
            for record in leaf_records
        ],
        "report_text": report.report_text,
        "field_messages": report.field_messages,
    }

    error_messages: List[str] = []
    if report.field_messages:
        error_messages.extend(report.field_messages)
    if report.generic_concepts:
        error_messages.append("Final validation failed. Adjust disease selections.")

    if not report.conforms and not error_messages:
        error_messages.append("Final validation failed. Please review the form.")

    state.final_validation_error = "\n".join(error_messages).strip()
    state.final_validation_result = summary
    state.validation_report_payload = summary

    if report.conforms:
        payload = build_purpose_payload(structured)
        state.final_purpose_payload = payload
    else:
        state.final_purpose_payload = None

    log_event(
        "shacl_validation_final",
        conforms=bool(report.conforms),
        disease_count=len(unique_iris),
    )

    return report


def coerce_to_schema(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract the JSON fields we care about from the LLM raw text."""
    if not raw_text:
        return None

    candidate_text = raw_text
    if "{" in raw_text and "}" in raw_text:
        first = raw_text.find("{")
        last = raw_text.rfind("}")
        if last > first:
            candidate_text = raw_text[first : last + 1]

    try:
        data = _state().json_loader(candidate_text) if "json_loader" in _state() else None
    except Exception:  # pragma: no cover - defensive
        data = None

    if data is None:
        try:
            import json

            data = json.loads(candidate_text)
        except Exception:
            log_event("parse_error", snippet=candidate_text[:200])
            return None

    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None

    normalised: Dict[str, Any] = {}
    for key, value in data.items():
        lookup_key = key.strip().lower()
        mapped_key = KEY_NORMALISATION.get(lookup_key, key)
        if mapped_key in EXPECTED_KEYS:
            normalised[mapped_key] = value

    if not normalised:
        return None

    coerced: Dict[str, Any] = {}
    for key in EXPECTED_KEYS:
        if key == "diseases":
            coerced[key] = normalised.get(key, [])
        else:
            coerced[key] = normalised.get(key)
    return coerced


def normalise_text(value: Any) -> Optional[str]:
    """Strip whitespace, convert numbers to strings, and reject empty values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def normalise_therapeutic_area(value: Any) -> Optional[str]:
    """Normalize therapeutic area to one of the allowed MeSH top-level categories."""
    text = normalise_text(value)
    if not text:
        return None

    trimmed = text.strip()
    lowered = trimmed.lower()

    for area in THERAPEUTIC_AREAS:
        if lowered == area.lower():
            return area

    for area in THERAPEUTIC_AREAS:
        if area.lower() in lowered:
            return area

    match = THERAPEUTIC_AREA_CODE_PATTERN.search(trimmed)
    if match:
        mapped = THERAPEUTIC_AREA_CODES.get(match.group(0).upper())
        if mapped:
            return mapped

    for keyword, area in THERAPEUTIC_AREA_SYNONYMS.items():
        if keyword in lowered:
            return area

    return None


def normalise_yes_no(value: Any) -> Optional[str]:
    """Normalise various truthy/falsy inputs into the literal yes/no strings."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if value == 1:
            return "yes"
        if value == 0:
            return "no"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "y"}:
            return "yes"
        if lowered in {"no", "n"}:
            return "no"
    return None


def normalise_diseases(value: Any) -> List[str]:
    """Turn strings or lists into a clean, de-duplicated disease list."""
    diseases: List[str] = []
    if isinstance(value, list):
        source = value
    elif isinstance(value, str):
        source = re.split(r"[;,/]| and ", value)
    else:
        source = []

    seen_lower: set[str] = set()
    for item in source:
        if not isinstance(item, str):
            item = str(item)
        cleaned = item.strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen_lower:
            diseases.append(cleaned)
            seen_lower.add(lowered)
    return diseases


def parse_structured_response(state: ResearchState) -> Dict[str, Any]:
    """Take the LLM raw JSON and normalise it into the session's structured data."""
    raw = state.get("raw_response", "")
    structured = coerce_to_schema(raw)
    if structured is None:
        run_disease_validation(None)
        return {"structured": None, "validation_result": None}

    normalised_structured: Dict[str, Any] = {
        "diseases": normalise_diseases(structured.get("diseases")),
        "medication": normalise_text(structured.get("medication")),
        "collaborator": normalise_yes_no(structured.get("collaborator")),
        "product_development": normalise_yes_no(structured.get("product_development")),
        "product_development_scope": normalise_text(structured.get("product_development_scope")),
        "TA": normalise_therapeutic_area(structured.get("TA")),
    }

    return {"structured": normalised_structured}


def validate_structured_response(state: ResearchState) -> Dict[str, Any]:
    """Kick off (deferred) ontology validation for any diseases in the payload."""
    structured = state.get("structured")
    if structured is None:
        run_disease_validation(None)
        return {"validation_result": None}

    run_disease_validation(structured.get("diseases"))
    return {"structured": structured, "validation_result": None}


def build_graph(call_model) -> StateGraph:
    """Wire the LangGraph workflow: LLM -> parse -> validate."""
    graph = StateGraph(ResearchState)
    # Single path workflow: generate LLM response -> parse JSON -> validate diseases.
    graph.add_node("generate", call_model)
    graph.add_node("parse", parse_structured_response)
    graph.add_node("validate", validate_structured_response)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "parse")
    graph.add_edge("parse", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


def missing_fields(structured: Dict[str, Any]) -> List[str]:
    """Return the keys that still need user input to be considered complete."""
    if not structured:
        return [key for key, _, _ in FIELD_CONFIG]

    missing: List[str] = []
    for key, _, _ in FIELD_CONFIG:
        value = structured.get(key)
        if key == "diseases":
            if not value:
                missing.append(key)
        elif key in {"collaborator", "product_development"}:
            if value not in {"yes", "no"}:
                missing.append(key)
        elif key == "product_development_scope":
            if structured.get("product_development") == "yes" and not value:
                missing.append(key)
        elif key in OPTIONAL_FIELDS:
            if value == "no":
                continue
            if key not in structured or value is None:
                if not _state().get(f"asked_{key}", False):
                    missing.append(key)
        else:
            if not value:
                missing.append(key)
    return missing


def missing_fields_for_chat(structured: Dict[str, Any]) -> List[str]:
    """Return missing fields the assistant should ask about."""
    return missing_fields(structured)


def purpose_complete(structured: Optional[Dict[str, Any]]) -> bool:
    """Convenience helper to see if the structured data satisfies all requirements."""
    if not structured:
        return False
    return len(missing_fields(structured)) == 0


def build_assistant_reply(structured: Dict[str, Any]) -> str:
    """Generate the assistant's next turn based on missing fields and progress."""
    clear_option_shortcuts()

    if not structured:
        return (
            "I'm ready to help craft your pharma research purpose. "
            "Tell me about the diseases you care about, any medication, "
            "product development plans and scope, and the therapeutic area."
        )

    acknowledgment = ""
    diseases = structured.get("diseases", [])
    if diseases and not _state().acknowledged_diseases:
        # Mirror the user's disease list once to show we've captured it, then avoid repetition.
        if len(diseases) == 1:
            acknowledgment = f"I understand you're working on {diseases[0]}. "
        elif len(diseases) == 2:
            acknowledgment = f"I understand you're investigating {diseases[0]} and {diseases[1]}. "
        else:
            disease_list = ", ".join(diseases[:-1]) + f", and {diseases[-1]}"
            acknowledgment = f"I understand you're working on {disease_list}. "
        _state().acknowledged_diseases = True

    missing = missing_fields_for_chat(structured)
    if not missing:
        summary_lines = []
        for key, label, _ in FIELD_CONFIG:
            summary_value = format_field_value(key, structured.get(key))
            summary_lines.append(f"- {label}: {summary_value}")
        summary_text = "Here is what I have captured:\n" + "\n".join(summary_lines)
        return (
            f"{summary_text}\n\nAll chat fields are filled. Please validate the purpose, then confirm it to generate the final payload."
        )

    next_field_key = missing[0]
    for key, label, prompt in FIELD_CONFIG:
        if key == next_field_key:
            if key in OPTIONAL_FIELDS:
                _state()[f"asked_{key}"] = True
            # Ask about one missing field at a time, but keep the user aware of what's left.
            remaining_labels = [
                lbl for k, lbl, _ in FIELD_CONFIG if k in missing and k != next_field_key
            ]
            chips = ""
            if remaining_labels:
                chips = " Still need: " + ", ".join(remaining_labels) + "."
            return f"{acknowledgment}{prompt}{chips}"

    missing_labels = ", ".join(
        label for key, label, _ in FIELD_CONFIG if key in missing
    )
    question_prompts = " ".join(
        prompt for key, _, prompt in FIELD_CONFIG if key in missing
    )

    return (
        f"{acknowledgment}"
        f"You are missing the fields: {missing_labels}. "
        f"{question_prompts}"
    )


def build_purpose_payload(structured: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the final export payload once SHACL validation passes."""
    linked_records = _state().get("ontology_linked_diseases", [])
    diseases_payload = [
        {
            "id": record["id"],
            "iri": record["iri"],
            "label": record["label"],
            "source_text": record["source_text"],
            "llt": record["label"],
            "path": record.get("path", []),
            "meddra": record.get("meddra"),
        }
        for record in linked_records
    ]

    medication_value = structured.get("medication")
    if medication_value == "no":
        medication_value = None

    payload = {
        "diseases": diseases_payload,
        "TA": structured.get("TA"),
        "medication": medication_value,
        "collaborator": structured.get("collaborator"),
        "product_development": structured.get("product_development"),
        "product_development_scope": structured.get("product_development_scope"),
        "ontology": {"name": "MedDRA LLT (via MONDO)", "version": ontology_validation.MONDO_VERSION},
    }

    _state().final_purpose_payload = payload
    return payload


def _load_meddra_llts(path: str = "data/mappings/meddra_llts.csv.gz") -> Dict[str, str]:
    """Read the gzipped MedDRA mapping so we can enrich MONDO leaves."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return {row["iri"]: row["meddra"] for row in reader if row.get("iri") and row.get("meddra")}
    except (FileNotFoundError, OSError):
        return {}


MEDDRA_LLT_MAP = _load_meddra_llts()
