"""
usage_tracker.py

Tracks Gemini usage against config.RATE_LIMITS for the active model --
both the RPM sliding window and the RPD daily quota. RPD is persisted
to disk (config.USAGE_STATE_PATH) so restarting main.py mid-day (an
explicitly supported flow -- see stream_adapter.py) doesn't lose the
count and let us blow through the real daily cap without noticing.

Ownership: one instance per process, constructed in main.py and handed
to GeminiWorker. record_request()/wait_time()/is_daily_quota_exhausted()
are only ever called from GeminiWorker's own thread. eta_seconds() and
snapshot() ARE called cross-thread (submit_* runs on main.py's polling
thread; recording happens on the worker thread), so everything goes
through one lock rather than trying to reason about which subset needs
it -- simpler to get right.
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config


class UsageTracker:
    def __init__(self, model_name=config.DEFAULT_MODEL, state_path=config.USAGE_STATE_PATH,
                 reset_timezone=None, reset_hour=None):
        self.model_name = model_name
        self._state_path = state_path
        self._lock = threading.RLock()

        limits = config.rate_limit_for(model_name)
        self.rpm_limit = limits.rpm
        self.tpm_limit = limits.tpm
        self.rpd_limit = limits.rpd

        self._request_timestamps = deque()  # monotonic times, RPM window
        self._latencies = deque(maxlen=config.ETA_ROLLING_WINDOW)
        
        self.reset_timezone = reset_timezone or config.QUOTA_RESET_TIMEZONE
        self.reset_hour = reset_hour if reset_hour is not None else config.QUOTA_RESET_HOUR

        self._quota_period = None
        self.requests_today = 0
        self.tokens_today = 0
        self._load_state()

    # -- Quota period bookkeeping ----------------------------------

    def _current_period(self) -> str:
        tz = ZoneInfo(config.QUOTA_RESET_TIMEZONE)
        now = datetime.now(tz) - timedelta(hours=config.QUOTA_RESET_HOUR)
        return now.date().isoformat()

    def _load_state(self):
        period = self._current_period()
        try:
            with open(self._state_path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        if data.get("quota_period") == period:
            self.requests_today = data.get("requests_today", 0)
            self.tokens_today = data.get("tokens_today", 0)
        self._quota_period = period

    def _save_state(self):
        data = {
            "quota_period": self._quota_period,
            "requests_today": self.requests_today,
            "tokens_today": self.tokens_today,
        }
        tmp_path = self._state_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, self._state_path)  # atomic on POSIX and Windows

    def _roll_period_if_needed(self):
        period = self._current_period()
        if period != self._quota_period:
            self._quota_period = period
            self.requests_today = 0
            self.tokens_today = 0
 
     # -- Reset timezone ---------------------------------------------------           
    def set_reset_rule(self, timezone_name: str, hour: int = 0):
        """Runtime override -- e.g. the GUI toggle between Google's actual
        Pacific reset and the player's local midnight. This only changes
        which 'period' we THINK we're in for our own proactive throttling;
        Google's servers enforce the real RPD limit on Pacific time
        regardless, so switching to 'local' trades a little accuracy in
        our own daily counter for a display the player finds intuitive."""
        with self._lock:
            self.reset_timezone = timezone_name
            self.reset_hour = hour
            self._roll_period_if_needed()

    def _current_period(self) -> str:
        if self.reset_timezone == "local":
            now = datetime.now() - timedelta(hours=self.reset_hour)
        else:
            tz = ZoneInfo(self.reset_timezone)
            now = datetime.now(tz) - timedelta(hours=self.reset_hour)
        return now.date().isoformat()

    # -- Public API ---------------------------------------------------

    def is_daily_quota_exhausted(self) -> bool:
        with self._lock:
            self._roll_period_if_needed()
            return self.requests_today >= self.rpd_limit

    def wait_time(self) -> float:
        """Seconds to sleep before the next request stays under the RPM
        sliding window. 0 if clear to go now."""
        with self._lock:
            now = time.monotonic()
            window_start = now - 60.0
            while self._request_timestamps and self._request_timestamps[0] < window_start:
                self._request_timestamps.popleft()
            if len(self._request_timestamps) < self.rpm_limit:
                return 0.0
            return max(0.0, 60.0 - (now - self._request_timestamps[0]))

    def record_request(self, latency_s: float, tokens: int = 0):
        with self._lock:
            self._roll_period_if_needed()
            self._request_timestamps.append(time.monotonic())
            self._latencies.append(latency_s)
            self.requests_today += 1
            self.tokens_today += tokens
            self._save_state()

    def eta_seconds(self) -> float:
        with self._lock:
            if not self._latencies:
                return 8.0  # conservative estimate before any real samples
            return sum(self._latencies) / len(self._latencies)

    def requests_this_minute(self) -> int:
        with self._lock:
            now = time.monotonic()
            window_start = now - 60.0
            return sum(1 for t in self._request_timestamps if t >= window_start)

    def snapshot(self) -> dict:
        with self._lock:
            self._roll_period_if_needed()
            return {
                "requests_today": self.requests_today,
                "rpd_limit": self.rpd_limit,
                "tokens_today": self.tokens_today,
                "requests_this_minute": self.requests_this_minute(),
                "rpm_limit": self.rpm_limit,
            }