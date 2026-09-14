"""Link manager: the automatic connect / disconnect lifecycle of the board.

A background thread owns the serial link: it watches the USB ports, connects
as soon as the board appears, detects a dead link, and reconnects when the
board comes back. The HTTP layer only observes the state and sends commands
through the manager, so no two tabs or processes can fight over the port.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from . import protocol
from .link import LinkError, SerialLink

# USB identifiers of the boards the handbrake firmware targets.
KNOWN_BOARD_IDS = {
    (0x2341, 0x8036),  # Arduino Leonardo (bootloader of most Pro Micros)
    (0x2341, 0x8037),  # Arduino Micro
}

SCAN_INTERVAL = 2.0  # port scan period while not connected
POLL_INTERVAL = 0.5  # dead-link watchdog period


class LinkManager:
    """Owns the serial link: detects the board, connects, watches, reconnects.

    `run_once` takes a monotonic timestamp so tests drive the state machine
    deterministically; the background thread only loops over it.
    """

    def __init__(
        self,
        list_ports_fn: Callable[[], List[dict]],
        connect_fn: Callable[[str], SerialLink],
        scan_interval: float = SCAN_INTERVAL,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self._list_ports = list_ports_fn
        self._connect = connect_fn
        self._scan_interval = scan_interval
        self._poll_interval = poll_interval

        self._lock = threading.Lock()
        self._link: Optional[SerialLink] = None
        self._state = "searching"  # connected | searching | busy | error
        self._last_error: Optional[str] = None
        self._port: Optional[str] = None
        self._port_description: Optional[str] = None
        self._last_scan = 0.0
        self._flash_active = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Starts the background watchdog thread (daemon)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="link-manager", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops the watchdog and closes the link if any."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self._drop_link()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once(time.monotonic())
            self._stop.wait(self._poll_interval)

    # --- State machine -----------------------------------------------------

    def run_once(self, now: float) -> None:
        """One watchdog iteration.

        With a live link: drop it if it died. Without: scan the ports on the
        scan cadence and try to connect to the handbrake. Suppressed while a
        flash is in progress: the port belongs to the flashing tool.
        """
        with self._lock:
            flash_active = self._flash_active
        if flash_active:
            return

        with self._lock:
            link = self._link
            if link is not None:
                dead, scan_due = link.dead, False
            else:
                dead = False
                scan_due = now - self._last_scan >= self._scan_interval
                if scan_due:
                    self._last_scan = now

        if dead:
            self._drop_link()
        elif scan_due:
            self._try_connect()

    def _try_connect(self) -> None:
        try:
            ports = [p for p in self._list_ports() if p.get("usb")]
        except Exception:
            ports = []

        known = [p for p in ports if self._board_id(p) in KNOWN_BOARD_IDS]
        if known:
            target = known[0]
        elif len(ports) == 1:
            target = ports[0]  # a clone reported under another identifier
        elif len(ports) > 1:
            self._set_error("multiple serial devices, cannot pick one")
            return
        else:
            self._set_searching()
            return

        self._set_state("busy")
        try:
            link = self._connect(target["device"])
        except LinkError as exc:
            self._set_error(str(exc))
            return

        with self._lock:
            self._link = link
            self._state = "connected"
            self._last_error = None
            self._port = target["device"]
            self._port_description = target.get("description") or None

    def _drop_link(self) -> None:
        """Closes the current link (if any) and goes back to searching."""
        with self._lock:
            link, self._link = self._link, None
            self._state = "searching"
            self._last_error = None
        if link is not None:
            # Ask the board to stop streaming before the port goes away:
            # otherwise it keeps the telemetry state on across the close.
            # Fire and forget - the board's reply is dropped with the link.
            try:
                link.send(protocol.cmd_stream(False))
            except LinkError:
                pass
            link.close()

    # --- Flash window -------------------------------------------------------

    def pause_for_flash(self) -> None:
        """Stops the scans and closes the link.

        The serial port is released to the flashing tool (flash.py); the
        manager stays out of the way until resume_flash().
        """
        with self._lock:
            self._flash_active = True
        self._drop_link()

    def resume_flash(self) -> None:
        """Ends the flash window: the next iteration scans immediately."""
        with self._lock:
            self._flash_active = False
            self._last_scan = 0.0

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def _set_searching(self) -> None:
        with self._lock:
            self._state = "searching"
            self._last_error = None

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._last_error = message

    @staticmethod
    def _board_id(port: dict):
        vid, pid = port.get("vid"), port.get("pid")
        if vid is None or pid is None:
            return None
        return (vid, pid)

    # --- Observation -------------------------------------------------------

    @property
    def link(self) -> Optional[SerialLink]:
        with self._lock:
            return self._link

    def status(self) -> dict:
        """State payload for GET /api/status."""
        with self._lock:
            link = self._link
            state = self._state
            last_error = self._last_error
            port = self._port
            port_description = self._port_description

        base = {
            "port": port,
            "port_description": port_description,
            "last_error": None if link is not None else last_error,
            "axis_max": protocol.AXIS_MAX,
            "gamma_min": protocol.GAMMA_MIN,
            "gamma_max": protocol.GAMMA_MAX,
            "alpha_min": protocol.ALPHA_MIN,
            "alpha_max": protocol.ALPHA_MAX,
        }
        if link is None:
            base.update(
                {
                    "connected": False,
                    "state": state,
                    "config": None,
                    "telemetry": None,
                }
            )
        else:
            config = link.config
            telemetry = link.telemetry
            base.update(
                {
                    "connected": True,
                    "state": "connected",
                    "config": config.as_dict() if config else None,
                    "telemetry": telemetry.as_dict() if telemetry else None,
                }
            )
        return base

    # --- Commands ------------------------------------------------------------

    def request_config(self, command: str):
        """Sends a command expected to answer with a CFG.

        Raises LinkError when not connected or when the dialog fails.
        """
        link = self.link
        if link is None:
            raise LinkError("not connected")
        return link.request_config(command)

    def subscribe(self):
        """Subscribes to the telemetry stream of the current link."""
        link = self.link
        if link is None:
            raise LinkError("not connected")
        return link.subscribe()
