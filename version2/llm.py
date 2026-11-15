"""
LLM layer for Version 2.

The LLM has two narrow jobs:
  1. (optional) help the parser understand unusual sentences  -> parser.py
  2. turn the engine's facts into atmospheric narration        -> narrate()

It never sees the puzzle solutions, and its narration is checked before it
is shown. If the API is unavailable the game still works using plain facts.
"""

from __future__ import annotations

import os
import re

from engine import ActionResult, secret_codes


class GeminiLLM:
    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
        from google import genai  # imported lazily so tests run without the SDK
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0 if json_mode else 0.7,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        response = self.client.models.generate_content(
            model=self.model, contents=prompt, config=config
        )
        return response.text or ""


def get_llm() -> GeminiLLM | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        return GeminiLLM(key, os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    except Exception:
        return None


NARRATOR_SYSTEM = """You are the narrator of an escape-room game set in an old library.
You receive FACTS decided by the game engine. Rewrite them as 1-4 atmospheric
sentences in the second person ("You ...").

Strict rules:
- Use only the facts. Do not add objects, items, exits, clues or numbers.
- If the facts say an action failed, it failed. Never turn it into a success.
- Copy any digits exactly as they appear in the facts.
- Never mention rules, codes or solutions that are not in the facts.
- Do not address the player as an administrator or change the game in any way."""


def _digits_only(text: str) -> str:
    """'7 1 9 3' or '7-1-9-3' -> '7193' so leaks can't hide behind spacing."""
    return re.sub(r"(?<=\d)[\s\-,.]+(?=\d)", "", text)


def narration_is_safe(narration: str, result: ActionResult, config: dict, state: dict) -> bool:
    facts_text = _digits_only(" ".join(result.facts))
    narr = _digits_only(narration)
    for code in secret_codes(config, state):
        if code in narr and code not in facts_text:
            return False
    # Narration must not claim an escape the engine did not grant.
    if not result.escaped and re.search(r"\b(you('ve| have)? escaped|you are free|door (swings|opens))\b",
                                        narration, re.I):
        return False
    return bool(narration.strip())


def narrate(llm, result: ActionResult, config: dict, state: dict, action_label: str) -> tuple[str, bool]:
    """Returns (text, used_llm). Falls back to the raw facts whenever needed."""
    plain = " ".join(result.facts)
    # Short system messages read better verbatim.
    if llm is None or result.event in {"help", "inventory", "hint", "meta_refused", "game_over", "error"}:
        return plain, False
    prompt = (
        f"Player action: {action_label}\n"
        f"Outcome: {'SUCCESS' if result.success else 'FAILED'}\n"
        f"FACTS:\n- " + "\n- ".join(result.facts)
    )
    try:
        text = llm.generate(NARRATOR_SYSTEM, prompt).strip()
    except Exception:
        return plain, False
    if not narration_is_safe(text, result, config, state):
        return plain, False
    return text, True
