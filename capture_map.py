"""One-time use: dumps the first MAP screen_state we see, then exits."""
import json
from net.stream_client import StreamClient

client = StreamClient()
client.start()

print("Connected -- waiting for a MAP screen_state...")
try:
    while True:
        message = client.get_message()
        if message is None:
            print("Adapter disconnected before a MAP screen showed up.")
            break
        game_state = message.get("game_state", {})
        if game_state.get("screen_type") == "MAP":
            with open("fixtures/sample_map_state.json", "w") as f:
                json.dump(message, f, indent=2)
            print("Captured -- written to fixtures/sample_map_state.json")
            break
finally:
    client.close()