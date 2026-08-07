"""
Tkinter Overlay for Coaching Feedback
======================================
Always-on-top overlay window that displays:
1. Primary coaching feedback, appended as a scrollable history (live)
2. Last prompt to Gemini (scrollable)
3. ETA countdown for response
4. Token usage/estimated limit
5. Connection status
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import time
import threading
import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ─── Configuration ───────────────────────────────────────────────────────────

@dataclass
class OverlayConfig:
    """Configuration settings for the overlay window."""
    width: int = 520
    height: int = 570
    min_width: int = 360
    min_height: int = 420
    offset_x: int = -540  # Right-aligned offset from right edge
    offset_y: int = 80    # From top edge
    bg_color: str = "#1a1a1a"
    fg_color: str = "#e0e0e0"
    accent_color: str = "#00ffcc"
    feedback_color: str = "#00ffcc"
    prompt_color: str = "#00ffff"
    eta_color: str = "#ff9900"
    token_color: str = "#aa88ff"
    success_color: str = "#00cc77"
    error_color: str = "#ff4466"
    dim_color: str = "#888888"
    # Real (blended) translucency only -- see _setup_window for why this
    # window deliberately does NOT also use a color-key transparency
    # trick. A lower value is more see-through but less legible over
    # bright content (e.g. the in-game map); this is the tuned middle
    # ground, not a hard requirement.
    opacity: float = 0.93
    font_family: str = "Segoe UI"
    font_size: int = 10
    title_font_size: int = 12
    border_color: str = "#333333"


# ─── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class FeedbackData:
    """Container for coaching feedback data."""
    feedback: str = ""
    last_prompt: str = ""
    eta_seconds: int = 0
    tokens_used: int = 0
    token_limit: int = 200000
    is_loading: bool = False
    last_update: float = field(default_factory=time.time)


def _resolve_font_family(preferred: str) -> str:
    """Falls back to a common cross-platform font if `preferred` isn't
    installed -- e.g. Segoe UI is Windows-only, and this overlay may
    well be developed/tested on a non-Windows machine before it's ever
    run under ModTheSpire."""
    try:
        available = set(tkfont.families())
    except tk.TclError:
        return preferred
    if preferred in available:
        return preferred
    for fallback in ("Segoe UI", "Helvetica", "Arial", "DejaVu Sans"):
        if fallback in available:
            return fallback
    return preferred


# ─── Main Overlay Class ────────────────────────────────────────────────────────

class CoachOverlay(tk.Tk):
    """Main overlay window that stays always-on-top."""

    def __init__(self, config: Optional[OverlayConfig] = None, on_close=None, on_reset_rule_change=None):
        super().__init__()

        self.config_data = config or OverlayConfig()
        self.config_data.font_family = _resolve_font_family(self.config_data.font_family)
        # Called from _on_close, before this window is torn down --
        # e.g. gui_main.py hooks this to close the StreamClient socket
        # so the background coaching loop shuts down cleanly instead of
        # being left blocked on a read that will never resolve.
        self._on_close_callback = on_close
        self._setup_window()
        self._setup_fonts()
        self._setup_styles()
        self._create_widgets()
        self._create_layout()

        # Data state
        self._feedback_data = FeedbackData()
        self._eta_start_time: Optional[float] = None
        self._eta_thread: Optional[threading.Thread] = None
        self._running = True
        self._feedback_entry_count = 0
        
        self._on_reset_rule_change = on_reset_rule_change

        # Position window on screen
        self._position_window()

    def _setup_window(self):
        """Configure the main window properties."""
        self.title("Gemini Coach Overlay")

        # Remove window decorations
        self.overrideredirect(True)

        # Always on top - critical for overlay over game
        self.attributes('-topmost', True)

        # Real (blended) translucency. Deliberately NOT combined with
        # Windows' -transparentcolor color-keying: that trick makes any
        # pixel matching bg_color fully invisible (not blended), which
        # is what made text unreadable over bright game content like
        # the map -- there was no darkened panel behind it at all, just
        # raw game pixels. Alpha blending keeps a legible dark card
        # over anything behind the window, at the cost of a square
        # (rather than color-keyed/irregular) window shape.
        self.attributes('-alpha', self.config_data.opacity)

        # Set geometry
        self.geometry(f"{self.config_data.width}x{self.config_data.height}")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_fonts(self):
        """Initialize font objects."""
        self.title_font = tkfont.Font(
            family=self.config_data.font_family,
            size=self.config_data.title_font_size,
            weight='bold'
        )
        self.label_font = tkfont.Font(
            family=self.config_data.font_family,
            size=self.config_data.font_size,
            weight='bold'
        )
        self.text_font = tkfont.Font(
            family=self.config_data.font_family,
            size=self.config_data.font_size,
        )
        self.small_font = tkfont.Font(
            family=self.config_data.font_family,
            size=9,
        )
        self.mini_font = tkfont.Font(
            family=self.config_data.font_family,
            size=8,
        )

    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style(self)
        style.theme_use('clam')

        style.configure('TFrame', background=self.config_data.bg_color)
        style.configure('TLabeledScale', background=self.config_data.bg_color)

        # Dark, flat scrollbar matching the overlay theme -- ttk's
        # default scrollbar is a light system widget that would stick
        # out badly against this panel.
        style.configure(
            'Overlay.Vertical.TScrollbar',
            background=self.config_data.border_color,
            troughcolor=self.config_data.bg_color,
            bordercolor=self.config_data.bg_color,
            arrowcolor=self.config_data.fg_color,
            relief=tk.FLAT,
            gripcount=0,
        )
        style.map(
            'Overlay.Vertical.TScrollbar',
            background=[('active', self.config_data.accent_color)],
        )

    def _make_scrollable_text(self, parent, height, fg_color, font, wrap=tk.WORD):
        """Text + Scrollbar as siblings in their own frame -- the
        pattern both the feedback and prompt panels use. (Previously
        the feedback panel used scrolledtext.ScrolledText, which bundles
        its own internal scrollbar, AND had a second scrollbar wired on
        top of it; that second wiring silently disconnected the first,
        leaving two non-functional scrollbars stacked on each other.
        One explicit scrollbar per text box, wired directly, avoids
        that class of bug entirely.)"""
        container = tk.Frame(parent, bg=self.config_data.bg_color)
        text_widget = tk.Text(
            container,
            wrap=wrap,
            font=font,
            bg=self.config_data.bg_color,
            fg=fg_color,
            insertbackground=fg_color,
            relief=tk.FLAT,
            state=tk.DISABLED,
            height=height,
            spacing1=4,
            spacing2=2,
            spacing3=6,
            undo=False,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(
            container, orient=tk.VERTICAL, command=text_widget.yview,
            style='Overlay.Vertical.TScrollbar',
        )
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        return container, text_widget

    def _create_widgets(self):
        """Create individual widget components."""
        self.main_frame = tk.Frame(self, bg=self.config_data.bg_color)

        # ── Title bar section (draggable) ──
        self.title_bar = tk.Frame(self.main_frame, bg=self.config_data.border_color, height=22)
        self.title_bar.pack_propagate(False)

        self.status_dot = tk.Canvas(
            self.title_bar, width=10, height=10,
            bg=self.config_data.border_color, highlightthickness=0,
        )
        self._status_dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=self.config_data.dim_color, outline="")
        self.status_dot.pack(side=tk.LEFT, padx=(8, 4))

        self.title_label = tk.Label(
            self.title_bar,
            text="Gemini Coach Overlay",
            font=self.title_font,
            fg=self.config_data.accent_color,
            bg=self.config_data.border_color,
            cursor="fleur",
        )
        self.title_label.pack(side=tk.LEFT)
        self.close_button = tk.Button(
            self.title_bar,
            text="×",
            width=3,
            font=self.label_font,
            fg="#ff6b6b",
            bg=self.config_data.border_color,
            activebackground="#442222",
            activeforeground="#ff9999",
            relief=tk.FLAT,
            bd=0,
            command=self._on_close,
        )
        self.close_button.pack(side=tk.RIGHT, padx=2)

        # Dragging is bound only to the title bar (not the whole
        # window) -- binding it on self previously meant every click
        # anywhere, including on the scrollbars and text boxes, also
        # triggered a drag-start, which is part of why interacting with
        # those felt broken.
        for widget in (self.title_bar, self.title_label, self.status_dot):
            widget.bind('<ButtonPress-1>', self._start_move)
            widget.bind('<B1-Motion>', self._do_move)
        
        self.title_bar.pack(fill=tk.X, side=tk.TOP)

        # ── Debug line (screen_type / event kind) ──
        debug_frame = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        debug_frame.pack(fill=tk.X, padx=10, pady=(4, 0))
        self.debug_label = tk.Label(
            debug_frame, text="screen: -  |  event: -", font=self.mini_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color, anchor='w',
        )
        self.debug_label.pack(fill=tk.X)

        # ── Coaching Feedback Section (PRIMARY ELEMENT) ──
        feedback_container = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        feedback_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 4))

        feedback_header_row = tk.Frame(feedback_container, bg=self.config_data.bg_color)
        feedback_header_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            feedback_header_row, text="COACH FEEDBACK", font=self.label_font,
            fg=self.config_data.feedback_color, bg=self.config_data.bg_color,
        ).pack(side=tk.LEFT)
        self.clear_button = tk.Button(
            feedback_header_row, text="Clear", font=self.mini_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
            activebackground=self.config_data.border_color,
            activeforeground=self.config_data.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self.clear_feedback_history,
        )
        self.clear_button.pack(side=tk.RIGHT)

        feedback_box, self.feedback_text = self._make_scrollable_text(
            feedback_container, height=10,
            fg_color=self.config_data.feedback_color, font=self.text_font,
        )
        feedback_box.pack(fill=tk.BOTH, expand=True)
        self.feedback_text.tag_configure(
            'timestamp', foreground=self.config_data.dim_color, font=self.mini_font,
        )
        self.feedback_text.tag_configure(
            'body', foreground=self.config_data.feedback_color, font=self.text_font,
        )

        self._add_divider()

        # ── Prompt Section ──
        prompt_container = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        prompt_container.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(
            prompt_container, text="LAST PROMPT", font=self.label_font,
            fg=self.config_data.prompt_color, bg=self.config_data.bg_color,
        ).pack(anchor=tk.W, pady=(0, 3))

        prompt_box, self.prompt_text = self._make_scrollable_text(
            prompt_container, height=4,
            fg_color=self.config_data.prompt_color, font=self.small_font,
        )
        prompt_box.pack(fill=tk.X)

        self._add_divider()

        # ── Bottom bar: ETA + Tokens ──
        bottom_row = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        bottom_row.pack(fill=tk.X, padx=10, pady=(4, 2))

        self.eta_frame = tk.Frame(bottom_row, bg=self.config_data.bg_color)
        self.eta_frame.pack(side=tk.LEFT)

        tk.Label(
            self.eta_frame, text="ETA", font=self.small_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
        ).pack(anchor=tk.W)

        self.eta_label = tk.Label(
            self.eta_frame, text="--:--", font=self.label_font,
            fg=self.config_data.eta_color, bg=self.config_data.bg_color, width=8,
        )
        self.eta_label.pack(anchor=tk.W)

        self.eta_bar = tk.Canvas(
            self.eta_frame, width=160, height=8,
            bg=self.config_data.bg_color, highlightthickness=0,
        )
        self.eta_bar.pack(anchor=tk.W, pady=(2, 0))
        self.eta_bar_bg = self.eta_bar.create_rectangle(0, 0, 160, 8, fill="#2a2a2a", outline="")
        self.eta_bar_progress = self.eta_bar.create_rectangle(0, 0, 0, 8, fill=self.config_data.eta_color, outline="")

        self.token_frame = tk.Frame(bottom_row, bg=self.config_data.bg_color)
        self.token_frame.pack(side=tk.RIGHT)

        tk.Label(
            self.token_frame, text="TOKENS", font=self.small_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
        ).pack(anchor=tk.E)

        self.token_label = tk.Label(
            self.token_frame, text="0 / 200k", font=self.label_font,
            fg=self.config_data.token_color, bg=self.config_data.bg_color,
        )
        self.token_label.pack(anchor=tk.E)

        self.token_bar = tk.Canvas(
            self.token_frame, width=140, height=8,
            bg=self.config_data.bg_color, highlightthickness=0,
        )
        self.token_bar.pack(anchor=tk.E, pady=(2, 0))
        self.token_bar_bg = self.token_bar.create_rectangle(0, 0, 140, 8, fill="#2a2a2a", outline="")

        # ── Rate limits ──
        rate_row = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        rate_row.pack(fill=tk.X, padx=10, pady=(2, 4))
        self.rate_daily_label = tk.Label(
            rate_row, text="Today: -- / --", font=self.small_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
        )
        self.rate_daily_label.pack(side=tk.LEFT)
        self.rate_minute_label = tk.Label(
            rate_row, text="-- / -- RPM", font=self.small_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
        )
        self.rate_minute_label.pack(side=tk.RIGHT)

    # ── Reset timer ──
        self.reset_rule_button = tk.Menubutton(
            rate_row, text="Reset: Pacific", font=self.mini_font,
            fg=self.config_data.dim_color, bg=self.config_data.bg_color,
            activebackground=self.config_data.border_color, activeforeground=self.config_data.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
        )
        reset_menu = tk.Menu(self.reset_rule_button, tearoff=0,
                              bg=self.config_data.bg_color, fg=self.config_data.fg_color)
        reset_menu.add_command(
            label="Pacific (Google default)",
            command=lambda: self._on_reset_rule_selected("America/Los_Angeles", "Pacific"),
        )
        reset_menu.add_command(
            label="Local time",
            command=lambda: self._on_reset_rule_selected("local", "Local"),
        )
        self.reset_rule_button.config(menu=reset_menu)
        self.reset_rule_button.pack(side=tk.RIGHT, padx=(0, 8))

        # Status bar
        self.status_frame = tk.Frame(self.main_frame, bg=self.config_data.border_color)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = tk.Label(
            self.status_frame, text="Ready", font=self.small_font,
            fg=self.config_data.accent_color, bg=self.config_data.border_color,
            anchor='e', padx=8, pady=2,
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Resize grip -- overrideredirect windows lose the OS's native
        # resize handles/border along with their title bar, so without
        # this the window is permanently stuck at its initial size.
        self.resize_grip = tk.Canvas(
            self, width=14, height=14, bg=self.config_data.border_color,
            highlightthickness=0, cursor="sizing",
        )
        for i in range(3):
            offset = i * 4
            self.resize_grip.create_line(
                2 + offset, 12, 12, 2 + offset,
                fill=self.config_data.dim_color, width=1,
            )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor='se')
        self.resize_grip.bind('<ButtonPress-1>', self._start_resize)
        self.resize_grip.bind('<B1-Motion>', self._do_resize)

        self._add_borders()

    def _add_divider(self):
        tk.Frame(self.main_frame, bg=self.config_data.border_color, height=1).pack(fill=tk.X, padx=10)

    def _create_layout(self):
        """Title bar is already packed first in _create_widgets, so it
        claims the top slot before any other TOP-side child of
        main_frame does."""
        self.main_frame.pack(fill=tk.BOTH, expand=True)

    def _add_borders(self):
        """Add subtle border highlights around the window."""
        left_border = tk.Frame(self, bg="#00cc77", width=1)
        left_border.place(x=0, y=0, relheight=1.0)
        right_border = tk.Frame(self, bg="#00cc77", width=1)
        right_border.place(relx=1.0, x=-1, y=0, relheight=1.0)
        bottom_border = tk.Frame(self, bg="#00cc77", height=1)
        bottom_border.place(x=0, rely=1.0, y=-1, relwidth=1.0)

    def _position_window(self):
        """Position window relative to game or screen."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        x = screen_width + self.config_data.offset_x
        y = self.config_data.offset_y

        if x < 0:
            x = 100
        if y < 0:
            y = 50

        self.geometry(f"+{x}+{y}")

    # ─── Dragging / resizing ────────────────────────────────────────────────
    # Both use screen-absolute (x_root/y_root) coordinates rather than
    # widget-relative ones. Widget-relative coordinates are relative to
    # whatever widget the event actually landed on, which varies as the
    # cursor crosses child widgets during a drag -- that mismatch was the
    # cause of the window jumping/lagging behind the mouse. Root
    # coordinates are a single consistent frame of reference throughout
    # the whole gesture.

    def _start_move(self, event):
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _do_move(self, event):
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.geometry(f"+{x}+{y}")

    def _start_resize(self, event):
        self._resize_start_x_root = event.x_root
        self._resize_start_y_root = event.y_root
        self._resize_start_width = self.winfo_width()
        self._resize_start_height = self.winfo_height()

    def _do_resize(self, event):
        dx = event.x_root - self._resize_start_x_root
        dy = event.y_root - self._resize_start_y_root
        new_w = max(self.config_data.min_width, self._resize_start_width + dx)
        new_h = max(self.config_data.min_height, self._resize_start_height + dy)
        self.geometry(f"{new_w}x{new_h}")

    def _on_close(self):
        """Clean up on close.

        Runs the shutdown callback (if any) BEFORE tearing this window
        down, so e.g. gui_main.py can close the StreamClient socket --
        which unblocks main()'s poll loop via the existing "adapter
        disconnected" path -- while the window is still alive to show
        the resulting on_connection_status(connected=False) update, if
        it arrives in time.
        """
        if self._on_close_callback:
            self._on_close_callback()
        self._running = False
        self.destroy()

    # ─── Public API Methods ────────────────────────────────────────────────

    @staticmethod
    def _is_scrolled_to_bottom(text_widget, threshold=0.98) -> bool:
        """Whether the visible viewport already reaches (or is very
        near) the end of the text. Used so a new entry only auto-scrolls
        the view down when the user was already reading the latest
        entry -- someone scrolled back through history shouldn't get
        yanked back to the bottom by an incoming update."""
        try:
            _, bottom = text_widget.yview()
        except tk.TclError:
            return True
        return bottom >= threshold

    def update_feedback(self, feedback: str):
        """Append a new coaching-feedback entry, with a timestamp
        header, to the scrollable history -- rather than replacing the
        previous entry. Auto-scrolls to the new entry only if the view
        was already at the bottom."""
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
        """Wipe the feedback history (button-triggered; safe to call
        from the main thread only)."""
        self.feedback_text.config(state=tk.NORMAL)
        self.feedback_text.delete('1.0', tk.END)
        self.feedback_text.config(state=tk.DISABLED)
        self._feedback_entry_count = 0

    def update_prompt(self, prompt: str):
        """Update the last-prompt display (shows only the most recent
        prompt, scrollable if long -- the feedback panel above is where
        history lives)."""
        def _update():
            self._feedback_data.last_prompt = prompt
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete('1.0', tk.END)
            self.prompt_text.insert(tk.END, prompt)
            self.prompt_text.config(state=tk.DISABLED)
            self.prompt_text.see('1.0')
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
        def _update():
            self.debug_label.config(text=f"screen: {screen_type or '-'}  |  event: {event_kind or '-'}")
        self.after(0, _update)

    def update_usage(self, requests_today, daily_limit, requests_this_minute, rpm_limit, tokens_today):
        def _update():
            pct = (requests_today / daily_limit * 100) if daily_limit else 0
            color = (self.config_data.success_color if pct < 75
                     else self.config_data.eta_color if pct < 90
                     else self.config_data.error_color)
            self.rate_daily_label.config(text=f"Today: {requests_today} / {daily_limit}", fg=color)
            self.rate_minute_label.config(text=f"{requests_this_minute} / {rpm_limit} RPM")
        self.after(0, _update)

    def feedback_status(self, message: str):
        """Update the status label with a message."""
        self.status_label.config(text=message)

    def set_connection_status(self, connected: bool):
        """Thread-safe: update the title-bar status dot."""
        color = self.config_data.success_color if connected else self.config_data.error_color

        def _update():
            self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self.after(0, _update)

    def set_eta_ready(self):
        """Thread-safe: mark the ETA display as complete (advice arrived).
        Use this instead of poking eta_label/eta_bar directly from a
        non-main thread (e.g. from a CoachingObserver callback, which
        runs on GeminiWorker's background thread)."""
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Ready!")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 160, 8)
        self.after(0, _update)

    def set_eta_error(self):
        """Thread-safe: mark the ETA display as errored out. See
        set_eta_ready() for why this goes through .after() rather than
        touching widgets directly."""
        def _update():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Error!")
        self.after(0, _update)

    def is_loading(self) -> bool:
        """Check if feedback is currently being loaded."""
        return self._feedback_data.is_loading
    
    def _on_reset_rule_selected(self, timezone_name, display_name):
        self.reset_rule_button.config(text=f"Reset: {display_name}")
        if self._on_reset_rule_change:
            self._on_reset_rule_change(timezone_name)


