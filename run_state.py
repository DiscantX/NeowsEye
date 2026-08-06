"""
run_state.py

The persistent layer that state.py doesn't have. Everything in state.py
is a pure dict-transform -- built fresh and discarded every poll. RunState
is the first thing in the whole pipeline that survives across polls: one
instance per run, updated (not rebuilt) as each game_state dict arrives
from StreamClient.

CombatState is owned by RunState (composition, not inheritance -- a fight
is not a kind of run). RunState.combat is None outside a fight and a
fresh CombatState instance during one; construction happens on the
combat_state key appearing, teardown on it disappearing.

Dirty tracking, per the design conversation:
  - "Changed since last poll" and "changed since Gemini last heard about
    it" are the same THING, but must be two different CLOCKS. apply()
    computes what changed and adds it to a dirty set. mark_synced() is
    the ONLY thing that clears it, and must only be called after a
    payload actually gets sent to Gemini -- never from inside apply().
    If those two clocks get collapsed into one, a change that arrives
    between two Gemini-worthy polls (e.g. mid-turn chip damage) can get
    silently marked "already known" before it's ever actually been sent.
  - A freshly-constructed CombatState has every one of its fields dirty
    by definition -- there's no prior baseline to diff against, and a
    new fight always needs a full snapshot sent regardless.
  - Diffing is done by "construct new objects from the incoming dict,
    compare whole-field to what's stored, replace if different" -- not
    in-place mutation. This applies at the level of whole fields (e.g.
    the whole `hand` list, the whole `monsters` list), not per-card --
    see _fingerprint().

Deliberately NOT built here (out of scope for this pass -- flagged, not
forgotten):
  - Gemini session/transcript persistence, seed-keyed resume, and
    mid-run-join catch-up-snapshot detection. That's gemini_client.py's
    concern; RunState just needs to expose enough (see `is_fresh_run()`)
    for that layer to make its own call.
  - MapState, and any other screen-scoped sub-state beyond CombatState.
    Per the rule of three, we're not generalizing the "owned sub-state
    with everything-dirty-on-entry" pattern into a shared base class
    until there's a second real example to generalize FROM. The
    convention to preserve for whoever builds the next one: an
    Optional[SomeState] field on RunState, None when inactive, and the
    sub-state's own __init__ seeds its dirty set with every tracked
    field so RunState.apply() doesn't need type-specific logic to know
    "this is new."
  - Bottled-card representation on Relic/Potion -- shape unconfirmed,
    needs a real capture with a bottled relic before it's built.
  - Frozen Eye ordered-draw-pile exception -- draw_pile is count-only
    for everyone right now. Add the conditional (full ordered list of
    card names, only when Frozen Eye is in self.relics) once we've
    confirmed Frozen Eye's actual relic id from a capture.
"""

import json
from typing import Optional

from state import Card, Monster, Orb, Power, Potion, Relic, dedupe_cards


def _fingerprint(value):
    """Structural equality check across polls. Works on dataclasses (via
    their generated __repr__... no -- dataclasses aren't JSON-serializable
    out of the box, so we go through __dict__) and on the (Card, qty)
    tuples dedupe_cards() produces."""

    def default(o):
        if hasattr(o, "__dict__"):
            return o.__dict__
        raise TypeError(f"Cannot fingerprint {type(o)}")

    return json.dumps(value, default=default, sort_keys=True)


