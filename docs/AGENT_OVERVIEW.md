# Purpose Creator Agent Overview

This document describes how the Streamlit + LangGraph application assembles, validates, and exports a pharma research “purpose” record. File references are relative to the repository root (for example `frontend/app.py` or `backend/api.py`).

---

## 1. High-Level Flow

1. **Streamlit entrypoint** (`frontend/app.py`) renders the chat UI, handles user input, and displays the structured summary panel while talking to the API.
2. **FastAPI backend** (`backend/api.py`) hosts the LangGraph workflow, manages per-session state, and proxies all LLM/validation logic.
2. **LangGraph workflow** (`purpose_app/common.py`) orchestrates the core pipeline:
   - Call the LLM to extract candidate fields.
   - Parse the model output into structured data.
3. **Ontology services** (`ontology_validation/*`) load a pinned DO snapshot, index labels/synonyms, fuzzy-match user diseases, run pySHACL, and produce refinement suggestions.
4. **Tests** (`tests/*.py`) exercise the linker, validator, and suggestion logic against the bundled ontology.

The figure below summarizes the runtime loop:

```
Streamlit Chat ──► LangGraph (generate → parse → validate) ──► Session State
       ▲                                                                │
       └────────────────── UI updates (messages, chips, buttons) ◄──────┘
```

---

## 2. Streamlit Layer

### 2.1 Entry Points

- `frontend/app.py` – Streamlit UI that fetches/updates backend session state through HTTP.
- `backend/api.py` – FastAPI server that wires LangGraph, ontology helpers, and the Apollo model client together.

The frontend still imports `purpose_app.common` for formatting helpers, but all LangGraph work and validation live behind the backend. Key responsibilities:

| Section | Responsibilities | Notes |
| --- | --- | --- |
| Page setup | `st.set_page_config`, custom CSS | Forces dark mode, hides Streamlit chrome |
| Chat column | Displays message history, collects user input (`st.form`) | Auto-scrolls to newest turn via injected JS; supports quick replies like `"option 4"` that map to a specific disease |
| Structured panel | Shows captured fields, validation alerts, download button | Uses `purpose_complete` to enable “Confirm Purpose” |
| Model call | `backend.llm.call_local_model` | Supplies `SYSTEM_INSTRUCTIONS`, wraps the Apollo response, emits telemetry via `logging_utils.log_event` |

### 2.2 Session State Keys

Managed in `purpose_app/common.py:init_session_state` and augmented by the validation flow:

| Key | Purpose |
| --- | --- |
| `messages` | Chat history with canonical content and optional `display` text (preserves inputs like “option 4”) |
| `structured_data` | Latest normalized payload (`diseases`, `TA`, `medication`, `collaborator`, `product_development`) |
| `thinking` | Boolean spinner flag while awaiting LLM output |
| `ontology_linked_diseases` | List of resolved concepts with DOID, IRI, label, score, original text |
| `ontology_generic_diseases` | Generic concepts still requiring subtype selection |
| `ontology_unknown_diseases` | Inputs that did not match the ontology (with top fuzzy suggestions) |
| `ontology_validation_report` | Text rendering of pySHACL output (or a note when the child-map shortcut is active) |
| `validation_cached` / `validation_locked` / `validated_diseases_key` | Track when SHACL validation can be skipped after the first pass |
| `option_shortcuts` | Captures the numbered suggestions currently shown so the user can respond with an option number |
| `acknowledged_diseases` | Prevents repeating the first “I understand…” acknowledgement |

---

## 3. Core Pipeline (`purpose_app/common.py`)

This module supplies everything the UI needs: model instructions, normalization helpers, LangGraph nodes, validation, export, and helper UI text.

### 3.1 LangGraph Workflow

```
START
  ↓
generate ──► parse ──► validate
  │           │          │
  │           │          └─► returns validation state (linked, unknown, report)
  │           └─► normalizes diseases, medication, yes/no answers
  └─► `call_*_model` in app-specific file
```

Each node operates on `ResearchState` (`TypedDict` with `user_messages`, `raw_response`, `structured`, `validation_result`).

### 3.2 Disease Linking & Validation

- `run_disease_validation`:
  1. Invokes `ontology_validation.disease_linker.link_many` to map strings to DO IRIs (or mark as unknown).
  2. Runs `ontology_validation.validator.validate_diseases` (pySHACL with RDFS inference) the first time a new disease list appears.
  3. Caches the SHACL report; subsequent turns skip expensive validation unless the disease list changes.
  4. Populates `ontology_generic_diseases`, `ontology_unknown_diseases`, and `ontology_linked_diseases` in session state.
- `build_assistant_reply` inspects these queues—generic issues prompt subtype selection, unknown issues propose fuzzy suggestions, otherwise it asks the next missing field and lists any remaining fields inline (“Still need: Medication, Collaborator…”).
- `build_assistant_reply` inspects these queues—generic issues prompt subtype selection (and populate `option_shortcuts` so replies like “option 4” work), unknown issues propose fuzzy suggestions, otherwise it asks the next missing field and lists any remaining fields inline (“Still need: Medication, Collaborator…”).

