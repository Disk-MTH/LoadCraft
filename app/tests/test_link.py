"""Tests de la liaison série, contre une carte simulée."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from handbrake_tuner import protocol
from handbrake_tuner.link import LinkError, SerialLink
from handbrake_tuner.protocol import Ack, Config, Err, Telemetry


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- Dialogue de base ------------------------------------------------------


def test_request_ping(link):
    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_request_config(link, board):
    config = link.request_config(protocol.cmd_get())
    assert config.raw_min == board.raw_min
    assert config.raw_max == board.raw_max
    assert config.curve == "LINEAR"


def test_config_mise_a_jour_en_arriere_plan(link):
    link.request(protocol.cmd_get())
    assert wait_for(lambda: link.config is not None)
    assert isinstance(link.config, Config)


def test_commande_transmise_avec_saut_de_ligne(link, board):
    link.request(protocol.cmd_ping())
    assert board.received == ["PING"]


# --- Réponses en retard ----------------------------------------------------


def test_reponse_en_retard_ne_pollue_pas_la_suivante(link, board):
    """Une réponse arrivée après expiration ne doit pas être servie à la
    commande suivante : l'app afficherait alors l'effet de la mauvaise
    commande."""
    board.emit("OK PARASITE")
    assert wait_for(lambda: link._replies.qsize() > 0)

    reply = link.request(protocol.cmd_ping())
    assert reply == Ack("PING")


def test_absence_de_reponse_leve_une_erreur(board):
    class Muet:
        def write(self, data):
            pass

        def readline(self):
            time.sleep(0.01)
            return b""

        def close(self):
            pass

    connection = SerialLink(Muet())
    connection.start()
    try:
        with pytest.raises(LinkError, match="pas de réponse"):
            connection.request(protocol.cmd_ping(), timeout=0.2)
    finally:
        connection.close()


def test_request_config_redemande_apres_un_simple_ack(link, board):
    """SET MIN répond « OK », pas une configuration : la liaison doit aller
    la chercher pour que l'app reste à jour."""
    config = link.request_config(protocol.cmd_set_min(4242))
    assert config.raw_min == 4242
    assert board.received == ["SET MIN 4242", "GET"]


def test_request_config_propage_une_erreur(link, board):
    with pytest.raises(LinkError, match="unknown command"):
        link.request_config("COMMANDE INCONNUE")


# --- Télémétrie ------------------------------------------------------------


def test_telemetrie_alimente_l_etat(link, board):
    board.emit_telemetry(500000)
    assert wait_for(lambda: link.telemetry is not None)
    assert link.telemetry.raw == 500000


def test_telemetrie_n_est_pas_prise_pour_une_reponse(link, board):
    """La télémétrie arrive en continu : si elle passait par la file des
    réponses, chaque commande recevrait une mesure au lieu de son accusé."""
    board.emit_telemetry(111111)
    board.emit_telemetry(222222)
    assert wait_for(lambda: link.telemetry is not None)

    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_abonnement(link, board):
    subscription = link.subscribe()
    board.emit_telemetry(123456)

    message = subscription.get(timeout=2.0)
    assert isinstance(message, Telemetry)
    assert message.raw == 123456

    link.unsubscribe(subscription)
    board.emit_telemetry(999999)
    time.sleep(0.1)
    with pytest.raises(queue.Empty):
        subscription.get_nowait()


def test_abonne_lent_perd_les_anciennes_mesures(link, board):
    """Un abonné qui ne suit pas ne doit pas faire grossir la file sans fin :
    les mesures les plus anciennes sont abandonnées."""
    subscription = link.subscribe()
    for i in range(40):
        board.emit_telemetry(100000 + i)

    assert wait_for(lambda: subscription.full())
    time.sleep(0.2)
    assert subscription.qsize() <= subscription.maxsize


def test_plusieurs_abonnes(link, board):
    first, second = link.subscribe(), link.subscribe()
    board.emit_telemetry(424242)

    assert first.get(timeout=2.0).raw == 424242
    assert second.get(timeout=2.0).raw == 424242


# --- Erreurs ---------------------------------------------------------------


def test_erreur_memorisee(link, board):
    link.request("COMMANDE INCONNUE")
    assert wait_for(lambda: link.last_error is not None)
    assert link.last_error == "unknown command"


def test_ecriture_sur_port_ferme(link, board):
    board.close()
    with pytest.raises(LinkError, match="écriture impossible"):
        link.send(protocol.cmd_ping())


def test_fermeture_idempotente(board):
    connection = SerialLink(board)
    connection.start()
    connection.close()
    connection.close()  # ne doit pas lever


def test_lignes_parasites_ignorees(link, board):
    """Un port série délivre des octets parasites à l'ouverture. Ils ne
    doivent ni faire tomber le thread de lecture, ni être pris pour des
    réponses."""
    board.emit_raw(b"\x00\xff bruit\n")
    board.emit("")
    board.emit("pas une commande connue")

    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_thread_survit_a_une_erreur_de_lecture():
    class Cassé:
        def __init__(self):
            self.calls = 0

        def write(self, data):
            pass

        def readline(self):
            self.calls += 1
            raise OSError("carte débranchée")

        def close(self):
            pass

    transport = Cassé()
    connection = SerialLink(transport)
    connection.start()
    try:
        assert wait_for(lambda: connection.last_error is not None)
        assert "débranchée" in connection.last_error
    finally:
        connection.close()
