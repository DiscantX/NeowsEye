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
    "REST",
    "EVENT",
    "BOSS_REWARD",
    "GRID",
    "HAND_SELECT",
}
# SHOP_ROOM removed -- first-enter payload is always screen_state: {},
# no stock loaded yet. SHOP_SCREEN is the one that carries real inventory.


def _count_enabled_options(screen_state: dict) -> int:
    options = screen_state.get("options") or []
    return sum(1 for o in options if not o.get("disabled"))


def _grid_flavor(screen_state: dict) -> str:
    """Distinguishes the different GRID sub-screens (purge/upgrade/
    transform) so a genuine flavor change within GRID is still treated
    as a new decision, even though we otherwise dedupe GRID per-visit
    rather than per-screen_state (see should_prompt)."""
    if screen_state.get("for_purge"):
        return "purge"
    if screen_state.get("for_upgrade"):
        return "upgrade"
    if screen_state.get("for_transform"):
        return "transform"
    return "other"

def _fingerprint(screen_state):
    try:
        return json.dumps(screen_state, sort_keys=True)
    except TypeError:
        return str(screen_state)

class DecisionTrigger:
    def __init__(self):
        self._last_combat_turn = None
        self._last_screen_key = None

    def should_prompt(self, game_state: dict) -> bool:
        combat_state = game_state.get("combat_state")

        if combat_state is not None:
            self._last_screen_key = None
            if game_state.get("action_phase") != "WAITING_ON_USER":
                # combat_state can already report the new turn number here
                # even though the hand/energy haven't actually been dealt
                # out yet (mid-resolution, draw animation, etc.) -- wait
                # for the game to confirm it's genuinely our decision
                # point before treating this as prompt-worthy. See the
                # empty-hand/0-energy combat_start bug this was written
                # to catch.
                return False
            turn = combat_state.get("turn")
            is_new_turn = turn != self._last_combat_turn
            self._last_combat_turn = turn
            return is_new_turn

        self._last_combat_turn = None

        screen_type = game_state.get("screen_type")
        if screen_type not in NON_COMBAT_DECISION_SCREENS:
            self._last_screen_key = None
            return False

        screen_state = game_state.get("screen_state") or {}

        # EVENT screens with <=1 enabled option are narrative pass-throughs
        # ("[Continue]", "[Leave]", "[Talk]") -- nothing to weigh in on.
        if screen_type == "EVENT" and _count_enabled_options(screen_state) <= 1:
            self._last_screen_key = None
            return False

        # REST fires again after the player has already rested/smithed --
        # has_rested=True means the decision is already made.
        if screen_type == "REST" and screen_state.get("has_rested"):
            self._last_screen_key = None
            return False

        if screen_type == "COMBAT_REWARD":
            return self._should_prompt_combat_reward(screen_state, game_state)

        if screen_type == "GRID":
            return self._should_prompt_grid(screen_state)

        # Default: fingerprint-based dedupe (CARD_REWARD, SHOP_SCREEN,
        # BOSS_REWARD, HAND_SELECT, and multi-option EVENT).
        screen_key = (screen_type, _fingerprint(screen_state))
        is_new = screen_key != self._last_screen_key
        self._last_screen_key = screen_key
        return is_new

    def _should_prompt_combat_reward(self, screen_state: dict, game_state: dict) -> bool:
        """Fires at most once per reward screen visit (not once per pick --
        the screen_state shrinks as gold/relic/potion/card get taken, which
        used to look like 3-4 'new' screens). Gold is auto-take and the
        card slot here is just a placeholder (the real card choice is the
        separate CARD_REWARD screen, tracked on its own), so the only
        genuine decision left is a potion pickup when slots are already
        full.

        TODO: revisit the relic side of this if playtesting turns up
        relics worth skipping (e.g. situational downsides) -- right now
        relics are assumed always-worth-taking and never gate a prompt.
        """
        screen_key = ("COMBAT_REWARD",)
        is_new_visit = screen_key != self._last_screen_key
        self._last_screen_key = screen_key
        if not is_new_visit:
            return False

        rewards = screen_state.get("rewards", [])
        has_potion_reward = any(r.get("reward_type") == "POTION" for r in rewards)
        if not has_potion_reward:
            return False

        current_potions = game_state.get("potions", [])
        real_potion_count = sum(
            1 for p in current_potions
            if p.get("name") and p.get("name") != "Potion Slot"
        )
        return real_potion_count >= 3

    def _should_prompt_grid(self, screen_state: dict) -> bool:
        """Fires once per visit to a GRID screen (keyed by type + flavor:
        purge/upgrade/transform), ignoring internal screen_state churn --
        e.g. a shop purchase elsewhere changing the fingerprint used to
        re-trigger this on every poll while the player was still looking
        at the same purge/upgrade choice."""
        screen_key = ("GRID", _grid_flavor(screen_state))
        is_new = screen_key != self._last_screen_key
        self._last_screen_key = screen_key
        return is_new