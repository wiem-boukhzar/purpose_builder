"""Simple Streamlit chat UI for the Apollo LLM."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import streamlit as st
from apollo_client import OpenAI, ApolloConfig
from dotenv import load_dotenv


st.set_page_config(page_title="Apollo Chat", page_icon="🛰️")

# Load .env if present to make local runs easier (no effect in production).
load_dotenv()


def _build_client() -> OpenAI:
    """Create the Apollo client from environment variables."""
    required = ["APOLLO_CLIENT_ID", "APOLLO_CLIENT_SECRET"]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        st.error(f"Missing environment variables: {', '.join(missing)}")
        st.stop()

    config = ApolloConfig(
        client_id=os.getenv("APOLLO_CLIENT_ID", ""),
        client_secret=os.getenv("APOLLO_CLIENT_SECRET", ""),
        token_url=os.getenv("APOLLO_TOKEN_URL"),
        base_url=os.getenv("APOLLO_BASE_URL"),
    )
    timeout = int(os.getenv("APOLLO_TIMEOUT", "120"))

    return OpenAI(config=config, timeout=timeout)


def _init_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"]: List[Dict[str, str]] = []
    if "system_prompt" not in st.session_state:
        st.session_state["system_prompt"] = "You are a helpful assistant."


def _render_history() -> None:
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])


def main() -> None:
    st.title("Apollo Chat")
    st.caption("Streamlit sandbox to chat with the Apollo LLM (OpenAI-compatible).")

    _init_state()

    system_prompt = st.sidebar.text_area(
        "System prompt",
        value=st.session_state["system_prompt"],
        help="Prepended to every conversation to steer behavior.",
    )
    model_name = st.sidebar.text_input("Model", value=os.getenv("APOLLO_MODEL", "gpt-5-mini"))
    temperature = st.sidebar.slider("Temperature", min_value=0.0, max_value=1.0, value=float(os.getenv("APOLLO_TEMPERATURE", "0.2")))
    max_tokens = st.sidebar.slider("Max tokens", min_value=64, max_value=4096, value=int(os.getenv("APOLLO_MAX_TOKENS", "512")), step=64)

    if st.sidebar.button("Clear chat"):
        st.session_state["chat_history"] = []
        st.session_state["system_prompt"] = system_prompt
        st.experimental_rerun()

    st.session_state["system_prompt"] = system_prompt
    _render_history()

    prompt = st.chat_input("Ask anything about your research intent...")
    if prompt:
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        messages = [{"role": "system", "content": system_prompt}, *st.session_state["chat_history"]]

        try:
            client = _build_client()
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            reply = (completion.choices[0].message.content or "").strip()
        except Exception as exc:  # pragma: no cover - UI path
            reply = f"Error contacting Apollo API: {exc}"

        st.session_state["chat_history"].append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.write(reply)


if __name__ == "__main__":
    main()
