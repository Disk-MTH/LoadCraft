"""Tests de l'API HTTP, contre une carte simulée."""

from __future__ import annotations

import time

import pytest

from handbrake_tuner.link import LinkError, SerialLink
from handbrake_tuner.server import TunerState, create_app

from fake_board import FakeBoard


@pytest.fixture
def wired():
    """App + carte simulée, non connectée au départ."""
    board = FakeBoard()
    state = TunerState()
    opened = []

    def connect_fn(port: str) -> SerialLink:
        if port == "/dev/absent":
            raise LinkError("ouverture de /dev/absent impossible")
        connection = SerialLink(board, port=port)
        connection.start()
        connection.request_config("GET")
        opened.append(connection)
        return connection

    def list_ports_fn():
        return [{"device": "/dev/fake0", "description": "Pro Micro", "hwid": "x"}]

    app = create_app(state=state, connect_fn=connect_fn, list_ports_fn=list_ports_fn)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, board, state

    state.detach()
    for connection in opened:
        connection.close()


@pytest.fixture
def connected(wired):
    client, board, state = wired
    response = client.post("/api/connect", json={"port": "/dev/fake0"})
    assert response.status_code == 200
    return client, board, state


# --- Interface -------------------------------------------------------------


def test_page_servie(wired):
    client, _, _ = wired
    response = client.get("/")
    assert response.status_code == 200
    assert b"Calibration du handbrake" in response.data


# --- Connexion -------------------------------------------------------------


def test_liste_des_ports(wired):
    client, _, _ = wired
    response = client.get("/api/ports")
    assert response.status_code == 200
    assert response.json["ports"][0]["device"] == "/dev/fake0"


def test_statut_hors_connexion(wired):
    client, _, _ = wired
    body = client.get("/api/status").json
    assert body["connected"] is False
    assert body["config"] is None


def test_connexion(wired):
    client, board, _ = wired
    body = client.post("/api/connect", json={"port": "/dev/fake0"}).json
    assert body["connected"] is True
    assert body["port"] == "/dev/fake0"
    assert body["config"]["raw_min"] == board.raw_min


def test_connexion_sans_port(wired):
    client, _, _ = wired
    response = client.post("/api/connect", json={})
    assert response.status_code == 400
    assert "port" in response.json["error"]


def test_connexion_impossible(wired):
    client, _, _ = wired
    response = client.post("/api/connect", json={"port": "/dev/absent"})
    assert response.status_code == 502
    assert "impossible" in response.json["error"]


def test_deconnexion(connected):
    client, board, _ = connected
    body = client.post("/api/disconnect").json
    assert body["connected"] is False
    assert "STREAM 0" in board.received


def test_deconnexion_hors_connexion(wired):
    """Se déconnecter sans être connecté doit aboutir sans erreur, sinon
    l'app peut rester bloquée sur un port mort."""
    client, _, _ = wired
    assert client.post("/api/disconnect").status_code == 200


def test_attacher_remplace_et_ferme_la_precedente():
    """Une liaison remplacée doit être fermée, sinon son thread de lecture
    continue de tourner et garde le port ouvert."""
    state = TunerState()
    first = SerialLink(FakeBoard(), port="/dev/fake0")
    second = SerialLink(FakeBoard(), port="/dev/fake1")
    first.start()
    second.start()

    state.attach(first)
    state.attach(second)
    try:
        assert state.link is second
        assert first._thread is None  # fermée
    finally:
        state.detach()
        first.close()
        second.close()


# --- Commandes hors connexion ---------------------------------------------


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/calibrate/min", {}),
        ("post", "/api/calibrate/max", {}),
        ("post", "/api/curve", {"curve": "POWER"}),
        ("post", "/api/gamma", {"gamma": 2.0}),
        ("post", "/api/save", {}),
        ("post", "/api/load", {}),
        ("post", "/api/reset", {}),
        ("get", "/api/stream", None),
    ],
)
def test_commandes_refusees_hors_connexion(wired, method, path, payload):
    client, _, _ = wired
    response = getattr(client, method)(path, json=payload) if payload is not None \
        else getattr(client, method)(path)
    assert response.status_code == 409
    assert response.json["error"] == "non connecté"


# --- Calibration -----------------------------------------------------------


def test_calibration_minimum(connected):
    client, board, _ = connected
    board.current_raw = 123456

    body = client.post("/api/calibrate/min").json
    assert body["config"]["raw_min"] == 123456
    assert "SET MIN" in board.received


def test_calibration_maximum(connected):
    client, board, _ = connected
    board.current_raw = 888888

    body = client.post("/api/calibrate/max").json
    assert body["config"]["raw_max"] == 888888


