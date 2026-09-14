"""Entry point: starts the local server and opens the interface.

The default interface is the user's browser, on both Windows and Linux.
The process lives as long as the interface does: closing the tab ends the
app (see lifecycle.py). The native window (pywebview, `[desktop]` extra)
remains available with --window for development.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from .flash import Flasher
from .lifecycle import KeepAlive
from .link import connect as connect_board
from .link import list_ports
from .manager import LinkManager
from .server import create_app

WINDOW_TITLE = "LoadCraft"
WINDOW_SIZE = (1024, 720)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loadcraft",
        description="LoadCraft calibration app.",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="local HTTP port (0 = automatic)"
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="open a native window instead of the browser "
        "(needs the 'desktop' extra)",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="start the server alone: no interface is opened and the app "
        "never auto-exits",
    )
    return parser


def _free_port() -> int:
    """Reserves a system-assigned free port.

    A fixed port would clash with another instance or service; letting the
    system pick avoids hunting for a "probably free" one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app, port: int) -> None:
    # threaded: the SSE streams hold a connection for its whole life; a
    # single-threaded server would stop answering anything else meanwhile.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


class _Tee:
    """Writes to two streams: the console (when there is one) and the log."""

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def write(self, data) -> None:
        self._primary.write(data)
        try:
            self._secondary.write(data)
            self._secondary.flush()
        except Exception:
            pass

    def flush(self) -> None:
        self._primary.flush()


def _attach_startup_log() -> None:
    """Packaged builds have no console: mirror stdout/stderr to a log file.

    Without this, a failed start (port bind, crash) would show up in the
    browser as a bare "connection refused" with nothing to diagnose.
    """
    try:
        log = open(
            Path(tempfile.gettempdir()) / "loadcraft.log", "a", encoding="utf-8"
        )
    except OSError:
        return
    sys.stdout = _Tee(sys.stdout, log)
    sys.stderr = _Tee(sys.stderr, log)


def main(argv: list[str] | None = None) -> int:
    _attach_startup_log()
    args = build_parser().parse_args(argv)

    port = args.port or _free_port()
    manager = LinkManager(list_ports_fn=list_ports, connect_fn=connect_board)

    # The keep-alive watchdog exits the process when the last UI client is
    # gone. Window mode does not use it: webview.start() blocks until the
    # window closes, which is the lifecycle there.
    keepalive = None
    if not args.no_window and not args.window:

        def shutdown() -> None:
            manager.stop()
            os._exit(0)  # watchdog thread: sys.exit would end only it

        keepalive = KeepAlive(exit_fn=shutdown)
        keepalive.start()

    app = create_app(manager, keepalive=keepalive, flasher=Flasher())
    url = f"http://127.0.0.1:{port}/"
    manager.start()

    if args.no_window:
        print(f"Interface available at {url}")
        _serve(app, port)
        return 0

    server = threading.Thread(
        target=_serve, args=(app, port), daemon=True
    )
    server.start()

    if args.window:
        try:
            import webview

            window = webview.create_window(
                WINDOW_TITLE, url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1]
            )
            webview.start()
            del window
            return 0
        except ImportError:
            print(
                "pywebview missing, opening in the browser "
                "(pip install 'loadcraft[desktop]' for a native window).",
                file=sys.stderr,
            )

    print(f"Interface available at {url}")
    webbrowser.open(url)

    # The browser keeps the app alive through /api/keepalive: closing the
    # tab ends the process from the watchdog thread after the grace period.
    try:
        server.join()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
