"""
config.py

Central configuration -- currently Gemini rate limits and the daily
quota reset rule. Google no longer publishes a static per-model
RPM/TPM/RPD table (limits are account/tier specific, shown live at
https://aistudio.google.com/rate-limit) -- these values are pulled
from Ficus's own dashboard and may drift. Re-check that page if
requests start getting throttled/rejected in ways these numbers don't
predict.

Search/Maps grounding have their own separate limits -- not tracked
here since this project doesn't use those tools.
"""

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRateLimit:
    rpm: int
    tpm: int
    rpd: int


# From Ficus's AI Studio dashboard, 2026-08-06.
RATE_LIMITS = {
    "gemini-3-flash-preview": ModelRateLimit(rpm=5, tpm=250_000, rpd=20),
    "gemini-3.1-flash-lite": ModelRateLimit(rpm=15, tpm=250_000, rpd=500),
    "gemini-2.5-flash": ModelRateLimit(rpm=5, tpm=250_000, rpd=20),  # availability to new accounts unconfirmed
}

DEFAULT_MODEL = "gemini-3.1-flash-lite"

# Per Google's docs: RPD resets at midnight Pacific by default.
# Configurable since Google could change this, and it's flagged for a
# future "set to local time" UI control rather than only a code
# constant -- not built yet.
QUOTA_RESET_TIMEZONE = "America/Los_Angeles"
QUOTA_RESET_HOUR = 0  # in QUOTA_RESET_TIMEZONE

USAGE_STATE_PATH = "data/usage_state.json"
ETA_ROLLING_WINDOW = 5

RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_S = 2.0
RETRY_MAX_DELAY_S = 20.0

# Gemini 3-series "thinking" (extended reasoning before responding).
# thinking_level is Gemini-3-only -- earlier models error if this is set.
# Accepted values per Google's docs: "minimal", "low", "medium", "high"
# for Flash-family models -- not yet confirmed against a live call for
# gemini-3.1-flash-lite specifically. If the first real response errors
# on this value, that's what to check first.
THINKING_LEVEL = "high"


def rate_limit_for(model_name: str) -> ModelRateLimit:
    """Falls back to DEFAULT_MODEL's limits for a model not yet in the
    table (e.g. one of the ones Ficus hasn't confirmed free-tier access
    to yet) -- but warns loudly rather than silently mis-throttling,
    since a wrong guess here either wastes quota or under-throttles."""
    if model_name not in RATE_LIMITS:
        print(
            f"[Neow's Eye] No configured rate limit for model '{model_name}' -- "
            f"falling back to {DEFAULT_MODEL}'s limits. Add it to "
            f"config.RATE_LIMITS if you're switching models.",
            file=sys.stderr,
        )
        return RATE_LIMITS[DEFAULT_MODEL]
    return RATE_LIMITS[model_name]