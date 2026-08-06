"""Serveur local de l'app de calibration.

N'écoute que sur la boucle locale : c'est un support d'interface pour une
application de bureau, pas un service réseau.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from . import link as link_module
from . import protocol
from .link import LinkError, SerialLink

WEB_DIR = Path(__file__).parent / "web"

# Intervalle des commentaires de maintien du flux SSE. Sans eux, un
# intermédiaire ou le navigateur peut clore une connexion restée muette.
SSE_KEEPALIVE_SECONDS = 1.0


class TunerState:
    """Liaison courante, partagée par les requêtes HTTP."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._link: Optional[SerialLink] = None

    @property
    def link(self) -> Optional[SerialLink]:
        with self._lock:
            return self._link

    def attach(self, new_link: SerialLink) -> None:
        with self._lock:
            previous, self._link = self._link, new_link
        if previous is not None:
            previous.close()

    def detach(self) -> None:
        with self._lock:
            previous, self._link = self._link, None
        if previous is not None:
            previous.close()


def create_app(
    state: Optional[TunerState] = None,
    connect_fn: Optional[Callable[[str], SerialLink]] = None,
    list_ports_fn: Optional[Callable[[], list]] = None,
) -> Flask:
    """Construit l'application.

    Les accès au matériel passent par des fonctions injectables : les tests
    couvrent toute l'API sans carte branchée.
    """
    state = state or TunerState()
    connect_fn = connect_fn or link_module.connect
    list_ports_fn = list_ports_fn or link_module.list_ports

    app = Flask(__name__, static_folder=None)
    app.config["TUNER_STATE"] = state

    # --- Interface ---------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    # --- Connexion ---------------------------------------------------------

    @app.get("/api/ports")
    def api_ports():
        return jsonify({"ports": list_ports_fn()})

    @app.post("/api/connect")
    def api_connect():
        payload = request.get_json(silent=True) or {}
        port = str(payload.get("port") or "").strip()
        if not port:
            return _error("port manquant")

        try:
            new_link = connect_fn(port)
        except LinkError as exc:
            return _error(str(exc), 502)

        state.attach(new_link)
        return jsonify(_status(state))

    @app.post("/api/disconnect")
    def api_disconnect():
        current = state.link
        if current is not None:
            try:
                current.send(protocol.cmd_stream(False))
            except LinkError:
                # La carte a pu être débranchée : la déconnexion doit aboutir
                # quoi qu'il arrive, sinon l'app reste bloquée sur un port mort.
                pass
        state.detach()
        return jsonify(_status(state))

    @app.get("/api/status")
    def api_status():
        return jsonify(_status(state))

    # --- Télémétrie --------------------------------------------------------

    @app.get("/api/stream")
    def api_stream():
        current = state.link
        if current is None:
            return _error("non connecté", 409)

        subscription = current.subscribe()

        def events():
            try:
                while True:
                    try:
                        message = subscription.get(
                            timeout=SSE_KEEPALIVE_SECONDS
                        )
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(message.as_dict())}\n\n"
            finally:
                current.unsubscribe(subscription)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Calibration -------------------------------------------------------

    @app.post("/api/calibrate/<string:bound>")
    def api_calibrate(bound: str):
        if bound not in ("min", "max"):
            return _error("borne inconnue")

        current = state.link
        if current is None:
            return _error("non connecté", 409)

        payload = request.get_json(silent=True) or {}
        value = payload.get("value")
        if value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                return _error("valeur invalide")

        builder = protocol.cmd_set_min if bound == "min" else protocol.cmd_set_max
        return _apply(current, builder(value))

    @app.post("/api/curve")
    def api_curve():
        current = state.link
        if current is None:
            return _error("non connecté", 409)

        payload = request.get_json(silent=True) or {}
        curve = str(payload.get("curve") or "").upper()
        if curve not in protocol.CURVES:
            return _error("courbe inconnue")

        gamma = payload.get("gamma")
        if gamma is not None:
            try:
                gamma = protocol.clamp_gamma(float(gamma))
            except (TypeError, ValueError):
                return _error("gamma invalide")

        return _apply(current, protocol.cmd_set_curve(curve, gamma))

    @app.post("/api/gamma")
    def api_gamma():
        current = state.link
        if current is None:
            return _error("non connecté", 409)

        payload = request.get_json(silent=True) or {}
        try:
            gamma = protocol.clamp_gamma(float(payload.get("gamma")))
        except (TypeError, ValueError):
            return _error("gamma invalide")

        return _apply(current, protocol.cmd_set_gamma(gamma))

    @app.post("/api/<any(save,load,reset):action>")
    def api_action(action: str):
        current = state.link
        if current is None:
            return _error("non connecté", 409)

        builder = {
            "save": protocol.cmd_save,
            "load": protocol.cmd_load,
            "reset": protocol.cmd_reset,
        }[action]
        return _apply(current, builder())

    # --- Aperçu de courbe --------------------------------------------------

    @app.get("/api/curve/preview")
    def api_curve_preview():
        curve = str(request.args.get("curve", "LINEAR")).upper()
        if curve not in protocol.CURVES:
            return _error("courbe inconnue")

        try:
            gamma = protocol.clamp_gamma(float(request.args.get("gamma", 1.0)))
        except (TypeError, ValueError):
            return _error("gamma invalide")

        return jsonify(
            {
                "curve": curve,
                "gamma": gamma,
                "points": protocol.curve_points(curve, gamma),
            }
        )

    return app


# --- Utilitaires -----------------------------------------------------------


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


def _apply(current: SerialLink, command: str):
    """Envoie une commande et renvoie la configuration qui en résulte."""
    try:
        config = current.request_config(command)
    except LinkError as exc:
        return _error(str(exc), 502)
    return jsonify({"config": config.as_dict()})


def _status(state: TunerState) -> dict:
    current = state.link
    if current is None:
        return {"connected": False, "port": None, "config": None, "telemetry": None}

    config = current.config
    telemetry = current.telemetry
    return {
        "connected": True,
        "port": current.port,
        "config": config.as_dict() if config else None,
        "telemetry": telemetry.as_dict() if telemetry else None,
        "axis_max": protocol.AXIS_MAX,
        "gamma_min": protocol.GAMMA_MIN,
        "gamma_max": protocol.GAMMA_MAX,
    }
