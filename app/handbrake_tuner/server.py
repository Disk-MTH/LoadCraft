"""Local server of the calibration app.

Listens on the loopback only: it is the support of a desktop interface, not a
network service. The link with the board is owned by a LinkManager (built and
started by __main__.py); this module only exposes it over HTTP.
"""

from __future__ import annotations

import json
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import protocol
from .link import LinkError
from .manager import LinkManager

WEB_DIR = Path(__file__).parent / "web"

# Interval of the SSE keep-alive comments. Without them, an intermediary or
# the browser may close a connection that stayed silent.
SSE_KEEPALIVE_SECONDS = 1.0


def create_app(manager: LinkManager) -> Flask:
    app = Flask(__name__, static_folder=None)

    # --- Interface ---------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    # --- Status ------------------------------------------------------------

    @app.get("/api/status")
    def api_status():
        return jsonify(manager.status())

    # --- Telemetry ---------------------------------------------------------

    @app.get("/api/stream")
    def api_stream():
        current = manager.link
        if current is None:
            return _error("not connected", 409)

        subscription = current.subscribe()

        def events():
            try:
                while True:
                    # The manager replaced the link (board unplugged then
                    # back): stop, so the client's EventSource reconnects
                    # and re-subscribes to the new link.
                    if manager.link is not current:
                        break
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
            return _error("unknown bound")

        payload = request.get_json(silent=True) or {}
        value = payload.get("value")
        if value is None:
            return _error("value required")
        try:
            value = int(value)
        except (TypeError, ValueError):
            return _error("invalid value")

        builder = protocol.cmd_set_min if bound == "min" else protocol.cmd_set_max
        return _apply(manager, builder(value))

    @app.post("/api/curve")
    def api_curve():
        payload = request.get_json(silent=True) or {}
        curve = str(payload.get("curve") or "").upper()
        if curve not in protocol.CURVES:
            return _error("unknown curve")

        gamma = payload.get("gamma")
        if gamma is not None:
            try:
                gamma = protocol.clamp_gamma(float(gamma))
            except (TypeError, ValueError):
                return _error("invalid gamma")

        return _apply(manager, protocol.cmd_set_curve(curve, gamma))

    @app.post("/api/gamma")
    def api_gamma():
        payload = request.get_json(silent=True) or {}
        try:
            gamma = protocol.clamp_gamma(float(payload.get("gamma")))
        except (TypeError, ValueError):
            return _error("invalid gamma")

        return _apply(manager, protocol.cmd_set_gamma(gamma))

    @app.post("/api/<any(save,load,reset):action>")
    def api_action(action: str):
        builder = {
            "save": protocol.cmd_save,
            "load": protocol.cmd_load,
            "reset": protocol.cmd_reset,
        }[action]
        return _apply(manager, builder())

    # --- Curve preview -----------------------------------------------------

    @app.get("/api/curve/preview")
    def api_curve_preview():
        curve = str(request.args.get("curve", "LINEAR")).upper()
        if curve not in protocol.CURVES:
            return _error("unknown curve")

        try:
            gamma = protocol.clamp_gamma(float(request.args.get("gamma", 1.0)))
        except (TypeError, ValueError):
            return _error("invalid gamma")

        return jsonify(
            {
                "curve": curve,
                "gamma": gamma,
                "points": protocol.curve_points(curve, gamma),
            }
        )

    return app


# --- Utilities ---------------------------------------------------------------


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


def _apply(manager: LinkManager, command: str):
    """Sends a command and returns the resulting configuration."""
    if manager.link is None:
        return _error("not connected", 409)
    try:
        config = manager.request_config(command)
    except LinkError as exc:
        return _error(str(exc), 502)
    return jsonify({"config": config.as_dict()})
