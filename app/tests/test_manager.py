"""Tests of the link manager: automatic connect / disconnect / reconnect.

The state machine is driven through run_once with the fake `clock` fixture:
no thread, no sleep, fully deterministic.
"""

from __future__ import annotations

import time

import pytest

from loadcraft import protocol
from loadcraft.link import LinkError, SerialLink
from loadcraft.manager import LinkManager

from fake_board import FakeBoard


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def make_manager(available, connectable: bool = True):
    """Manager plus a fake board behind an injectable port list.

    `holder["board"]` can be replaced to simulate a fresh device on the same
    port (an unplug / replug).
    """
    holder = {"board": FakeBoard()}
    opened: list = []

    def connect_fn(port: str) -> SerialLink:
        if not connectable:
            raise LinkError(f"cannot open {port}")
        connection = SerialLink(holder["board"], port=port)
        connection.start()
        connection.request_config("GET")
        opened.append(connection)
        return connection

    manager = LinkManager(
        list_ports_fn=lambda: available,
        connect_fn=connect_fn,
        scan_interval=2.0,
        poll_interval=0.5,
    )
    return manager, holder, opened


def known_port(device: str = "/dev/ttyACM0") -> dict:
    return {
        "device": device,
        "description": "Arduino Leonardo [2341:8036]",
        "hwid": "USB VID:PID=2341:8036",
        "usb": True,
        "vid": 0x2341,
        "pid": 0x8036,
    }


# --- Detection -------------------------------------------------------------


def test_no_port_is_searching(clock):
    manager, _, _ = make_manager([])
    manager.run_once(clock())
    status = manager.status()
    assert status["connected"] is False
    assert status["state"] == "searching"


def test_connects_when_the_known_board_appears(available, clock):
    available.clear()
    manager, holder, opened = make_manager(available)

    manager.run_once(clock())
    assert opened == []

    available.append(known_port())
    manager.run_once(clock(2.0))

    status = manager.status()
    assert status["connected"] is True
    assert status["port"] == "/dev/ttyACM0"
    assert status["port_description"] == "Arduino Leonardo [2341:8036]"
    assert status["config"]["raw_min"] == holder["board"].raw_min
    assert len(opened) == 1


def test_a_single_unknown_usb_port_is_accepted(clock):
    available = [
        {
            "device": "/dev/ttyACM9",
            "description": "some other board",
            "hwid": "",
            "usb": True,
            "vid": 0x1234,
            "pid": 0x5678,
        }
    ]
    manager, _, opened = make_manager(available)
    manager.run_once(clock())

    assert manager.status()["connected"] is True
    assert manager.status()["port"] == "/dev/ttyACM9"
    assert len(opened) == 1


def test_non_usb_ports_are_ignored(clock):
    available = [
        {**known_port(), "usb": False, "vid": None, "pid": None},
        {
            "device": "/dev/ttyS0",
            "description": "legacy",
            "hwid": "",
            "usb": False,
            "vid": None,
            "pid": None,
        },
    ]
    manager, _, opened = make_manager(available)
    manager.run_once(clock())

    assert manager.status()["state"] == "searching"
    assert opened == []


def test_multiple_unknown_ports_are_refused(clock):
    available = [
        {
            "device": "/dev/ttyACM1",
            "description": "board one",
            "hwid": "",
            "usb": True,
            "vid": 0x1234,
            "pid": 0x0001,
        },
        {
            "device": "/dev/ttyACM2",
            "description": "board two",
            "hwid": "",
            "usb": True,
            "vid": 0x1234,
            "pid": 0x0002,
        },
    ]
    manager, _, opened = make_manager(available)
    manager.run_once(clock())

    status = manager.status()
    assert status["state"] == "error"
    assert status["last_error"] == "multiple serial devices, cannot pick one"
    assert opened == []


