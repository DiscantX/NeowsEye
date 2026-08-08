"""
Configuration settings and data models for the Tkinter overlay.
"""

from dataclasses import dataclass, field
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

DEFAULT_DRAWER_OPEN = True

@dataclass
class OverlayConfig:
    """Configuration settings for the overlay window."""
    width: int = 520
    height: int = 680
    min_width: int = 360
    min_height: int = 510
    offset_x: int = -540  # Right-aligned offset from right edge
    offset_y: int = 80    # From top edge
    drawer_width: int = 260  # width of the chat/question drawer panel
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
    summary_color: str = "#ffd966"
    opacity: float = 0.93
    font_family: str = "Segoe UI"
    font_size: int = 10
    title_font_size: int = 12
    border_color: str = "#333333"


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


def resolve_font_family(preferred: str) -> str:
    """Falls back to a common cross-platform font if `preferred` isn't installed."""
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