class CombatState:
    """One fight's worth of state. Constructed when combat_state first
    appears in a poll, discarded (the RunState.combat slot is set back to
    None) when it disappears. Everything is dirty at construction --
    see module docstring."""

    # Field names we diff/track. Kept as a tuple (not derived from
    # dataclass introspection) since some of these are derived values
    # (pile counts) rather than 1:1 JSON fields.
    TRACKED_FIELDS = (
        "turn",
        "cards_discarded_this_turn",
        "player_hp",
        "player_block",
        "player_energy",
        "player_powers",
        "player_orbs",
        "monsters",
        "hand",
        "draw_pile_count",
        "discard_pile_count",
        "exhaust_pile_count",
    )

    def __init__(self, combat_state_dict: dict):
        # Defaults so getattr() in _apply's diff loop always has
        # something to compare against on the very first call (which
        # then immediately marks everything dirty anyway).
        for f in self.TRACKED_FIELDS:
            setattr(self, f, None)
        self.player_powers = []
        self.player_orbs = []
        self.monsters = []
        self.hand = []

        self.dirty = set()
        self._apply(combat_state_dict, force_dirty=True)

    def apply(self, combat_state_dict: dict):
        """Call on every poll while combat is ongoing."""
        self._apply(combat_state_dict, force_dirty=False)

    def _apply(self, data: dict, force_dirty: bool):
        player = data.get("player", {})
        new_values = {
            "turn": data.get("turn"),
            "cards_discarded_this_turn": data.get("cards_discarded_this_turn", 0),
            "player_hp": player.get("current_hp"),
            "player_block": player.get("block"),
            "player_energy": player.get("energy"),
            "player_powers": [Power.from_dict(p) for p in player.get("powers", [])],
            "player_orbs": [Orb.from_dict(o) for o in player.get("orbs", [])],
            "monsters": [
                Monster.from_dict(m) for m in data.get("monsters", []) if not m.get("is_gone")
            ],
            "hand": dedupe_cards([Card.from_dict(c) for c in data.get("hand", [])]),
            "draw_pile_count": len(data.get("draw_pile", [])),
            "discard_pile_count": len(data.get("discard_pile", [])),
            "exhaust_pile_count": len(data.get("exhaust_pile", [])),
        }
        for field_name, new_value in new_values.items():
            if force_dirty or _fingerprint(new_value) != _fingerprint(getattr(self, field_name)):
                setattr(self, field_name, new_value)
                self.dirty.add(field_name)

    def mark_synced(self):
        self.dirty.clear()

    def full_payload(self) -> dict:
        """Everything, regardless of dirty state -- used for combat_start."""
        return self._payload(self.TRACKED_FIELDS)

    def dirty_payload(self) -> dict:
        """Only fields that changed since the last mark_synced() -- used
        for the ongoing per-turn deltas within a ChatSession."""
        return self._payload(self.dirty)

    def _payload(self, fields) -> dict:
        d = {}
        if "turn" in fields:
            d["turn"] = self.turn
        if "cards_discarded_this_turn" in fields and self.cards_discarded_this_turn:
            d["cards_discarded_this_turn"] = self.cards_discarded_this_turn
        player = {}
        if "player_hp" in fields:
            player["hp"] = self.player_hp
        if "player_block" in fields:
            player["block"] = self.player_block
        if "player_energy" in fields:
            player["energy"] = self.player_energy
        if "player_powers" in fields:
            player["powers"] = [p.to_prompt_dict() for p in self.player_powers]
        if "player_orbs" in fields and self.player_orbs:
            player["orbs"] = [o.to_prompt_dict() for o in self.player_orbs]
        if player:
            d["player"] = player
        if "monsters" in fields:
            d["monsters"] = [m.to_prompt_dict() for m in self.monsters]
        if "hand" in fields:
            d["hand"] = [card.to_prompt_dict(qty) for card, qty in self.hand]
        if "draw_pile_count" in fields:
            d["draw_pile_count"] = self.draw_pile_count
        if "discard_pile_count" in fields:
            d["discard_pile_count"] = self.discard_pile_count
        if "exhaust_pile_count" in fields:
            d["exhaust_pile_count"] = self.exhaust_pile_count
        return d


