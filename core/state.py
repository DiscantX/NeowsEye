"""
state.py

Pure dict-transform layer. Every class here does ONE job: turn a raw
CommunicationMod JSON fragment into a typed object, and (optionally) back
into a compact dict for a Gemini payload. Nothing in this file persists
across polls -- that's run_state.py's job (RunState / CombatState own the
objects built here and decide what's changed since we last spoke to
Gemini).

Keep it that way: if you find yourself wanting one of these objects to
remember something between calls, that need belongs in run_state.py, not
here.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Card:
    uuid: str
    id: str
    name: str
    type: str
    rarity: str
    cost: int
    upgrades: int
    is_playable: bool
    has_target: bool
    exhausts: bool
    ethereal: bool
    
    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        raw_name = data.get("name", data.get("id", "?"))
        return cls(
            uuid=data.get("uuid", ""),
            id=data.get("id", ""),
            name=raw_name.rstrip("+"),
            type=data.get("type", ""),
            rarity=data.get("rarity", ""),
            cost=data.get("cost", -1),
            upgrades=data.get("upgrades", 0),
            is_playable=data.get("is_playable", False),
            has_target=data.get("has_target", False),
            exhausts=data.get("exhausts", False),
            ethereal=data.get("ethereal", False),
        )

    def dedupe_key(self) -> tuple:
        return (
            self.name,
            self.upgrades,
            self.cost,
            self.type,
            self.rarity,
            self.is_playable,
            self.has_target,
            self.exhausts,
            self.ethereal,
        )

    def to_prompt_dict(self, quantity: int = 1) -> dict:
        d = {
            "name": self.name + ("+" * self.upgrades if self.upgrades else ""),
            "cost": "X" if self.cost == -1 else self.cost,
            "type": self.type,
            "playable": self.is_playable,
            "quantity": quantity,
        }
        if self.cost == -1:
            d["variable_cost"] = True
        if self.has_target:
            d["single_target"] = True
        if self.exhausts:
            d["exhausts"] = True
        if self.ethereal:
            d["ethereal"] = True
        return d

    def to_deck_entry(self, quantity: int = 1) -> dict:
        return {
            "name": self.name + ("+" * self.upgrades if self.upgrades else ""),
            "cost": "X" if self.cost == -1 else self.cost,
            "quantity": quantity,
        }

def dedupe_cards(cards: list) -> list:
    """Collapse a list of Card objects into (card, quantity) pairs,
    grouping by Card.dedupe_key(). Order of first appearance is
    preserved. Used for both deck listings and hand listings -- same
    rule either way: identical on every tracked field means functionally
    the same card, so collapse to a quantity instead of repeating it."""
    groups = {}
    order = []
    for card in cards:
        key = card.dedupe_key()
        if key not in groups:
            groups[key] = [card, 0]
            order.append(key)
        groups[key][1] += 1
    return [tuple(groups[key]) for key in order]


@dataclass
class Power:
    id: str
    amount: int

    @classmethod
    def from_dict(cls, data: dict) -> "Power":
        return cls(id=data.get("id", ""), amount=data.get("amount", 0))

    def to_prompt_dict(self) -> dict:
        return {"name": self.id, "amount": self.amount}


@dataclass
class Orb:
    """Defect's orb slots (Frost/Lightning/Dark/Plasma).

    FLAGGED UNCERTAIN: built from the documented CommunicationMod field
    names, but we haven't captured a real Defect combat_state yet to
    confirm them. 'evoke_amount' is a guess for Dark/Frost orb values
    based on the mod's general naming pattern (mirrors move_adjusted_damage
    style keys) -- verify against a real capture before trusting this,
    and adjust from_dict() rather than downstream code if the field name
    is wrong.
    """

    id: str  # e.g. "Frost", "Lightning", "Dark", "Plasma", "Empty"
    evoke_amount: Optional[int]  # meaningful for Dark (stored dmg) / Frost (stored block)

    @classmethod
    def from_dict(cls, data: dict) -> "Orb":
        return cls(
            id=data.get("id", data.get("name", "?")),
            evoke_amount=data.get("evoke_amount"),
        )

    def to_prompt_dict(self) -> dict:
        d = {"type": self.id}
        if self.evoke_amount is not None:
            d["value"] = self.evoke_amount
        return d


@dataclass
class Monster:
    name: str
    current_hp: int
    max_hp: int
    block: int
    intent: str
    move_damage: Optional[int]
    move_hits: Optional[int]
    half_dead: bool
    powers: list

    @classmethod
    def from_dict(cls, data: dict) -> "Monster":
        raw_intent = data.get("intent", "NONE")
        intent = "UNKNOWN" if raw_intent == "DEBUG" else raw_intent
        return cls(
            name=data.get("name", data.get("id", "?")),
            current_hp=data.get("current_hp", 0),
            max_hp=data.get("max_hp", 0),
            block=data.get("block", 0),
            intent=intent,
            move_damage=data.get("move_adjusted_damage"),
            move_hits=data.get("move_hits"),
            half_dead=data.get("half_dead", False),
            powers=[Power.from_dict(p) for p in data.get("powers", [])],
        )

    def to_prompt_dict(self) -> dict:
        d = {
            "name": self.name,
            "hp": self.current_hp,
            "max_hp": self.max_hp,
            "block": self.block,
            "intent": self.intent,
        }
        if self.move_damage is not None and self.move_damage >= 0:
            d["incoming_damage"] = self.move_damage
            d["hits"] = self.move_hits
        if self.half_dead:
            # Slime-split warning -- only worth the tokens when true.
            d["half_dead"] = True
        if self.powers:
            d["powers"] = [p.to_prompt_dict() for p in self.powers]
        return d


@dataclass
class Relic:
    id: str
    name: str
    counter: int

    @classmethod
    def from_dict(cls, data: dict) -> "Relic":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "?")),
            counter=data.get("counter", -1),
        )

    def to_prompt_dict(self) -> dict:
        d = {"name": self.name}
        if self.counter != -1:
            # -1 appears to be CommunicationMod's "not applicable" sentinel
            # for relics that don't track a counter at all -- confirm
            # against more captures, but treat it as "omit" for now.
            d["counter"] = self.counter
        return d


@dataclass
class Potion:
    id: str
    name: str
    can_use: bool

    @classmethod
    def from_dict(cls, data: dict) -> "Potion":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", "?"),
            can_use=data.get("can_use", False),
        )

    def is_real(self) -> bool:
        """False for empty 'Potion Slot' placeholder entries."""
        return bool(self.name) and self.name != "Potion Slot"

    def to_prompt_dict(self) -> dict:
        return {"name": self.name, "can_use": self.can_use}
    
ROOM_SYMBOLS = {
    "M": "monster",
    "E": "elite",
    "R": "rest",
    "$": "shop",
    "T": "treasure",
    "?": "unknown",
}

@dataclass
class MapNode:
    x: Optional[int]
    y: Optional[int]
    symbol: str
    children: list  # list of (x, y) tuples this node connects to -- only
                     # populated for nodes from the full act graph
                     # (game_state.map); current_node/next_nodes entries
                     # from screen_state don't carry children and default
                     # to empty, which is fine -- we already have the
                     # full graph to look them up in if needed.

    @classmethod
    def from_dict(cls, data: dict) -> "MapNode":
        return cls(
            x=data.get("x"),
            y=data.get("y"),
            symbol=data.get("symbol", "?"),
            children=[(c.get("x"), c.get("y")) for c in data.get("children", [])],
        )

    def to_prompt_dict(self, position: Optional[str] = None) -> dict:
        d = {"x": self.x, "y": self.y, "type": ROOM_SYMBOLS.get(self.symbol, self.symbol)}
        if position:
            d["position"] = position
        if self.children:
            d["connects_to"] = [{"x": x, "y": y} for x, y in self.children]
        return d