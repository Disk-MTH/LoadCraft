"""Serial link with the board.

The transport is injected rather than created here: the tests supply a fake
transport and cover the whole dialogue logic without hardware or pyserial.
"""

from __future__ import annotations

import errno
import queue
import sys
import threading
from typing import List, Optional

from . import protocol
from .protocol import Ack, Config, Err, Telemetry

# Baud rate ignored by a CDC port (the rate is the USB one), present by
# convention and because pyserial requires a value.
BAUDRATE = 115200

# The firmware replies immediately; beyond that, the board is not speaking
# this protocol or has restarted.
REPLY_TIMEOUT = 2.0

# Beyond this size an SSE subscriber falls behind: its oldest events are
# dropped rather than growing the queue without bound.
SUBSCRIBER_QUEUE_SIZE = 8


class LinkError(RuntimeError):
    """Dialogue failure with the board."""


class SerialLink:
    """Dialogue with the board: read thread, command sending.

    The read thread sorts the received lines: telemetry feeds the current
    state and the subscribers, everything else goes into the replies queue
    awaited by :meth:`request`.
    """

    def __init__(self, transport, port: str = ""):
        self._transport = transport
        self.port = port
        self._lock = threading.Lock()
        self._config: Optional[Config] = None
        self._telemetry: Optional[Telemetry] = None
        self._last_error: Optional[str] = None
        self._replies: "queue.Queue" = queue.Queue()
        self._subscribers: List["queue.Queue"] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop, name="handbrake-serial", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._transport.close()
        except Exception:
            # The port may already be gone (board unplugged): closing must
            # stay side-effect free.
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)

    # --- State -------------------------------------------------------------

    @property
    def config(self) -> Optional[Config]:
        with self._lock:
            return self._config

    @property
    def telemetry(self) -> Optional[Telemetry]:
        with self._lock:
            return self._telemetry

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    @property
    def dead(self) -> bool:
        """The read thread is dead: the transport failed (board unplugged)
        or the link was closed. It is unusable; the link manager
        (manager.py) handles the cleanup."""
        thread = self._thread
        return thread is None or not thread.is_alive()

    # --- Sending -----------------------------------------------------------

    def send(self, command: str) -> None:
        try:
            self._transport.write((command + "\n").encode("ascii"))
        except Exception as exc:
            raise LinkError(f"cannot write: {exc}") from exc

    def request(self, command: str, timeout: float = REPLY_TIMEOUT) -> object:
        """Sends a command and waits for the matching reply.

        Pending replies are drained before sending: otherwise a late reply
        from a previous command would be mistaken for this one.
        """
        if self.dead:
            raise LinkError("link is down")

        while True:
            try:
                self._replies.get_nowait()
            except queue.Empty:
                break

        self.send(command)

        try:
            return self._replies.get(timeout=timeout)
        except queue.Empty:
            raise LinkError(f"no reply to {command}") from None

    def request_config(self, command: str) -> Config:
        """Sends a command whose expected reply is a ``CFG``."""
        reply = self.request(command)
        if isinstance(reply, Config):
            return reply
        if isinstance(reply, Err):
            raise LinkError(reply.reason)
        # Some commands acknowledge without resending the configuration:
        # it is fetched again so the app stays up to date.
        reply = self.request(protocol.cmd_get())
        if isinstance(reply, Config):
            return reply
        raise LinkError("unreadable configuration")

    # --- SSE subscriptions -------------------------------------------------

    def subscribe(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    # --- Read thread -------------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._transport.readline()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                break

            if not raw:
                continue  # timeout, nothing to read

            try:
                line = raw.decode("ascii", errors="replace")
            except Exception:
                continue

            self._dispatch(protocol.parse_line(line))

    def _dispatch(self, message) -> None:
        if message is None:
            return

        if isinstance(message, Telemetry):
            with self._lock:
                self._telemetry = message
                subscribers = list(self._subscribers)
            for q in subscribers:
                _offer(q, message)
            return

        if isinstance(message, Config):
            with self._lock:
                self._config = message
        elif isinstance(message, Err):
            with self._lock:
                self._last_error = message.reason

        # Config, Ack and Err are all replies to a command.
        self._replies.put(message)


def _offer(q: "queue.Queue", item) -> None:
    """Deposits without ever blocking, dropping the oldest item if needed."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except (queue.Empty, queue.Full):
            pass


# --- Real transport --------------------------------------------------------


def _describe(port) -> dict:
    label = port.description or ""
    if port.vid is not None and port.pid is not None:
        label = f"{label} [{port.vid:04X}:{port.pid:04X}]".strip()
    return {
        "device": port.device,
        "description": label,
        "hwid": port.hwid or "",
        "usb": port.vid is not None,
        "vid": port.vid,
        "pid": port.pid,
    }


def list_ports() -> List[dict]:
    """Available serial ports.

    Only USB ports are kept: on Linux, pyserial also lists the thirty or so
    inherited 8250 ports (``/dev/ttyS*``), which would bury the board in a
    list where it is unfindable. A handbrake is a USB device by construction.

    If no USB port is detected, the full list is returned rather than an
    empty one: a cluttered choice is better than no choice at all.

    pyserial is imported here and not at module load: the tests run without
    it, and the app stays diagnosable if it is missing.
    """
    try:
        from serial.tools import list_ports as _list_ports
    except ImportError:
        return []

    ports = [_describe(p) for p in _list_ports.comports()]
    usb_ports = [p for p in ports if p["usb"]]
    return sorted(usb_ports or ports, key=lambda p: p["device"])


def _open_failure_hint(port: str, exc: Exception) -> str:
    """Actionable open-failure message.

    Each open error has a dominant cause and a known fix. Returning the
    raw error ("[Errno 13] Permission denied") leaves the user hunting
    for what the program already knows.
    """
    code = getattr(exc, "errno", None)

    if code == errno.EACCES:
        if sys.platform.startswith("linux"):
            return (
                f"access to {port} denied. On Linux, serial port access "
                "goes through the dialout group: "
                "sudo usermod -aG dialout $USER, then log out and log "
                "back in. An application started before that step keeps "
                "its old credentials and must be fully restarted."
            )
        return f"access to {port} denied. Check the port permissions."

    if code == errno.EBUSY:
        return (
            f"{port} is already open by another program "
            "(serial monitor, another app instance...)."
        )

    if code == errno.ENOENT:
        return (
            f"{port} does not exist. Was the board unplugged, or did "
            "the port change its name?"
        )

    return f"cannot open {port}: {exc}"


def open_serial(port: str, timeout: float = 0.2):
    """Opens a real serial port."""
    try:
        import serial
    except ImportError as exc:
        raise LinkError(
            "pyserial is not installed (pip install pyserial)"
        ) from exc

    try:
        return serial.Serial(port=port, baudrate=BAUDRATE, timeout=timeout)
    except Exception as exc:
        raise LinkError(_open_failure_hint(port, exc)) from exc


def connect(port: str) -> SerialLink:
    """Opens the port, starts reading and fetches the configuration."""
    link = SerialLink(open_serial(port), port=port)
    link.start()
    try:
        config = link.request_config(protocol.cmd_get())
        if config is None:
            raise LinkError("the board did not answer")
        link.send(protocol.cmd_stream(True))
    except Exception:
        link.close()
        raise
    return link
