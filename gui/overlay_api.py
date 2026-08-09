"""
Public API update methods and background ETA worker for the Coach Overlay.
"""

import time
import threading
import queue
from datetime import datetime
import tkinter as tk

class OverlayApiMixin:

    def _init_dispatch_queue(self):
        """Call once from the main thread, after self._running is set.
        Every background-thread UI update (GeminiWorker's thread, main.py's
        polling thread, each _eta_worker thread) goes through _dispatch()
        -> this queue -> _poll_ui_queue(), instead of calling
        self._dispatch(...) directly from those threads. Tk's .after() has
        no documented thread-safety guarantee; concurrent callers can lose
        or reorder callbacks, which is what produced the 'stuck until N
        prompts later, then flushes' symptom."""
        self._ui_queue = queue.Queue()
        self._eta_generation = 0
        self._poll_ui_queue()

    def _poll_ui_queue(self):
        """MAIN THREAD ONLY. Drains everything queued so far (not just one
        item per tick -- a fixed per-tick budget would fall behind under
        load and reproduce the same batching symptom), then reschedules."""
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        if self._running:
            self.after(15, self._poll_ui_queue)

    def _dispatch(self, callback):
        """Thread-safe replacement for self._dispatch(callback)."""
        self._ui_queue.put(callback)
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
        self._dispatch(_update)

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
        self._dispatch(_update)

    def start_eta_countdown(self, seconds: int):
        """Start the ETA countdown timer."""
        self._feedback_data.eta_seconds = seconds
        self._feedback_data.is_loading = True

        self._eta_generation += 1
        my_generation = self._eta_generation

        self._eta_start_time = time.time()
        self._eta_thread = threading.Thread(
            target=self._eta_worker, args=(seconds, my_generation), daemon=True,
        )
        self._eta_thread.start()

        def _update():
            self.eta_label.config(text="0:00")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 8)
        self._dispatch(_update)

    def _eta_worker(self, total_seconds: int, generation: int):
            """Background worker for countdown timer. `generation` pins this
            thread to the prompt it was started for -- if a newer prompt
            starts its own countdown (bumping self._eta_generation) or the
            real response already arrived (set_eta_ready() also bumps it)
            before this thread finishes, it stops writing instead of
            clobbering the newer/'Ready!' state with its own stale numbers."""
            total = total_seconds

            for remaining in range(total, -1, -1):
                if not self._running or generation != self._eta_generation:
                    return

                elapsed = total - remaining
                progress_width = int((elapsed / total) * 160) if total > 0 else 0
                mins = remaining // 60
                secs = remaining % 60
                time_str = f"{mins}:{secs:02d}"

                def _update_eta_display(remaining=remaining, progress_width=progress_width,
                                        time_str=time_str, generation=generation):
                    if generation != self._eta_generation:
                        return
                    self.eta_label.config(text=time_str)
                    self.eta_bar.coords(
                        self.eta_bar_progress, 0, 0,
                        max(progress_width, 1) if remaining > 0 else 160, 8,
                    )
                    if remaining > 0:
                        self.status_label.config(text="Awaiting response...")

                self._dispatch(_update_eta_display)

                if remaining > 0:
                    time.sleep(1)

            if generation != self._eta_generation:
                return

            def _finish_countdown(generation=generation):
                if generation != self._eta_generation:
                    return
                self._feedback_data.is_loading = False
                self.eta_label.config(text="Ready!")
                self.status_label.config(text="Response ready!")
                self.eta_bar.coords(self.eta_bar_progress, 0, 0, 160, 8)
                self.after(3000, lambda: self.eta_label.config(text="--:--"))
                self.after(3000, lambda: self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 8))

            self._dispatch(_finish_countdown)

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

            self._dispatch(_update_token_display)

    def update_debug_info(self, screen_type, event_kind):
        """Update debug panel info."""
        def _update():
            self.debug_label.config(text=f"screen: {screen_type or '-'}  |  event: {event_kind or '-'}")
        self._dispatch(_update)

    def update_usage(self, requests_today, daily_limit, requests_this_minute, rpm_limit, tokens_today):
        """Update rate limit usage counts."""
        def _update():
            pct = (requests_today / daily_limit * 100) if daily_limit else 0
            color = (self.config_data.success_color if pct < 75
                     else self.config_data.eta_color if pct < 90
                     else self.config_data.error_color)
            self.rate_daily_label.config(text=f"Today: {requests_today} / {daily_limit}", fg=color)
            self.rate_minute_label.config(text=f"{requests_this_minute} / {rpm_limit} RPM")
        self._dispatch(_update)
        
    def update_daily_tokens(self, tokens_today: int):
        """Update daily accumulated tokens."""
        def _update():
            display = f"{tokens_today/1000:.1f}k" if tokens_today >= 1000 else str(tokens_today)
            self.daily_tokens_label.config(text=f"{display} tokens today")
        self._dispatch(_update)

    def feedback_status(self, message: str):
        """Thread-safe: update status label message."""
        def _update():
            self.status_label.config(text=message)
        self._dispatch(_update)

    def set_connection_status(self, connected: bool):
        """Thread-safe: update title-bar connection status dot."""
        color = self.config_data.success_color if connected else self.config_data.error_color

        def _update():
            self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self._dispatch(_update)

    def set_eta_ready(self):
        """Thread-safe: mark ETA display as complete."""
        self._eta_generation += 1  # silence any still-running eta_worker
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Ready!")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 160, 8)
        self._dispatch(_update)

    def set_eta_error(self):
        """Thread-safe: mark ETA display as errored out."""
        self._eta_generation += 1
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Error!")
        self._dispatch(_update)

    def is_loading(self) -> bool:
        """Check if feedback is currently loading."""
        return self._feedback_data.is_loading
