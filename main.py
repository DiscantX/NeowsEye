"""
main.py

Coaching Mode: connects to CommunicationMod (via stream_adapter.py),
maintains one RunState for the life of the run, and asks Gemini for
advice at exactly the moments DecisionTrigger flags as worth asking --
once per player combat turn, and once per new non-combat decision
screen (card reward, shop, campfire, event, ...).

This replaces the old capture-mode main.py, which just dumped the first
combat_state it saw to disk and exited -- that dump is how state.py and
run_state.py's shapes got confirmed (sample_combat_state.json). This
version runs indefinitely, for the life of a run.
"""

from decision_trigger import DecisionTrigger
from gemini_client import GeminiClient
from run_state import RunState
from stream_client import StreamClient


def main():
    print("Main process started. Connecting to stream_adapter.py...")
    client = StreamClient()
    client.start()
    print("Connected!\n")

    try:
        gemini = GeminiClient()
    except RuntimeError as e:
        # Fail loud but graceful -- no API key shouldn't crash with a
        # traceback, but there's nothing useful this process can do
        # without one either.
        print(f"[Neow's Eye] {e}")
        client.close()
        return

    run_state = RunState()
    trigger = DecisionTrigger()

    # Tracks whether we were IN COMBAT as of the end of the PREVIOUS poll.
    # This is how we tell "first turn of a new fight" (-> start_combat)
    # apart from "another turn of the same fight" (-> turn_update), and
    # how we notice a fight ending (-> end_combat) even on a poll that
    # itself isn't otherwise prompt-worthy.
    in_combat = False

    try:
        while True:
            message = client.get_message()
            if message is None:
                print("Adapter disconnected.")
                break

            if not message.get("in_game"):
                if in_combat:
                    # Run ended (or was abandoned) mid-fight -- don't
                    # leave a stale Gemini session open across runs.
                    gemini.end_combat()
                    in_combat = False
                continue

            game_state = message.get("game_state", {})

            # should_prompt() reads the raw poll and its own trigger
            # history -- it doesn't depend on RunState, so it can run
            # before or after run_state.apply(). Doing it first keeps
            # "should we even bother" and "update our model of the
            # world" as separate, easy-to-follow steps.
            should_prompt = trigger.should_prompt(game_state)
            was_in_combat = in_combat

            run_state.apply(game_state)
            in_combat = run_state.combat is not None

            if was_in_combat and not in_combat:
                gemini.end_combat()

            if not should_prompt:
                continue

            if in_combat:
                if not was_in_combat:
                    payload = run_state.combat_intro_payload()
                    advice = gemini.start_combat(payload)
                else:
                    payload = run_state.turn_delta_payload()
                    advice = gemini.turn_update(payload)
                run_state.mark_synced()
                run_state.combat.mark_synced()
            else:
                payload = run_state.noncombat_payload()
                advice = gemini.one_off(payload)
                run_state.mark_synced()

            print(f"\n[Neow's Eye] {advice}\n")
    except KeyboardInterrupt:
        print("\nStopping (Ctrl+C) -- stream_adapter.py stays up, safe to restart main.py.")
    finally:
        client.close()


if __name__ == "__main__":
    main()