"""Local server of the calibration app.

Listens on the loopback only: it is the support of a desktop interface, not a
network service. The link with the board is owned by a LinkManager (built and
started by __main__.py); this module only exposes it over HTTP.
"""

from __future__ import annotations

import json
import queue
import time
from pathlib import Path
from typing import Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from . import protocol
from .flash import FlashError, Flasher
from .lifecycle import KeepAlive
from .link import LinkError
from .manager import LinkManager

WEB_DIR = Path(__file__).parent / "web"

# Interval of the SSE keep-alive comments. Without them, an intermediary or
# the browser may close a connection that stayed silent.
SSE_KEEPALIVE_SECONDS = 1.0


def create_app(
    manager: LinkManager,
    keepalive: Optional[KeepAlive] = None,
    flasher: Optional[Flasher] = None,
) -> Flask:
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

    # --- Keep-alive ------------------------------------------------------------

    @app.get("/api/keepalive")
    def api_keepalive():
        if keepalive is None:
            return _error("keep-alive disabled", 503)
        keepalive.register()

        def events():
            try:
                while True:
                    yield ": keepalive\n\n"
                    time.sleep(SSE_KEEPALIVE_SECONDS)
            finally:
                # The client left (tab closed, server shutting down):
                # unregister so the lifecycle watchdog can fire.
                keepalive.unregister()

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Firmware ----------------------------------------------------------------

    @app.get("/api/firmware")
    def api_firmware():
        app_version = _app_version()
        link = manager.link
        board_version = (
            link.config.ver if (link is not None and link.config is not None)
            else None
        )
        if link is None:
            status = "not-connected"
        elif board_version is None:
            status = "board-unknown"  # older firmware, no ver field
        elif board_version == app_version:
            status = "up-to-date"
        else:
            status = "mismatch"
        return jsonify(
            {
                "app_version": app_version,
                "board_fw_version": board_version,
                "status": status,
            }
        )

    # --- Flash --------------------------------------------------------------------

    @app.post("/api/flash")
    def api_flash():
        if flasher is None:
            return _error("flash not available", 503)
        if manager.link is None:
            return _error("not connected", 409)
        if flasher.busy:
            return _error("flash in progress", 409)

        port = manager.status()["port"]
        manager.pause_for_flash()
        try:
            try:
                log = flasher.run(port)
            except FlashError as exc:
                return _error(str(exc), 502)
            return jsonify({"ok": True, "log": log})
        finally:
            # Success or failure: the manager takes the port back and
            # reconnects to the board once the bootloader has reset it.
            manager.resume_flash()

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

    @app.post("/api/alpha")
    def api_alpha():
        payload = request.get_json(silent=True) or {}
        try:
            alpha = protocol.clamp_alpha(float(payload.get("alpha")))
        except (TypeError, ValueError):
            return _error("invalid alpha")

        return _apply(manager, protocol.cmd_set_alpha(alpha))

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


def _app_version() -> str:
    """The app version from the generated _version.py, or "dev"."""
    try:
        from . import _version

        return _version.__version__
    except ImportError:
        return "dev"


def _apply(manager: LinkManager, command: str):
    """Sends a command and returns the resulting configuration."""
    if manager.link is None:
        return _error("not connected", 409)
    try:
        config = manager.request_config(command)
    except LinkError as exc:
        return _error(str(exc), 502)
    return jsonify({"config": config.as_dict()})
