"""Application lifecycle: the app lives as long as its interface does.

The interface is a browser tab. The page keeps an SSE channel open for its
whole life (see the /api/keepalive endpoint); when the tab closes the
channel dies with it. After a grace period - long enough to absorb
EventSource reconnects and laptop sleep/wake - the process exits. Closing
the tab is the uninstall-free way to stop the app, with no orphan server.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

KEEPALIVE_GRACE_SECONDS = 10.0
WATCHDOG_INTERVAL = 1.0


def _default_exit() -> None:
    # The watchdog runs in a daemon thread: sys.exit would only end that
    # thread, so the process is terminated outright. All state worth saving
    # (calibration) lives in the board EEPROM, not here.
    os._exit(0)


class KeepAlive:
    """Tracks live UI clients and exits when the last one is gone.

    now_fn and exit_fn are injected so tests drive the clock and capture
    the exit instead of killing the test process.
    """

    def __init__(
        self,
        now_fn: Optional[Callable[[], float]] = None,
        exit_fn: Optional[Callable[[], None]] = None,
        grace_seconds: float = KEEPALIVE_GRACE_SECONDS,
    ) -> None:
        self._now = now_fn if now_fn is not None else time.monotonic
        self._exit = exit_fn if exit_fn is not None else _default_exit
        self._grace = float(grace_seconds)

        self._lock = threading.Lock()
        self._clients = 0
        self._lost_at: Optional[float] = None
        self._exited = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Starts the watchdog thread (daemon)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="keepalive", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check()
            self._stop.wait(WATCHDOG_INTERVAL)

    # --- Client tracking ------------------------------------------------------

    def register(self) -> None:
        with self._lock:
            self._clients += 1
            self._lost_at = None

    def unregister(self) -> None:
        with self._lock:
            if self._clients > 0:
                self._clients -= 1
            if self._clients == 0:
                self._lost_at = self._now()

    @property
    def clients(self) -> int:
        with self._lock:
            return self._clients

    @property
    def exited(self) -> bool:
        with self._lock:
            return self._exited

    # --- Watchdog -------------------------------------------------------------

    def check(self, now: Optional[float] = None) -> None:
        """One watchdog iteration.

        Arms the timer on the first absence, then exits once the clients
        have been absent for the whole grace period. A returning client
        (register) restarts the window.
        """
        with self._lock:
            if self._exited:
                return
            if self._clients > 0:
                return
            if self._lost_at is None:
                self._lost_at = self._now() if now is None else now
                return
            gone = (self._now() if now is None else now) - self._lost_at
            fire = gone >= self._grace
        if fire:
            with self._lock:
                if self._exited:
                    return
                self._exited = True
            self._exit()
