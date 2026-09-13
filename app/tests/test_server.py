"""Tests of the HTTP API, against a simulated board.

The link manager is driven deterministically through run_once and the fake
`clock` fixture (conftest.py): no thread, no sleep.
"""

from __future__ import annotations

import time

import pytest

from handbrake_tuner.link import LinkError, SerialLink
from handbrake_tuner.manager import LinkManager
from handbrake_tuner.server import create_app

from fake_board import FakeBoard


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def wired(available):
    """App + link manager + fake board, not connected at first."""
    holder = {"board": FakeBoard()}

    def connect_fn(port: str) -> SerialLink:
        if port == "/dev/absent":
            raise LinkError(f"cannot open {port}")
        connection = SerialLink(holder["board"], port=port)
        connection.start()
        connection.request_config("GET")
        return connection

    manager = LinkManager(
        list_ports_fn=lambda: available,
        connect_fn=connect_fn,
        scan_interval=2.0,
        poll_interval=0.5,
    )
    app = create_app(manager)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, manager, holder, available

    manager.stop()


@pytest.fixture
def connected(wired, clock):
    """The manager has already connected to the fake board."""
    client, manager, holder, available = wired
    manager.run_once(clock())
    assert client.get("/api/status").json["connected"] is True
    return client, manager, holder, available


# --- Interface -------------------------------------------------------------


def test_page_served(wired):
    client, *_ = wired
    response = client.get("/")
    assert response.status_code == 200
    assert b"<!DOCTYPE html>" in response.data


# --- Status ----------------------------------------------------------------


def test_status_searching_without_board(wired, clock):
    client, manager, _, available = wired
    available.clear()
    manager.run_once(clock())
    body = client.get("/api/status").json
    assert body["connected"] is False
    assert body["state"] == "searching"
    assert body["config"] is None


def test_status_connected(connected):
    client, _, _, _ = connected
    body = client.get("/api/status").json
    assert body["connected"] is True
    assert body["state"] == "connected"
    assert body["port"] == "/dev/fake0"
    assert body["config"]["raw_min"] == 100000


# --- Manual connection endpoints are gone -----------------------------------


@pytest.mark.parametrize("path", ["/api/ports", "/api/connect", "/api/disconnect"])
def test_manual_connection_endpoints_removed(wired, path):
    client, *_ = wired
    assert client.get(path).status_code == 404
    assert client.post(path).status_code == 404


# --- Commands when not connected --------------------------------------------


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/calibrate/min", {"value": 42}),
        ("post", "/api/calibrate/max", {"value": 42}),
        ("post", "/api/curve", {"curve": "POWER"}),
        ("post", "/api/gamma", {"gamma": 2.0}),
        ("post", "/api/save", {}),
        ("post", "/api/load", {}),
        ("post", "/api/reset", {}),
        ("get", "/api/stream", None),
    ],
)
def test_commands_refused_when_not_connected(wired, method, path, payload):
    client, *_ = wired
    response = getattr(client, method)(path, json=payload) \
        if payload is not None else getattr(client, method)(path)
    assert response.status_code == 409
    assert response.json["error"] == "not connected"


# --- Calibration -------------------------------------------------------------


def test_calibrate_requires_value(connected):
    client, *_ = connected
    response = client.post("/api/calibrate/min", json={})
    assert response.status_code == 400
    assert response.json["error"] == "value required"


def test_calibrate_min_explicit_value(connected):
    client, _, holder, _ = connected
    body = client.post("/api/calibrate/min", json={"value": 4242}).json
    assert body["config"]["raw_min"] == 4242
    assert "SET MIN 4242" in holder["board"].received


def test_calibrate_max_explicit_value(connected):
    client, _, holder, _ = connected
    body = client.post("/api/calibrate/max", json={"value": 888888}).json
    assert body["config"]["raw_max"] == 888888


def test_calibrate_invalid_value(connected):
    client, *_ = connected
    assert client.post(
        "/api/calibrate/min", json={"value": "much"}
    ).status_code == 400


def test_calibrate_unknown_bound(connected):
    client, *_ = connected
    assert client.post(
        "/api/calibrate/mid", json={"value": 1}
    ).status_code == 400


# --- Curve -------------------------------------------------------------------


