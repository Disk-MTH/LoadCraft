"""Carte simulée : transport série factice pour tester sans matériel."""

from __future__ import annotations

import queue
import threading

from handbrake_tuner import protocol


class FakeBoard:
    """Carte simulée : rejoue la logique de réponse du firmware.

    Assez fidèle pour valider le dialogue (ordre des réponses, effet des
    commandes sur la configuration), sans prétendre remplacer un essai réel.
    """

    def __init__(self, calibrated: bool = True):
        self.raw_min = 100000
        self.raw_max = 900000
        self.curve = "LINEAR"
        self.gamma = 1.0
        self.calibrated = calibrated
        self.current_raw = 500000
        self.streaming = False
        self.saved = None
        self.received: list[str] = []

        self._out: "queue.Queue[bytes]" = queue.Queue()
        self._closed = threading.Event()

    # --- Interface transport ---------------------------------------------

    def write(self, data: bytes) -> None:
        if self._closed.is_set():
            raise OSError("port fermé")
        for line in data.decode("ascii").splitlines():
            line = line.strip()
            if line:
                self.received.append(line)
                self._handle(line)

    def readline(self) -> bytes:
        if self._closed.is_set():
            raise OSError("port closed")
        try:
            return self._out.get(timeout=0.05)
        except queue.Empty:
            return b""

    def close(self) -> None:
        self._closed.set()

    # --- Émission ---------------------------------------------------------

    def emit(self, line: str) -> None:
        self._out.put((line + "\n").encode("ascii"))

    def emit_raw(self, data: bytes) -> None:
        """Émet des octets bruts, y compris non ASCII.

        Une vraie carte en délivre à l'ouverture du port et pendant son
        redémarrage : la liaison doit y survivre.
        """
        self._out.put(data)

    def emit_config(self) -> None:
        self.emit(
            f"CFG min={self.raw_min} max={self.raw_max} curve={self.curve} "
            f"gamma={self.gamma:.3f} calibrated={1 if self.calibrated else 0}"
        )

    def emit_telemetry(self, raw: int | None = None) -> None:
        raw = self.current_raw if raw is None else raw
        t = protocol.normalize(raw, self.raw_min, self.raw_max)
        out = protocol.apply_curve(self.curve, self.gamma, t)
        self.emit(f"T raw={raw} out={out:.3f} axis={round(out * protocol.AXIS_MAX)}")

    # --- Réponses ---------------------------------------------------------

    def _handle(self, line: str) -> None:
        parts = line.split()
        head = parts[0].upper()

        if head == "PING":
            self.emit("OK PING")
        elif head == "GET":
            self.emit_config()
        elif head == "STREAM":
            self.streaming = parts[1] == "1"
            self.emit(f"OK STREAM {parts[1]}")
        elif head == "SAVE":
            self.saved = (self.raw_min, self.raw_max, self.curve, self.gamma)
            self.emit("OK SAVE")
        elif head == "LOAD":
            if self.saved:
                self.raw_min, self.raw_max, self.curve, self.gamma = self.saved
            self.emit_config()
        elif head == "RESET":
            self.raw_min, self.raw_max = 0, 8000000
            self.curve, self.gamma, self.calibrated = "LINEAR", 1.0, False
            self.emit_config()
        elif head == "SET":
            self._handle_set(parts)
        else:
            self.emit("ERR unknown command")

    def _handle_set(self, parts: list[str]) -> None:
        target = parts[1].upper()

        if target in ("MIN", "MAX"):
            value = int(parts[2]) if len(parts) > 2 else self.current_raw
            if target == "MIN":
                self.raw_min = value
            else:
                self.raw_max = value
            self.calibrated = True
            self.emit(f"OK SET {target} {value}")
        elif target == "CURVE":
            self.curve = parts[2].upper()
            if len(parts) > 3:
                self.gamma = float(parts[3])
            self.emit_config()
        elif target == "GAMMA":
            self.gamma = float(parts[2])
            self.emit_config()
        else:
            self.emit("ERR unknown command")
