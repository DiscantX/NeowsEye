"""
Decision Trigger

CommunicationMod pushes an unprompted 'state' message after every single
in-game action (a block resolving, an enemy attacking, a card animation
finishing) -- not just when the player actually has a decision to make.
This class filters that firehose down to the moments actually worth
asking Gemini about: once per player turn in combat, and once per new
non-combat decision screen (card reward, shop, campfire, event, ...).
"""

import json

NON_COMBAT_DECISION_SCREENS = {
    "CARD_REWARD",
    "COMBAT_REWARD",
    "SHOP_SCREEN",
    "SHOP_ROOM",
    "REST",
    "EVENT",
    "BOSS_REWARD",
    "GRID",  # e.g. discard/select-card screens
    "HAND_SELECT",
}


class DecisionTrigger:
    def __init__(self):
        self._last_combat_turn = None
        self._last_screen_key = None

    def should_prompt(self, game_state: dict) -> bool:
        combat_state = game_state.get("combat_state")

        if combat_state is not None:
            self._last_screen_key = None  # left any non-combat screen
            turn = combat_state.get("turn")
            is_new_turn = turn != self._last_combat_turn
            self._last_combat_turn = turn
            return is_new_turn

        # Not in combat right now -- reset so the next fight's turn 1
        # always registers as new.
        self._last_combat_turn = None

        screen_type = game_state.get("screen_type")
        if screen_type not in NON_COMBAT_DECISION_SCREENS:
            self._last_screen_key = None
            return False

        # Fingerprint screen_type + screen_state so repeated unprompted
        # pushes for the *same* reward/shop/event screen don't re-fire.
        screen_key = (screen_type, _fingerprint(game_state.get("screen_state")))
        is_new = screen_key != self._last_screen_key
        self._last_screen_key = screen_key
        return is_new


def _fingerprint(screen_state):
    try:
        return json.dumps(screen_state, sort_keys=True)
    except TypeError:
        return str(screen_state)