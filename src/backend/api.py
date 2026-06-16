"""FastAPI backend that wraps purpose_app graph logic and the Apollo LLM client to serve
the chat/validation workflow used by the Streamlit frontend."""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from importlib import metadata
from typing import Any, Dict

from fastapi import FastAPI, HTTPException

from backend.agents import (
    AGENT_DESCRIPTIONS,
    AGENT_RECEPTIONIST,
    AgentDependencies,
    AgentRegistry,
    is_reset_request,
    receptionist_prompt,
)
from backend.llm import call_local_model, call_support_rag_model
from backend.models import (
    CollaboratorRequest,
    FaqContextRequest,
    MessageRequest,
    PurposeRequest,
    SelectionRequest,
    SessionResponse,
)
from backend.session import SessionState, SessionStore
from purpose_app import (
    add_message,
    build_graph,
    current_selected_leaf_iris,
    fresh_structured_data,
    get_field_schema,
    init_session_state,
    prepare_final_validation,
    resolve_option_shortcut,
    run_final_pyshacl_validation,
    update_structured_data,
)
from purpose_app.state_manager import configure_session_state

app = FastAPI(title="Purpose Creator Backend", version="1.0.0")

session_store = SessionStore()
graph = build_graph(call_local_model)
agent_registry = AgentRegistry(
    AgentDependencies(
        graph=graph,
        call_support_model=call_support_rag_model,
    )
)


def _attach_state(session_id: str) -> SessionState:
    """Look up the session by id and hydrate purpose_app's context with its state."""
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    configure_session_state(state)
    if not state.get("_initialized"):
        init_session_state()
        state["_initialized"] = True
    state["session_id"] = session_id
    return state


def _serialize_state(state: SessionState) -> Dict[str, Any]:
    """Shape the raw session state into the response payload expected by the UI."""
    structured = state.get("structured_data") or fresh_structured_data()
    messages = state.get("messages", [])
    return {
        "messages": messages,
        "message_count": len(messages),
        "session_created_at": state.get("created_at", ""),
        "structured_data": structured,
        "ontology_unknown_diseases": state.get("ontology_unknown_diseases", []),
        "ontology_generic_diseases": state.get("ontology_generic_diseases", []),
        "ontology_linked_diseases": state.get("ontology_linked_diseases", []),
        "ontology_validation_report": state.get("ontology_validation_report", ""),
        "ontology_validation_error": state.get("ontology_validation_error", ""),
        "ontology_conforms": state.get("ontology_conforms", False),
        "final_validation_candidates": state.get("final_validation_candidates", []),
        "final_selected_leaves": state.get("final_selected_leaves", {}),
        "final_validation_result": state.get("final_validation_result"),
        "final_validation_error": state.get("final_validation_error", ""),
        "final_purpose_payload": state.get("final_purpose_payload"),
        "validation_report_payload": state.get("validation_report_payload"),
        "show_validation_toast": state.get("show_validation_toast", False),
        "selected_purpose": state.get("selected_purpose", ""),
        "active_agent": state.get("active_agent", AGENT_RECEPTIONIST),
        "pending_purpose_selection": state.get("pending_purpose_selection", False),
        "faq_context": state.get("faq_context", ""),
        "support_rag_last_hits": state.get("support_rag_last_hits", []),
        "last_raw_response": state.get("last_raw_response", ""),
        "last_response_fallback": state.get("last_response_fallback", False),
    }


@app.get("/schema/fields")
def get_field_schema_view() -> Dict[str, Any]:
    """Expose the shared purpose field/schema metadata to any client."""
    return get_field_schema()


@app.get("/healthz")
def healthcheck() -> Dict[str, str]:
    """Simple readiness probe used by Docker health checks."""
    return {"status": "ok"}


def _mask_secret(value: str | None) -> Dict[str, Any]:
    if not value:
        return {"set": False, "preview": "<unset>", "sha256": None, "length": 0}

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if len(value) <= 6:
        preview = "***"
    else:
        preview = f"{value[:3]}...{value[-2:]}"
    return {"set": True, "preview": preview, "sha256": digest, "length": len(value)}


def _list_installed_packages() -> list[Dict[str, str]]:
    packages = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or dist.name or "unknown"
        packages.append({"name": name, "version": dist.version})
    packages.sort(key=lambda item: item["name"].lower())
    return packages


def _apollo_client_status() -> Dict[str, Any]:
    status: Dict[str, Any] = {"importable": False, "module_version": None, "package_version": None, "error": None}
    try:
        import apollo_client  # type: ignore

        status["importable"] = True
        status["module_version"] = getattr(apollo_client, "__version__", None)
    except Exception as exc:  # pragma: no cover - debug endpoint
        status["error"] = f"{type(exc).__name__}: {exc}"

    try:
        status["package_version"] = metadata.version("apollo-client")
    except metadata.PackageNotFoundError:
        status["package_version"] = None
    return status


