# Purpose Creator Backend 🎯

This repository contains everything required to run the Purpose Creator backend: the FastAPI service, LangGraph workflow, ontology utilities, and data assets. It exposes a REST API that powers the standalone Streamlit UI stored in a separate frontend repo.

## Features

- 🧠 LangGraph workflow that extracts structured purpose fields
- 🗂️ MONDO-backed disease linking with pySHACL validation
- 🪵 Structured logging via `purpose_app/logging_utils.py`
- 📡 REST endpoints for session lifecycle, chat turns, disease selection, and validation runs

## Prerequisites

- Python 3.10+
- Access to the internal Apollo LLM (client id/secret and network reachability)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To run the pytest suite and linting tools install the extended requirements:

```bash
pip install -r requirements-dev.txt
```

## Configuration

Environment variables:

- `APOLLO_CLIENT_ID` *(required)*
- `APOLLO_CLIENT_SECRET` *(required)*
- `APOLLO_TOKEN_URL` *(optional override when off-network)*
- `APOLLO_BASE_URL` *(optional override when off-network)*
- `APOLLO_MODEL` (default `gpt-5-mini`)
- `APOLLO_MAX_TOKENS` (default `2048`)
- `APOLLO_TEMPERATURE` (default `0.1`)
- `APOLLO_TIMEOUT` (default `120`, seconds)
- `PURPOSE_LOG_PATH` *(optional)* – custom JSON log destination

The backend uses the `apollo_client` SDK (OpenAI-compatible). Install it from the internal Nexus index and set the credentials above.

## Run the API

```bash
PYTHONPATH=src uvicorn backend.api:app --host 0.0.0.0 --port 8080
```

Point the frontend repo (or any client) at `http://localhost:8080`.

### Field Schema & Formatting

The backend owns the single source of truth for purpose-field metadata (`purpose_app/field_schema.json`). Clients can fetch the schema (labels, prompts, and display hints) via:

```bash
GET /schema/fields
```

The Streamlit frontend consumes this endpoint to keep its layout fully aligned with the backend.

### Validation Rules

Final SHACL validation now enforces both ontology specificity and form completeness:

- Every disease must be confirmed at the MONDO leaf level.
- `medication` must be answered (use `"no"` when none is available).
- `collaborator` must explicitly be `"yes"` or `"no"`.
- `TA` (therapeutic area) must be populated.

The backend surfaces detailed error messages when these checks fail so the frontend can guide users before export.

### Run with Docker / ODS build

The Jenkins pipeline (ODS) builds from `docker/`. To mirror it locally:

```bash
# prepare docker context
rm -rf docker/src docker/data docker/requirements.txt
cp -rv src docker/src
cp -rv data docker/data
cp requirements.txt docker/requirements.txt

# build
docker build -f docker/Dockerfile docker -t purpose-backend
```

Run it (injecting Apollo credentials):

```bash
docker run --rm -p 8000:8080 \
  -e APOLLO_CLIENT_ID=*** \
  -e APOLLO_CLIENT_SECRET=*** \
  -e APOLLO_MODEL=gpt-5-mini \
  purpose-backend
```
Note: the container listens on `8080`; map any host port you prefer (e.g. `-p 8000:8080`).

## Project Structure

- `src/backend/` – FastAPI entry points, session management, and Apollo client wrapper
- `src/purpose_app/` – LangGraph workflow, prompts, normalization, and validation orchestration
- `src/ontology_validation/` – DO loader, fuzzy linker, SHACL validator, suggestion logic
- `src/streamlit_chat/` – Lightweight Streamlit UI to chat directly with the Apollo LLM
- `data/` – Ontology files and shapes (large assets; consider external storage for prod)
- `docs/` – Architecture notes shared with the frontend team
- `docker/` – OpenShift build context (Dockerfile plus copied `src/`/`data/`/`requirements.txt` during pipeline build)

## Testing

Running the ontology tests loads the full Disease Ontology snapshot (expect a long first run):

```bash
PYTHONPATH=. pytest tests -k linker
```

## Frontend

The UI is maintained separately in the sibling frontend repository. Configure it with `PURPOSE_BACKEND_URL` to reach this API.
