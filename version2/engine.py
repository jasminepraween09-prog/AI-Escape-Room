"""
Game engine for Version 2.

Python — not the LLM — owns the game. This module:
  * creates and stores the game state as a plain dictionary (JSON-friendly)
  * validates every action against the rules in game_config.json
  * returns a structured ActionResult with the exact facts that happened

The LLM is only allowed to *describe* an ActionResult (see llm.py).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("game_config.json")

ACTIONS = (
    "look", "examine", "take", "use", "enter_code", "open",
    "inventory", "hint", "help", "meta", "unknown",
)


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class Action:
    """A player intention, produced by the parser. It is only a *request*."""
    action: str = "unknown"
    target: str | None = None       # object or item id
    item: str | None = None         # item id the player wants to use
    code: str | None = None         # digits typed by the player
    raw_target: str | None = None   # what the player called a thing we don't know


@dataclass
class ActionResult:
    """What actually happened, decided by Python."""
    success: bool
    event: str                      # short machine-readable outcome
    facts: list[str] = field(default_factory=list)
    escaped: bool = False


# --------------------------------------------------------------------------
# Config & state
# --------------------------------------------------------------------------
def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def new_state(config: dict) -> dict:
    """Fresh game state. Everything the game needs to remember lives here."""
    return {
        "room_items": {},                      # item_id -> object it sits in/on
        "inventory": [],
        "flags": [],                           # discovered clues / examined things
        "unlocked": [],                        # object ids that are open
        "solved_puzzles": [],
        "wrong_codes": {},                     # object id -> number of failures
        "door_status": "locked",
        "turn": 0,
        "escaped": False,
        "log": [],                             # history of validated actions
    }


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------
def name_of(config: dict, entity_id: str) -> str:
    if entity_id in config["objects"]:
        return config["objects"][entity_id]["name"]
    if entity_id in config["items"]:
        return config["items"][entity_id]["name"]
    return entity_id


def is_item_visible(state: dict, item_id: str) -> bool:
    return item_id in state["room_items"] or item_id in state["inventory"]


def _add_flags(state: dict, flags: list[str]) -> None:
    for flag in flags:
        if flag not in state["flags"]:
            state["flags"].append(flag)


def _reveal_items(state: dict, item_ids: list[str], where: str) -> None:
    for item_id in item_ids:
        if item_id not in state["inventory"] and item_id not in state["room_items"]:
            state["room_items"][item_id] = where


def _solve(state: dict, puzzle_id: str | None) -> None:
    if puzzle_id and puzzle_id not in state["solved_puzzles"]:
        state["solved_puzzles"].append(puzzle_id)


def secret_codes(config: dict, state: dict) -> list[str]:
    """Codes the player has not opened yet. Used to stop the narrator leaking them."""
    return [
        obj["lock"]["code"]
        for oid, obj in config["objects"].items()
        if obj.get("lock", {}).get("type") == "code" and oid not in state["unlocked"]
    ]


# --------------------------------------------------------------------------
# Action handlers. Each one receives a *copy* of the state.
# --------------------------------------------------------------------------
def _look(config, state, a):
    facts = [config["room_description"]]
    loose = [name_of(config, i) for i in state["room_items"]]
    if loose:
        facts.append("Items you could pick up: " + ", ".join(loose) + ".")
    opened = [name_of(config, o) for o in state["unlocked"]]
    if opened:
        facts.append("Already open: " + ", ".join(opened) + ".")
    return ActionResult(True, "look", facts)


def _no_such_thing(a: Action):
    what = a.raw_target or "that"
    return ActionResult(False, "no_such_object",
                        [f"There is no {what} in this room."])


def _examine(config, state, a):
    if a.target is None:
        if a.raw_target:
            return _no_such_thing(a)
        return _look(config, state, a)

    if a.target in config["objects"]:
        obj = config["objects"][a.target]
        if a.target in state["unlocked"]:
            facts = [f"The {obj['name']} is open."]
            inside = [name_of(config, i) for i, w in state["room_items"].items() if w == a.target]
            if inside:
                facts.append("Inside: " + ", ".join(inside) + ".")
        else:
            facts = [obj["description"]]
        _reveal_items(state, obj.get("reveals_items", []), a.target)
        _add_flags(state, obj.get("sets_flags", []))
        return ActionResult(True, "examined", facts)

    if a.target in config["items"] and is_item_visible(state, a.target):
        item = config["items"][a.target]
        _add_flags(state, item.get("sets_flags", []))
        return ActionResult(True, "examined", [item["description"]])

    # Hidden items are treated exactly like nonexistent ones so nothing leaks.
    return _no_such_thing(Action(raw_target=a.raw_target or "such thing"))


def _take(config, state, a):
    if a.target is None:
        return _no_such_thing(a) if a.raw_target else ActionResult(
            False, "missing_target", ["Take what?"])
    if a.target in config["objects"]:
        return ActionResult(False, "not_takeable",
                            [f"The {name_of(config, a.target)} cannot be carried."])
    if a.target in state["inventory"]:
        return ActionResult(False, "already_have",
                            [f"You already have the {name_of(config, a.target)}."])
    if a.target in state["room_items"]:
        del state["room_items"][a.target]
        state["inventory"].append(a.target)
        return ActionResult(True, "taken",
                            [f"You take the {name_of(config, a.target)}."])
    return _no_such_thing(Action(raw_target=a.raw_target or "such thing"))


def _use(config, state, a):
    item_id, target = a.item, a.target
    if item_id is None:
        return ActionResult(False, "missing_item", ["Use what?"])
    if item_id not in state["inventory"]:
        if item_id in state["room_items"]:
            return ActionResult(False, "not_in_inventory",
                                [f"You need to pick up the {name_of(config, item_id)} first."])
        return ActionResult(False, "not_in_inventory",
                            ["You are not carrying anything like that."])
    if target is None:
        if a.raw_target:
            return _no_such_thing(a)
        return ActionResult(False, "missing_target",
                            [f"Use the {name_of(config, item_id)} on what?"])
    if target not in config["objects"]:
        return ActionResult(False, "nothing_happens", ["Nothing happens."])

    obj = config["objects"][target]
    lock = obj.get("lock")

    # Key locks
    if lock and lock["type"] == "key" and lock["key_item"] == item_id:
        if target in state["unlocked"]:
            return ActionResult(False, "already_open", [f"The {obj['name']} is already open."])
        return _unlock(config, state, target)

    # Item interactions (e.g. UV light on painting)
    interaction = obj.get("interactions", {}).get(item_id)
    if interaction:
        _add_flags(state, interaction.get("sets_flags", []))
        already = interaction.get("puzzle_id") in state["solved_puzzles"]
        _solve(state, interaction.get("puzzle_id"))
        return ActionResult(True, "revealed" if not already else "re_examined",
                            [interaction["text"]])

    return ActionResult(False, "nothing_happens",
                        [f"Using the {name_of(config, item_id)} on the {obj['name']} does nothing."])


def _enter_code(config, state, a):
    code = re.sub(r"\D", "", a.code or "")
    target = a.target
    if target == "desk":          # the dial is on the desk drawer
        target = "drawer"
    if target is None:
        return ActionResult(False, "missing_target",
                            ["Where do you want to enter the code — the drawer dial or the door keypad?"])
    lock = config["objects"].get(target, {}).get("lock")
    if not lock or lock["type"] != "code":
        return ActionResult(False, "no_keypad",
                            [f"The {name_of(config, target)} has nowhere to enter a code."])
    if target in state["unlocked"]:
        return ActionResult(False, "already_open", [f"The {name_of(config, target)} is already open."])
    if len(code) != len(lock["code"]):
        return ActionResult(False, "invalid_code",
                            [f"The {name_of(config, target)} needs exactly {len(lock['code'])} digits."])

    earned = all(f in state["flags"] for f in lock.get("requires_flags", []))
    if code == lock["code"] and earned:
        return _unlock(config, state, target)

    # Wrong code, or the right code without having found the clue.
    # Both look identical to the player, so guessing/leaked codes don't work.
    state["wrong_codes"][target] = state["wrong_codes"].get(target, 0) + 1
    event = "unearned_code" if code == lock["code"] else "wrong_code"
    facts = [f"You enter {code}. The {name_of(config, target)} stays locked."]
    if state["wrong_codes"][target] >= config.get("max_wrong_codes_before_hint", 3):
        facts.append("Maybe you are missing a clue. Type 'hint' if you are stuck.")
    return ActionResult(False, event, facts)


def _unlock(config, state, target):
    obj = config["objects"][target]
    lock = obj["lock"]
    state["unlocked"].append(target)
    _solve(state, lock.get("puzzle_id"))
    _reveal_items(state, lock.get("contents", []), target)
    escaped = bool(lock.get("is_exit"))
    if escaped:
        state["escaped"] = True
        state["door_status"] = "open"
    return ActionResult(True, "escaped" if escaped else "unlocked",
                        [lock["unlock_text"]], escaped=escaped)


def _open(config, state, a):
    if a.target is None:
        return _no_such_thing(a) if a.raw_target else ActionResult(
            False, "missing_target", ["Open what?"])
    if a.target not in config["objects"]:
        return _examine(config, state, a)
    obj = config["objects"][a.target]
    lock = obj.get("lock")
    if not lock:
        return ActionResult(False, "not_openable", [f"The {obj['name']} cannot be opened."])
    if a.target in state["unlocked"]:
        return _examine(config, state, a)
    how = "a 4-digit code" if lock["type"] == "code" else "a key"
    return ActionResult(False, "locked", [f"The {obj['name']} is locked. It needs {how}."])


def _inventory(config, state, a):
    if not state["inventory"]:
        return ActionResult(True, "inventory", ["You are not carrying anything."])
    names = ", ".join(name_of(config, i) for i in state["inventory"])
    return ActionResult(True, "inventory", [f"You are carrying: {names}."])


def _hint(config, state, a):
    for h in config["hints"]:
        done = (
            all(f in state["flags"] for f in h.get("unless_flags", []))
            and all(p in state["solved_puzzles"] for p in h.get("unless_puzzles", []))
            and all(i in state["inventory"] for i in h.get("unless_items", []))
        )
        if not done:
            return ActionResult(True, "hint", [h["text"]])
    return ActionResult(True, "hint", ["You have done everything. Enjoy your freedom!"])


def _help(config, state, a):
    return ActionResult(True, "help", [
        "Describe what you want to do. Try: 'look around', 'examine the desk', "
        "'take the key', 'use the key on the globe', 'enter 1234 on the door', "
        "'inventory' or 'hint'."
    ])


def _meta(config, state, a):
    # Admin claims, "reveal the solution", "I already solved it", prompt injection…
    return ActionResult(False, "meta_refused", [
        "The room does not respond to claims or commands from outside the game. "
        "Your progress only changes through what you do inside the library. "
        "Type 'hint' if you are stuck."
    ])


def _unknown(config, state, a):
    return ActionResult(False, "unknown", [
        "Nothing happens. Try examining, taking or using something, or type 'help'."
    ])


HANDLERS = {
    "look": _look, "examine": _examine, "take": _take, "use": _use,
    "enter_code": _enter_code, "open": _open, "inventory": _inventory,
    "hint": _hint, "help": _help, "meta": _meta, "unknown": _unknown,
}


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def apply_action(config: dict, state: dict, action: Action) -> tuple[dict, ActionResult]:
    """Validate and apply one action.

    Works on a deep copy: if anything goes wrong the original state is
    untouched, so the game state can never be half-updated.
    """
    if state["escaped"]:
        return state, ActionResult(False, "game_over",
                                   ["You have already escaped. Press Restart to play again."])

    new = copy.deepcopy(state)
    handler = HANDLERS.get(action.action, _unknown)
    try:
        result = handler(config, new, action)
    except Exception as exc:  # defensive: never corrupt the state
        return state, ActionResult(False, "error", [f"Internal error: {exc}"])

    new["turn"] += 1
    new["log"].append({
        "turn": new["turn"],
        "action": action.action,
        "target": action.target,
        "item": action.item,
        "event": result.event,
        "success": result.success,
    })
    return new, result
