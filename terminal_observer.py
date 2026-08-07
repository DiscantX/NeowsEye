"""
Terminal Observer

Preserves the pre-UI behavior: coaching advice printed to stdout as it
arrives. Deliberately minimal -- doesn't render prompts, ETA, state
snapshots, or usage; those only matter once there's something visual
to put them in. If terminal-mode debugging ever wants more than this,
extend here rather than routing terminal output back through main.py.
"""

from coaching_observer import AdviceEvent, CoachingObserver, ConnectionEvent, ErrorEvent


class TerminalObserver(CoachingObserver):
    def on_connection_status(self, event: ConnectionEvent) -> None:
        if not event.connected:
            print(f"[Neow's Eye] {event.detail or 'Disconnected.'}")

    def on_advice_received(self, event: AdviceEvent) -> None:
        if event.reasoning:
            print(f"\n[Neow's Eye] (reasoning)\n{event.reasoning}")
        print(f"\n[Neow's Eye] {event.advice}\n")

    def on_error(self, event: ErrorEvent) -> None:
        print(f"[Neow's Eye] {event.message}")