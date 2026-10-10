"""Per-window ownership of analysis runs.

Every browser window gets its own id and owns only the runs it created. While the window is open it
sends a heartbeat. A run with no live owner is removed - so closing the window (or submitting a new
URL in it) discards its data. Nothing is written to disk; this registry lives in process memory, like
the analysis data itself.
"""

from __future__ import annotations

import os
import threading
import time

# A window that stops sending heartbeats for this long is considered closed.
# The web app pings every 20 seconds, so 180 seconds leaves room for throttled background tabs.
WINDOW_TTL_SECONDS = float(os.getenv("WINDOW_TTL_SECONDS", "180"))
# How often the server checks for expired windows.
SWEEP_INTERVAL_SECONDS = float(os.getenv("WINDOW_SWEEP_SECONDS", "15"))


class WindowRegistry:
    def __init__(self, ttl: float = WINDOW_TTL_SECONDS) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._created: dict[str, float] = {}
        self._owners: dict[str, dict[str, float]] = {}

    def track(self, analysis_id: str, window_id: str | None = None) -> None:
        """Register a run, and (optionally) make a window its owner."""
        now = time.monotonic()
        with self._lock:
            self._created.setdefault(analysis_id, now)
            if window_id:
                self._owners.setdefault(analysis_id, {})[window_id] = now

    def heartbeat(self, analysis_id: str, window_id: str) -> bool:
        """Mark a window as alive. Returns False when the run is unknown (already discarded)."""
        with self._lock:
            if analysis_id not in self._created:
                return False
            self._owners.setdefault(analysis_id, {})[window_id] = time.monotonic()
            return True

    def release(self, analysis_id: str, window_id: str) -> bool:
        """Drop one window's ownership. Returns True when no owner is left."""
        with self._lock:
            owners = self._owners.get(analysis_id, {})
            owners.pop(window_id, None)
            if owners:
                return False
            self._owners.pop(analysis_id, None)
            return True

    def expired(self) -> list[str]:
        """Runs whose owners have all gone quiet. Untracked-owner runs get one TTL of grace."""
        now = time.monotonic()
        with self._lock:
            result = []
            for analysis_id, created in self._created.items():
                owners = self._owners.get(analysis_id, {})
                if any(now - seen < self.ttl for seen in owners.values()):
                    continue
                if not owners and now - created < self.ttl:
                    continue
                result.append(analysis_id)
            return result

    def is_owner(self, analysis_id: str, window_id: str) -> bool:
        with self._lock:
            return window_id in self._owners.get(analysis_id, {})

    def forget(self, analysis_id: str) -> None:
        with self._lock:
            self._created.pop(analysis_id, None)
            self._owners.pop(analysis_id, None)


_registry = WindowRegistry()


def get_windows() -> WindowRegistry:
    return _registry
