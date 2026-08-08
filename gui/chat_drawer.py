"""
Chat / Question drawer component for the Coach Overlay.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional


class ChatDrawerMixin:
    """Mixin class providing chat drawer UI creation and handling methods for CoachOverlay."""

    def _create_drawer_widgets(self):
        """Builds the chat/question drawer panel with a multi-line input box and grey border separator."""
        cfg = self.config_data
        self.drawer_outer_frame = tk.Frame(self, bg=cfg.bg_color, cursor="fleur")
        
        self.drawer_frame = tk.Frame(
            self.drawer_outer_frame, bg=cfg.bg_color, width=cfg.drawer_width,
        )
        self.drawer_frame.pack_propagate(False)
        self.drawer_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        separator_border = tk.Frame(self.drawer_outer_frame, bg=cfg.border_color, width=2)
        separator_border.pack(side=tk.RIGHT, fill=tk.Y)

        drawer_header = tk.Frame(self.drawer_frame, bg=cfg.border_color, height=22, cursor="fleur")
        drawer_header.pack_propagate(False)
        drawer_header.pack(fill=tk.X, side=tk.TOP)
        
        drawer_header_label = tk.Label(
            drawer_header, text="ASK THE COACH", font=self.label_font,
            fg=cfg.accent_color, bg=cfg.border_color,
            cursor="fleur",
        )
        drawer_header_label.pack(side=tk.LEFT, padx=8)

        for widget in (drawer_header, drawer_header_label):
            widget.bind('<ButtonPress-1>', self._start_move)
            widget.bind('<B1-Motion>', self._do_move)

        chat_container = tk.Frame(self.drawer_frame, bg=cfg.bg_color)
        chat_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(6, 4))
        chat_box, self.chat_text = self._make_scrollable_text(
            chat_container, height=10,
            fg_color=cfg.fg_color, font=self.small_font,
        )
        chat_box.pack(fill=tk.BOTH, expand=True)
        self.chat_text.tag_configure('player', foreground=cfg.fg_color, font=self.small_font)
        self.chat_text.tag_configure('coach', foreground=cfg.feedback_color, font=self.small_font)
        self.chat_text.tag_configure('chat_label', foreground=cfg.dim_color, font=self.mini_font)

        self.message_type_var = tk.StringVar(value="question")
        type_row = tk.Frame(self.drawer_frame, bg=cfg.bg_color)
        type_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        for label, value in (("Question", "question"), ("Feedback", "feedback")):
            tk.Radiobutton(
                type_row, text=label, value=value, variable=self.message_type_var,
                font=self.mini_font, fg=cfg.fg_color,
                bg=cfg.bg_color, activebackground=cfg.bg_color,
                selectcolor=cfg.border_color, relief=tk.FLAT,
            ).pack(side=tk.LEFT, padx=(0, 8))

        input_row = tk.Frame(self.drawer_frame, bg=cfg.bg_color)
        input_row.pack(fill=tk.X, padx=8, pady=(0, 8))
        
        self.chat_entry = tk.Text(
            input_row, font=self.small_font, bg=cfg.bg_color,
            fg=cfg.fg_color, insertbackground=cfg.fg_color,
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=cfg.border_color,
            highlightcolor=cfg.accent_color,
            height=3, wrap=tk.WORD
        )
        self.chat_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self.chat_entry.bind('<Return>', self._handle_text_return)

        send_button = tk.Button(
            input_row, text="Send", font=self.mini_font,
            fg=cfg.accent_color, bg=cfg.border_color,
            activebackground=cfg.border_color,
            activeforeground=cfg.fg_color,
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._handle_send,
        )
        send_button.pack(side=tk.RIGHT, anchor="s", padx=(2, 0))

    def _handle_text_return(self, event):
        if event.state & 0x0001:
            return 
        else:
            self._handle_send()
            return "break"

    def _handle_send(self):
        text = self.chat_entry.get("1.0", tk.END).strip()
        if not text:
            return
        message_type = self.message_type_var.get()

        self.append_chat_message("player", text, type_label=message_type)
        self.chat_entry.delete("1.0", tk.END)

        if self._on_send_message:
            self._on_send_message(text, message_type)
        else:
            self.append_chat_message("coach", "(not connected yet -- try again in a moment)")

    def append_chat_message(self, role: str, text: str, type_label: Optional[str] = None):
        def _update():
            label = "You" if role == "player" else "Coach"
            if type_label:
                label += f" ({type_label})"
            was_at_bottom = self._is_scrolled_to_bottom(self.chat_text)

            self.chat_text.config(state=tk.NORMAL)
            if self.chat_text.index('end-1c') != '1.0':
                self.chat_text.insert(tk.END, "\n\n")
            self.chat_text.insert(tk.END, f"{label}\n", 'chat_label')
            self.chat_text.insert(tk.END, text, role)
            self.chat_text.config(state=tk.DISABLED)

            if was_at_bottom:
                self.chat_text.see(tk.END)
        self.after(0, _update)
