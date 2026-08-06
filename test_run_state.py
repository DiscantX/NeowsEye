import copy
import json

from run_state import RunState

with open("sample_combat_state.json") as f:
    message = json.load(f)

game_state = message["game_state"]

print("=== 1. First poll (combat_start) ===")
rs = RunState()
rs.apply(game_state)
intro = rs.combat_intro_payload()
print(json.dumps(intro, indent=2))
rs.mark_synced()
rs.combat.mark_synced()

print("\n=== 2. Identical re-poll (nothing should be dirty) ===")
rs.apply(game_state)
print("RunState dirty:", rs.dirty)
print("CombatState dirty:", rs.combat.dirty)
assert rs.dirty == set()
assert rs.combat.dirty == set()
print("OK -- no spurious dirt on an unchanged poll.")

print("\n=== 3. Simulated chip damage across a few polls DecisionTrigger ignores ===")
gs2 = copy.deepcopy(game_state)
gs2["combat_state"]["player"]["current_hp"] = 70
rs.apply(gs2)  # DecisionTrigger wouldn't send here -- no mark_synced() call
print("CombatState dirty after chip damage (not yet synced):", rs.combat.dirty)
assert "player_hp" in rs.combat.dirty

gs3 = copy.deepcopy(gs2)
gs3["combat_state"]["player"]["current_hp"] = 65
rs.apply(gs3)  # still not synced -- dirty set should just keep player_hp, not lose it
print("CombatState dirty after second chip (still not synced):", rs.combat.dirty)
assert "player_hp" in rs.combat.dirty
assert rs.combat.player_hp == 65
print("OK -- dirty flag survives multiple polls until actually synced (no premature clearing).")

print("\n=== 4. Turn delta payload only includes what's dirty ===")
delta = rs.turn_delta_payload()
print(json.dumps(delta, indent=2))
assert "hand" not in delta  # hand didn't change, shouldn't be resent
assert delta["player"]["hp"] == 65
rs.combat.mark_synced()
print("OK -- turn delta is lean, only carries the changed field.")

print("\n=== 5. Deck/hand dedup ===")
print("Deck entries:", len(rs.deck), "-> expect 3 (Strike x5, Defend x4, Bash x1)")
for card, qty in rs.deck:
    print(f"  {card.name}{'+' if card.upgrades else ''} x{qty}  cost={card.cost}")
assert len(rs.deck) == 3
strike_entry = next((c, q) for c, q in rs.deck if c.name == "Strike")
assert strike_entry[1] == 5
defend_entry = next((c, q) for c, q in rs.deck if c.name == "Defend")
assert defend_entry[1] == 4
print("OK -- deck correctly deduped to 3 entries with right quantities.")

print("\n=== 6. Potion Slot placeholders filtered out ===")
print("Potions:", rs.potions)
assert rs.potions == []
print("OK -- empty potion slots don't leak into the payload.")

print("\n=== 7. Relic counter: -1 sentinel omitted, real counter kept ===")
relic_payload = rs._run_level_payload({"relics"})["relics"]
print(relic_payload)
assert relic_payload[0] == {"name": "Burning Blood"}  # counter -1 -> omitted
assert relic_payload[1] == {"name": "Neow's Lament", "counter": 2}  # counter 2 -> kept
print("OK.")

print("\n=== 8. Combat ends -> RunState.combat goes back to None ===")
gs_no_combat = copy.deepcopy(game_state)
gs_no_combat["combat_state"] = None
gs_no_combat["screen_type"] = "CARD_REWARD"
rs.apply(gs_no_combat)
assert rs.combat is None
assert rs.screen_type == "CARD_REWARD"
print("OK -- combat cleared, screen_type picked up as dirty for the next noncombat payload.")
noncombat = rs.noncombat_payload()
print(json.dumps(noncombat, indent=2))

print("\n=== 9. New fight starts -> fresh CombatState, everything dirty again ===")
gs_new_fight = copy.deepcopy(game_state)
gs_new_fight["combat_state"]["turn"] = 1
rs.apply(gs_new_fight)
assert rs.combat is not None
assert rs.combat.dirty == set(rs.combat.TRACKED_FIELDS)
print("OK -- new CombatState instance starts fully dirty, no leftover state from the last fight.")

print("\nAll checks passed.")