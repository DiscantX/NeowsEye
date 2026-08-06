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

from coaching_observer import AdviceEvent, CoachingObserver, ConnectionEvent, ErrorEvent, PromptEvent
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
    """

    def __init__(self, overlay: CoachOverlay):
        self._overlay = overlay
        self._lock = threading.Lock()
        self._prompt_sequence = {}  # prompt_seq -> prompt_text for ETA tracking

    def on_connection_status(self, event: ConnectionEvent) -> None:
        """Update overlay status when ConnectionMod connects/disconnects."""
        with self._lock:
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

            # Start ETA countdown (estimate ~5-15 seconds for Gemini responses)
            eta_seconds = 10  # Safe estimate for free tier
            self._overlay.start_eta_countdown(eta_seconds)

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

            # Update tokens usage
            if event.usage_metadata and hasattr(event.usage_metadata, 'prompt_token_count'):
                tokens_used = event.usage_metadata.prompt_token_count + \
                            (event.usage_metadata.candidates_token_count or 0)
            else:
                # Fallback for demo/mocked responses
                tokens_used = 150  # Approximate 150 tokens per advice

            limit = 200000  # Configurable from .env or settings
            self._overlay.update_tokens(tokens_used, limit)

            # Clear ETA after response arrives
            self._overlay.eta_label.config(text="Ready!")
            self._overlay.eta_bar.coords(self._overlay.eta_bar_progress, 0, 0, 140, 10)
            self._overlay.feedback_status(f"Response received (lat {event.latency_s:.1f}s)")

    def on_error(self, event: ErrorEvent) -> None:
        """Display API errors in the overlay."""
        with self._lock:
            error_msg = f"API Error: {event.message}"
            if event.prompt_seq and event.prompt_seq in self._prompt_sequence:
                error_msg += f" (Prompt #{event.prompt_seq})"

            self._overlay.update_feedback(f"⚠️ Error: {error_msg}")
            self._overlay.eta_label.config(text="Error!")
            self._overlay.feedback_status(f"Error: {event.message}")

    def on_state_snapshot(self, event) -> None:
        """Optional: Could update overlay with game state info."""
        pass

    def _get_prompt_for_seq(self, seq: int) -> Optional[str]:
        """Helper to retrieve stored prompt text."""
        with self._lock:
            return self._prompt_sequence.get(seq)