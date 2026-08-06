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
        # is_playable/has_target only appear on cards CommunicationMod
        # reports as being IN HAND during combat -- cards from a plain
        # deck listing (e.g. game_state["deck"], used outside combat or
        # for the one-time combat intro) don't carry those fields at
        # all, so they need defaults rather than being required.
        return cls(
            uuid=data.get("uuid", ""),
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "?")),
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
        """Two cards are 'the same card' for listing purposes iff every
        one of these matches. NOTE: cost is deliberately included --
        this is what makes Snecko Eye's randomized-cost copies of a card
        correctly show up as separate entries instead of being
        (wrongly) collapsed together."""
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
            "name": self.name,
            "cost": self.cost,
            "playable": self.is_playable,
            "quantity": quantity,
        }
        if self.exhausts:
            d["exhausts"] = True
        if self.ethereal:
            d["ethereal"] = True
        return d

def to_deck_entry(self, quantity: int = 1) -> dict:
    return {
        "name": self.name,
        "cost": self.cost,
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
        return cls(
            name=data.get("name", data.get("id", "?")),
            current_hp=data.get("current_hp", 0),
            max_hp=data.get("max_hp", 0),
            block=data.get("block", 0),
            intent=data.get("intent", "NONE"),
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