@app.get("/debug/apollo")
def debug_apollo_config() -> Dict[str, Any]:
    """Expose Apollo-related configuration for troubleshooting (secrets are masked)."""
    return {
        "apollo": {
            "APOLLO_CLIENT_ID": _mask_secret(os.getenv("APOLLO_CLIENT_ID")),
            "APOLLO_CLIENT_SECRET": _mask_secret(os.getenv("APOLLO_CLIENT_SECRET")),
            "APOLLO_TOKEN_URL": os.getenv("APOLLO_TOKEN_URL"),
            "APOLLO_BASE_URL": os.getenv("APOLLO_BASE_URL"),
            "APOLLO_MODEL": os.getenv("APOLLO_MODEL", "gpt-5-mini"),
            "APOLLO_TIMEOUT": os.getenv("APOLLO_TIMEOUT", "120"),
            "APOLLO_MAX_TOKENS": os.getenv("APOLLO_MAX_TOKENS", "2048"),
            "APOLLO_TEMPERATURE": os.getenv("APOLLO_TEMPERATURE", "0.1"),
        },
        "network": {
            "HTTP_PROXY": os.getenv("HTTP_PROXY"),
            "HTTPS_PROXY": os.getenv("HTTPS_PROXY"),
            "NO_PROXY": os.getenv("NO_PROXY"),
            "REQUESTS_CA_BUNDLE": os.getenv("REQUESTS_CA_BUNDLE"),
            "SSL_CERT_FILE": os.getenv("SSL_CERT_FILE"),
        },
    }


@app.get("/debug/packages")
def debug_packages() -> Dict[str, Any]:
    """Expose installed package versions for troubleshooting."""
    return {
        "python": {"version": sys.version, "executable": sys.executable},
        "apollo_client": _apollo_client_status(),
        "packages": _list_installed_packages(),
    }


