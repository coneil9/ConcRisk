import json
import os

import streamlit as st

from concrisk.chat import run_chat

st.set_page_config(page_title="Ask", page_icon="💬", layout="wide")
st.title("Ask ConcRisk")
st.caption(
    "Ask any concentration-risk question about the tracked funds. "
    "Powered by Anthropic Claude with typed tool calls — the model never sees raw "
    "DB rows and never writes SQL."
)

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning(
        "ANTHROPIC_API_KEY is not set in this process. Add it to `.env` and restart Streamlit."
    )
    st.stop()

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # API-format messages list
if "chat_traces" not in st.session_state:
    st.session_state["chat_traces"] = {}  # {assistant_turn_index: [ToolCall, ...]}


def _render_history() -> None:
    history = st.session_state["chat_history"]
    traces = st.session_state["chat_traces"]
    assistant_idx = 0
    for msg in history:
        role = msg["role"]
        content = msg["content"]
        if role == "user" and isinstance(content, str):
            with st.chat_message("user"):
                st.write(content)
        elif role == "assistant" and isinstance(content, list):
            text_parts = [b["text"] for b in content if b.get("type") == "text"]
            text = "\n\n".join(text_parts).strip()
            if text:
                with st.chat_message("assistant"):
                    st.write(text)
                    turn_trace = traces.get(assistant_idx, [])
                    if turn_trace:
                        with st.expander(f"tool trace ({len(turn_trace)} calls)"):
                            for call in turn_trace:
                                st.markdown(f"**{call['name']}**")
                                st.markdown("Input:")
                                st.code(json.dumps(call["input"], indent=2), language="json")
                                st.markdown("Result:")
                                st.code(json.dumps(call["result"], indent=2), language="json")
            assistant_idx += 1


_render_history()

user_msg = st.chat_input("Ask about a fund's holdings, breaches, exposure...")
if user_msg:
    with st.chat_message("user"):
        st.write(user_msg)

    with st.spinner("Thinking..."):
        result = run_chat(
            user_message=user_msg,
            history=st.session_state["chat_history"],
        )

    # Update history + traces
    st.session_state["chat_history"] = result.messages
    assistant_msgs = [m for m in result.messages if m["role"] == "assistant"]
    turn_idx = len(assistant_msgs) - 1
    st.session_state["chat_traces"][turn_idx] = [
        {"name": c.name, "input": c.input, "result": c.result} for c in result.trace
    ]

    with st.chat_message("assistant"):
        st.write(result.text)
        if result.trace:
            with st.expander(f"tool trace ({len(result.trace)} calls)"):
                for call in result.trace:
                    st.markdown(f"**{call.name}**")
                    st.markdown("Input:")
                    st.code(json.dumps(call.input, indent=2), language="json")
                    st.markdown("Result:")
                    st.code(json.dumps(call.result, indent=2), language="json")
        if result.truncated:
            st.caption(
                f"Hit tool-call round limit ({result.rounds} rounds). "
                "Ask a narrower question if you need more detail."
            )

with st.sidebar:
    if st.button("Clear conversation", type="secondary"):
        st.session_state["chat_history"] = []
        st.session_state["chat_traces"] = {}
        st.rerun()
