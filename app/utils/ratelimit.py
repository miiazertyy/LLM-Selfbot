"""
app/utils/ratelimit.py - tiny sliding-window budgets for API calls we don't want
to burst (profile fetches, message-history scans). Caps are generous - they only
smooth bulk sweeps, never block normal chat.
"""

import time
from collections import deque


class SlidingWindow:
    """Allow at most `limit` uses within `window_seconds` (rolling)."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._times: deque = deque()

    def allow(self) -> bool:
        now = time.time()
        while self._times and now - self._times[0] > self.window:
            self._times.popleft()
        if len(self._times) >= self.limit:
            return False
        self._times.append(now)
        return True
