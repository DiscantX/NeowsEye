"""
main.py

Coaching Mode: connects to CommunicationMod (via stream_adapter.py),
maintains one RunState for the life of the run, and asks Gemini for
advice at exactly the moments DecisionTrigger flags as worth asking --
once per player combat turn, and once per new non-combat decision
screen (card reward, shop, campfire, event, ...).

As of the observer/worker refactor: this loop no longer talks to
Gemini directly and no longer prints anything itself (other than the
Ctrl+C shutdown notice, which is a pure operator courtesy on the way
out the door, not something a UI needs to see). It only (a) polls
CommunicationMod via StreamClient, (b) updates RunState, (c) decides
whether a moment is worth asking Gemini about and hands the payload to
GeminiWorker's queue if so. Everything the user actually sees flows
out through the CoachingObserver interface, so this file stays runnable
as either the terminal path or (once built) the UI path without caring
which observer is attached.
"""

import time

from coaching_observer import ConnectionEvent, ErrorEvent, ObserverBroadcaster, StateSnapshot, next_seq
from decision_trigger import DecisionTrigger
from gemini_client import GeminiClient
from gemini_worker import GeminiWorker
from run_state import RunState
from stream_client import StreamClient
from terminal_observer import TerminalObserver


def build_default_observer() -> ObserverBroadcaster:
    """The terminal path. A future UI entry point adds a UI observer
    here (or passes its own broadcaster into main()) without touching
    anything below."""
    return ObserverBroadcaster([TerminalObserver()])


def main(observer: ObserverBroadcaster = None):
    observer = observer or build_default_observer()

    client = StreamClient()
    client.start()  # blocks (with retry/backoff) until stream_adapter.py accepts
    observer.on_connection_status(
        ConnectionEvent(seq=next_seq(), timestamp=time.monotonic(), connected=True)
    )

    try:
        gemini = GeminiClient()
    except RuntimeError as e:
        # No API key -- nothing useful this process can do without one,
        # but that shouldn't crash with a traceback.
        observer.on_error(ErrorEvent(seq=next_seq(), timestamp=time.monotonic(), message=str(e)))
        client.close()
        return

    worker = GeminiWorker(gemini, observer)
    worker.start()

    run_state = RunState()
    trigger = DecisionTrigger()

    # Tracks whether we were IN COMBAT as of the end of the PREVIOUS poll.
    # This is how we tell "first turn of a new fight" (-> start_combat)
    # apart from "another turn of the same fight" (-> turn_update), and
    # how we notice a fight ending (-> end_combat) even on a poll that
    # isn't otherwise prompt-worthy.
    in_combat = False
    polls_seen = 0
    prompts_fired = 0

    try:
        while True:
            message = client.get_message()
            if message is None:
                observer.on_connection_status(ConnectionEvent(
                    seq=next_seq(), timestamp=time.monotonic(),
                    connected=False, detail="Adapter disconnected.",
                ))
                break

            polls_seen += 1

            if not message.get("in_game"):
                if in_combat:
                    worker.submit_end_combat()
                    in_combat = False
                continue

            game_state = message.get("game_state", {})

            should_prompt = trigger.should_prompt(game_state)
            was_in_combat = in_combat

            run_state.apply(game_state)
            in_combat = run_state.combat is not None

            if was_in_combat and not in_combat:
                worker.submit_end_combat()

            observer.on_state_snapshot(StateSnapshot(
                seq=next_seq(),
                timestamp=time.monotonic(),
                screen_type=run_state.screen_type,
                act=run_state.act,
                floor=run_state.floor,
                in_combat=in_combat,
                combat_turn=run_state.combat.turn if run_state.combat else None,
                polls_seen=polls_seen,
                prompts_fired=prompts_fired,
            ))

            if not should_prompt:
                continue

            prompts_fired += 1

            if in_combat:
                if not was_in_combat:
                    worker.submit_start_combat(run_state.combat_intro_payload())
                else:
                    worker.submit_turn_update(run_state.turn_delta_payload())
                run_state.mark_synced()
                run_state.combat.mark_synced()
            else:
                worker.submit_one_off(run_state.noncombat_payload())
                run_state.mark_synced()
    except KeyboardInterrupt:
        print("\nStopping (Ctrl+C) -- stream_adapter.py stays up, safe to restart main.py.")
    finally:
        client.close()


if __name__ == "__main__":
    main()