@app.get("/debug/test-llm")
def debug_test_llm() -> Dict[str, Any]:
    """Minimal LLM round-trip: create client, send 'ping', return result."""
    import time
    import traceback

    import requests as req

    result: Dict[str, Any] = {
        "client_ok": False,
        "llm_ok": False,
        "client_error": None,
        "llm_error": None,
        "llm_response": None,
        "elapsed_ms": 0,
        "token_test": None,
    }

    from backend.llm import _apollo_client_settings, _create_apollo_client

    settings = _apollo_client_settings()
    result["settings_summary"] = {
        "model": settings.get("model_name"),
        "timeout": settings.get("timeout"),
        "token_url": settings.get("token_url"),
        "base_url": settings.get("base_url"),
        "client_id_set": bool(settings.get("client_id")),
        "client_secret_set": bool(settings.get("client_secret")),
    }

    # ── Raw token endpoint probe ──
    token_url = settings.get("token_url")
    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    if token_url and client_id and client_secret:
        try:
            tok_resp = req.post(
                token_url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=15,
                headers={"Accept": "application/json"},
            )
            result["token_test"] = {
                "status_code": tok_resp.status_code,
                "headers": dict(tok_resp.headers),
                "body_preview": tok_resp.text[:2000],
                "content_type": tok_resp.headers.get("Content-Type", ""),
            }
        except Exception as exc:
            result["token_test"] = {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
    else:
        result["token_test"] = {"error": "Missing token_url, client_id, or client_secret"}

    client, client_error, client_id_prefix = _create_apollo_client(settings)
    result["client_id_prefix"] = client_id_prefix
    if client_error or client is None:
        result["client_error"] = client_error or "Client is None"
        return result

    result["client_ok"] = True

    try:
        t0 = time.time()
        completion = client.chat.completions.create(
            model=settings["model_name"],
            messages=[
                {"role": "system", "content": "Reply with exactly: pong"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        elapsed = int((time.time() - t0) * 1000)
        reply = (completion.choices[0].message.content or "").strip()
        result["llm_ok"] = True
        result["llm_response"] = reply
        result["elapsed_ms"] = elapsed
    except Exception as exc:
        result["llm_error"] = f"{type(exc).__name__}: {exc}"
        result["llm_traceback"] = traceback.format_exc()

    return result


@app.post("/sessions", response_model=SessionResponse)
def create_session() -> SessionResponse:
    """Create a new conversation session and bootstrap purpose_app state."""
    session_id, state = session_store.create()
    configure_session_state(state)
    init_session_state()
    state["_initialized"] = True
    state["session_id"] = session_id
    state["created_at"] = datetime.now(timezone.utc).isoformat()
    # Add initial welcome message from receptionist
    add_message("assistant", receptionist_prompt())
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    """Return the latest state for a previously created session."""
    state = _attach_state(session_id)
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.get("/sessions/{session_id}/export")
def export_conversation(session_id: str) -> Dict[str, Any]:
    """Export the full conversation history as a downloadable payload."""
    state = _attach_state(session_id)
    messages = state.get("messages", [])
    return {
        "session_id": session_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "message_count": len(messages),
        "messages": messages,
        "active_agent": state.get("active_agent", AGENT_RECEPTIONIST),
        "selected_purpose": state.get("selected_purpose", ""),
        "structured_data": state.get("structured_data"),
    }


@app.get("/agents")
def list_agents() -> Dict[str, Any]:
    """Return available agents with descriptions."""
    return {
        "agents": [
            {"id": agent_id, "name": agent_id.replace("_", " ").title(), "description": desc}
            for agent_id, desc in AGENT_DESCRIPTIONS.items()
        ]
    }


@app.post("/sessions/{session_id}/purpose", response_model=SessionResponse)
def set_purpose(session_id: str, payload: PurposeRequest) -> SessionResponse:
    """Store the user's selected research purpose for the current session."""
    state = _attach_state(session_id)
    purpose = payload.purpose.strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="Purpose cannot be empty.")

    state["selected_purpose"] = purpose
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/faq-context", response_model=SessionResponse)
def set_faq_context(session_id: str, payload: FaqContextRequest) -> SessionResponse:
    """Store FAQ context that the FAQ agent should use when answering questions."""
    state = _attach_state(session_id)
    state["faq_context"] = payload.context.strip()
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/collaborator", response_model=SessionResponse)
def set_collaborator(session_id: str, payload: CollaboratorRequest) -> SessionResponse:
    """Store the user's collaborator flag for the current session."""
    state = _attach_state(session_id)
    update_structured_data({"collaborator": "yes" if payload.collaborator else "no"})
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/messages", response_model=SessionResponse)
def send_message(session_id: str, payload: MessageRequest) -> SessionResponse:
    """Add a user turn, run the LangGraph workflow, and append the assistant reply."""
    import logging
    import traceback

    state = _attach_state(session_id)
    raw_message = payload.content.strip()
    if not raw_message:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    canonical_message = resolve_option_shortcut(raw_message)
    display_text = raw_message if raw_message == canonical_message else f"{raw_message} ({canonical_message})"
    add_message("user", canonical_message, display_content=display_text)

    if is_reset_request(raw_message):
        agent_registry.activate_agent(state, AGENT_RECEPTIONIST)
        return SessionResponse(session_id=session_id, state=_serialize_state(state))

    # Agent switching is intentionally disabled mid-chat.
    # A new chat should be started to activate a different agent.
    try:
        agent_registry.handle(state, raw_message)
    except Exception as exc:  # pragma: no cover - defensive
        tb = traceback.format_exc()
        logging.getLogger(__name__).error("agent_registry.handle() failed: %s\n%s", exc, tb)
        add_message(
            "assistant",
            "\u26a0\ufe0f Something went wrong while processing your message. "
            "Please try again or start a new chat.\n\n"
            f"_Error: {type(exc).__name__}: {exc}_",
        )

    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/prepare-validation", response_model=SessionResponse)
def prepare_validation(session_id: str) -> SessionResponse:
    """Trigger candidate generation so the UI can prompt for concrete disease selections."""
    state = _attach_state(session_id)
    structured = state.get("structured_data")
    prepare_final_validation(structured)
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/run-validation", response_model=SessionResponse)
def run_validation(session_id: str) -> SessionResponse:
    """Execute the final pySHACL validation run using the user's selected leaf IRIs."""
    state = _attach_state(session_id)
    structured = state.get("structured_data")
    selections = current_selected_leaf_iris()
    run_final_pyshacl_validation(structured, selections)
    return SessionResponse(session_id=session_id, state=_serialize_state(state))


@app.post("/sessions/{session_id}/selections", response_model=SessionResponse)
def update_selections(session_id: str, payload: SelectionRequest) -> SessionResponse:
    """Persist the UI's selected MONDO leaves for a raw disease before validation."""
    state = _attach_state(session_id)
    raw = payload.raw.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Raw disease label cannot be empty.")

    selections = payload.selections
    lookup = state.setdefault("final_selected_leaves", {})
    lookup[raw] = selections
    return SessionResponse(session_id=session_id, state=_serialize_state(state))
