"""Tests of the keep-alive, firmware and flash endpoints."""

from __future__ import annotations

import time

import pytest

from loadcraft.flash import Flasher
from loadcraft.lifecycle import KeepAlive
from loadcraft.link import SerialLink
from loadcraft.manager import LinkManager
from loadcraft.server import create_app

from fake_board import FakeBoard


@pytest.fixture
def firmware_app(available, clock):
    """App with keep-alive and a stubbed flasher, wired to a fake board."""
    holder = {"board": FakeBoard()}
    calls = {"flash": 0, "port": None, "fail": False}

    def connect_fn(port: str) -> SerialLink:
        connection = SerialLink(holder["board"], port=port)
        connection.start()
        connection.request_config("GET")
        return connection

    def fake_flash_fn(port: str) -> str:
        calls["flash"] += 1
        calls["port"] = port
        if calls["fail"]:
            from loadcraft.flash import FlashError
            raise FlashError("stub avrdude failure log")
        return "stub avrdude log: verified"

    manager = LinkManager(
        list_ports_fn=lambda: available,
        connect_fn=connect_fn,
        scan_interval=2.0,
        poll_interval=0.5,
    )
    keepalive = KeepAlive()
    flasher = Flasher(flash_fn=fake_flash_fn)
    app = create_app(manager, keepalive=keepalive, flasher=flasher)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, manager, holder, available, keepalive, flasher, calls

    manager.stop()


def connect_manager(firmware_app, clock):
    client, manager, *rest = firmware_app
    manager.run_once(clock())
    assert client.get("/api/status").json["connected"] is True
    return client, manager, firmware_app[4:]


# --- /api/firmware -------------------------------------------------------------


def test_firmware_not_connected(firmware_app, monkeypatch):
    client, *_ = firmware_app
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body == {
        "app_version": "1.0.0",
        "board_fw_version": None,
        "status": "not-connected",
    }


def test_firmware_up_to_date(firmware_app, clock, monkeypatch):
    connect_manager(firmware_app, clock)
    client, *_ = firmware_app
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body == {
        "app_version": "1.0.0",
        "board_fw_version": "1.0.0",
        "status": "up-to-date",
    }


def test_firmware_mismatch(firmware_app, clock, monkeypatch):
    client, manager, holder, *rest = firmware_app
    holder["board"].ver = "0.9.0"
    manager.run_once(clock())
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    assert client.get("/api/firmware").json["status"] == "mismatch"


def test_firmware_board_unknown(firmware_app, clock, monkeypatch):
    client, manager, holder, *rest = firmware_app
    holder["board"].ver = None  # old firmware: no ver field
    manager.run_once(clock())
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body["board_fw_version"] is None
    assert body["status"] == "board-unknown"


# --- POST /api/flash -------------------------------------------------------------


def test_flash_refused_when_not_connected(firmware_app):
    client, *_ = firmware_app
    response = client.post("/api/flash")
    assert response.status_code == 409
    assert response.json["error"] == "not connected"


def test_flash_success_and_reconnect(firmware_app, clock):
    client, manager, holder, _, _, _, calls = firmware_app
    manager.run_once(clock())

    response = client.post("/api/flash")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert "verified" in response.json["log"]
    assert calls["flash"] == 1
    assert calls["port"] == "/dev/fake0"

    # The flash reset the chip: it comes back as a fresh device (the pause
    # had closed the old link, so a fresh FakeBoard stands in for it, as in
    # test_manager.py::test_resume_flash_reconnects).
    holder["board"] = FakeBoard()

    # After resume the manager reconnects on the next scan.
    manager.run_once(clock(2.0))
    assert client.get("/api/status").json["connected"] is True


def test_flash_failure_returns_502_with_log(firmware_app, clock):
    client, manager, holder, _, _, _, calls = firmware_app
    manager.run_once(clock())
    calls["fail"] = True

    response = client.post("/api/flash")
    assert response.status_code == 502
    assert "stub avrdude failure log" in response.json["error"]

    # The failure path must resume the manager too. The flash reset the
    # chip: a fresh device stands in for the (closed) one.
    holder["board"] = FakeBoard()
    manager.run_once(clock(2.0))
    assert client.get("/api/status").json["connected"] is True


# --- GET /api/keepalive ------------------------------------------------------------


def test_keepalive_registers_and_unregisters(firmware_app):
    client, _, _, _, keepalive, _, _ = firmware_app
    response = client.get("/api/keepalive")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert keepalive.clients == 1

    first = next(response.response).decode("utf-8")
    assert first.startswith(": keepalive")

    response.response.close()  # client gone: the generator's finally runs
    assert keepalive.clients == 0
    response.close()


# --- POST /api/goodbye -----------------------------------------------------------


def test_goodbye_503_without_keepalive():
    manager = LinkManager(list_ports_fn=lambda: [], connect_fn=None)
    app = create_app(manager, keepalive=None, flasher=None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.post("/api/goodbye").status_code == 503


def test_goodbye_keeps_running_while_a_client_is_open():
    # A captured exit_fn: the endpoint under test must not end the test
    # process, and the goodbye watcher thread is stopped before the test
    # returns so it cannot outlive it.
    exited = []
    keepalive = KeepAlive(exit_fn=lambda: exited.append(1))
    manager = LinkManager(list_ports_fn=lambda: [], connect_fn=None)
    app = create_app(manager, keepalive=keepalive, flasher=None)
    app.config["TESTING"] = True

    keepalive.register()  # an open tab's SSE
    with app.test_client() as client:
        reply = client.post("/api/goodbye")
        assert reply.status_code == 200
        assert reply.json == {"ok": True}

    time.sleep(0.6)  # the goodbye watcher polls a few times
    assert not exited  # the client is still here: no exit
    assert keepalive.exited is False
    keepalive.stop()