def test_calibration_valeur_explicite(connected):
    client, board, _ = connected
    body = client.post("/api/calibrate/min", json={"value": 4242}).json
    assert body["config"]["raw_min"] == 4242
    assert "SET MIN 4242" in board.received


def test_calibration_valeur_invalide(connected):
    client, _, _ = connected
    response = client.post("/api/calibrate/min", json={"value": "beaucoup"})
    assert response.status_code == 400


def test_calibration_borne_inconnue(connected):
    client, _, _ = connected
    assert client.post("/api/calibrate/milieu").status_code == 400


# --- Courbe ----------------------------------------------------------------


def test_changement_de_courbe(connected):
    client, board, _ = connected
    body = client.post("/api/curve", json={"curve": "SCURVE", "gamma": 1.8}).json
    assert body["config"]["curve"] == "SCURVE"
    assert body["config"]["gamma"] == pytest.approx(1.8)


def test_courbe_insensible_a_la_casse(connected):
    client, _, _ = connected
    body = client.post("/api/curve", json={"curve": "power"}).json
    assert body["config"]["curve"] == "POWER"


def test_courbe_inconnue_refusee(connected):
    client, _, _ = connected
    response = client.post("/api/curve", json={"curve": "PARABOLE"})
    assert response.status_code == 400


def test_gamma(connected):
    client, _, _ = connected
    body = client.post("/api/gamma", json={"gamma": 2.5}).json
    assert body["config"]["gamma"] == pytest.approx(2.5)


def test_gamma_borne_avant_envoi(connected):
    """Le firmware borne déjà, mais borner ici évite d'envoyer une valeur que
    la carte va corriger en silence — l'app afficherait autre chose que ce
    qui s'applique."""
    client, board, _ = connected
    body = client.post("/api/gamma", json={"gamma": 999}).json
    assert body["config"]["gamma"] == pytest.approx(5.0)


def test_gamma_invalide(connected):
    client, _, _ = connected
    assert client.post("/api/gamma", json={"gamma": "beaucoup"}).status_code == 400
    assert client.post("/api/gamma", json={}).status_code == 400


# --- Persistance -----------------------------------------------------------


def test_sauvegarde(connected):
    client, board, _ = connected
    client.post("/api/calibrate/min", json={"value": 1111})
    assert client.post("/api/save").status_code == 200
    assert board.saved is not None
    assert board.saved[0] == 1111


def test_rechargement_annule_les_modifications_non_sauvees(connected):
    client, board, _ = connected
    client.post("/api/calibrate/min", json={"value": 1111})
    client.post("/api/save")

    client.post("/api/calibrate/min", json={"value": 9999})
    body = client.post("/api/load").json
    assert body["config"]["raw_min"] == 1111


def test_reinitialisation(connected):
    client, _, _ = connected
    body = client.post("/api/reset").json
    assert body["config"]["calibrated"] is False
    assert body["config"]["curve"] == "LINEAR"


# --- Aperçu de courbe ------------------------------------------------------


def test_apercu_de_courbe(wired):
    """L'aperçu ne dépend pas de la carte : on doit pouvoir comparer les
    courbes avant même de brancher quoi que ce soit."""
    client, _, _ = wired
    body = client.get("/api/curve/preview?curve=POWER&gamma=2.0").json

    assert body["curve"] == "POWER"
    assert body["gamma"] == pytest.approx(2.0)
    assert body["points"][0] == [0.0, 0.0]
    assert body["points"][-1] == [1.0, 1.0]
    assert any(point[1] < point[0] - 1e-6 for point in body["points"])


def test_apercu_gamma_borne(wired):
    client, _, _ = wired
    body = client.get("/api/curve/preview?curve=POWER&gamma=999").json
    assert body["gamma"] == pytest.approx(5.0)


def test_apercu_courbe_inconnue(wired):
    client, _, _ = wired
    assert client.get("/api/curve/preview?curve=PARABOLE").status_code == 400


def test_apercu_gamma_invalide(wired):
    client, _, _ = wired
    assert client.get("/api/curve/preview?curve=POWER&gamma=beaucoup").status_code == 400


# --- Flux temps réel -------------------------------------------------------


def test_flux_sse(connected):
    client, board, _ = connected

    response = client.get("/api/stream")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"

    board.emit_telemetry(654321)

    stream = response.response
    deadline = time.monotonic() + 3.0
    payload = ""
    for chunk in stream:
        payload += chunk.decode("utf-8")
        if "654321" in payload or time.monotonic() > deadline:
            break
    response.close()

    assert "654321" in payload
