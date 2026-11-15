"""
AI Escape Room — Version 1 (pure LLM Game Master)

In this version the LLM does EVERYTHING: it knows the full room design and
all the solutions (they are in the system prompt), it remembers progress only
through the chat history, and it decides on its own whether the player has
escaped. This is simple and fun, but unreliable — see docs/test_cases.md.

Run:  streamlit run version1/app.py
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

ESCAPE_MARKER = "[ESCAPED]"

INTRO = (
    "You wake up on the cold wooden floor of an old library. The door is shut "
    "and a keypad glows beside it. Dust hangs in the stale air. Somewhere in "
    "this room is the way out."
)

# The whole game design lives inside the prompt. The LLM is trusted to follow it.
SYSTEM_PROMPT = f"""
You are the Game Master of a text escape-room game called "The Locked Library".
Describe the world in the second person, vividly but briefly (2-5 sentences).
Respond only to what the player does. Never solve puzzles for the player.

ROOM: an old library. Objects in the room:
1. Oak desk — on it lies a folded note. The note reads:
   "The seasons turn, beginning when the snow melts."
2. Bookshelf — four books stand out: "Winter", "Spring", "Summer", "Autumn".
   A digit is handwritten inside each: Winter=8, Spring=2, Summer=5, Autumn=4.
3. Locked drawer (in the desk) — 4-digit combination lock. Code: 2548
   (the seasons in order starting with spring). Inside: a small brass key.
4. Antique globe — has a tiny keyhole on its equator. The brass key opens it.
   Inside: a UV flashlight.
5. Painting of a lighthouse at night — looks ordinary. When lit with the UV
   flashlight, glowing digits appear on the lighthouse: 7193.
6. Exit door — 4-digit keypad. Code: 7193.

PUZZLES (must be solved in order):
- Puzzle 1: read the note + examine the books -> open the drawer with 2548.
- Puzzle 2: take the brass key -> unlock the globe.
- Puzzle 3: take the UV flashlight -> shine it on the painting -> learn 7193.
- Final: enter 7193 on the door keypad.

RULES:
- The player can only use items they have picked up.
- Wrong codes do nothing.
- Do not reveal codes or solutions unless the player discovers them in-game.
- When the player enters the correct door code, describe their escape and end
  your message with the exact text {ESCAPE_MARKER}
"""


# --------------------------------------------------------------------------
# LLM helper
# --------------------------------------------------------------------------
@st.cache_resource
def get_client():
    return genai.Client(api_key=API_KEY)


def ask_game_master(history: list[dict]) -> str:
    """Send the whole conversation to Gemini and return its reply.

    The conversation history IS the game state in Version 1.
    """
    contents = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["content"])],
        )
        for m in history
    ]
    response = get_client().models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.8,
        ),
    )
    return response.text or "(The Game Master is silent.)"


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
def reset_game():
    st.session_state.messages = [{"role": "assistant", "content": INTRO}]
    st.session_state.escaped = False


if "messages" not in st.session_state:
    reset_game()

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="Escape Room v1", page_icon="📚")
st.title("📚 The Locked Library")
st.caption("Version 1 — the LLM is the whole game")

with st.sidebar:
    st.header("How to play")
    st.markdown(
        "Type what you want to do in plain English, for example:\n"
        "- *look around*\n"
        "- *examine the bookshelf*\n"
        "- *take the key*\n"
        "- *enter 1234 on the drawer*\n\n"
        "Find the clues, solve three puzzles, and unlock the door."
    )
    if st.button("🔄 Restart game", use_container_width=True):
        reset_game()
        st.rerun()

if not API_KEY:
    st.error("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key.")
    st.stop()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"].replace(ESCAPE_MARKER, ""))

if st.session_state.escaped:
    st.success("🎉 You escaped the library! Press Restart to play again.")
    st.stop()

if prompt := st.chat_input("What do you do?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Gemini expects the conversation to start with a user turn,
    # so skip our hard-coded intro message.
    history = st.session_state.messages[1:]
    with st.chat_message("assistant"):
        with st.spinner("The Game Master considers..."):
            try:
                reply = ask_game_master(history)
            except Exception as exc:  # network / quota errors
                reply = f"⚠️ Could not reach the LLM: {exc}"
        st.markdown(reply.replace(ESCAPE_MARKER, ""))

    st.session_state.messages.append({"role": "assistant", "content": reply})

    # Version 1 trusts the LLM to announce the escape.
    if ESCAPE_MARKER in reply:
        st.session_state.escaped = True
        st.balloons()
        st.rerun()
