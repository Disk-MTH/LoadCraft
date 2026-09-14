"""Serial port enumeration tests."""

from __future__ import annotations

import sys
import types

import pytest

from loadcraft import link


class FakePort:
    def __init__(self, device, description="", vid=None, pid=None, hwid=""):
        self.device = device
        self.description = description
        self.vid = vid
        self.pid = pid
        self.hwid = hwid


@pytest.fixture
def fake_comports(monkeypatch):
    """Replaces serial.tools.list_ports, imported lazily by link."""
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


def test_legacy_ports_filtered_out(fake_comports):
    """On Linux, pyserial lists about thirty inherited 8250 ports. The
    board would be unfindable in there."""
    fake_comports.extend(
        [FakePort(f"/dev/ttyS{i}") for i in range(32)]
        + [FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)]
    )

    ports = link.list_ports()
    assert len(ports) == 1
    assert ports[0]["device"] == "/dev/ttyACM0"


def test_usb_identifiers_displayed(fake_comports):
    """The VID:PID lets you recognize the board when several USB serial
    devices are plugged in."""
    fake_comports.append(
        FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)
    )
    assert link.list_ports()[0]["description"] == "Pro Micro [2341:8037]"


def test_fallback_to_the_full_list(fake_comports):
    """With no USB port detected, a cluttered choice is better than no
    choice."""
    fake_comports.extend([FakePort("/dev/ttyS0"), FakePort("/dev/ttyS1")])

    ports = link.list_ports()
    assert [p["device"] for p in ports] == ["/dev/ttyS0", "/dev/ttyS1"]
    assert all(p["usb"] is False for p in ports)


def test_sorted_list(fake_comports):
    fake_comports.extend(
        [
            FakePort("/dev/ttyACM2", vid=1, pid=1),
            FakePort("/dev/ttyACM0", vid=1, pid=1),
            FakePort("/dev/ttyACM1", vid=1, pid=1),
        ]
    )
    devices = [p["device"] for p in link.list_ports()]
    assert devices == ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2"]


def test_no_port(fake_comports):
    assert link.list_ports() == []


def test_port_dict_exposes_vid_pid(fake_comports):
    """The manager recognizes the board by its USB identifier."""
    fake_comports.append(
        FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)
    )
    port = link.list_ports()[0]
    assert port["vid"] == 0x2341
    assert port["pid"] == 0x8037


def test_pyserial_absent(monkeypatch):
    """The app must stay diagnosable if pyserial is missing, not crash."""
    monkeypatch.setitem(sys.modules, "serial", None)
    monkeypatch.setitem(sys.modules, "serial.tools", None)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", None)
    assert link.list_ports() == []