class RunState:
    """One instance per run. Construct once, then call apply(game_state)
    on every poll for the life of the run."""

    TRACKED_FIELDS = (
        "class_name",
        "ascension_level",
        "seed",
        "act",
        "act_boss",
        "floor",
        "current_hp",
        "max_hp",
        "gold",
        "deck",
        "relics",
        "potions",
        "screen_type",
        "screen_state",
    )

    def __init__(self):
        for f in self.TRACKED_FIELDS:
            setattr(self, f, None)
        self.deck = []
        self.relics = []
        self.potions = []
        self.combat: Optional[CombatState] = None

        self.dirty = set()
        self._initialized = False

    def apply(self, game_state: dict):
        """Call on every poll, with game_state == message['game_state']
        from a StreamClient message. Handles both the run-level fields
        and combat start/continue/end."""
        force_dirty = not self._initialized
        self._initialized = True

        new_act = game_state.get("act")
        new_values = {
            "class_name": game_state.get("class"),
            "ascension_level": game_state.get("ascension_level"),
            "seed": game_state.get("seed"),
            "act": new_act,
            "floor": game_state.get("floor"),
            "current_hp": game_state.get("current_hp"),
            "max_hp": game_state.get("max_hp"),
            "gold": game_state.get("gold"),
            "deck": dedupe_cards([Card.from_dict(c) for c in game_state.get("deck", [])]),
            "relics": [Relic.from_dict(r) for r in game_state.get("relics", [])],
            "potions": [
                p for p in (Potion.from_dict(p) for p in game_state.get("potions", []))
                if p.is_real()
            ],
            "screen_type": game_state.get("screen_type"),
            "screen_state": game_state.get("screen_state"),
        }

        act_changed = new_act != self.act
        for field_name, new_value in new_values.items():
            if field_name == "act_boss":
                continue  # handled below, paired with act
            if force_dirty or _fingerprint(new_value) != _fingerprint(getattr(self, field_name)):
                setattr(self, field_name, new_value)
                self.dirty.add(field_name)

        # act_boss only changes once per act -- key it off act changing
        # rather than diffing it independently (per design: cheaper
        # signal, and the two are semantically one event).
        if force_dirty or act_changed:
            self.act_boss = game_state.get("act_boss")
            self.dirty.add("act_boss")

        combat_dict = game_state.get("combat_state")
        if combat_dict is not None:
            if self.combat is None:
                self.combat = CombatState(combat_dict)  # fresh fight: everything dirty
            else:
                self.combat.apply(combat_dict)
        else:
            self.combat = None  # fight ended (or never started)

    def mark_synced(self):
        """Call after a run-level payload has actually been sent to
        Gemini. Does NOT touch self.combat's dirty state -- that's
        cleared separately via self.combat.mark_synced(), since combat
        turns and run-level decision screens are sent as distinct
        messages."""
        self.dirty.clear()

    def is_fresh_run(self) -> bool:
        """Best-effort signal for 'this looks like floor 1 of a brand
        new run' vs. 'we're joining a run already in progress' -- for
        gemini_client.py's session-resume logic to consult. Not a
        guarantee (a modified starting deck via Neow bonus is still
        floor 1), just the cheap/obvious check.
        """
        return self.floor == 1 and len(self.relics) <= 1

    # -- Payload builders -------------------------------------------------
    # These replace state.py's old build_combat_intro / build_turn_delta /
    # build_noncombat_context. They read from RunState instead of a raw
    # dict, and lean on dirty tracking instead of always resending
    # everything -- the piece that actually delivers Tier 5 ("only send
    # when changed") now that there's something to diff against.

    def _run_level_payload(self, fields) -> dict:
        d = {}
        if "class_name" in fields:
            d["class"] = self.class_name
        if "ascension_level" in fields:
            d["ascension"] = self.ascension_level
        if "act" in fields:
            d["act"] = self.act
        if "act_boss" in fields:
            d["act_boss"] = self.act_boss
        if "floor" in fields:
            d["floor"] = self.floor
        if "current_hp" in fields or "max_hp" in fields:
            d["hp"] = self.current_hp
            d["max_hp"] = self.max_hp
        if "gold" in fields:
            d["gold"] = self.gold
        if "deck" in fields:
            d["deck"] = [card.to_deck_entry(qty) for card, qty in self.deck]
        if "relics" in fields:
            d["relics"] = [r.to_prompt_dict() for r in self.relics]
        if "potions" in fields:
            d["potions"] = [p.to_prompt_dict() for p in self.potions]
        return d

    def combat_intro_payload(self) -> dict:
        """Sent once, when a fresh CombatState is created (chats.create()
        time in gemini_client.py). Full run-level state (first time or
        whatever's dirty since we last synced) + full combat snapshot."""
        assert self.combat is not None
        payload = {"event": "combat_start"}
        payload.update(self._run_level_payload(self.dirty))
        payload.update(self.combat.full_payload())
        return payload

    def turn_delta_payload(self) -> dict:
        """Sent on subsequent turns of an ongoing fight. Only dirty
        run-level fields (e.g. a relic picked up mid-combat via a card
        effect) plus only dirty combat fields."""
        assert self.combat is not None
        payload = {"event": "turn_update"}
        payload.update(self._run_level_payload(self.dirty))
        payload.update(self.combat.dirty_payload())
        return payload

    def noncombat_payload(self) -> dict:
        """Sent for a decision screen (card reward, shop, campfire,
        event...). Only dirty run-level fields -- with a long-lived
        Gemini session, deck/relics/potions that haven't changed since
        last mentioned don't need to be resent here."""
        payload = {
            "event": "decision_screen",
            "screen_type": self.screen_type,
            "screen_state": self.screen_state,
        }
        payload.update(self._run_level_payload(self.dirty))
        return payload