"""
Public API update methods and background ETA worker for the Coach Overlay.
"""

import time
import threading
from datetime import datetime
import tkinter as tk


class OverlayApiMixin:
    """Mixin providing state updates, feedback history, ETA countdown, and telemetry methods."""

    @staticmethod
    def _is_scrolled_to_bottom(text_widget, threshold=0.98) -> bool:
        """Whether the visible viewport already reaches (or is very near) the end of the text."""
        try:
            _, bottom = text_widget.yview()
        except tk.TclError:
            return True
        return bottom >= threshold

    def update_feedback(self, feedback: str):
        """Append a new coaching-feedback entry, with a timestamp header, to the scrollable history."""
        def _update():
            text = self.feedback_text
            was_at_bottom = self._is_scrolled_to_bottom(text)
            timestamp = datetime.now().strftime('%H:%M:%S')

            text.config(state=tk.NORMAL)
            if self._feedback_entry_count > 0:
                text.insert(tk.END, "\n\n")
            text.insert(tk.END, f"── {timestamp} ──\n", 'timestamp')
            text.insert(tk.END, feedback, 'body')
            text.config(state=tk.DISABLED)
            self._feedback_entry_count += 1

            if was_at_bottom:
                text.see(tk.END)

            self._feedback_data.feedback = feedback
            self._feedback_data.last_update = time.time()
            self.status_label.config(text=f"Updated: {timestamp}")
        self.after(0, _update)

    def clear_feedback_history(self):
        """Wipe the feedback history."""
        self.feedback_text.config(state=tk.NORMAL)
        self.feedback_text.delete('1.0', tk.END)
        self.feedback_text.config(state=tk.DISABLED)
        self._feedback_entry_count = 0

    def update_prompt(self, prompt: str):
        """Update the last-prompt display."""
        def _update():
            self._feedback_data.last_prompt = prompt
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete('1.0', tk.END)
            self.prompt_text.insert(tk.END, prompt)
            self.prompt_text.config(state=tk.DISABLED)
            self.prompt_text.see('1.0')
        self.after(0, _update)

    def update_state_summary(self, summary: str):
        """Update the state of the game summary display."""
        def _update():
            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete('1.0', tk.END)
            self.summary_text.insert(tk.END, summary)
            self.summary_text.config(state=tk.DISABLED)
            self.summary_text.see('1.0')
        self.after(0, _update)

    def start_eta_countdown(self, seconds: int):
        """Start the ETA countdown timer."""
        self._feedback_data.eta_seconds = seconds
        self._feedback_data.is_loading = True

        self._eta_start_time = time.time()
        self._eta_thread = threading.Thread(
            target=self._eta_worker, args=(seconds,), daemon=True,
        )
        self._eta_thread.start()

        self.eta_label.config(text="0:00")
        self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 8)

    def _eta_worker(self, total_seconds: int):
        """Background worker for countdown timer."""
        total = total_seconds

        for remaining in range(total, -1, -1):
            if not self._running:
                break

            elapsed = total - remaining
            progress_width = int((elapsed / total) * 160) if total > 0 else 0

            mins = remaining // 60
            secs = remaining % 60
            time_str = f"{mins}:{secs:02d}"

            def _update_eta_display():
                self.eta_label.config(text=time_str)
                self.eta_bar.coords(
                    self.eta_bar_progress, 0, 0,
                    max(progress_width, 1) if remaining > 0 else 160, 8,
                )
                if remaining > 0:
                    self.status_label.config(text="Awaiting response...")

            self.after(0, _update_eta_display)

            if remaining > 0:
                time.sleep(1)

        def _finish_countdown():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Ready!")
            self.status_label.config(text="Response ready!")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 160, 8)
            self.after(3000, lambda: self.eta_label.config(text="--:--"))
            self.after(3000, lambda: self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 8))

        self.after(0, _finish_countdown)

    def update_tokens(self, used: int, limit: int = 200000):
        """Update token usage display."""
        self._feedback_data.tokens_used = used
        self._feedback_data.token_limit = limit

        def _update_token_display():
            percentage = (used / limit * 100) if limit > 0 else 0

            used_str = f"{used/1000:.1f}k" if used >= 1000 else str(used)
            limit_str = f"{limit/1000:.0f}k" if limit >= 1000 else str(limit)

            if percentage < 75:
                bar_color = self.config_data.success_color
            elif percentage < 90:
                bar_color = self.config_data.eta_color
            else:
                bar_color = self.config_data.error_color

            self.token_label.config(text=f"{used_str} / {limit_str}", fg=bar_color)

            bar_width = int((percentage / 100) * 140)
            self.token_bar.delete("progress")
            self.token_bar.create_rectangle(
                1, 1, max(bar_width, 1), 7, fill=bar_color, outline="", tags="progress",
            )

        self.after(0, _update_token_display)

    def update_debug_info(self, screen_type, event_kind):
        """Update debug panel info."""
        def _update():
            self.debug_label.config(text=f"screen: {screen_type or '-'}  |  event: {event_kind or '-'}")
        self.after(0, _update)

    def update_usage(self, requests_today, daily_limit, requests_this_minute, rpm_limit, tokens_today):
        """Update rate limit usage counts."""
        def _update():
            pct = (requests_today / daily_limit * 100) if daily_limit else 0
            color = (self.config_data.success_color if pct < 75
                     else self.config_data.eta_color if pct < 90
                     else self.config_data.error_color)
            self.rate_daily_label.config(text=f"Today: {requests_today} / {daily_limit}", fg=color)
            self.rate_minute_label.config(text=f"{requests_this_minute} / {rpm_limit} RPM")
        self.after(0, _update)
        
    def update_daily_tokens(self, tokens_today: int):
        """Update daily accumulated tokens."""
        def _update():
            display = f"{tokens_today/1000:.1f}k" if tokens_today >= 1000 else str(tokens_today)
            self.daily_tokens_label.config(text=f"{display} tokens today")
        self.after(0, _update)

    def feedback_status(self, message: str):
        """Update status label message."""
        self.status_label.config(text=message)

    def set_connection_status(self, connected: bool):
        """Thread-safe: update title-bar connection status dot."""
        color = self.config_data.success_color if connected else self.config_data.error_color

        def _update():
            self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self.after(0, _update)

    def set_eta_ready(self):
        """Thread-safe: mark ETA display as complete."""
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Ready!")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 160, 8)
        self.after(0, _update)

    def set_eta_error(self):
        """Thread-safe: mark ETA display as errored out."""
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Error!")
        self.after(0, _update)

    def is_loading(self) -> bool:
        """Check if feedback is currently loading."""
        return self._feedback_data.is_loading
