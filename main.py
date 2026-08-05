"""
main.py

CAPTURE MODE (temporary): listens to CommunicationMod's state pushes,
relayed through stream_adapter.py, until a combat_state shows up --
then saves that ENTIRE raw message to disk as a single fixed reference
state and exits. This gives us something stable to itemize offline and
decide what's worth sending to Gemini, instead of a moving target.

The decision-engine wiring (DecisionTrigger / GeminiClient / state.py's
snapshot builders) will come back in a later pass once we know what
CommunicationMod actually sends.

To use: start a fight in-game while this is running. It captures the
first combat_state it sees and exits on its own.
"""

import json

from stream_client import StreamClient

OUTPUT_PATH = "sample_combat_state.json"

print("Main process started. Connecting to stream_adapter.py...")

client = StreamClient()
client.start()

print("Connected! Waiting for a combat state to capture...\n")

captured = False
while not captured:
    message = client.get_message()
    if message is None:
        print("Adapter disconnected before a combat state arrived.")
        break

    if not message.get("in_game"):
        print("in_game=False -- waiting for a run to start...")
        continue

    game_state = message.get("game_state", {})
    if game_state.get("combat_state") is None:
        print(
            f"screen_type={game_state.get('screen_type')} "
            f"room_type={game_state.get('room_type')} (waiting for combat)"
        )
        continue

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(message, f, indent=2, sort_keys=True)

    combat_state = game_state["combat_state"]
    print(f"\nCaptured combat state -> {OUTPUT_PATH}")
    print(f"  turn={combat_state.get('turn')} room_type={game_state.get('room_type')}")
    captured = True

client.close()