# Purpose Creator Architecture

This document complements `docs/AGENT_OVERVIEW.md` by focusing on the structural layers, primary modules, and data flows that power the Purpose Creator agent. File paths are repository-relative.

---

## 1. Layered Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Streamlit UI                        │
│  frontend/app.py                                            │
│  • Chat history, input form                                  │
│  • Structured summary + downloads                            │
└───────────────▲──────────────────────────────────────────────┘
                │ HTTP (JSON API)
┌───────────────┴──────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│  backend/api.py + backend/llm.py                             │
│  • Session lifecycle + LangGraph workflow                    │
│  • Apollo model calls + validation orchestration             │
└───────────────▲──────────────────────────────────────────────┘
                │ session_state adapter
┌───────────────┴──────────────────────────────────────────────┐
│                 Purpose Application Core                     │
│  purpose_app/common.py                                       │
│  • LangGraph workflow (generate → parse → validate)          │
│  • Normalisation, reply logic, export helpers                │
└───────────────▲──────────────────────────────────────────────┘
                │ ontology + validation requests
┌───────────────┴──────────────────────────────────────────────┐
│                   Ontology & Validation Layer                │
│  ontology_validation/*                                       │
│  • DO graph loading + label index                            │
│  • Fuzzy disease linking, child-map heuristics, and on-demand pySHACL │
│  • Subclass suggestions                                      │
└───────────────▲──────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────┐
│                   Data Assets & Infrastructure               │
│  data/ontology/doid.owl                                      │
│  ontology_validation/shapes.ttl                              │
│  requirements.txt / create a fresh env                        │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Frontend & Backend Entry Points

| Concern | Implementation |
| --- | --- |
| Page setup | `st.set_page_config`, custom CSS enforcing dark mode and hiding Streamlit chrome |
| Chat column | Renders `st.session_state.messages`, auto-scrolls via injected JS, captures user input through `st.form` |
| Structured panel | Displays normalized fields, ontology warnings, and the confirm/download button (`purpose_complete`) |
| Backend API | `backend/api.py` exposes `/sessions`, `/messages`, `/validate`, `/selections` endpoints |
| Telemetry | `log_event` records chat turns, validation outcomes, and LLM request metadata | JSON logs rotate under `logs/purpose_app.log` by default |

Each input submission now travels to the backend, which attaches the appropriate session state, runs the LangGraph workflow defined in `purpose_app/common.py`, and returns the updated view model back to the Streamlit frontend.

---

## 3. Purpose Application Core (`purpose_app/common.py`)

### 3.1 LangGraph Workflow

```
START
  ↓
generate  (call_*_model → adds raw_response)
  ↓
parse      (coerce_to_schema, normalise fields)
  ↓
validate   (run_disease_validation → linked/unknown/generic/status)
  ↓
END
```

`ResearchState` (a `TypedDict`) travels through the graph and is updated in-place. The workflow returns a dict that merges back into Streamlit session state.

### 3.2 Validation & State

`run_disease_validation` orchestrates the ontology-backed pipeline:

1. `link_many` (fuzzy matching) produces `LinkedDisease` and `UnknownDisease` records.
3. Session state receives:
   - `ontology_linked_diseases`: DOID/IRI/label/score/source text.
   - `ontology_generic_diseases`: parents needing refinement + child suggestions.
   - `ontology_unknown_diseases`: unmatched strings with top fuzzy suggestions.
4. `build_assistant_reply` inspects those queues. If all diseases are resolved, it progresses through the required purpose fields and lists any remaining items inline (“Still need: …”).
5. `build_purpose_payload` composes the export JSON consumed by the sidebar button (and optional in-chat confirmation).

### 3.3 Normalisation Helpers

The module also exposes:

- `normalise_diseases`, `normalise_text`, `normalise_yes_no` – clean raw LLM fields.
- `missing_fields`, `purpose_complete` – gate keepers for the workflow and download UI.
- `format_field_value` – consistent human-readable display for the structured panel/chat summaries.
- `resolve_option_shortcut` – maps replies like “option 4” to the underlying suggestion label.

---

## 4. Ontology Layer (`ontology_validation/`)

| Module | Responsibilities |
| --- | --- |
| `ontology_loader.py` | Loads the DO graph (`load_graph`), derives version info, builds the normalized label/synonym index (`build_label_index`). |
| `normalization.py` | Handles lowercasing, ASCII folding, punctuation stripping, and special case swaps (e.g., “cancer of lung” ⇄ “lung cancer”). |
| `disease_linker.py` | - Fuzzy matching via RapidFuzz (`link_best`, `link_many`) <br> - Cached label lookup (`label_for`) <br> - Top label suggestions for unknown inputs (`_top_label_suggestions`). |
| `validator.py` | Builds a mini RDF data graph, runs `pyshacl.validate` with `ontology_validation/shapes.ttl`, and returns a `ValidationReport`. |
| `suggestions.py` | Queries subclasses via SPARQL to suggest more specific options when SHACL reports a generic concept. |

### Shapes File (`ontology_validation/shapes.ttl`)

```turtle
ex:ResearchIntentShape     Ensures at least one `ex:diseaseConcept`
ex:DiseaseSpecificityShape Flags concepts with subclasses (generic umbrella)
```

### Ontology Data (`data/ontology/doid.owl`)

Pinned DO snapshot (~26 MB). The loader caches the graph on first import, keeping memory usage around 150 MB and avoiding repeated parsing.

---

## 5. Testing

Pytests rely on the real ontology snapshot; run them via the designated conda environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pytest
```

| Test file | Focus |
| --- | --- |
| `tests/test_linker.py` | Abbreviation handling (e.g., “NSCLC”), ambiguous labels (“diabetes” resolving to “diabetes mellitus”). |
| `tests/test_suggestions.py` | Quality of child suggestions for representative parents (lung cancer). |
| `tests/test_validator.py` | SHACL specificity enforcement and automatic resolution when a more specific child (e.g., type 2 diabetes) replaces a generic parent. |
| `tests/test_smoke.py` | End-to-end smoke coverage for multiple diseases, misspellings, and unknown terms. |

---

## 6. Operational Notes

- **Environment configuration**: create a fresh environment (e.g., `python -m venv .venv`) and `pip install -r requirements.txt`.
- **LLM endpoint**: Apollo via `apollo_client.OpenAI`; set `APOLLO_CLIENT_ID`/`APOLLO_CLIENT_SECRET` (and optional `APOLLO_TOKEN_URL`, `APOLLO_BASE_URL`, `APOLLO_MODEL`).
- **Initial latency**: expect a one-time cost on startup as the ontology is parsed and indexed; subsequent runs reuse cached data structures.
- **Extensibility**: To add custom behaviour (e.g., new structured fields), extend the `FIELD_CONFIG` list and update the normalization/export helpers in `purpose_app/common.py`.
- **Observability**: Log events are JSON-encoded via `purpose_app/logging_utils.py` (location configurable with `PURPOSE_LOG_PATH`).

For a narrative walkthrough of the runtime behaviour, see `docs/AGENT_OVERVIEW.md`.
- `log_event` (imported from `purpose_app.logging_utils`) encapsulates structured telemetry; `add_message` and `run_disease_validation` call it automatically.
