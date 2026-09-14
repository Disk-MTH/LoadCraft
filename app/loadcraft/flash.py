"""Firmware flashing through the built-in ATmega32u4 bootloader.

Sequence: the app opens the board's port at 1200 baud - the touch that makes
the chip reset into its bootloader - waits for the bootloader to re-appear as
a serial port, then runs avrdude against it. avrdude writes flash only
(-U flash:w:), so the EEPROM - and with it the calibration - survives.

avrdude is invoked with the plain ``avr109`` programmer type (the AVR109
bootloader protocol the ATmega32u4/Caterina bootloader speaks - the same
protocol the Arduino AVR core uses for the Leonardo): the 1200-baud touch is
done by this module rather than by avrdude's ``arduino`` programmer type, so
any avrdude build works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from . import link
from .manager import KNOWN_BOARD_IDS

BAUD_BOOTLOADER_TOUCH = 1200
TOUCH_HOLD_SECONDS = 1.0
BOOTLOADER_SETTLE_SECONDS = 2.0
AVRDUDE_TIMEOUT_SECONDS = 60.0
MAX_FLASH_ATTEMPTS = 2
MCU = "m32u4"
BOOTLOADER_BAUD = 57600


class FlashError(RuntimeError):
    """Flash failure with an actionable message (avrdude log included)."""


# --- Path resolution ----------------------------------------------------------


def _data_dir() -> Path:
    """Where the bundled data (hex, avrdude) lives.

    A PyInstaller onefile build extracts to sys._MEIPASS; a normal
    installation reads from the package directory.
    """
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "loadcraft" / "data"
    return Path(__file__).parent / "data"


def avrdude_path() -> str:
    name = "avrdude.exe" if os.name == "nt" else "avrdude"
    bundled = _data_dir() / "avrdude" / name
    if bundled.is_file():
        return str(bundled)
    system = shutil.which("avrdude")
    if system:
        return system
    raise FlashError(
        "avrdude not found: no bundled binary and no avrdude on PATH "
        "(on Linux: dnf install avrdude)"
    )


def hex_path() -> str:
    path = _data_dir() / "handbrake.hex"
    if not path.is_file():
        raise FlashError("firmware not bundled - run `make build-hex` first")
    return str(path)


# --- Bootloader touch ------------------------------------------------------------


def _real_open(port: str, baud: int):
    import serial

    return serial.Serial(port=port, baudrate=baud)


def trigger_bootloader(
    port: str,
    opener: Callable[[str, int], object] = _real_open,
    hold_seconds: float = TOUCH_HOLD_SECONDS,
) -> None:
    """Resets the chip into its bootloader.

    Opening the CDC port at 1200 baud is the standard touch of the 32u4
    bootloaders (the same mechanism the Arduino tooling uses). The chip
    re-enumerates in bootloader mode while the port stays open; it stays
    there for about 8 seconds.
    """
    serial = opener(port, BAUD_BOOTLOADER_TOUCH)
    try:
        time.sleep(hold_seconds)
    finally:
        serial.close()


# --- Port discovery ----------------------------------------------------------------


def _usb_ports(list_ports_fn: Callable[[], List[dict]]) -> List[dict]:
    try:
        return [p for p in list_ports_fn() if p.get("usb")]
    except Exception:
        return []


def bootloader_candidates(
    before: List[dict], after: List[dict], board_port: str
) -> List[str]:
    """Ports to try for the bootloader, ordered by likelihood.

    The bootloader usually reuses the board's port name; on some systems it
    appears as a new device with a bootloader PID (typically 2341:0043 or
    2341:0001, clone-dependent).
    """
    candidates: List[str] = []
    if any(p["device"] == board_port for p in after):
        candidates.append(board_port)

    before_devices = {p["device"] for p in before}
    for p in after:
        if p["device"] in candidates or p["device"] in before_devices:
            continue
        vid, pid = p.get("vid"), p.get("pid")
        if vid is None or pid is None:
            continue
        if (vid, pid) in KNOWN_BOARD_IDS:
            continue  # a handbrake in app mode, not the bootloader
        candidates.append(p["device"])

    return candidates[:MAX_FLASH_ATTEMPTS]


# --- Flash -----------------------------------------------------------------------


def _run(cmd: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(
        list(cmd), capture_output=True, text=True,
        timeout=AVRDUDE_TIMEOUT_SECONDS,
    )


def _conf_for(avrdude_bin: str) -> Optional[str]:
    """The avrdude.conf next to the binary, if present.

    The vendored binary is passed -C explicitly: a bare standalone avrdude
    may not find its configuration file from an arbitrary working directory.
    """
    conf = Path(avrdude_bin).resolve().parent / "avrdude.conf"
    return str(conf) if conf.is_file() else None


def flash(
    board_port: str,
    *,
    avrdude: Optional[str] = None,
    hexfile: Optional[str] = None,
    list_ports_fn: Callable[[], List[dict]] = link.list_ports,
    runner: Callable[[List[str]], "subprocess.CompletedProcess"] = _run,
    sleeper: Callable[[float], None] = time.sleep,
    touch: Callable[[str], None] = trigger_bootloader,
) -> str:
    """Flashes the bundled firmware and returns the combined avrdude log.

    Raises FlashError when the bootloader cannot be found or no candidate
    port accepted the write.
    """
    avrdude_bin = avrdude or avrdude_path()
    hexfile_ = hexfile or hex_path()

    before = _usb_ports(list_ports_fn)
    touch(board_port)
    sleeper(BOOTLOADER_SETTLE_SECONDS)
    after = _usb_ports(list_ports_fn)

    candidates = bootloader_candidates(before, after, board_port)
    if not candidates:
        raise FlashError(
            "bootloader port not found after the 1200-baud touch "
            "(double-tap RESET manually and retry)"
        )

    conf = _conf_for(avrdude_bin)
    logs: List[str] = []
    for port in candidates:
        cmd: List[str] = [avrdude_bin]
        if conf is not None:
            cmd += ["-C", conf]
        cmd += [
            "-q", "-p", MCU, "-c", "avr109",
            "-b", str(BOOTLOADER_BAUD), "-P", port,
            "-U", f"flash:w:{hexfile_}",
        ]
        try:
            proc = runner(cmd)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"[{port}] {exc}")
            continue
        log = (proc.stdout or "") + (proc.stderr or "")
        logs.append(f"[{port}] {log}")
        if proc.returncode == 0:
            return "\n".join(logs)

    raise FlashError(
        "flash failed on all candidate ports:\n" + "\n".join(logs)
    )


# --- Single-flight wrapper ---------------------------------------------------------


class Flasher:
    """At most one flash at a time (the second request gets a 409)."""

    def __init__(self, flash_fn: Callable[[str], str] = flash) -> None:
        self._flash = flash_fn
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def run(self, board_port: str) -> str:
        with self._lock:
            if self._busy:
                raise FlashError("flash in progress")
            self._busy = True
        try:
            return self._flash(board_port)
        finally:
            with self._lock:
                self._busy = False
