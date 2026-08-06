"""Point d'entrée : lance le serveur local et ouvre l'interface.

La fenêtre native passe par pywebview, qui réutilise le moteur web du système
(WebKitGTK sous Linux, WebView2 sous Windows). Si pywebview est absent, l'app
bascule sur le navigateur par défaut plutôt que de refuser de démarrer.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

from .server import create_app

WINDOW_TITLE = "Calibration du handbrake"
WINDOW_SIZE = (1024, 720)


def _free_port() -> int:
    """Réserve un port libre attribué par le système.

    Un port fixe entrerait en conflit avec une autre instance ou un autre
    service ; laisser le système choisir évite d'avoir à en trouver un
    « probablement libre ».
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app, port: int) -> None:
    # threaded : le flux SSE occupe une connexion en continu, un serveur
    # mono-thread ne répondrait plus à rien d'autre pendant ce temps.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="handbrake-tuner",
        description="Calibration du handbrake de simracing.",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="port HTTP local (0 = automatique)"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="ouvrir dans le navigateur au lieu d'une fenêtre native",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="démarrer le serveur seul, sans ouvrir d'interface",
    )
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    app = create_app()
    url = f"http://127.0.0.1:{port}/"

    if args.no_window:
        print(f"Interface disponible sur {url}")
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
                "pywebview absent, ouverture dans le navigateur "
                "(pip install 'handbrake-tuner[desktop]' pour une fenêtre "
                "native).",
                file=sys.stderr,
            )

    print(f"Interface disponible sur {url}")
    webbrowser.open(url)
    try:
        server.join()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
