"""Entry point: starts the local server and opens the interface.

The native window goes through pywebview, which reuses the system web engine
(WebKitGTK on Linux, WebView2 on Windows). When pywebview is missing, the app
falls back to the default browser instead of refusing to start.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

from .link import connect as connect_board
from .link import list_ports
from .manager import LinkManager
from .server import create_app

WINDOW_TITLE = "Handbrake calibration"
WINDOW_SIZE = (1024, 720)


def _free_port() -> int:
    """Reserves a system-assigned free port.

    A fixed port would clash with another instance or service; letting the
    system pick avoids hunting for a "probably free" one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app, port: int) -> None:
    # threaded: the SSE stream holds a connection for its whole life; a
    # single-threaded server would stop answering anything else meanwhile.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loadcraft",
        description="Calibration app for the simracing handbrake.",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="local HTTP port (0 = automatic)"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="open in the browser instead of a native window",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="start the server alone, without opening an interface",
    )
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    manager = LinkManager(list_ports_fn=list_ports, connect_fn=connect_board)
    app = create_app(manager)
    url = f"http://127.0.0.1:{port}/"
    manager.start()

    if args.no_window:
        print(f"Interface available at {url}")
        _serve(app, port)
        return 0

    server = threading.Thread(target=_serve, args=(app, port), daemon=True)
    server.start()

    if not args.browser:
        try:
            import webview  # type: ignore

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
    try:
        server.join()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