def test_scan_cadence_is_respected(available, clock):
    manager, _, opened = make_manager(available)
    manager.run_once(clock())
    assert len(opened) == 1

    # A fresh scan cadence has not elapsed: no second connection attempt.
    manager.run_once(clock(0.5))
    assert len(opened) == 1


# --- Failures and recovery ---------------------------------------------------


def test_connect_failure_goes_to_error_and_retries(available, clock):
    manager, _, opened = make_manager(available, connectable=False)

    manager.run_once(clock())
    assert manager.status()["state"] == "error"
    assert "cannot open" in manager.status()["last_error"]
    assert opened == []

    # The scan cadence has not elapsed: no retry yet...
    manager.run_once(clock(0.5))
    assert manager.status()["state"] == "error"

    # ...then the attempt is made again (and fails again here).
    manager.run_once(clock(2.0))
    assert manager.status()["state"] == "error"
    assert "cannot open" in manager.status()["last_error"]


def test_dead_link_is_dropped_and_reconnected(available, clock):
    manager, holder, opened = make_manager(available)
    manager.run_once(clock())
    assert manager.status()["connected"] is True
    first = opened[0]

    # The board is unplugged: the read thread dies, the link is dead.
    holder["board"].close()
    assert wait_for(lambda: first.dead)

    manager.run_once(clock())
    status = manager.status()
    assert status["connected"] is False
    assert status["state"] == "searching"
    assert manager.link is None

    # The board comes back (fresh device) and is reconnected.
    holder["board"] = FakeBoard()
    manager.run_once(clock(2.0))
    assert manager.status()["connected"] is True
    assert len(opened) == 2


def test_dropping_the_link_stops_streaming_on_the_board(available, clock):
    manager, holder, _ = make_manager(available)
    manager.run_once(clock())
    assert manager.status()["connected"] is True

    # The app enables streaming on connect; the board remembers it.
    holder["board"].streaming = True

    manager._drop_link()

    # The port is released with the board told to stop streaming first.
    assert holder["board"].streaming is False
    assert manager.link is None
    assert manager.status()["state"] == "searching"


# --- Commands ----------------------------------------------------------------


def test_commands_rejected_when_not_connected():
    manager, _, _ = make_manager([])
    with pytest.raises(LinkError, match="not connected"):
        manager.request_config("GET")
    with pytest.raises(LinkError, match="not connected"):
        manager.subscribe()


def test_request_config_round_trip(available, clock):
    manager, holder, _ = make_manager(available)
    manager.run_once(clock())

    config = manager.request_config(protocol.cmd_set_min(4242))
    assert config.raw_min == 4242
    assert holder["board"].received[-1] == "GET"


def test_stop_is_prompt_and_terminates_the_watchdog(clock):
    manager, _, _ = make_manager([])
    manager.start()
    started = time.monotonic()
    manager.stop()
    elapsed = time.monotonic() - started
    # A functioning stop flag makes the join return in milliseconds; the old
    # flagless loop always burned the full 2 s join timeout.
    assert elapsed < 1.5


# --- Flash pause / resume ----------------------------------------------------


def test_pause_for_flash_closes_the_link_and_blocks_scans(available, clock):
    manager, _, _ = make_manager(available)
    manager.run_once(clock())
    assert manager.status()["connected"] is True

    manager.pause_for_flash()
    assert manager.link is None
    assert manager.status()["connected"] is False

    # Far past the scan cadence: a paused manager must not reconnect.
    manager.run_once(clock(5.0))
    assert manager.link is None


def test_resume_flash_reconnects(available, clock):
    manager, holder, _ = make_manager(available)
    manager.run_once(clock())
    assert manager.status()["connected"] is True

    manager.pause_for_flash()
    # The bootloader resets the chip: it comes back as a fresh device.
    holder["board"] = FakeBoard()
    manager.resume_flash()

    manager.run_once(clock(2.0))  # scan cadence elapsed: reconnect
    assert manager.status()["connected"] is True
