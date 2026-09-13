"""Protocole série du handbrake, côté hôte.

Miroir de ``firmware/handbrake/hb_protocol.c``. Volontairement sans état et
sans entrée/sortie : tout ce qui peut être faux dans l'échange avec la carte
est testable sans carte.

Les courbes sont réimplémentées ici plutôt que demandées au firmware, pour que
l'aperçu affiché dans l'app corresponde exactement à ce que le firmware
calcule. ``tests/test_curve.py`` vérifie les mêmes propriétés que les tests C.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# Doivent rester alignées sur firmware/handbrake/hb_core.h
AXIS_MAX = 1023
GAMMA_MIN = 0.10
GAMMA_MAX = 5.00
CURVES = ("LINEAR", "POWER", "SCURVE")


@dataclass(frozen=True)
class Config:
    """Configuration renvoyée par la carte (ligne ``CFG …``)."""

    raw_min: int
    raw_max: int
    curve: str
    gamma: float
    calibrated: bool

    def as_dict(self) -> dict:
        return {
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "curve": self.curve,
            "gamma": self.gamma,
            "calibrated": self.calibrated,
        }


@dataclass(frozen=True)
class Telemetry:
    """Mesure temps réel (ligne ``T …``)."""

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


# --- Analyse ---------------------------------------------------------------


def _fields(parts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep:
            out[key] = value
    return out


def parse_line(line: str) -> Optional[Message]:
    """Analyse une ligne reçue de la carte.

    Renvoie ``None`` pour une ligne vide ou non reconnue. Le port série
    délivre des octets parasites à l'ouverture et pendant le redémarrage de la
    carte : les ignorer est plus sûr que de lever une exception dans le thread
    de lecture.
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


# --- Construction des commandes -------------------------------------------


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
        raise ValueError(f"courbe inconnue: {curve}")
    if gamma is None:
        return f"SET CURVE {curve}"
    return f"SET CURVE {curve} {_fmt_gamma(gamma)}"


def cmd_set_gamma(gamma: float) -> str:
    return f"SET GAMMA {_fmt_gamma(gamma)}"


def _fmt_gamma(gamma: float) -> str:
    return f"{float(gamma):.3f}"


# --- Courbes ---------------------------------------------------------------


def clamp_gamma(gamma: float) -> float:
    """Applique les mêmes bornes que ``hb_config_sanitize``."""
    try:
        gamma = float(gamma)
    except (TypeError, ValueError):
        return 1.0
    if gamma != gamma:  # NaN
        return 1.0
    return max(GAMMA_MIN, min(GAMMA_MAX, gamma))


def apply_curve(curve: str, gamma: float, t: float) -> float:
    """Courbe de réponse. Miroir de ``hb_curve_apply``."""
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
    """Position dans la plage calibrée. Miroir de ``hb_normalize``.

    Gère les plages inversées : une cellule câblée en polarité opposée donne
    ``raw_max < raw_min`` et reste correctement traitée.
    """
    span = float(raw_max) - float(raw_min)
    if span == 0.0:
        return 0.0
    return max(0.0, min(1.0, (float(raw) - float(raw_min)) / span))


def curve_points(curve: str, gamma: float, count: int = 64) -> list[list[float]]:
    """Points ``[t, sortie]`` pour tracer l'aperçu de la courbe."""
    count = max(2, min(512, int(count)))
    step = 1.0 / (count - 1)
    return [
        [round(i * step, 6), round(apply_curve(curve, gamma, i * step), 6)]
        for i in range(count)
    ]