### 3.3 Export Helpers

- `build_purpose_payload` creates the final JSON payload used by both the sidebar download (`frontend/app.py`) and any in-chat confirmation features.
- Formatting helpers (`format_field_value`, `format_numbered_list`) prepare human-friendly strings for the chat and the structured panel.

### 3.4 Telemetry & Logging

- `purpose_app/logging_utils.py` initialises a rotating JSON logger (defaults to `logs/purpose_app.log`, overridable via `PURPOSE_LOG_PATH`).
- High-level events—chat turns, LLM requests/responses, validation results, and parse errors—are captured via `log_event`, enabling downstream monitoring or ingestion into enterprise observability stacks.

---

## 4. Ontology Services (`ontology_validation/`)

### 4.1 `ontology_loader.py`

- `load_graph` – Parses `data/ontology/doid.owl` once, infers version via `owl:versionInfo` (or file metadata/sha).
- `build_label_index` – Collects English `rdfs:label`, `skos:altLabel`, and `oboInOwl:hasExactSynonym` entries into a normalized lookup usable by RapidFuzz.

### 4.2 `normalization.py`

- `normalize` – Lowercases, ASCII-flattens, strips punctuation, and handles “cancer of X” ↔ “X cancer” symmetry for better fuzzy matching.

### 4.3 `disease_linker.py`

- `link_best` – Fuzzy matches a term against the label index (preferring exact or “closest” matches), returns `LinkedDisease` or `None`.
- `link_many` – Applies the matcher to a list of terms, returning `LinkedDisease` or `UnknownDisease` entries.
- `label_for` – Cached helper to fetch preferred labels for IRIs from the RDF graph.

### 4.4 `validator.py`

- Creates a temporary RDF data graph with a single `ex:ResearchIntent` node and properties `ex:diseaseConcept` pointing to the chosen concepts.
- Runs `pyshacl.validate` with `ontology_validation/shapes.ttl`, which enforces two rules:
  1. At least one disease must be provided (`sh:minCount 1`).
  2. Any concept that has a subclass is flagged as “generic” (the SPARQL constraint checks for `rdfs:subClassOf` children).
- Returns a `ValidationReport` dataclass with `.conforms`, `.generic_concepts`, and `.report_text`.

### 4.5 `suggestions.py`

- `suggest_children` – SPARQL query to enumerate direct subclasses of a given concept (filtered to English labels) used to populate subtype suggestions.

---

## 5. Data & Dependencies

- **Ontology** (`data/ontology/doid.owl`) – Pinned Disease Ontology snapshot (~26 MB) loaded at startup.
- **Shapes** (`ontology_validation/shapes.ttl`) – SHACL constraints for research intent validation.
- **Python Requirements** (`requirements.txt`) – Uses `fastapi`, `streamlit`, `langgraph`, `apollo-client` (OpenAI-compatible), `rdflib`, `pyshacl`, `rapidfuzz` (install with `pip install -r requirements.txt` inside the active environment).

---

## 6. Testing

Run the suite inside the configured environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pytest
```

Tests include:

| File | Purpose |
| --- | --- |
| `tests/test_linker.py` | Confirms abbreviations (e.g., “NSCLC”) and ambiguous terms (“diabetes”) resolve to the expected ontology nodes. |
| `tests/test_suggestions.py` | Ensures subtype suggestions for key parents (e.g., lung cancer) include representative children. |
| `tests/test_validator.py` | Verifies SHACL flags generic parents (e.g., diabetes mellitus) but passes once a child concept is supplied. |

---

## 7. Operational Notes

- **Environment Variables**: `APOLLO_CLIENT_ID`, `APOLLO_CLIENT_SECRET` (plus optional `APOLLO_TOKEN_URL`, `APOLLO_BASE_URL`, `APOLLO_MODEL`) for the backend; `PURPOSE_BACKEND_URL` for the frontend → backend connection.
- **First-run latency**: Loading the full DO graph and building the label index consumes ~150 MB RAM; this happens once per process thanks to module-level caching.
- **State-driven UI**: All chat logic, field prompts, and completion gating are derived from `st.session_state` so the UI stays in sync without re-running expensive steps.

For quick orientation, refer to these primary files:

- `frontend/app.py` – Streamlit UI that renders chat/history, structured purpose panel, and validation controls.
- `backend/api.py` – FastAPI backend that owns the LangGraph workflow, state store, and validations.
- `backend/llm.py` – Apollo client wrapper used by the workflow.
- `purpose_app/common.py` – Core workflow, validation orchestrator, reply logic, export helpers.
- `purpose_app/logging_utils.py` – Structured logging helper.
- `ontology_validation/` – Ontology loading, fuzzy linking, SHACL validation, and subtype suggestions.
- `docs/AGENT_OVERVIEW.md` (this file) – Architectural summary.
