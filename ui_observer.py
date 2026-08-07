"""
UI Observer

Bridge between main.py's coaching event stream and the CoachOverlay.
Listens for AdviceEvent and PromptEvent and updates the Tikinter overlay
in real-time, replacing the existing terminal observer for CLI output.

This is the real integration point where:
- main.py knows "advice arrived"
- GeminiWorker sends advice via observer
- UIObserver receives advice
- CoachOverlay displays advice to user
"""

import json
import threading
import time

from coaching_observer import (
    AdviceEvent, CoachingObserver, ConnectionEvent, ErrorEvent, PromptEvent, UsageEvent,
)
from gemini_client import GeminiReply
from tkinter_app import CoachOverlay
from typing import Optional



class UIObserver(CoachingObserver):
    """
    Connects CoachOverlay to main.py's event stream.

    Events flow:
    1. main.py decides to ask Gemini (via GeminiWorker.submit_*)
    2. GeminiWorker.queue task and calls observer.on_prompt_sent(PromptEvent)
    3. GeminiWorker.background thread calls GeminiClient
    4. GeminiClient receives API response
    5. GeminiWorker.background thread calls observer.on_advice_received(AdviceEvent)
    6. UIObserver receives event via on_advice_received()
    7. UIObserver calls coach_overlay.update_feedback()

    All UI updates happen in the GeminiWorker thread (background thread) so
    main.py's event loop never blocks on network latency or UI painting.
    Every CoachOverlay method this class calls (update_feedback,
    update_prompt, update_tokens, start_eta_countdown, set_eta_ready,
    set_eta_error) is itself safe to call from a non-main thread --
    each hands off to Tkinter's main thread internally via .after(0, ...).
    This class must never touch overlay widgets (e.g. eta_label,
    eta_bar) directly, since those aren't thread-safe on their own.
    """

    def __init__(self, overlay: CoachOverlay):
        self._overlay = overlay
        self._lock = threading.Lock()
        self._prompt_sequence = {}  # prompt_seq -> prompt_text for ETA tracking

    def on_connection_status(self, event: ConnectionEvent) -> None:
        """Update overlay status when ConnectionMod connects/disconnects."""
        with self._lock:
            self._overlay.set_connection_status(event.connected)
            if event.connected:
                self._overlay.feedback_status("Connected to Neow's Eye")
            else:
                self._overlay.feedback_status(f"Disconnected: {event.detail or 'Connection lost'}")

    def on_prompt_sent(self, event: PromptEvent) -> None:
        """
        Track prompts so we can update the Last Prompt section and ETA.

        This triggers when main.py decides to ask Gemini - before the API
        call is actually made. We display the prompt immediately and
        start the ETA countdown.
        """
        with self._lock:
            # Store prompt for ETA tracking
            self._prompt_sequence[event.seq] = json.dumps(event.payload) if event.payload else ""

            # Update prompt display immediately
            prompt_text = json.dumps(event.payload, indent=2) if event.payload else ""
            self._overlay.update_prompt(prompt_text)

            self._overlay.update_prompt(prompt_text)
            self._overlay.start_eta_countdown(round(event.eta_seconds))
            self._overlay.feedback_status(f"Coaching prompt #{event.seq} sent to Gemini")

            # Update status
            self._overlay.feedback_status(f"Coaching prompt #{event.seq} sent to Gemini")

    def on_advice_received(self, event: AdviceEvent) -> None:
        """
        Update the coaching feedback overlay when advice arrives.

        This is the MAIN UI update - everything the user actually sees
        comes through here: actual coaching tips, recommendations, strategies.

        We also update tokens and ETA when advice arrives.
        """
        with self._lock:
            # Update the main feedback display
            self._overlay.update_feedback(event.advice)

            # Clear ETA after response arrives -- routed through the
            # thread-safe helper rather than touching eta_label/eta_bar
            # directly, since this method runs on GeminiWorker's thread.
            self._overlay.set_eta_ready()
            self._overlay.feedback_status(f"Response received (lat {event.latency_s:.1f}s)")

    def on_error(self, event: ErrorEvent) -> None:
        """Display API errors in the overlay."""
        with self._lock:
            error_msg = f"API Error: {event.message}"
            if event.prompt_seq and event.prompt_seq in self._prompt_sequence:
                error_msg += f" (Prompt #{event.prompt_seq})"

            self._overlay.update_feedback(f"⚠️ Error: {error_msg}")
            self._overlay.set_eta_error()
            self._overlay.feedback_status(f"Error: {event.message}")

    def on_state_snapshot(self, event) -> None:
        with self._lock:
            self._overlay.update_debug_info(event.screen_type, "combat" if event.in_combat else "non-combat")
    
    def on_usage_update(self, event: UsageEvent) -> None:
        with self._lock:
            self._overlay.update_usage(
                requests_today=event.requests_today,
                daily_limit=event.daily_limit,
                requests_this_minute=event.requests_this_minute,
                rpm_limit=event.rpm_limit,
                tokens_today=event.tokens_today,
            )
            self._overlay.update_tokens(event.tokens_this_minute, event.tpm_limit)
            self._overlay.update_daily_tokens(event.tokens_today)

    def on_summary_updated(self, event: SummaryEvent) -> None:
        with self._lock:
            if event.state_summary:
                self._overlay.update_state_summary(event.state_summary)
            self._overlay.set_eta_ready()
            self._overlay.feedback_status("State of the game updated")

    def _get_prompt_for_seq(self, seq: int) -> Optional[str]:
        """Helper to retrieve stored prompt text."""
        with self._lock:
            return self._prompt_sequence.get(seq)