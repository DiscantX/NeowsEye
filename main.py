"""
main.py

Listens continuously to CommunicationMod's unprompted state pushes (sent
after every in-game action), relayed through stream_adapter.py. Parses
combat pile data (hand, draw, discard, exhaust) into Card objects via
state.py. Sends 'state' only to request a snapshot without taking an action.
"""

from stream_client import StreamClient
from state import Card

print("Main process started. Connecting to stream_adapter.py...")

client = StreamClient()
client.start()

print("Connected successfully! Listening for state updates...\n")

PILE_KEYS = ("hand", "draw_pile", "discard_pile", "exhaust_pile")

while True:
    message = client.get_message()
    if message is None:
        print("Adapter disconnected.")
        break

    if not message.get("in_game"):
        print(f"in_game=False available_commands={message.get('available_commands')}")
        continue

    game_state = message.get("game_state", {})
    screen_type = game_state.get("screen_type")
    combat_state = game_state.get("combat_state")

    if combat_state is None:
        # Not in combat right now (e.g. on the map, in a shop, at a reward screen).
        print(f"screen_type={screen_type} room_type={game_state.get('room_type')}")
        continue

    piles = {
        key: [Card.from_dict(c) for c in combat_state.get(key, [])]
        for key in PILE_KEYS
    }

    print(f"screen_type={screen_type} turn={combat_state.get('turn')}")
    print(
        f"  hand={len(piles['hand'])} "
        f"draw_pile={len(piles['draw_pile'])} "
        f"discard_pile={len(piles['discard_pile'])} "
        f"exhaust_pile={len(piles['exhaust_pile'])}"
    )

    print("Hand:")
    for card in piles["hand"]:
        tag = " [UPGRADED]" if card.upgrades else ""
        playable = "" if card.is_playable else " (not playable)"
        print(f"  - {card.name}{tag} cost={card.cost}{playable}")

client.close()