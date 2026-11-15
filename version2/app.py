"""
AI Escape Room — Version 2 (reliable)

Pipeline for every player message:
    text --> parser --> Action --> engine (Python rules) --> ActionResult --> narrator (LLM) --> chat

Run:  streamlit run version2/app.py
"""

import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from engine import apply_action, load_config, name_of, new_state
from llm import get_llm, narrate
from parser import parse

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CONFIG = load_config()


@st.cache_resource
def cached_llm():
    return get_llm()


def reset_game():
    st.session_state.state = new_state(CONFIG)
    st.session_state.messages = [{"role": "assistant", "content": CONFIG["intro"]}]


if "state" not in st.session_state:
    reset_game()

llm = cached_llm()
state = st.session_state.state

# --------------------------------------------------------------------------
# Sidebar: instructions, restart, live game state
# --------------------------------------------------------------------------
st.set_page_config(page_title="Escape Room v2", page_icon="🔐")
st.title("🔐 The Locked Library")
st.caption("Version 2 — Python enforces the rules, the LLM tells the story")

with st.sidebar:
    st.header("How to play")
    st.markdown(
        "Type actions in plain English:\n"
        "- *look around* · *examine the desk*\n"
        "- *take the note* · *read the note*\n"
        "- *use the key on the globe*\n"
        "- *enter 1234 on the drawer*\n"
        "- *inventory* · *hint* · *help*"
    )
    if st.button("🔄 Restart game", use_container_width=True):
        reset_game()
        st.rerun()

    st.divider()
    st.subheader("🎒 Inventory")
    st.write(", ".join(name_of(CONFIG, i) for i in state["inventory"]) or "Empty")

    st.subheader("🧩 Puzzles")
    for pid, label in CONFIG["puzzles"].items():
        st.write(("✅ " if pid in state["solved_puzzles"] else "⬜ ") + label)

    st.divider()
    st.caption("LLM: " + (f"connected ({os.getenv('GEMINI_MODEL', 'gemini-3.6-flash')})"
                          if llm else "offline — plain text mode"))
    with st.expander("🔍 Debug: game state (JSON)"):
        st.code(json.dumps(state, indent=2), language="json")

# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if state["escaped"]:
    st.success(f"🎉 You escaped in {state['turn']} turns! Press Restart to play again.")
    st.stop()

if prompt := st.chat_input("What do you do?"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    action, parser_used = parse(prompt, CONFIG, llm)
    new, result = apply_action(CONFIG, state, action)
    label = action.action + (f" {action.item} on" if action.item else "") + \
        (f" {action.target}" if action.target else "")
    text, _ = narrate(llm, result, CONFIG, new, label)

    st.session_state.state = new
    st.session_state.messages.append({"role": "assistant", "content": text})
    if result.escaped:
        st.balloons()
    st.rerun()
