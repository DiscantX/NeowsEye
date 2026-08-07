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

import config
from coaching_observer import AdviceEvent, ErrorEvent, PromptEvent, UsageEvent, SummaryEvent, next_seq
from gemini_client import GeminiClient
from usage_tracker import UsageTracker


class _Task:
    __slots__ = ("kind", "payload", "seq", "enqueued_at")

    def __init__(self, kind, payload, seq):
        self.kind = kind
        self.payload = payload
        self.seq = seq
        self.enqueued_at = time.monotonic()


class GeminiWorker:
    def __init__(self, gemini_client: GeminiClient, observer, usage_tracker: UsageTracker):
        self._gemini = gemini_client
        self._observer = observer
        self._usage = usage_tracker
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

    def submit_end_combat(self, prior_state_summary: str = "") -> int:
        return self._submit("end_combat", {"prior_state_summary": prior_state_summary})

    def _submit(self, kind, payload) -> int:
        seq = next_seq()
        task = _Task(kind, payload, seq)
        self._observer.on_prompt_sent(
            PromptEvent(
                seq=seq, timestamp=task.enqueued_at, kind=kind, payload=payload,
                eta_seconds=self._usage.eta_seconds(),
            )
        )
        self._queue.put(task)
        return seq

    def _run(self):
        while True:
            task = self._queue.get()

            if self._usage.is_daily_quota_exhausted():
                if task.kind == "end_combat":
                    # Can't afford the extra request -- still have to close
                    # the session so it doesn't leak into the next fight's
                    # start_combat(). No error surfaced here specifically:
                    # whatever advice call already hit this quota wall this
                    # fight will have shown the error once already.
                    self._gemini.discard_combat_session()
                else:
                    self._observer.on_error(ErrorEvent(
                        seq=next_seq(), timestamp=time.monotonic(),
                        message=(
                            f"Daily Gemini quota reached ({self._usage.rpd_limit} requests) -- "
                            f"resets at {config.QUOTA_RESET_HOUR}:00 {config.QUOTA_RESET_TIMEZONE}."
                        ),
                        prompt_seq=task.seq,
                    ))
                continue

            wait = self._usage.wait_time()
            if wait > 0:
                time.sleep(wait)

            start = time.monotonic()
            try:
                reply = self._dispatch(task)
            except Exception as e:
                if task.kind == "end_combat":
                    self._gemini.discard_combat_session()
                self._observer.on_error(ErrorEvent(
                    seq=next_seq(), timestamp=time.monotonic(),
                    message=f"Gemini call failed ({task.kind}): {e}",
                    prompt_seq=task.seq,
                ))
                continue

            if task.kind == "end_combat" and reply is None:
                # No session was open -- nothing to summarize, no request
                # made. Still emit a SummaryEvent so an ETA countdown the
                # observer started on submit doesn't hang indefinitely.
                self._observer.on_summary_updated(SummaryEvent(
                    seq=next_seq(), timestamp=time.monotonic(),
                    combat_summary="", state_summary=task.payload.get("prior_state_summary", ""),
                ))
                continue

            latency = time.monotonic() - start
            self._usage.record_request(latency_s=latency, tokens=_total_tokens(reply.usage_metadata))

            usage = self._usage.snapshot()
            self._observer.on_usage_update(UsageEvent(
                seq=next_seq(), timestamp=time.monotonic(),
                requests_today=usage["requests_today"], daily_limit=usage["rpd_limit"],
                requests_this_minute=usage["requests_this_minute"], rpm_limit=usage["rpm_limit"],
                tokens_today=usage["tokens_today"],
                tokens_this_minute=usage["tokens_this_minute"], tpm_limit=usage["tpm_limit"],
            ))

            if task.kind == "end_combat":
                self._observer.on_summary_updated(SummaryEvent(
                    seq=next_seq(), timestamp=time.monotonic(),
                    combat_summary=reply.combat_summary, state_summary=reply.state_summary,
                ))
            else:
                self._observer.on_advice_received(AdviceEvent(
                    seq=next_seq(), timestamp=time.monotonic(), prompt_seq=task.seq,
                    kind=task.kind, advice=reply.text, usage_metadata=reply.usage_metadata,
                    latency_s=latency, reasoning=reply.reasoning,
                ))

    def _dispatch(self, task: _Task):
        if task.kind == "start_combat":
            return self._gemini.start_combat(task.payload)
        if task.kind == "turn_update":
            return self._gemini.turn_update(task.payload)
        if task.kind == "one_off":
            return self._gemini.one_off(task.payload)
        if task.kind == "end_combat":
            return self._gemini.end_combat(task.payload.get("prior_state_summary", ""))
        raise ValueError(f"Unknown task kind: {task.kind}")


def _total_tokens(usage_metadata) -> int:
    if usage_metadata is None:
        return 0
    prompt = getattr(usage_metadata, "prompt_token_count", 0) or 0
    candidates = getattr(usage_metadata, "candidates_token_count", 0) or 0
    return prompt + candidates