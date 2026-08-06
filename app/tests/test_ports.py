"""Tests de l'énumération des ports série."""

from __future__ import annotations

import sys
import types

import pytest

from handbrake_tuner import link


class FakePort:
    def __init__(self, device, description="", vid=None, pid=None, hwid=""):
        self.device = device
        self.description = description
        self.vid = vid
        self.pid = pid
        self.hwid = hwid


@pytest.fixture
def fake_comports(monkeypatch):
    """Remplace serial.tools.list_ports, importé paresseusement par link."""
    ports: list = []

    module = types.ModuleType("serial.tools.list_ports")
    module.comports = lambda: ports  # type: ignore[attr-defined]

    tools = types.ModuleType("serial.tools")
    tools.list_ports = module  # type: ignore[attr-defined]

    serial = types.ModuleType("serial")
    serial.tools = tools  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "serial", serial)
    monkeypatch.setitem(sys.modules, "serial.tools", tools)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", module)
    return ports


def test_ports_legacy_ecartes(fake_comports):
    """Sous Linux, pyserial énumère une trentaine de ports 8250 hérités. La
    carte y serait introuvable."""
    fake_comports.extend(
        [FakePort(f"/dev/ttyS{i}") for i in range(32)]
        + [FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)]
    )

    ports = link.list_ports()
    assert len(ports) == 1
    assert ports[0]["device"] == "/dev/ttyACM0"


def test_identifiants_usb_affiches(fake_comports):
    """Le VID:PID permet de reconnaître la carte quand plusieurs
    périphériques USB-série sont branchés."""
    fake_comports.append(
        FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)
    )
    assert link.list_ports()[0]["description"] == "Pro Micro [2341:8037]"


def test_repli_sur_la_liste_complete(fake_comports):
    """Sans port USB détecté, mieux vaut un choix encombré qu'aucun choix."""
    fake_comports.extend([FakePort("/dev/ttyS0"), FakePort("/dev/ttyS1")])

    ports = link.list_ports()
    assert [p["device"] for p in ports] == ["/dev/ttyS0", "/dev/ttyS1"]
    assert all(p["usb"] is False for p in ports)


def test_liste_triee(fake_comports):
    fake_comports.extend(
        [
            FakePort("/dev/ttyACM2", vid=1, pid=1),
            FakePort("/dev/ttyACM0", vid=1, pid=1),
            FakePort("/dev/ttyACM1", vid=1, pid=1),
        ]
    )
    devices = [p["device"] for p in link.list_ports()]
    assert devices == ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2"]


def test_aucun_port(fake_comports):
    assert link.list_ports() == []


def test_pyserial_absent(monkeypatch):
    """L'app doit rester diagnosticable si pyserial manque, pas exploser."""
    monkeypatch.setitem(sys.modules, "serial", None)
    monkeypatch.setitem(sys.modules, "serial.tools", None)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", None)
    assert link.list_ports() == []
