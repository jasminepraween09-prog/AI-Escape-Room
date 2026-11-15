# 🔐 AI Escape Room — The Locked Library

An interactive text escape-room game where a Large Language Model (Google Gemini) acts as the Game Master. The player wakes up locked inside an old library and must explore, collect items, solve three puzzles and unlock the exit door.

The project is built in two versions to show a real problem with LLM applications and how to fix it:

| | Version 1 — Interactive | Version 2 — Reliable |
|---|---|---|
| Who decides what happens? | The LLM | Python rules engine |
| Where are the solutions? | Inside the LLM prompt | `game_config.json` (never sent to the LLM) |
| Game memory | Chat history only | Structured JSON state |
| Escape detection | LLM prints `[ESCAPED]` | Engine checks the door lock |
| Resists cheating / prompt injection | ❌ | ✅ |
| Works without API key | ❌ | ✅ (plain-text mode) |

> Built for the Generative AI module (MSc).

## Screenshots

**The same cheat in both versions:** typing the exit code without solving any puzzle.

| Version 1: the player escapes ❌ | Version 2: the door stays locked ✅ |
|---|---|
| ![V1 lets the player escape](docs/screenshots/v1_test7.png) | ![V2 keeps the door locked](docs/screenshots/v2_sidebar.png) |

More screenshots are in [`docs/screenshots`](docs/screenshots).

---

## The game

| Object | What's special |
|---|---|
| Oak desk | Has a note with a riddle |
| Bookshelf | Four "season" books, each with a hidden digit |
| Desk drawer | 4-digit combination lock |
| Antique globe | Hidden keyhole |
| Lighthouse painting | Hides something only special light can reveal |
| Exit door | 4-digit keypad — the final challenge |

**Puzzles:** (1) decode the drawer combination from the note + books → (2) use the brass key on the globe → (3) shine the UV flashlight on the painting → **final:** enter the door code.

<details>
<summary>⚠️ Spoiler: full solution</summary>

`examine desk` → `read note` → `examine bookshelf` → `enter 2548 on drawer` → `take key` → `use key on globe` → `take flashlight` → `shine flashlight on painting` → `enter 7193 on door`
</details>

---

## Architecture

### Version 1 — the LLM is the whole game

```mermaid
flowchart LR
    P([Player]) -->|natural language| UI[Streamlit chat UI]
    UI -->|full chat history| LLM[Gemini<br/>Game Master]
    SP[System prompt<br/>room + rules + ALL solutions] --> LLM
    LLM -->|narration + maybe ESCAPED marker| UI
    UI <--> SS[(session_state<br/>chat history only)]
```

Everything — rules, memory, solutions, win detection — depends on the LLM following its prompt. Because the solutions are in the prompt, the LLM *can* reveal them, and because there is no structured state, it can forget or contradict earlier events.

### Version 2 — Python decides, the LLM narrates

```mermaid
flowchart LR
    P([Player]) -->|natural language| UI[Streamlit UI]
    UI --> PA[Parser<br/>rules first, LLM fallback]
    PA -->|"Action {action, target, item, code}"| V{Validate<br/>allowed values only}
    V --> EN[Game engine<br/>Python rules]
    CFG[(game_config.json<br/>objects, locks, solutions)] --> EN
    ST[(Game state JSON<br/>inventory, flags, locks,<br/>solved puzzles, door)] <--> EN
    EN -->|"ActionResult {success, facts}"| NA[Narrator<br/>Gemini]
    NA --> G{Leak / fake-success<br/>guard}
    G -->|safe| UI
    G -->|unsafe or API down| F[Plain facts] --> UI
```

Key ideas:
1. **Separation of decision and description.** The engine decides *whether* an action succeeds; the LLM only describes the result.
2. **The LLM never sees the solutions.** The narrator only receives the facts of the current turn, so it cannot leak codes it does not know.
3. **The player's raw text never reaches the narrator.** Injection text like "ignore your rules" only reaches the parser, whose output is restricted to a fixed list of actions and object ids.
4. **Atomic state updates.** Every action runs on a copy of the state; if anything fails, the old state is kept.

---

## Project structure

```
AI-Escape-Room/
├── version1/
│   └── app.py              # V1: single prompt, LLM does everything
├── version2/
│   ├── app.py              # V2: Streamlit UI
│   ├── engine.py           # game state + action validation (the rules)
│   ├── parser.py           # text -> structured Action
│   ├── llm.py              # Gemini wrapper + constrained narrator + guards
│   └── game_config.json    # room, objects, locks, solutions, hints
├── tests/
│   └── test_version2.py    # 17 automated tests (no API key needed)
├── docs/
│   ├── test_cases.md       # V1 vs V2 test case comparison
│   ├── report.md           # project report
│   └── screenshots/
├── .env.example
├── requirements.txt
└── README.md
```

---

## Installation and running

**Requirements:** Python 3.10+ and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

```bash
git clone https://github.com/<your-username>/AI-Escape-Room.git
cd AI-Escape-Room

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# open .env and paste your GEMINI_API_KEY
```

Run either version:

```bash
streamlit run version1/app.py
streamlit run version2/app.py
```

Run the tests:

```bash
pytest -v
```

If the default model is unavailable on your free tier, set `GEMINI_MODEL` in `.env` to another model listed in Google AI Studio.

---

## Testing

**Key result:** Version 1 resisted obvious attacks (admin impersonation, "reveal all codes"), but let the player escape by typing the door code on the first move without solving any puzzle. Version 2 rejects this because the door only accepts its code after the clue has been discovered.

Eight adversarial test cases compare V1 and V2 — see **[docs/test_cases.md](docs/test_cases.md)**. They cover: using an uncollected key, wrong codes, false "already solved" claims, administrator impersonation, requests for all solutions, nonexistent objects, and guessing the exit code. Most are also automated in `tests/test_version2.py`.

## Report

The design, implementation, problems encountered and improvements are explained in **[docs/report.md](docs/report.md)**.

## Technologies

Python · Streamlit · Google Gemini API (`google-genai`) · JSON · pytest · python-dotenv

## Known limitations

- The rule-based parser understands common phrasings; unusual sentences fall back to the LLM parser, which needs an API key.
- The leak guard checks for secret codes and fake escapes, but cannot catch every possible invented detail in the narration.
- One room only; the engine is config-driven, so more rooms could be added through `game_config.json` with modest changes.
