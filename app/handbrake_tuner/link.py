"""Liaison série avec la carte.

Le transport est injecté plutôt que créé ici : les tests fournissent un faux
transport et couvrent toute la logique de dialogue sans matériel ni pyserial.
"""

from __future__ import annotations

import queue
import threading
from typing import List, Optional

from . import protocol
from .protocol import Ack, Config, Err, Telemetry

# Vitesse ignorée par un port CDC (le débit est celui de l'USB), présente par
# convention et parce que pyserial exige une valeur.
BAUDRATE = 115200

# Le firmware répond immédiatement ; au-delà, c'est que la carte ne parle pas
# ce protocole ou a redémarré.
REPLY_TIMEOUT = 2.0

# Au-delà de cette taille, un abonné SSE ne suit plus : ses évènements les plus
# anciens sont abandonnés plutôt que de faire grossir la file sans fin.
SUBSCRIBER_QUEUE_SIZE = 8


class LinkError(RuntimeError):
    """Échec de dialogue avec la carte."""


class SerialLink:
    """Dialogue avec la carte : thread de lecture, envoi de commandes.

    Le thread de lecture trie les lignes reçues : la télémétrie alimente
    l'état courant et les abonnés, tout le reste part dans la file de réponses
    attendue par :meth:`request`.
    """

    def __init__(self, transport, port: str = ""):
        self._transport = transport
        self.port = port
        self._lock = threading.Lock()
        self._config: Optional[Config] = None
        self._telemetry: Optional[Telemetry] = None
        self._last_error: Optional[str] = None
        self._replies: "queue.Queue" = queue.Queue()
        self._subscribers: List["queue.Queue"] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- Cycle de vie ------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop, name="handbrake-serial", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._transport.close()
        except Exception:
            # Le port peut déjà avoir disparu (carte débranchée) : la
            # fermeture doit rester sans conséquence.
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)

    # --- État --------------------------------------------------------------

    @property
    def config(self) -> Optional[Config]:
        with self._lock:
            return self._config

    @property
    def telemetry(self) -> Optional[Telemetry]:
        with self._lock:
            return self._telemetry

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    # --- Envoi -------------------------------------------------------------

    def send(self, command: str) -> None:
        try:
            self._transport.write((command + "\n").encode("ascii"))
        except Exception as exc:
            raise LinkError(f"écriture impossible : {exc}") from exc

    def request(self, command: str, timeout: float = REPLY_TIMEOUT) -> object:
        """Envoie une commande et attend la réponse correspondante.

        Les réponses en attente sont vidées avant l'envoi : sinon la réponse
        d'une commande précédente arrivée en retard serait prise pour celle-ci.
        """
        while True:
            try:
                self._replies.get_nowait()
            except queue.Empty:
                break

        self.send(command)

        try:
            return self._replies.get(timeout=timeout)
        except queue.Empty:
            raise LinkError(f"pas de réponse à « {command} »") from None

    def request_config(self, command: str) -> Config:
        """Envoie une commande dont la réponse attendue est une ``CFG``."""
        reply = self.request(command)
        if isinstance(reply, Config):
            return reply
        if isinstance(reply, Err):
            raise LinkError(reply.reason)
        # Certaines commandes accusent réception sans renvoyer la
        # configuration : on la redemande pour que l'app reste à jour.
        reply = self.request(protocol.cmd_get())
        if isinstance(reply, Config):
            return reply
        raise LinkError("configuration illisible")

    # --- Abonnements SSE ---------------------------------------------------

    def subscribe(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    # --- Thread de lecture -------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._transport.readline()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                break

            if not raw:
                continue  # délai d'attente écoulé, rien à lire

            try:
                line = raw.decode("ascii", errors="replace")
            except Exception:
                continue

            self._dispatch(protocol.parse_line(line))

    def _dispatch(self, message) -> None:
        if message is None:
            return

        if isinstance(message, Telemetry):
            with self._lock:
                self._telemetry = message
                subscribers = list(self._subscribers)
            for q in subscribers:
                _offer(q, message)
            return

        if isinstance(message, Config):
            with self._lock:
                self._config = message
        elif isinstance(message, Err):
            with self._lock:
                self._last_error = message.reason

        # Config, Ack et Err sont toutes des réponses à une commande.
        self._replies.put(message)


def _offer(q: "queue.Queue", item) -> None:
    """Dépose sans jamais bloquer, en abandonnant le plus ancien si besoin."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except (queue.Empty, queue.Full):
            pass


# --- Transport réel --------------------------------------------------------


def _describe(port) -> dict:
    label = port.description or ""
    if port.vid is not None and port.pid is not None:
        label = f"{label} [{port.vid:04X}:{port.pid:04X}]".strip()
    return {
        "device": port.device,
        "description": label,
        "hwid": port.hwid or "",
        "usb": port.vid is not None,
    }


def list_ports() -> List[dict]:
    """Ports série disponibles.

    Seuls les ports USB sont retenus : sous Linux, pyserial énumère aussi la
    trentaine de ports 8250 hérités (``/dev/ttyS*``), qui noieraient la carte
    dans une liste où elle est introuvable. Un handbrake est par construction
    un périphérique USB.

    Si aucun port USB n'est détecté, la liste complète est renvoyée plutôt
    qu'une liste vide : mieux vaut un choix encombré qu'aucun choix.

    pyserial est importé ici et non au chargement du module : les tests
    tournent sans lui, et l'app reste diagnosticable s'il manque.
    """
    try:
        from serial.tools import list_ports as _list_ports
    except ImportError:
        return []

    ports = [_describe(p) for p in _list_ports.comports()]
    usb_ports = [p for p in ports if p["usb"]]
    return sorted(usb_ports or ports, key=lambda p: p["device"])


def open_serial(port: str, timeout: float = 0.2):
    """Ouvre un port série réel."""
    try:
        import serial
    except ImportError as exc:
        raise LinkError(
            "pyserial n'est pas installé (pip install pyserial)"
        ) from exc

    try:
        return serial.Serial(port=port, baudrate=BAUDRATE, timeout=timeout)
    except Exception as exc:
        raise LinkError(f"ouverture de {port} impossible : {exc}") from exc


def connect(port: str) -> SerialLink:
    """Ouvre le port, démarre la lecture et récupère la configuration."""
    link = SerialLink(open_serial(port), port=port)
    link.start()
    try:
        config = link.request_config(protocol.cmd_get())
        if config is None:
            raise LinkError("la carte n'a pas répondu")
        link.send(protocol.cmd_stream(True))
    except Exception:
        link.close()
        raise
    return link
