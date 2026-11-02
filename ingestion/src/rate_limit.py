"""Sliding-window limiter for HTTP ingestion, per process (not cluster-wide)."""
from collections import deque
from threading import Lock
from time import monotonic


class RateLimiter:
    def __init__(self, requests_per_second: int):
        if requests_per_second < 0:
            raise ValueError("requests_per_second must be >= 0")
        self.limit = requests_per_second
        self._lock = Lock()
        self._times: deque[float] = deque()

    def allow(self) -> bool:
        if self.limit == 0:
            return True
        with self._lock:
            now = monotonic()
            while self._times and self._times[0] <= now - 1.0:
                self._times.popleft()
            if len(self._times) >= self.limit:
                return False
            self._times.append(now)
            return True
