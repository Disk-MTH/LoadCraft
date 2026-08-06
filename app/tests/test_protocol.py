"""Tests du protocole côté hôte.

Les attentes doivent rester alignées sur tests/test_hb_protocol.c : c'est le
seul garde-fou contre une dérive silencieuse entre les deux implémentations.
"""

import math

import pytest

from handbrake_tuner import protocol
from handbrake_tuner.protocol import Ack, Config, Err, Telemetry


# --- Analyse des réponses --------------------------------------------------


def test_parse_config():
    message = protocol.parse_line(
        "CFG min=12345 max=987654 curve=POWER gamma=1.800 calibrated=1"
    )
    assert message == Config(
        raw_min=12345, raw_max=987654, curve="POWER", gamma=1.8, calibrated=True
    )


def test_parse_config_non_calibree():
    message = protocol.parse_line(
        "CFG min=0 max=8000000 curve=LINEAR gamma=1.000 calibrated=0"
    )
    assert message.calibrated is False


def test_parse_config_valeurs_negatives():
    message = protocol.parse_line(
        "CFG min=-8388608 max=-1 curve=SCURVE gamma=5.000 calibrated=1"
    )
    assert message.raw_min == -8388608
    assert message.raw_max == -1


def test_parse_telemetry():
    assert protocol.parse_line("T raw=123456 out=0.750 axis=767") == Telemetry(
        raw=123456, out=0.75, axis=767
    )


def test_parse_ok_et_err():
    assert protocol.parse_line("OK SAVE") == Ack("SAVE")
    assert protocol.parse_line("OK SET MIN 1234") == Ack("SET MIN 1234")
    assert protocol.parse_line("ERR unknown command") == Err("unknown command")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "bruit",
        "CFG",
        "CFG min=abc max=1 curve=LINEAR gamma=1.0 calibrated=0",
        "CFG min=1 curve=LINEAR gamma=1.0 calibrated=0",  # max manquant
        "CFG min=1 max=2 curve=PARABOLE gamma=1.0 calibrated=0",
        "T raw=1 out=x axis=2",
        "T raw=1",
    ],
)
def test_lignes_illisibles_ignorees(line):
    """Le port délivre des parasites à l'ouverture et au redémarrage de la
    carte : les ignorer vaut mieux que de faire tomber le thread de lecture."""
    assert protocol.parse_line(line) is None


# --- Construction des commandes --------------------------------------------


def test_commandes_simples():
    assert protocol.cmd_ping() == "PING"
    assert protocol.cmd_get() == "GET"
    assert protocol.cmd_save() == "SAVE"
    assert protocol.cmd_load() == "LOAD"
    assert protocol.cmd_reset() == "RESET"
    assert protocol.cmd_stream(True) == "STREAM 1"
    assert protocol.cmd_stream(False) == "STREAM 0"


def test_commandes_calibration():
    assert protocol.cmd_set_min() == "SET MIN"
    assert protocol.cmd_set_max() == "SET MAX"
    assert protocol.cmd_set_min(1234) == "SET MIN 1234"
    assert protocol.cmd_set_max(-9876) == "SET MAX -9876"


def test_commandes_courbe():
    assert protocol.cmd_set_curve("POWER") == "SET CURVE POWER"
    assert protocol.cmd_set_curve("power") == "SET CURVE POWER"
    assert protocol.cmd_set_curve("SCURVE", 1.8) == "SET CURVE SCURVE 1.800"
    assert protocol.cmd_set_gamma(2.5) == "SET GAMMA 2.500"


def test_courbe_inconnue_rejetee():
    with pytest.raises(ValueError):
        protocol.cmd_set_curve("PARABOLE")


def test_commandes_relisibles_par_le_firmware():
    """Toute commande produite ici doit correspondre à la grammaire testée
    dans tests/test_hb_protocol.c."""
    commands = [
        protocol.cmd_ping(),
        protocol.cmd_get(),
        protocol.cmd_save(),
        protocol.cmd_load(),
        protocol.cmd_reset(),
        protocol.cmd_stream(True),
        protocol.cmd_set_min(),
        protocol.cmd_set_min(42),
        protocol.cmd_set_max(-42),
        protocol.cmd_set_curve("LINEAR"),
        protocol.cmd_set_curve("POWER", 1.5),
        protocol.cmd_set_gamma(0.5),
    ]
    for command in commands:
        assert "\n" not in command
        assert command == command.strip()
        assert len(command) < 64  # HB_LINE_MAX


# --- Bornes du gamma -------------------------------------------------------


def test_clamp_gamma():
    assert protocol.clamp_gamma(1.0) == 1.0
    assert protocol.clamp_gamma(99.0) == protocol.GAMMA_MAX
    assert protocol.clamp_gamma(0.0) == protocol.GAMMA_MIN
    assert protocol.clamp_gamma(-5.0) == protocol.GAMMA_MIN
    assert protocol.clamp_gamma(float("nan")) == 1.0
    assert protocol.clamp_gamma("bruit") == 1.0


# --- Normalisation ---------------------------------------------------------


def test_normalize():
    assert protocol.normalize(1500, 1000, 2000) == pytest.approx(0.5)
    assert protocol.normalize(500, 1000, 2000) == 0.0
    assert protocol.normalize(9999, 1000, 2000) == 1.0


def test_normalize_plage_inversee():
    """Même comportement que hb_normalize : une cellule câblée en polarité
    opposée reste exploitable sans option d'inversion."""
    assert protocol.normalize(1500, 2000, 1000) == pytest.approx(0.5)
    assert protocol.normalize(1000, 2000, 1000) == 1.0
    assert protocol.normalize(2000, 2000, 1000) == 0.0


def test_normalize_plage_nulle():
    assert protocol.normalize(1000, 1000, 1000) == 0.0
