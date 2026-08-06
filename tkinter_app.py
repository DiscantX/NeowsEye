"""
Tkinter Overlay for Coaching Feedback
======================================
Always-on-top overlay window that displays:
1. Primary coaching feedback (live)
2. Last prompt to Gemini
3. ETA countdown for response
4. Token usage/estimated limit
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
from tkinter import scrolledtext
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
    width: int = 480
    height: int = 380
    offset_x: int = -500  # Right-aligned offset from right edge
    offset_y: int = 80    # From top edge
    bg_color: str = "#1a1a1a"
    fg_color: str = "#e0e0e0"
    accent_color: str = "#00ffcc"
    feedback_color: str = "#00ffcc"
    prompt_color: str = "#00ffff"
    eta_color: str = "#ff9900"
    token_color: str = "#aa88ff"
    opacity: float = 0.92
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


# ─── Main Overlay Class ────────────────────────────────────────────────────────

class CoachOverlay(tk.Tk):
    """Main overlay window that stays always-on-top."""

    def __init__(self, config: Optional[OverlayConfig] = None):
        super().__init__()

        self.config_data = config or OverlayConfig()
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

        # Position window on screen
        self._position_window()

    def _setup_window(self):
        """Configure the main window properties."""
        self.title("Gemini Coach Overlay")

        # Remove window decorations
        self.overrideredirect(True)

        # Always on top - critical for overlay over game
        self.attributes('-topmost', True)

        # Semi-transparency
        self.attributes('-alpha', self.config_data.opacity)

        # Transparent background for clean rounded corners effect (Windows)
        if os.name == 'nt':
            try:
                self.wm_attributes("-transparentcolor", self.config_data.bg_color)
            except tk.TclError:
                pass

        # Set geometry
        self.geometry(f"{self.config_data.width}x{self.config_data.height}")

        # Bind events for draggable window
        self.bind('<Configure>', self._on_configure)
        self.bind('<ButtonPress-1>', self._start_move)
        self.bind('<B1-Motion>', self._do_move)
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

    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style(self)
        style.theme_use('clam')

        # Override default styles
        style.configure('TFrame', background=self.config_data.bg_color)
        style.configure('TLabeledScale', background=self.config_data.bg_color)

    def _create_widgets(self):
        """Create individual widget components."""
        # Main container
        self.main_frame = tk.Frame(self, bg=self.config_data.bg_color)

        # ── Title bar section (draggable) ──
        self.title_bar = tk.Frame(self.main_frame, bg=self.config_data.border_color, height=18)
        self.title_bar.pack_propagate(False)
        self.title_label = tk.Label(
            self.title_bar,
            text="🎮 Gemini Coach Overlay",
            font=self.title_font,
            fg=self.config_data.accent_color,
            bg=self.config_data.border_color,
            cursor="fleur",
        )
        self.title_label.pack(side=tk.LEFT, padx=8)
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
            command=self._on_close,
        )
        self.close_button.pack(side=tk.RIGHT, padx=2)

        # ── Coaching Feedback Section (PRIMARY ELEMENT) ──
        feedback_container = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        feedback_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        feedback_header = tk.Label(
            feedback_container,
            text="COACH FEEDBACK",
            font=self.label_font,
            fg=self.config_data.feedback_color,
            bg=self.config_data.bg_color,
        )
        feedback_header.pack(anchor=tk.W, pady=(0, 4))

        self.feedback_frame = feedback_container
        self.feedback_text = scrolledtext.ScrolledText(
            feedback_container,
            wrap=tk.WORD,
            font=self.text_font,
            bg=self.config_data.bg_color,
            fg=self.config_data.feedback_color,
            insertbackground=self.config_data.feedback_color,  # caret color
            relief=tk.FLAT,
            state=tk.DISABLED,
            height=10,
            width=55,
            spacing1=5,
            spacing2=3,
            spacing3=5,
            undo=False,
        )
        feedback_scroll = ttk.Scrollbar(self.feedback_text, orient=tk.VERTICAL, command=self.feedback_text.yview)
        self.feedback_text.configure(yscrollcommand=feedback_scroll.set)
        feedback_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.feedback_text.pack(fill=tk.BOTH, expand=True)

        # ── Prompt Section ──
        self.prompt_frame = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        self.prompt_frame.pack(fill=tk.X, padx=8, pady=4)

        prompt_header = tk.Label(
            self.prompt_frame,
            text="LAST PROMPT",
            font=self.label_font,
            fg=self.config_data.prompt_color,
            bg=self.config_data.bg_color,
        )
        prompt_header.pack(anchor=tk.W, pady=(0, 3))

        self.prompt_text = tk.Text(
            self.prompt_frame,
            wrap=tk.WORD,
            font=self.small_font,
            bg=self.config_data.bg_color,
            fg=self.config_data.prompt_color,
            relief=tk.FLAT,
            state=tk.DISABLED,
            height=3,
            width=55,
            spacing1=3,
            spacing2=2,
            spacing3=3,
            undo=False,
        )
        self.prompt_text.pack(fill=tk.X, expand=False)

        # ── Bottom bar: ETA + Tokens + Status ──
        self.eta_frame = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        self.eta_frame.pack(side=tk.LEFT, padx=(5, 10), pady=4)

        tk.Label(
            self.eta_frame,
            text="ETA",
            font=self.small_font,
            fg="#888888",
            bg=self.config_data.bg_color,
        ).pack(anchor=tk.W)

        self.eta_label = tk.Label(
            self.eta_frame,
            text="--:--",
            font=self.label_font,
            fg=self.config_data.eta_color,
            bg=self.config_data.bg_color,
            width=8,
        )
        self.eta_label.pack(anchor=tk.W)

        # ETA progress bar (canvas-based for color control)
        self.eta_bar = tk.Canvas(
            self.eta_frame,
            width=140,
            height=10,
            bg=self.config_data.bg_color,
            highlightthickness=0,
        )
        self.eta_bar.pack(anchor=tk.W, pady=(2, 0))
        self.eta_bar_bg = self.eta_bar.create_rectangle(0, 0, 140, 10, fill="#2a2a2a", outline="")
        self.eta_bar_progress = self.eta_bar.create_rectangle(0, 0, 0, 10, fill=self.config_data.eta_color, outline="")

        # Token section
        self.token_frame = tk.Frame(self.main_frame, bg=self.config_data.bg_color)
        self.token_frame.pack(side=tk.RIGHT, padx=(10, 5), pady=4)

        tk.Label(
            self.token_frame,
            text="TOKENS",
            font=self.small_font,
            fg="#888888",
            bg=self.config_data.bg_color,
        ).pack(anchor=tk.W)

        self.token_label = tk.Label(
            self.token_frame,
            text="0 / 200k",
            font=self.label_font,
            fg=self.config_data.token_color,
            bg=self.config_data.bg_color,
        )
        self.token_label.pack(anchor=tk.W)

        # Token progress bar (canvas-based)
        self.token_bar = tk.Canvas(
            self.token_frame,
            width=120,
            height=8,
            bg=self.config_data.bg_color,
            highlightthickness=0,
        )
        self.token_bar.pack(anchor=tk.W, pady=(2, 0))
        self.token_bar_bg = self.token_bar.create_rectangle(0, 0, 120, 8, fill="#2a2a2a", outline="")

        # Status bar
        self.status_frame = tk.Frame(self.main_frame, bg=self.config_data.border_color)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=0)

        self.status_label = tk.Label(
            self.status_frame,
            text="Ready",
            font=self.small_font,
            fg=self.config_data.accent_color,
            bg=self.config_data.border_color,
            relief=tk.SUNKEN,
            anchor='e',
            padx=8,
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Add outer border highlights
        self._add_borders()

    def _create_layout(self):
        """Arrange widgets in the layout."""
        # Pack main frame
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _add_borders(self):
        """Add subtle border highlights around the window."""
        # Top border highlight
        top_border = tk.Frame(self, bg=self.config_data.feedback_color, height=1)
        top_border.pack(fill=tk.X, side=tk.TOP)

        # Left border
        left_border = tk.Frame(self, bg="#00cc77", width=1)
        left_border.pack(fill=tk.Y, side=tk.LEFT)

        # Right border
        right_border = tk.Frame(self, bg="#00cc77", width=1)
        right_border.pack(fill=tk.Y, side=tk.RIGHT)

    def _position_window(self):
        """Position window relative to game or screen."""
        # Get screen dimensions
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Calculate position (right-aligned, from top)
        x = screen_width + self.config_data.offset_x
        y = self.config_data.offset_y

        # Ensure the window stays within screen bounds
        if x < 0:
            x = 100  # Fallback position
        if y < 0:
            y = 50

        self.geometry(f"+{x}+{y}")

    def _on_configure(self, event):
        """Handle window configuration events."""
        pass

    def _start_move(self, event):
        """Start dragging the window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_start_pos_x = self.winfo_x()
        self._drag_start_pos_y = self.winfo_y()

    def _do_move(self, event):
        """Move the window while dragging."""
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        new_x = self._drag_start_pos_x + dx
        new_y = self._drag_start_pos_y + dy
        self.geometry(f"+{new_x}+{new_y}")

    def _on_close(self):
        """Clean up on close."""
        self._running = False
        self.destroy()

    # ─── Public API Methods ────────────────────────────────────────────────────

    def update_feedback(self, feedback: str):
        """Update the coaching feedback text with live response."""
        def _update():
            self._feedback_data.feedback = feedback
            self._feedback_data.last_update = time.time()
            self.feedback_text.config(state=tk.NORMAL)
            self.feedback_text.delete(1.0, tk.END)
            self.feedback_text.insert(tk.END, feedback)
            self.feedback_text.config(state=tk.DISABLED)
            self.status_label.config(text=f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        self.after(0, _update)

    def update_prompt(self, prompt: str):
        """Update the last prompt display."""
        def _update():
            self._feedback_data.last_prompt = prompt
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete(1.0, tk.END)
            self.prompt_text.insert(tk.END, prompt)
            self.prompt_text.config(state=tk.DISABLED)
        self.after(0, _update)

    def start_eta_countdown(self, seconds: int):
        """Start the ETA countdown timer."""
        self._feedback_data.eta_seconds = seconds
        self._feedback_data.is_loading = True

        self._eta_start_time = time.time()
        self._eta_thread = threading.Thread(
            target=self._eta_worker,
            args=(seconds,),
            daemon=True
        )
        self._eta_thread.start()

        # Show starting state
        self.eta_label.config(text="0:00")
        self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 10)

    def _eta_worker(self, total_seconds: int):
        """Background worker for countdown timer."""
        elapsed = 0
        total = total_seconds

        for remaining in range(total, -1, -1):
            if not self._running:
                break

            # Calculate progress (reverse: starts empty, fills up)
            elapsed = total - remaining
            progress_width = int((elapsed / total) * 140) if total > 0 else 0

            # Format as M:SS
            mins = remaining // 60
            secs = remaining % 60
            time_str = f"{mins}:{secs:02d}"

            def _update_eta_display():
                self.eta_label.config(text=time_str)
                self.eta_bar.coords(self.eta_bar_progress, 0, 0, max(progress_width, 1) if remaining > 0 else 140, 10)
                if remaining > 0:
                    self.status_label.config(text="Awaiting response...")

            self.after(0, _update_eta_display)

            if remaining > 0:
                time.sleep(1)

        # Countdown complete
        def _finish_countdown():
            self._feedback_data.is_loading = False
            self.eta_label.config(text="Ready!")
            self.status_label.config(text="Response ready!")
            self.eta_bar.coords(self.eta_bar_progress, 0, 0, 140, 10)

            # Reset after short delay
            self.after(3000, lambda: self.eta_label.config(text="--:--"))
            self.after(3000, lambda: self.eta_bar.coords(self.eta_bar_progress, 0, 0, 0, 10))

        self.after(0, _finish_countdown)

    def update_tokens(self, used: int, limit: int = 200000):
        """Update token usage display."""
        self._feedback_data.tokens_used = used
        self._feedback_data.token_limit = limit

        def _update_token_display():
            # Calculate percentage and color
            percentage = (used / limit * 100) if limit > 0 else 0

            # Format numbers nicely
            used_str = f"{used/1000:.1f}k" if used >= 1000 else str(used)
            limit_str = f"{limit/1000:.0f}k" if limit >= 1000 else str(limit)

            # Color based on usage
            if percentage < 75:
                bar_color = "#00cc77"  # Green
            elif percentage < 90:
                bar_color = "#ff9900"  # Orange
            else:
                bar_color = "#ff0044"  # Red

            # Update label
            self.token_label.config(
                text=f"{used_str} / {limit_str}",
                fg=bar_color
            )

            # Update progress bar
            bar_width = int((percentage / 100) * 120)
            self.token_bar.delete("progress")
            self.token_bar.create_rectangle(
                1, 1, max(bar_width, 1), 7,
                fill=bar_color, outline="",
                tags="progress"
            )

        self.after(0, _update_token_display)

    def feedback_status(self, message: str):
        """Update the status label with a message."""
        self.status_label.config(text=message)

    def is_loading(self) -> bool:
        """Check if feedback is currently being loaded."""
        return self._feedback_data.is_loading


# ─── Main Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = CoachOverlay()

    # Demo: Simulate live updates
    def demo_updates():
        """Simulate live feedback updates for testing."""
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
            # Update feedback
            app.update_feedback(demo_feedbacks[idx])
            app.update_prompt(demo_prompts[idx])

            # Update token usage with simulated data
            tokens_used = 150000 + (idx * 8000) + random.randint(-5000, 5000)
            app.update_tokens(tokens_used, 200000)

            # Start ETA countdown (simulate API response delay)
            eta_seconds = random.randint(8, 20)
            app.start_eta_countdown(eta_seconds)

            idx += 1
            time.sleep(eta_seconds + random.uniform(2, 5))

    demo_thread = threading.Thread(target=demo_updates, daemon=True)
    demo_thread.start()

    app.mainloop()