# ─── Main Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = CoachOverlay()
    app.set_connection_status(True)

    def demo_updates():
        """Simulate live feedback updates for testing -- also doubles as
        a manual test of the history/scrollback behavior, since each
        call below appends rather than replaces."""
        demo_feedbacks = [
            "Excellent positioning! Maintaining control of the mid lane.\n\n"
            "Your last-hitting is 85% efficient - focus on the mage creep at 7:35.",

            "Watch out for enemy rotations in the river area.\n\n"
            "Enemy jungler spotted near dragon. Be cautious of steals.",

            "Consider backing now - you have enough gold for a significant purchase.\n\n"
            "Vision score low (3 wards placed last 5 min). Clear more wards.",

            "Great engage! Your teamfight initiation caught them off-guard.\n\n"
            "Level advantage detected. Apply pressure while you have the lead.",

            "Your creep wave is building up - freeze it to deny gold.\n\n"
            "Warning: Missing from action for 20 seconds. Stay aware of your map presence.",
        ]
        demo_prompts = [
            "Analyze the current game state after 35 minutes of farming top lane",
            "What's the optimal build path for my carry against their lineup?",
            "Evaluate my positioning during the last teamfight near Baron",
            "How's my vision control and ward placement in the river?",
            "Analyze the game tempo and suggest next objective priorities",
        ]

        import random
        random.seed(42)

        idx = 0
        while app._running and idx < len(demo_feedbacks):
            app.update_feedback(demo_feedbacks[idx])
            app.update_prompt(demo_prompts[idx])

            tokens_used = 150000 + (idx * 8000) + random.randint(-5000, 5000)
            app.update_tokens(tokens_used, 200000)

            eta_seconds = random.randint(8, 20)
            app.start_eta_countdown(eta_seconds)

            idx += 1
            time.sleep(eta_seconds + random.uniform(2, 5))

    demo_thread = threading.Thread(target=demo_updates, daemon=True)
    demo_thread.start()

    app.mainloop()