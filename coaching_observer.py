"""
Coaching Observer

Defines the boundary between "the core loop knows something happened"
and "something displays it." main.py (and gemini_worker.py, which runs
on its own thread) report events by calling methods on a
CoachingObserver; they never know or care whether that observer prints
to a terminal, feeds a UI queue, both, or neither.

Every event carries a global, thread-safe monotonic sequence number
(next_seq()) and a timestamp. Two threads touch this module
concurrently -- main.py's poll loop and GeminiWorker's background
thread -- so sequencing has to be assigned centrally rather than
trusted to arrival order. Nothing here currently NEEDS strict ordering
(GeminiWorker's own FIFO queue is what actually guarantees Gemini sees
turns in order -- see gemini_worker.py's docstring), but a UI reading
this event stream should still be able to detect "this arrived out of
order" from the sequence number rather than trusting wall-clock
arrival, in case that invariant ever changes.
"""

import itertools
import threading
from dataclasses import dataclass
from typing import Optional


_seq_lock = threading.Lock()
_seq_counter = itertools.count(1)


def next_seq() -> int:
    """Thread-safe monotonic event id. Call once per event, at the
    moment the event is known to have happened -- not when it's about
    to be displayed."""
    with _seq_lock:
        return next(_seq_counter)


@dataclass
class PromptEvent:
    seq: int
    timestamp: float          # time.monotonic() at enqueue
    kind: str                 # "start_combat" | "turn_update" | "one_off"
    payload: dict             # exactly what was/will be sent to Gemini
    eta_seconds: float = 8.0  # UsageTracker's rolling estimate at submit time

@dataclass
class UsageEvent:
    seq: int
    timestamp: float
    requests_today: int
    daily_limit: int
    requests_this_minute: int
    rpm_limit: int
    tokens_today: int
    tokens_this_minute: int
    tpm_limit: int

@dataclass
class AdviceEvent:
    seq: int
    timestamp: float          # time.monotonic() when the reply arrived
    prompt_seq: int           # links back to the PromptEvent this answers
    kind: str
    advice: str
    usage_metadata: object    # raw google.genai usage_metadata, or None --
                               # left un-shaped here; a usage_tracker.py
                               # (next slice) owns turning this into
                               # cumulative session/run totals against
                               # configured RPM/TPM limits
    latency_s: float          # wall time actually observed for this call
    reasoning: Optional[str] = None  # thinking-mode trace, if returned


@dataclass
class ErrorEvent:
    seq: int
    timestamp: float
    message: str
    prompt_seq: Optional[int] = None  # set if tied to a specific prompt


@dataclass
class ConnectionEvent:
    seq: int
    timestamp: float
    connected: bool
    detail: str = ""


@dataclass
class StateSnapshot:
    """Debug-panel material -- not coaching content, just what's useful
    for seeing what's going on. main.py decides when to emit these;
    left as its judgment call, not baked in here."""
    seq: int
    timestamp: float
    screen_type: Optional[str]
    act: Optional[int]
    floor: Optional[int]
    in_combat: bool
    combat_turn: Optional[int]
    polls_seen: int           # total messages received from StreamClient
    prompts_fired: int        # how many of those DecisionTrigger approved


class CoachingObserver:
    """Base class. All methods are no-ops by default so a concrete
    observer only needs to override what it actually displays --
    TerminalObserver, for instance, has no use for StateSnapshot."""

    def on_connection_status(self, event: ConnectionEvent) -> None:
        pass

    def on_prompt_sent(self, event: PromptEvent) -> None:
        pass

    def on_advice_received(self, event: AdviceEvent) -> None:
        pass

    def on_error(self, event: ErrorEvent) -> None:
        pass

    def on_state_snapshot(self, event: StateSnapshot) -> None:
        pass
    
    def on_usage_update(self, event: UsageEvent) -> None:
        pass


class ObserverBroadcaster(CoachingObserver):
    """Fan-out to N observers so main.py only ever holds one reference,
    regardless of whether that's [TerminalObserver], [UIObserver], or
    both. Each observer's failure is isolated -- one broken observer
    (e.g. a closed UI window) shouldn't take terminal output down with
    it."""

    def __init__(self, observers=None):
        self._observers = list(observers) if observers else []

    def add(self, observer: CoachingObserver) -> None:
        self._observers.append(observer)

    def _broadcast(self, method_name: str, event) -> None:
        for observer in self._observers:
            try:
                getattr(observer, method_name)(event)
            except Exception as e:
                # Not re-raised -- see class docstring. Printed directly
                # (not routed back through the broadcaster) to avoid
                # recursion if the failure is in a print-based observer.
                print(f"[Neow's Eye] Observer error in {method_name}: {e}")

    def on_connection_status(self, event: ConnectionEvent) -> None:
        self._broadcast("on_connection_status", event)

    def on_prompt_sent(self, event: PromptEvent) -> None:
        self._broadcast("on_prompt_sent", event)

    def on_advice_received(self, event: AdviceEvent) -> None:
        self._broadcast("on_advice_received", event)

    def on_error(self, event: ErrorEvent) -> None:
        self._broadcast("on_error", event)

    def on_state_snapshot(self, event: StateSnapshot) -> None:
        self._broadcast("on_state_snapshot", event)
        
    def on_usage_update(self, event: UsageEvent) -> None:
        self._broadcast("on_usage_update", event)