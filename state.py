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

    def to_prompt_dict(self) -> dict:
        """Compact form for a HAND card mid-combat: name (with '+' if
        upgraded), cost, and this-turn playability. Deliberately no
        effect-text field -- we lean on Gemini already knowing Slay the
        Spire's cards rather than shipping/maintaining a card-effect
        database ourselves."""
        return {
            "name": self.name + ("+" if self.upgrades else ""),
            "cost": self.cost,
            "playable": self.is_playable,
            "exhausts": self.exhausts,
            "ethereal": self.ethereal,
        }

    def to_deck_entry(self) -> dict:
        """Compact form for a DECK listing (outside the context of a
        hand/turn) -- playable/exhausts/ethereal aren't meaningful here
        since they depend on combat state this card isn't currently in."""
        return {"name": self.name + ("+" if self.upgrades else ""), "cost": self.cost}


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
class Monster:
    name: str
    current_hp: int
    max_hp: int
    block: int
    intent: str
    move_damage: Optional[int]
    move_hits: Optional[int]
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
        if self.move_damage is not None:
            d["incoming_damage"] = self.move_damage
            d["hits"] = self.move_hits
        if self.powers:
            d["powers"] = [p.to_prompt_dict() for p in self.powers]
        return d


PILE_KEYS = ("hand", "draw_pile", "discard_pile", "exhaust_pile")


def _relic_names(game_state: dict) -> list:
    return [r.get("name", r.get("id")) for r in game_state.get("relics", [])]


def _potion_names(game_state: dict) -> list:
    return [
        p.get("name")
        for p in game_state.get("potions", [])
        if p.get("name") and p.get("name") != "Potion Slot"
    ]


def _turn_payload(combat_state: dict) -> dict:
    player = combat_state.get("player", {})
    return {
        "turn": combat_state.get("turn"),
        "player": {
            "hp": player.get("current_hp"),
            "max_hp": player.get("max_hp"),
            "block": player.get("block"),
            # NOTE: verify against a real CommunicationMod dump -- energy
            # may live at combat_state level rather than under player.
            "energy": player.get("energy", combat_state.get("player_energy")),
            "powers": [Power.from_dict(p).to_prompt_dict() for p in player.get("powers", [])],
        },
        "monsters": [
            Monster.from_dict(m).to_prompt_dict()
            for m in combat_state.get("monsters", [])
            if not m.get("is_gone")
        ],
        "hand": [Card.from_dict(c).to_prompt_dict() for c in combat_state.get("hand", [])],
        "draw_pile_count": len(combat_state.get("draw_pile", [])),
        "discard_pile_count": len(combat_state.get("discard_pile", [])),
        "exhaust_pile_count": len(combat_state.get("exhaust_pile", [])),
    }


def build_combat_intro(game_state: dict) -> dict:
    """One-time payload sent when a new combat starts and a fresh Gemini
    chat session opens: everything that WON'T change turn to turn (deck,
    relics, potions), plus the turn-1 snapshot. Everything after this is
    a cheap build_turn_delta() within the same session."""
    combat_state = game_state["combat_state"]
    return {
        "event": "combat_start",
        "deck": [Card.from_dict(c).to_deck_entry() for c in game_state.get("deck", [])],
        "relics": _relic_names(game_state),
        "potions": _potion_names(game_state),
        **_turn_payload(combat_state),
    }


def build_turn_delta(combat_state: dict) -> dict:
    """Lightweight per-turn payload sent within an already-open combat
    chat session: just what changed (hand, energy, hp/block, monster
    intents). No deck/relics resend needed."""
    return {"event": "turn_update", **_turn_payload(combat_state)}


def build_noncombat_context(game_state: dict) -> dict:
    """Payload for non-combat decision screens (card reward, shop,
    campfire, event, etc). Sent as a one-off ask rather than a persistent
    chat session, since these are spaced far apart in a run."""
    return {
        "event": "decision_screen",
        "screen_type": game_state.get("screen_type"),
        "screen_state": game_state.get("screen_state"),
        "hp": game_state.get("current_hp"),
        "max_hp": game_state.get("max_hp"),
        "gold": game_state.get("gold"),
        "act": game_state.get("act"),
        "floor": game_state.get("floor"),
        "deck": [Card.from_dict(c).to_deck_entry() for c in game_state.get("deck", [])],
        "relics": _relic_names(game_state),
        "potions": _potion_names(game_state),
    }