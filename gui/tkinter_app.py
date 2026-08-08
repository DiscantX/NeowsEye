"""
Tkinter Overlay for Coaching Feedback
======================================
Always-on-top overlay window that displays:
1. Primary coaching feedback, appended as a scrollable history (live)
2. Last prompt to Gemini (collapsible)
3. ETA countdown for response
4. Token usage/estimated limit
5. Connection status
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import time
import threading
from typing import Optional

from gui.models import OverlayConfig, FeedbackData, resolve_font_family, DEFAULT_DRAWER_OPEN
from gui.chat_drawer import ChatDrawerMixin
from gui.overlay_api import OverlayApiMixin


class CoachOverlay(tk.Tk, ChatDrawerMixin, OverlayApiMixin):
    """Main overlay window that stays always-on-top."""

    def __init__(self, config: Optional[OverlayConfig] = None, on_close=None,
                 on_reset_rule_change=None, on_send_message=None):
        super().__init__()

        self.config_data = config or OverlayConfig()
        self.config_data.font_family = resolve_font_family(self.config_data.font_family)
        self._on_close_callback = on_close
        self._on_send_message = on_send_message

        self._drawer_open = DEFAULT_DRAWER_OPEN
        self._prompt_collapsed = True

        self._setup_window()
        self._setup_fonts()
        self._setup_styles()
        self._create_drawer_widgets()
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
        cfg = self.config_data
        self.title("Gemini Coach Overlay")
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', cfg.opacity)

        initial_width = cfg.width + (cfg.drawer_width if self._drawer_open else 0)
        self.geometry(f"{initial_width}x{cfg.height}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_fonts(self):
        """Initialize font objects."""
        cfg = self.config_data
        self.title_font = tkfont.Font(family=cfg.font_family, size=cfg.title_font_size, weight='bold')
        self.label_font = tkfont.Font(family=cfg.font_family, size=cfg.font_size, weight='bold')
        self.text_font = tkfont.Font(family=cfg.font_family, size=cfg.font_size)
        self.small_font = tkfont.Font(family=cfg.font_family, size=9)
        self.mini_font = tkfont.Font(family=cfg.font_family, size=8)

    def _setup_styles(self):
        """Configure ttk styles."""
        cfg = self.config_data
        style = ttk.Style(self)
        style.theme_use('clam')

        style.configure('TFrame', background=cfg.bg_color)
        style.configure('TLabeledScale', background=cfg.bg_color)

        style.configure(
            'Overlay.Vertical.TScrollbar',
            background=cfg.border_color,
            troughcolor=cfg.bg_color,
            bordercolor=cfg.bg_color,
            arrowcolor=cfg.fg_color,
            relief=tk.FLAT,
            gripcount=0,
        )
        style.map(
            'Overlay.Vertical.TScrollbar',
            background=[('active', cfg.accent_color)],
        )

    def _make_scrollable_text(self, parent, height, fg_color, font, wrap=tk.WORD):
        """Creates a scrollable text area component container."""
        cfg = self.config_data
        container = tk.Frame(parent, bg=cfg.bg_color)
        text_widget = tk.Text(
            container,
            wrap=wrap,
            font=font,
            bg=cfg.bg_color,
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
        """Create individual widget components for the main panel."""
        cfg = self.config_data
        self.main_frame = tk.Frame(self, bg=cfg.bg_color)

        # ── Title bar section (draggable across both panels & cursor fix) ──
        self.title_bar = tk.Frame(self.main_frame, bg=cfg.border_color, height=22, cursor="fleur")
        self.title_bar.pack_propagate(False)

        # Drawer toggle button on the LEFT of the title bar
        self.drawer_toggle_button = tk.Button(
            self.title_bar,
            text="« Chat" if self._drawer_open else "Chat »",
            font=self.mini_font,
            fg=cfg.accent_color,
            bg=cfg.border_color,
            activebackground=cfg.border_color,
            activeforeground=cfg.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._toggle_drawer,
        )
        self.drawer_toggle_button.pack(side=tk.LEFT, padx=(6, 4))

        self.status_dot = tk.Canvas(
            self.title_bar, width=10, height=10,
            bg=cfg.border_color, highlightthickness=0, cursor="fleur",
        )
        self._status_dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=cfg.dim_color, outline="")
        self.status_dot.pack(side=tk.LEFT, padx=(4, 4))

        self.title_label = tk.Label(
            self.title_bar,
            text="Gemini Coach Overlay",
            font=self.title_font,
            fg=cfg.accent_color,
            bg=cfg.border_color,
            cursor="fleur",
        )
        self.title_label.pack(side=tk.LEFT)
        
        self.close_button = tk.Button(
            self.title_bar,
            text="×",
            width=3,
            font=self.label_font,
            fg="#ff6b6b",
            bg=cfg.border_color,
            activebackground="#442222",
            activeforeground="#ff9999",
            relief=tk.FLAT,
            bd=0,
            command=self._on_close,
        )
        self.close_button.pack(side=tk.RIGHT, padx=2)

        for widget in (self.title_bar, self.title_label, self.status_dot, self.drawer_toggle_button):
            widget.bind('<ButtonPress-1>', self._start_move)
            widget.bind('<B1-Motion>', self._do_move)
        
        self.title_bar.pack(fill=tk.X, side=tk.TOP)

        # ── Debug line ──
        debug_frame = tk.Frame(self.main_frame, bg=cfg.bg_color)
        debug_frame.pack(fill=tk.X, padx=10, pady=(4, 0))
        self.debug_label = tk.Label(
            debug_frame, text="screen: -  |  event: -", font=self.mini_font,
            fg=cfg.dim_color, bg=cfg.bg_color, anchor='w',
        )
        self.debug_label.pack(fill=tk.X)

        # ── State of the Game Section (Adjustable height via collapsed prompt state) ──
        summary_container = tk.Frame(self.main_frame, bg=cfg.bg_color)
        summary_container.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(
            summary_container, text="STATE OF THE GAME", font=self.label_font,
            fg=cfg.summary_color, bg=cfg.bg_color,
        ).pack(anchor=tk.W, pady=(0, 3))

        summary_box, self.summary_text = self._make_scrollable_text(
            summary_container, height=4,
            fg_color=cfg.summary_color, font=self.small_font,
        )
        summary_box.pack(fill=tk.X)

        self._add_divider()

        # ── Coaching Feedback Section (PRIMARY ELEMENT) ──
        feedback_container = tk.Frame(self.main_frame, bg=cfg.bg_color)
        feedback_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 4))

        feedback_header_row = tk.Frame(feedback_container, bg=cfg.bg_color)
        feedback_header_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            feedback_header_row, text="COACH FEEDBACK", font=self.label_font,
            fg=cfg.feedback_color, bg=cfg.bg_color,
        ).pack(side=tk.LEFT)
        self.clear_button = tk.Button(
            feedback_header_row, text="Clear", font=self.mini_font,
            fg=cfg.dim_color, bg=cfg.bg_color,
            activebackground=cfg.border_color,
            activeforeground=cfg.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self.clear_feedback_history,
        )
        self.clear_button.pack(side=tk.RIGHT)

        feedback_box, self.feedback_text = self._make_scrollable_text(
            feedback_container, height=10,
            fg_color=cfg.feedback_color, font=self.text_font,
        )
        feedback_box.pack(fill=tk.BOTH, expand=True)
        self.feedback_text.tag_configure('timestamp', foreground=cfg.dim_color, font=self.mini_font)
        self.feedback_text.tag_configure('body', foreground=cfg.feedback_color, font=self.text_font)

        self._add_divider()

        # ── Prompt Section (Collapsible, defaults to collapsed) ──
        prompt_outer_container = tk.Frame(self.main_frame, bg=cfg.bg_color)
        prompt_outer_container.pack(fill=tk.X, padx=10, pady=4)

        prompt_header_row = tk.Frame(prompt_outer_container, bg=cfg.bg_color)
        prompt_header_row.pack(fill=tk.X, pady=(0, 3))
        
        self.prompt_toggle_btn = tk.Button(
            prompt_header_row, text="▶ LAST PROMPT", font=self.label_font,
            fg=cfg.prompt_color, bg=cfg.bg_color,
            activebackground=cfg.bg_color, activeforeground=cfg.accent_color,
            relief=tk.FLAT, bd=0, cursor="hand2", anchor="w",
            command=self._toggle_prompt_section
        )
        self.prompt_toggle_btn.pack(side=tk.LEFT, fill=tk.X)

        self.prompt_content_frame = tk.Frame(prompt_outer_container, bg=cfg.bg_color)
        
        prompt_box, self.prompt_text = self._make_scrollable_text(
            self.prompt_content_frame, height=4,
            fg_color=cfg.prompt_color, font=self.small_font,
        )
        prompt_box.pack(fill=tk.X)
        
        self.prompt_content_frame.pack_forget()

        self._add_divider()

        # ── Bottom bar: ETA + Tokens ──
        bottom_row = tk.Frame(self.main_frame, bg=cfg.bg_color)
        bottom_row.pack(fill=tk.X, padx=10, pady=(4, 2))

        self.eta_frame = tk.Frame(bottom_row, bg=cfg.bg_color)
        self.eta_frame.pack(side=tk.LEFT)

        tk.Label(self.eta_frame, text="ETA", font=self.small_font, fg=cfg.dim_color, bg=cfg.bg_color).pack(anchor=tk.W)
        self.eta_label = tk.Label(self.eta_frame, text="--:--", font=self.label_font, fg=cfg.eta_color, bg=cfg.bg_color, width=8)
        self.eta_label.pack(anchor=tk.W)

        self.eta_bar = tk.Canvas(self.eta_frame, width=160, height=8, bg=cfg.bg_color, highlightthickness=0)
        self.eta_bar.pack(anchor=tk.W, pady=(2, 0))
        self.eta_bar_bg = self.eta_bar.create_rectangle(0, 0, 160, 8, fill="#2a2a2a", outline="")
        self.eta_bar_progress = self.eta_bar.create_rectangle(0, 0, 0, 8, fill=cfg.eta_color, outline="")

        self.token_frame = tk.Frame(bottom_row, bg=cfg.bg_color)
        self.token_frame.pack(side=tk.RIGHT)

        tk.Label(self.token_frame, text="TPM", font=self.small_font, fg=cfg.dim_color, bg=cfg.bg_color).pack(anchor=tk.E)
        self.token_label = tk.Label(self.token_frame, text="0 / 200k", font=self.label_font, fg=cfg.token_color, bg=cfg.bg_color)
        self.token_label.pack(anchor=tk.E)

        self.token_bar = tk.Canvas(self.token_frame, width=140, height=8, bg=cfg.bg_color, highlightthickness=0)
        self.token_bar.pack(anchor=tk.E, pady=(2, 0))
        self.token_bar_bg = self.token_bar.create_rectangle(0, 0, 140, 8, fill="#2a2a2a", outline="")

        # ── Rate limits ──
        rate_row = tk.Frame(self.main_frame, bg=cfg.bg_color)
        rate_row.pack(fill=tk.X, padx=10, pady=(2, 4))
        self.rate_daily_label = tk.Label(rate_row, text="Today: -- / --", font=self.small_font, fg=cfg.dim_color, bg=cfg.bg_color)
        self.rate_daily_label.pack(side=tk.LEFT)
        self.rate_minute_label = tk.Label(rate_row, text="-- / -- RPM", font=self.small_font, fg=cfg.dim_color, bg=cfg.bg_color)
        self.rate_minute_label.pack(side=tk.RIGHT)
        
        self.daily_tokens_label = tk.Label(rate_row, text="0 tokens today", font=self.small_font, fg=cfg.dim_color, bg=cfg.bg_color)
        self.daily_tokens_label.pack(side=tk.LEFT, padx=(12, 0))

        # ── Reset timer ──
        self.reset_rule_button = tk.Menubutton(
            rate_row, text="Reset: Pacific", font=self.mini_font,
            fg=cfg.dim_color, bg=cfg.bg_color,
            activebackground=cfg.border_color, activeforeground=cfg.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
        )
        reset_menu = tk.Menu(self.reset_rule_button, tearoff=0, bg=cfg.bg_color, fg=cfg.fg_color)
        reset_menu.add_command(label="Pacific (Google default)", command=lambda: self._on_reset_rule_selected("America/Los_Angeles", "Pacific"))
        reset_menu.add_command(label="Local time", command=lambda: self._on_reset_rule_selected("local", "Local"))
        self.reset_rule_button.config(menu=reset_menu)
        self.reset_rule_button.pack(side=tk.RIGHT, padx=(0, 8))

        # Status bar
        self.status_frame = tk.Frame(self.main_frame, bg=cfg.border_color)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = tk.Label(
            self.status_frame, text="Ready", font=self.small_font,
            fg=cfg.accent_color, bg=cfg.border_color,
            anchor='e', padx=8, pady=2,
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 20))

        # Resize grip
        self.resize_grip = tk.Canvas(self, width=14, height=14, bg=cfg.border_color, highlightthickness=0, cursor="sizing")
        for i in range(3):
            offset = i * 4
            self.resize_grip.create_line(2 + offset, 12, 12, 2 + offset, fill=cfg.dim_color, width=1)
        self.resize_grip.place(relx=1.0, rely=1.0, anchor='se')
        self.resize_grip.bind('<ButtonPress-1>', self._start_resize)
        self.resize_grip.bind('<B1-Motion>', self._do_resize)

        self._add_borders()

    def _toggle_prompt_section(self):
        """Collapses or expands the Last Prompt box, extending/reducing State of the Game by exact gained space."""
        if self._prompt_collapsed:
            self.prompt_content_frame.pack(fill=tk.X, pady=(0, 3))
            self.prompt_toggle_btn.config(text="▼ LAST PROMPT")
            self._prompt_collapsed = False
            self.summary_text.config(height=4)
        else:
            self.prompt_content_frame.pack_forget()
            self.prompt_toggle_btn.config(text="▶ LAST PROMPT")
            self._prompt_collapsed = True
            self.summary_text.config(height=8)

    def _add_divider(self):
        tk.Frame(self.main_frame, bg=self.config_data.border_color, height=1).pack(fill=tk.X, padx=10)

    def _create_layout(self):
        if self._drawer_open:
            self.drawer_outer_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _add_borders(self):
        left_border = tk.Frame(self, bg="#00cc77", width=1)
        left_border.place(x=0, y=0, relheight=1.0)
        right_border = tk.Frame(self, bg="#00cc77", width=1)
        right_border.place(relx=1.0, x=-1, y=0, relheight=1.0)
        bottom_border = tk.Frame(self, bg="#00cc77", height=1)
        bottom_border.place(x=0, rely=1.0, y=-1, relwidth=1.0)

    def _position_window(self):
        cfg = self.config_data
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        drawer_offset = cfg.drawer_width if self._drawer_open else 0
        x = screen_width + cfg.offset_x - drawer_offset
        y = cfg.offset_y

        if x < 0: x = 100
        if y < 0: y = 50

        self.geometry(f"+{x}+{y}")

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
        cfg = self.config_data
        dx = event.x_root - self._resize_start_x_root
        dy = event.y_root - self._resize_start_y_root
        new_w = max(cfg.min_width, self._resize_start_width + dx)
        new_h = max(cfg.min_height, self._resize_start_height + dy)
        self.geometry(f"{new_w}x{new_h}")

    def _on_close(self):
        if self._on_close_callback:
            self._on_close_callback()
        self._running = False
        self.destroy()

    def _toggle_drawer(self):
        self._set_drawer_visible(not self._drawer_open)

    def _set_drawer_visible(self, visible: bool):
        if visible == self._drawer_open:
            return

        current_x = self.winfo_x()
        current_y = self.winfo_y()
        current_width = self.winfo_width()
        current_height = self.winfo_height()
        delta = self.config_data.drawer_width

        self.attributes('-alpha', 0.0)

        if visible:
            self.drawer_outer_frame.pack(side=tk.LEFT, fill=tk.Y, before=self.main_frame)
            new_x = current_x - delta
            new_width = current_width + delta
        else:
            self.drawer_outer_frame.pack_forget()
            new_x = current_x + delta
            new_width = current_width - delta

        self._drawer_open = visible
        self.geometry(f"{new_width}x{current_height}+{new_x}+{current_y}")
        self.drawer_toggle_button.config(text="« Chat" if visible else "Chat »")
        
        self.update_idletasks()
        self.attributes('-alpha', self.config_data.opacity)

    def _on_reset_rule_selected(self, timezone_name, display_name):
        self.reset_rule_button.config(text=f"Reset: {display_name}")
        if self._on_reset_rule_change:
            self._on_reset_rule_change(timezone_name)


# ─── Main Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = CoachOverlay()
    app.set_connection_status(True)

    def demo_updates():
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
