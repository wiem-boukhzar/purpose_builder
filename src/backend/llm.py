"""Apollo LLM client helpers used by backend agents.

This module now supports two support modes:
1) Basic docs-grounded Q&A (`call_support_model`)
2) RAG with Apollo Qdrant vector store (`call_support_rag_model`)
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from purpose_app import SYSTEM_INSTRUCTIONS, log_event
from purpose_app.common import ResearchState
from purpose_app.state_manager import get_session_state


def _build_conversation_messages(session_state: Dict[str, Any]) -> list[Dict[str, str]]:
    """Replay the chat so providers receive full context for structured extraction."""
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTIONS}]
    for msg in session_state.get("messages", []):
        content = msg.get("display") or msg.get("content", "")
        role = msg.get("role")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append(
        {
            "role": "user",
            "content": "Based on the conversation above, extract all the information and respond with the JSON object only.",
        }
    )
    return messages


def _apollo_client_settings() -> Dict[str, Any]:
    return {
        "model_name": os.getenv("APOLLO_MODEL", "gpt-5-mini"),
        "max_tokens": int(os.getenv("APOLLO_MAX_TOKENS", "2048")),
        "temperature": float(os.getenv("APOLLO_TEMPERATURE", "0.1")),
        "timeout": int(os.getenv("APOLLO_TIMEOUT", "120")),
        "client_id": os.getenv("APOLLO_CLIENT_ID"),
        "client_secret": os.getenv("APOLLO_CLIENT_SECRET"),
        "token_url": os.getenv("APOLLO_TOKEN_URL"),
        "base_url": os.getenv("APOLLO_BASE_URL"),
    }


def _safe_int(value: str | None, default: int, minimum: int = 0) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _support_rag_settings() -> Dict[str, Any]:
    embedding_model = os.getenv("APOLLO_RAG_EMBEDDING_MODEL") or os.getenv(
        "APOLLO_EMBEDDING_MODEL", "text-embedding-3-small"
    )
    chunk_size = _safe_int(os.getenv("APOLLO_RAG_CHUNK_SIZE"), 900, minimum=200)
    chunk_overlap = _safe_int(os.getenv("APOLLO_RAG_CHUNK_OVERLAP"), 120, minimum=0)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(chunk_size // 6, 0)

    return {
        "embedding_model": embedding_model,
        "top_k": _safe_int(os.getenv("APOLLO_RAG_TOP_K"), 5, minimum=1),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "collection_prefix": os.getenv("APOLLO_RAG_COLLECTION_PREFIX", "purpose_support_qa"),
    }


def _create_apollo_client(settings: Dict[str, Any]) -> tuple[Any | None, str | None, str | None]:
    try:
        from apollo_client import ApolloConfig, OpenAI
    except Exception as exc:  # pragma: no cover - optional dependency
        error = (
            "Apollo client SDK is not installed. "
            "Install 'apollo-client' from the internal Nexus index to enable this provider."
        )
        log_event("llm_response", provider="apollo", status="error", error=str(exc))
        return None, error, None

    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    client_id_prefix = client_id[:5] if client_id else None
    missing = [
        name
        for name, value in [("APOLLO_CLIENT_ID", client_id), ("APOLLO_CLIENT_SECRET", client_secret)]
        if not value
    ]
    if missing:
        error = f"Apollo credentials missing: {', '.join(missing)}"
        log_event(
            "llm_response",
            provider="apollo",
            status="error",
            error=error,
            client_id_prefix=client_id_prefix,
        )
        return None, error, client_id_prefix

    try:
        config = ApolloConfig(
            client_id=client_id,
            client_secret=client_secret,
            token_url=settings.get("token_url"),
            base_url=settings.get("base_url"),
        )
        client = OpenAI(config=config, timeout=settings.get("timeout"))
    except Exception as exc:
        error = f"Apollo client initialisation failed: {type(exc).__name__}: {exc}"
        log_event("llm_response", provider="apollo", status="error", error=error, client_id_prefix=client_id_prefix)
        return None, error, client_id_prefix

    return client, None, client_id_prefix


def _create_qdrant_client(settings: Dict[str, Any]) -> tuple[Any | None, str | None]:
    try:
        from apollo_client import ApolloConfig, QdrantClient
    except Exception as exc:  # pragma: no cover - optional dependency
        error = (
            "Apollo Qdrant client is not available. "
            "Install 'apollo-client' with vector-store support."
        )
        log_event("rag_index", status="error", error=str(exc))
        return None, error

    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    if not client_id or not client_secret:
        return None, "Apollo credentials missing for vector store."

    config = ApolloConfig(
        client_id=client_id,
        client_secret=client_secret,
        token_url=settings.get("token_url"),
        base_url=settings.get("base_url"),
    )
    return QdrantClient(config=config, timeout=settings.get("timeout")), None


@lru_cache(maxsize=1)
def _load_support_docs() -> str:
    root = Path(__file__).resolve().parents[2]
    docs = [
        root / "docs" / "AGENT_OVERVIEW.md",
        root / "docs" / "ARCHITECTURE.md",
    ]
    chunks: List[str] = []
    for path in docs:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


def _build_support_messages(session_state: Dict[str, Any], user_message: str) -> list[Dict[str, str]]:
    system_prompt = (
        "You are the ReSource Assistant Support module. "
        "Answer questions using only the provided documentation context. "
        "If the answer is not in the context, say it is not available in the docs."
    )
    doc_context = _load_support_docs()

    messages = [{"role": "system", "content": system_prompt}]
    if doc_context:
        messages.append({"role": "system", "content": f"Documentation context:\n{doc_context[:10000]}"})

    for msg in session_state.get("messages", [])[-6:]:
        content = msg.get("display") or msg.get("content", "")
        role = msg.get("role")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})
    return messages


def _build_faq_messages(session_state: Dict[str, Any], user_message: str) -> list[Dict[str, str]]:
    system_prompt = (
        "You are the FAQ assistant. Answer using only the provided FAQ context. "
        "If the answer is not in the context, say it is not available in the FAQ."
    )
    faq_context = (session_state.get("faq_context") or "").strip()

    messages = [{"role": "system", "content": system_prompt}]
    if faq_context:
        messages.append({"role": "system", "content": f"FAQ context:\n{faq_context}"})

    for msg in session_state.get("messages", [])[-6:]:
        content = msg.get("display") or msg.get("content", "")
        role = msg.get("role")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})
    return messages


def _split_text_into_chunks(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        piece = normalized[start:end]

        if end < len(normalized):
            sentence_cut = piece.rfind(". ")
            if sentence_cut > max(chunk_size // 3, 40):
                end = start + sentence_cut + 1
                piece = normalized[start:end]

        cleaned = piece.strip()
        if cleaned:
            chunks.append(cleaned)

        if end >= len(normalized):
            break

        next_start = end - chunk_overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _build_support_chunks(session_state: Dict[str, Any], rag_settings: Dict[str, Any]) -> List[Dict[str, str]]:
    chunk_size = int(rag_settings["chunk_size"])
    chunk_overlap = int(rag_settings["chunk_overlap"])

    sources: List[Tuple[str, str]] = []
    docs = _load_support_docs()
    if docs:
        sources.append(("docs", docs))

    faq_context = (session_state.get("faq_context") or "").strip()
    if faq_context:
        sources.append(("faq", faq_context))

    chunks: List[Dict[str, str]] = []
    for source_name, source_text in sources:
        split_chunks = _split_text_into_chunks(source_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        for idx, chunk in enumerate(split_chunks, start=1):
            chunks.append(
                {
                    "chunk_id": f"{source_name}_{idx}",
                    "source": source_name,
                    "text": chunk,
                }
            )

    return chunks


def _rag_collection_name(session_state: Dict[str, Any], rag_settings: Dict[str, Any]) -> str:
    prefix = str(rag_settings["collection_prefix"]).strip().lower() or "purpose_support_qa"
    session_id = str(session_state.get("session_id") or "default")
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", session_id).strip("_").lower() or "default"
    return f"{prefix}_{safe[:24]}"


def _corpus_fingerprint(chunks: Sequence[Dict[str, str]], embedding_model: str) -> str:
    digest = hashlib.sha256()
    digest.update(embedding_model.encode("utf-8"))
    for item in chunks:
        digest.update(item["chunk_id"].encode("utf-8"))
        digest.update(item["source"].encode("utf-8"))
        digest.update(item["text"].encode("utf-8"))
    return digest.hexdigest()


def _embed_texts(client: Any, embedding_model: str, texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []

    embeddings: List[List[float]] = []
    batch_size = 32
    for idx in range(0, len(texts), batch_size):
        batch = list(texts[idx : idx + batch_size])
        result = client.embeddings.create(model=embedding_model, input=batch)
        for item in result.data:
            embeddings.append(list(item.embedding))

    return embeddings


def _recreate_collection(qdrant_client: Any, collection_name: str, vector_size: int) -> None:
    from qdrant_client.http import models as qdrant_models

    try:
        exists = bool(qdrant_client.collection_exists(collection_name))
    except Exception:
        exists = False

    if exists:
        try:
            qdrant_client.delete_collection(collection_name=collection_name)
        except Exception:
            pass

    vectors_config = qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE)
    try:
        qdrant_client.create_collection(collection_name=collection_name, vectors_config=vectors_config)
    except Exception:
        qdrant_client.recreate_collection(collection_name=collection_name, vectors_config=vectors_config)


def _index_support_chunks(
    session_state: Dict[str, Any],
    qdrant_client: Any,
    llm_client: Any,
    rag_settings: Dict[str, Any],
) -> tuple[str, List[Dict[str, str]]]:
    collection_name = _rag_collection_name(session_state, rag_settings)
    chunks = _build_support_chunks(session_state, rag_settings)

    if not chunks:
        session_state["_support_rag_index_key"] = ""
        session_state["_support_rag_collection"] = collection_name
        session_state["_support_rag_chunks"] = 0
        return collection_name, chunks

    embedding_model = str(rag_settings["embedding_model"])
    corpus_key = _corpus_fingerprint(chunks, embedding_model)
    if (
        session_state.get("_support_rag_index_key") == corpus_key
        and session_state.get("_support_rag_collection") == collection_name
    ):
        return collection_name, chunks

    vectors = _embed_texts(llm_client, embedding_model, [item["text"] for item in chunks])
    if not vectors:
        raise RuntimeError("Embedding request returned no vectors.")

    _recreate_collection(qdrant_client, collection_name=collection_name, vector_size=len(vectors[0]))

    from qdrant_client.http import models as qdrant_models

    points = [
        qdrant_models.PointStruct(
            id=idx,
            vector=vector,
            payload={
                "chunk_id": chunks[idx - 1]["chunk_id"],
                "source": chunks[idx - 1]["source"],
                "text": chunks[idx - 1]["text"],
            },
        )
        for idx, vector in enumerate(vectors, start=1)
    ]
    qdrant_client.upsert(collection_name=collection_name, points=points, wait=True)

    session_state["_support_rag_index_key"] = corpus_key
    session_state["_support_rag_collection"] = collection_name
    session_state["_support_rag_chunks"] = len(chunks)

    log_event(
        "rag_index",
        status="ok",
        collection=collection_name,
        chunk_count=len(chunks),
        embedding_model=embedding_model,
    )

    return collection_name, chunks


def _search_support_chunks(
    qdrant_client: Any,
    llm_client: Any,
    collection_name: str,
    user_message: str,
    rag_settings: Dict[str, Any],
) -> List[Dict[str, Any]]:
    query_vector = _embed_texts(llm_client, str(rag_settings["embedding_model"]), [user_message])[0]
    top_k = int(rag_settings["top_k"])

    try:
        hits = qdrant_client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
        )
    except Exception:
        # Compatibility fallback for newer qdrant-client APIs.
        query_result = qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
        )
        hits = getattr(query_result, "points", query_result)

    retrieved: List[Dict[str, Any]] = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        retrieved.append(
            {
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "source": str(payload.get("source") or "docs"),
                "chunk_id": str(payload.get("chunk_id") or ""),
                "text": text,
            }
        )

    return retrieved


def _build_support_rag_messages(
    session_state: Dict[str, Any],
    user_message: str,
    retrieved_chunks: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    system_prompt = (
        "You are the ReSource Q&A assistant. "
        "Answer only with evidence from the retrieved context. "
        "If the context is insufficient, explicitly say that the answer is not available in the indexed knowledge base."
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

    if retrieved_chunks:
        rendered = []
        for idx, chunk in enumerate(retrieved_chunks, start=1):
            source = chunk.get("source", "docs")
            text = str(chunk.get("text", ""))
            rendered.append(f"[{idx}] source={source}\n{text}")
        messages.append({"role": "system", "content": "Retrieved context:\n\n" + "\n\n".join(rendered)})
    else:
        messages.append(
            {
                "role": "system",
                "content": "No retrieved context is available for this question. Reply that the answer is not available.",
            }
        )

    for msg in session_state.get("messages", [])[-6:]:
        content = msg.get("display") or msg.get("content", "")
        role = msg.get("role")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})
    return messages


def call_local_model(state: ResearchState) -> Dict[str, Any]:
    """Invoke the Apollo (OpenAI-compatible) endpoint using the apollo_client SDK."""
    session_state = get_session_state()
    user_messages = state.get("user_messages", [])

    if not user_messages:
        return {"raw_response": ""}

    try:
        settings = _apollo_client_settings()
        client, error, client_id_prefix = _create_apollo_client(settings)
        if error or client is None:
            return {"raw_response": error or "Apollo client unavailable."}

        model_name = settings["model_name"]
        max_tokens = settings["max_tokens"]
        temperature = settings["temperature"]
        token_url = settings.get("token_url")
        base_url = settings.get("base_url")

        conversation_messages = _build_conversation_messages(session_state)
        log_event(
            "llm_request",
            provider="apollo",
            model=model_name,
            message_count=len(conversation_messages),
            token_url=token_url,
            base_url=base_url,
            client_id_prefix=client_id_prefix,
        )
        completion = client.chat.completions.create(
            model=model_name,
            messages=conversation_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        raw_text = (completion.choices[0].message.content or "").strip()
        log_event(
            "llm_response",
            provider="apollo",
            status="ok",
            client_id_prefix=client_id_prefix,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raw_text = f"Error contacting Apollo API: {type(exc).__name__}: {exc}"
        log_event(
            "llm_response",
            provider="apollo",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            client_id_prefix=client_id_prefix,
        )

    return {"raw_response": raw_text}


def call_support_model(user_message: str, session_state: Dict[str, Any]) -> str:
    """Fallback support mode that uses static docs context without vector retrieval."""
    settings = _apollo_client_settings()
    client, error, client_id_prefix = _create_apollo_client(settings)
    if error or client is None:
        return error or "Apollo client unavailable."

    model_name = settings["model_name"]
    max_tokens = settings["max_tokens"]
    temperature = settings["temperature"]
    token_url = settings.get("token_url")
    base_url = settings.get("base_url")

    try:
        messages = _build_support_messages(session_state, user_message)
        log_event(
            "llm_request",
            provider="apollo",
            model=model_name,
            message_count=len(messages),
            token_url=token_url,
            base_url=base_url,
            client_id_prefix=client_id_prefix,
        )
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        reply = (completion.choices[0].message.content or "").strip()
        log_event(
            "llm_response",
            provider="apollo",
            status="ok",
            client_id_prefix=client_id_prefix,
        )
    except Exception as exc:  # pragma: no cover - defensive
        reply = f"Error contacting Apollo API: {type(exc).__name__}: {exc}"
        log_event(
            "llm_response",
            provider="apollo",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            client_id_prefix=client_id_prefix,
        )

    return reply


def call_support_rag_model(user_message: str, session_state: Dict[str, Any]) -> str:
    """Support mode backed by Apollo Vector Store (Qdrant) + retrieval-grounded generation."""
    settings = _apollo_client_settings()
    rag_settings = _support_rag_settings()

    llm_client, llm_error, client_id_prefix = _create_apollo_client(settings)
    if llm_error or llm_client is None:
        return llm_error or "Apollo client unavailable."

    qdrant_client, qdrant_error = _create_qdrant_client(settings)
    if qdrant_error or qdrant_client is None:
        # Keep support usable even if vector store is temporarily unavailable.
        log_event("rag_index", status="degraded", error=qdrant_error)
        return call_support_model(user_message, session_state)

    model_name = settings["model_name"]
    max_tokens = settings["max_tokens"]
    temperature = settings["temperature"]
    token_url = settings.get("token_url")
    base_url = settings.get("base_url")

    try:
        collection_name, chunks = _index_support_chunks(
            session_state=session_state,
            qdrant_client=qdrant_client,
            llm_client=llm_client,
            rag_settings=rag_settings,
        )

        retrieved_chunks = _search_support_chunks(
            qdrant_client=qdrant_client,
            llm_client=llm_client,
            collection_name=collection_name,
            user_message=user_message,
            rag_settings=rag_settings,
        )
        session_state["support_rag_last_hits"] = retrieved_chunks

        log_event(
            "rag_retrieve",
            status="ok",
            collection=collection_name,
            indexed_chunks=len(chunks),
            retrieved=len(retrieved_chunks),
            client_id_prefix=client_id_prefix,
        )

        messages = _build_support_rag_messages(
            session_state=session_state,
            user_message=user_message,
            retrieved_chunks=retrieved_chunks,
        )
        log_event(
            "llm_request",
            provider="apollo",
            model=model_name,
            message_count=len(messages),
            token_url=token_url,
            base_url=base_url,
            client_id_prefix=client_id_prefix,
        )

        completion = llm_client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        reply = (completion.choices[0].message.content or "").strip()
        log_event("llm_response", provider="apollo", status="ok", client_id_prefix=client_id_prefix)
        return reply
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            "rag_retrieve",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            client_id_prefix=client_id_prefix,
        )
        # Graceful fallback keeps Support available while vector store issues are diagnosed.
        return call_support_model(user_message, session_state)


def call_faq_model(user_message: str, session_state: Dict[str, Any]) -> str:
    settings = _apollo_client_settings()
    client, error, client_id_prefix = _create_apollo_client(settings)
    if error or client is None:
        return error or "Apollo client unavailable."

    model_name = settings["model_name"]
    max_tokens = settings["max_tokens"]
    temperature = settings["temperature"]
    token_url = settings.get("token_url")
    base_url = settings.get("base_url")

    try:
        messages = _build_faq_messages(session_state, user_message)
        log_event(
            "llm_request",
            provider="apollo",
            model=model_name,
            message_count=len(messages),
            token_url=token_url,
            base_url=base_url,
            client_id_prefix=client_id_prefix,
        )
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        reply = (completion.choices[0].message.content or "").strip()
        log_event(
            "llm_response",
            provider="apollo",
            status="ok",
            client_id_prefix=client_id_prefix,
        )
    except Exception as exc:  # pragma: no cover - defensive
        reply = f"Error contacting Apollo API: {type(exc).__name__}: {exc}"
        log_event(
            "llm_response",
            provider="apollo",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            client_id_prefix=client_id_prefix,
        )

    return reply
