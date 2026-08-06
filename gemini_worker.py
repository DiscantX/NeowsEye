"""
Gemini Worker

Owns the single background thread allowed to touch GeminiClient. Runs
Gemini calls off the main polling thread so main.py's loop (and any UI
reading the observer stream) never blocks on network latency -- and,
just as importantly, serializes every call through one FIFO queue so
two decision points landing close together (e.g. a fast turn resolving
right after a slow combat_start round-trip) can never race on
GeminiClient's shared self._chat session state. One worker thread, one
queue, strict submission order -- THAT ordering guarantee is what makes
this safe, not the event sequence numbers in coaching_observer.py
(those are UI-side insurance only).

Session teardown (end_combat) is a queued task too, not a direct call
-- see submit_end_combat(). If it bypassed the queue, a combat-ending
poll could null out self._chat while a still-queued turn_update from
that same fight was in flight, and the worker would misread that
straggler as the start of a brand new session.

main.py's job is reduced to: build a payload, call one of the submit_*
methods, keep polling CommunicationMod. Everything about actually
talking to Gemini -- and reporting what happened -- lives here.
"""

import queue
import threading
import time

from coaching_observer import AdviceEvent, ErrorEvent, PromptEvent, next_seq
from gemini_client import GeminiClient


class _Task:
    __slots__ = ("kind", "payload", "seq", "enqueued_at")

    def __init__(self, kind, payload, seq):
        self.kind = kind  # "start_combat" | "turn_update" | "one_off" | "end_combat"
        self.payload = payload
        self.seq = seq
        self.enqueued_at = time.monotonic()


class GeminiWorker:
    def __init__(self, gemini_client: GeminiClient, observer):
        self._gemini = gemini_client
        self._observer = observer
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            self._thread.start()

    def submit_start_combat(self, payload: dict) -> int:
        return self._submit("start_combat", payload)

    def submit_turn_update(self, payload: dict) -> int:
        return self._submit("turn_update", payload)

    def submit_one_off(self, payload: dict) -> int:
        return self._submit("one_off", payload)

    def submit_end_combat(self) -> int:
        """Queued, not direct -- see module docstring."""
        seq = next_seq()
        self._queue.put(_Task("end_combat", None, seq))
        return seq

    def _submit(self, kind, payload) -> int:
        seq = next_seq()
        task = _Task(kind, payload, seq)
        self._observer.on_prompt_sent(
            PromptEvent(seq=seq, timestamp=task.enqueued_at, kind=kind, payload=payload)
        )
        self._queue.put(task)
        return seq

    def _run(self):
        """THREAD: the only thread ever allowed to call into
        self._gemini. Processes tasks strictly in submission order --
        this is what keeps a combat session's message history coherent,
        not anything on the caller's side."""
        while True:
            task = self._queue.get()

            if task.kind == "end_combat":
                try:
                    self._gemini.end_combat()
                except Exception as e:
                    self._observer.on_error(ErrorEvent(
                        seq=next_seq(), timestamp=time.monotonic(),
                        message=f"end_combat failed: {e}", prompt_seq=task.seq,
                    ))
                continue

            start = time.monotonic()
            try:
                reply = self._dispatch(task)
            except Exception as e:
                # Gemini/network errors shouldn't kill the worker thread --
                # report and keep processing the next queued task.
                self._observer.on_error(ErrorEvent(
                    seq=next_seq(), timestamp=time.monotonic(),
                    message=f"Gemini call failed ({task.kind}): {e}",
                    prompt_seq=task.seq,
                ))
                continue

            self._observer.on_advice_received(AdviceEvent(
                seq=next_seq(),
                timestamp=time.monotonic(),
                prompt_seq=task.seq,
                kind=task.kind,
                advice=reply.text,
                usage_metadata=reply.usage_metadata,
                latency_s=time.monotonic() - start,
            ))

    def _dispatch(self, task: _Task):
        if task.kind == "start_combat":
            return self._gemini.start_combat(task.payload)
        if task.kind == "turn_update":
            return self._gemini.turn_update(task.payload)
        if task.kind == "one_off":
            return self._gemini.one_off(task.payload)
        raise ValueError(f"Unknown task kind: {task.kind}")