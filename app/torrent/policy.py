"""Stateful policies for /add flow (rate limiting and metrics)."""

from __future__ import annotations

from collections import Counter, deque
import threading
import time


class AddPolicyService:
    def __init__(self, adds_per_minute: int) -> None:
        self._adds_per_minute = max(1, adds_per_minute)
        self._recent_adds_by_user: dict[int, deque[float]] = {}
        self._metrics = Counter()
        self._lock = threading.Lock()

    def enforce_rate_limit(self, user_id: int) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._recent_adds_by_user.setdefault(user_id, deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self._adds_per_minute:
                self._metrics["rejected:rate_limit"] += 1
                return False
            window.append(now)
            return True

    def mark_accepted(self) -> None:
        with self._lock:
            self._metrics["accepted"] += 1

    def mark_rejection(self, reason: str) -> None:
        with self._lock:
            self._metrics[f"rejected:{reason}"] += 1

    def mark_qbit_error(self) -> None:
        with self._lock:
            self._metrics["qbit:error"] += 1

    def mark_qbit_latency(self, seconds: float) -> None:
        with self._lock:
            self._metrics["qbit:add_calls"] += 1
            self._metrics["qbit:add_latency_ms_total"] += int(seconds * 1000)
