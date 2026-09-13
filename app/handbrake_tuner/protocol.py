"""Handbrake serial protocol, host side.

Mirror of ``firmware/handbrake/hb_protocol.c``. Deliberately stateless and
free of I/O: everything that can go wrong in the exchange with the board is
testable without a board.

The curves are re-implemented here rather than requested from the firmware,
so that the preview shown in the app matches exactly what the firmware
computes. ``tests/test_curve.py`` checks the same properties as the C tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# Must stay aligned with firmware/handbrake/hb_core.h
AXIS_MAX = 1023
GAMMA_MIN = 0.10
GAMMA_MAX = 5.00
ALPHA_MIN = 0.10
ALPHA_MAX = 1.00
ALPHA_DEFAULT = 0.50
CURVES = ("LINEAR", "POWER", "SCURVE")


@dataclass(frozen=True)
class Config:
    """Configuration returned by the board (``CFG ...`` line)."""

    raw_min: int
    raw_max: int
    curve: str
    gamma: float
    alpha: float
    calibrated: bool

    def as_dict(self) -> dict:
        return {
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "curve": self.curve,
            "gamma": self.gamma,
            "alpha": self.alpha,
            "calibrated": self.calibrated,
        }


@dataclass(frozen=True)
class Telemetry:
    """Real-time measurement (``T ...`` line)."""

    raw: int
    out: float
    axis: int
    sensor: bool = True

    def as_dict(self) -> dict:
        return {
            "raw": self.raw,
            "out": self.out,
            "axis": self.axis,
            "sensor": self.sensor,
        }


@dataclass(frozen=True)
class Ack:
    text: str


@dataclass(frozen=True)
class Err:
    reason: str


Message = Union[Config, Telemetry, Ack, Err]


# --- Parsing ---------------------------------------------------------------


def _fields(parts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep:
            out[key] = value
    return out


def parse_line(line: str) -> Optional[Message]:
    """Parses a line received from the board.

    Returns ``None`` for an empty or unrecognized line. The serial port
    emits stray bytes on open and during the board's restart: ignoring them
    is safer than raising an exception in the read thread.
    """
    line = line.strip()
    if not line:
        return None

    parts = line.split()
    tag = parts[0]

    if tag == "CFG":
        fields = _fields(parts[1:])
        try:
            curve = fields["curve"]
            if curve not in CURVES:
                return None
            return Config(
                raw_min=int(fields["min"]),
                raw_max=int(fields["max"]),
                curve=curve,
                gamma=float(fields["gamma"]),
                alpha=float(fields["alpha"]),
                calibrated=fields["calibrated"] == "1",
            )
        except (KeyError, ValueError):
            return None

    if tag == "T":
        fields = _fields(parts[1:])
        try:
            return Telemetry(
                raw=int(fields["raw"]),
                out=float(fields["out"]),
                axis=int(fields["axis"]),
                sensor=fields.get("s", "1") == "1",
            )
        except (KeyError, ValueError):
            return None

    if tag == "OK":
        return Ack(line[3:].strip())

    if tag == "ERR":
        return Err(line[4:].strip())

    return None


# --- Command building --------------------------------------------------------


def cmd_ping() -> str:
    return "PING"


def cmd_get() -> str:
    return "GET"


def cmd_save() -> str:
    return "SAVE"


def cmd_load() -> str:
    return "LOAD"


def cmd_reset() -> str:
    return "RESET"


def cmd_stream(on: bool) -> str:
    return f"STREAM {1 if on else 0}"


def cmd_set_min(value: Optional[int] = None) -> str:
    return "SET MIN" if value is None else f"SET MIN {int(value)}"


def cmd_set_max(value: Optional[int] = None) -> str:
    return "SET MAX" if value is None else f"SET MAX {int(value)}"


def cmd_set_curve(curve: str, gamma: Optional[float] = None) -> str:
    curve = curve.upper()
    if curve not in CURVES:
        raise ValueError(f"unknown curve: {curve}")
    if gamma is None:
        return f"SET CURVE {curve}"
    return f"SET CURVE {curve} {_fmt_float(gamma)}"


def cmd_set_gamma(gamma: float) -> str:
    return f"SET GAMMA {_fmt_float(gamma)}"


def cmd_set_alpha(alpha: float) -> str:
    return f"SET ALPHA {_fmt_float(alpha)}"


def _fmt_float(value: float) -> str:
    return f"{float(value):.3f}"


# --- Curves ------------------------------------------------------------------


def clamp_gamma(gamma: float) -> float:
    """Applies the same bounds as ``hb_config_sanitize``."""
    try:
        gamma = float(gamma)
    except (TypeError, ValueError):
        return 1.0
    if gamma != gamma:  # NaN
        return 1.0
    return max(GAMMA_MIN, min(GAMMA_MAX, gamma))


def clamp_alpha(alpha: float) -> float:
    """Applies the same bounds as ``hb_config_sanitize``."""
    try:
        alpha = float(alpha)
    except (TypeError, ValueError):
        return ALPHA_DEFAULT
    if alpha != alpha:  # NaN
        return ALPHA_DEFAULT
    return max(ALPHA_MIN, min(ALPHA_MAX, alpha))


def apply_curve(curve: str, gamma: float, t: float) -> float:
    """Response curve. Mirror of ``hb_curve_apply``."""
    t = max(0.0, min(1.0, t))
    gamma = clamp_gamma(gamma)

    if curve == "POWER":
        return max(0.0, min(1.0, t**gamma))

    if curve == "SCURVE":
        if t < 0.5:
            return max(0.0, min(1.0, 0.5 * (2.0 * t) ** gamma))
        return max(0.0, min(1.0, 1.0 - 0.5 * (2.0 * (1.0 - t)) ** gamma))

    return t


def normalize(raw: int, raw_min: int, raw_max: int) -> float:
    """Position within the calibrated range. Mirror of ``hb_normalize``.

    Handles inverted ranges: a cell wired with opposite polarity yields
    ``raw_max < raw_min`` and is still handled correctly.
    """
    span = float(raw_max) - float(raw_min)
    if span == 0.0:
        return 0.0
    return max(0.0, min(1.0, (float(raw) - float(raw_min)) / span))


def curve_points(curve: str, gamma: float, count: int = 64) -> list[list[float]]:
    """``[t, output]`` points for drawing the curve preview."""
    count = max(2, min(512, int(count)))
    step = 1.0 / (count - 1)
    return [
        [round(i * step, 6), round(apply_curve(curve, gamma, i * step), 6)]
        for i in range(count)
    ]