def test_curve_change(connected):
    client, *_ = connected
    body = client.post("/api/curve", json={"curve": "SCURVE", "gamma": 1.8}).json
    assert body["config"]["curve"] == "SCURVE"
    assert body["config"]["gamma"] == pytest.approx(1.8)


def test_curve_case_insensitive(connected):
    client, *_ = connected
    body = client.post("/api/curve", json={"curve": "power"}).json
    assert body["config"]["curve"] == "POWER"


def test_unknown_curve_refused(connected):
    client, *_ = connected
    assert client.post("/api/curve", json={"curve": "PARABOLE"}).status_code == 400


def test_gamma(connected):
    client, *_ = connected
    body = client.post("/api/gamma", json={"gamma": 2.5}).json
    assert body["config"]["gamma"] == pytest.approx(2.5)


def test_gamma_clamped_before_sending(connected):
    """The firmware already clamps, but clamping here avoids sending a value
    the board would fix silently — the app would display something else than
    what actually applies."""
    client, *_ = connected
    body = client.post("/api/gamma", json={"gamma": 999}).json
    assert body["config"]["gamma"] == pytest.approx(5.0)


def test_gamma_invalid(connected):
    client, *_ = connected
    assert client.post("/api/gamma", json={"gamma": "much"}).status_code == 400
    assert client.post("/api/gamma", json={}).status_code == 400


# --- Persistence --------------------------------------------------------------


def test_save(connected):
    client, _, holder, _ = connected
    client.post("/api/calibrate/min", json={"value": 1111})
    assert client.post("/api/save").status_code == 200
    assert holder["board"].saved is not None
    assert holder["board"].saved[0] == 1111


def test_load_cancels_unsaved_changes(connected):
    client, _, holder, _ = connected
    client.post("/api/calibrate/min", json={"value": 1111})
    client.post("/api/save")

    client.post("/api/calibrate/min", json={"value": 9999})
    body = client.post("/api/load").json
    assert body["config"]["raw_min"] == 1111


def test_reset(connected):
    client, *_ = connected
    body = client.post("/api/reset").json
    assert body["config"]["calibrated"] is False
    assert body["config"]["curve"] == "LINEAR"


# --- Curve preview -------------------------------------------------------------


def test_curve_preview(connected):
    """The preview does not depend on the board: curves can be compared
    before anything is connected."""
    client, *_ = connected
    body = client.get("/api/curve/preview?curve=POWER&gamma=2.0").json
    assert body["curve"] == "POWER"
    assert body["gamma"] == pytest.approx(2.0)
    assert body["points"][0] == [0.0, 0.0]
    assert body["points"][-1] == [1.0, 1.0]
    assert any(point[1] < point[0] - 1e-6 for point in body["points"])


def test_preview_gamma_clamped(connected):
    client, *_ = connected
    body = client.get("/api/curve/preview?curve=POWER&gamma=999").json
    assert body["gamma"] == pytest.approx(5.0)


def test_preview_unknown_curve(connected):
    client, *_ = connected
    assert client.get("/api/curve/preview?curve=PARABOLE").status_code == 400


def test_preview_invalid_gamma(connected):
    client, *_ = connected
    assert client.get(
        "/api/curve/preview?curve=POWER&gamma=much"
    ).status_code == 400


# --- Live stream ----------------------------------------------------------------


def test_stream_sse(connected):
    client, _, holder, _ = connected
    board = holder["board"]

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


def test_stream_ends_when_the_link_is_replaced(connected, clock):
    """When the board is unplugged and a fresh one takes its port, the old
    stream must end: the browser's EventSource then re-subscribes to the new
    link on its own."""
    client, manager, holder, _ = connected
    board = holder["board"]

    response = client.get("/api/stream")
    stream = response.response
    board.emit_telemetry(111111)

    # The first chunk can be a keep-alive comment: consume chunks until the
    # telemetry event arrives.
    first = ""
    deadline = time.monotonic() + 3.0
    while "111111" not in first and time.monotonic() < deadline:
        first += next(stream).decode("utf-8")
    assert "111111" in first

    board.close()
    assert wait_for(lambda: manager.link is not None and manager.link.dead)
    manager.run_once(clock())      # the dead link is dropped
    holder["board"] = FakeBoard()  # a fresh device on the same port
    manager.run_once(clock(2.0))   # the scan cadence has elapsed: reconnect
    assert manager.status()["connected"] is True

    with pytest.raises(StopIteration):
        next(stream)
    response.close()
