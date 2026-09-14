"""Serial link tests, against a simulated board."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from loadcraft import protocol
from loadcraft.link import LinkError, SerialLink
from loadcraft.protocol import Ack, Config, Err, Telemetry

from fake_board import FakeBoard


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- Basic dialogue ---------------------------------------------------------


def test_request_ping(link):
    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_request_config(link, board):
    config = link.request_config(protocol.cmd_get())
    assert config.raw_min == board.raw_min
    assert config.raw_max == board.raw_max
    assert config.curve == "LINEAR"


def test_config_updated_in_background(link):
    link.request(protocol.cmd_get())
    assert wait_for(lambda: link.config is not None)
    assert isinstance(link.config, Config)


def test_command_sent_with_newline(link, board):
    link.request(protocol.cmd_ping())
    assert board.received == ["PING"]


# --- Late replies ------------------------------------------------------------


def test_late_reply_does_not_pollute_the_next_one(link, board):
    """A reply arriving after the timeout must not be served to the next
    command: the app would then show the effect of the wrong command."""
    board.emit("OK NOISE")
    assert wait_for(lambda: link._replies.qsize() > 0)

    reply = link.request(protocol.cmd_ping())
    assert reply == Ack("PING")


def test_missing_reply_raises_an_error(board):
    class Mute:
        def write(self, data):
            pass

        def readline(self):
            time.sleep(0.01)
            return b""

        def close(self):
            pass

    connection = SerialLink(Mute())
    connection.start()
    try:
        with pytest.raises(LinkError, match="no reply"):
            connection.request(protocol.cmd_ping(), timeout=0.2)
    finally:
        connection.close()


def test_request_config_asks_again_after_a_simple_ack(link, board):
    """SET MIN answers "OK", not a configuration: the link must fetch it
    so the app stays up to date."""
    config = link.request_config(protocol.cmd_set_min(4242))
    assert config.raw_min == 4242
    assert board.received == ["SET MIN 4242", "GET"]


def test_request_config_propagates_an_error(link, board):
    with pytest.raises(LinkError, match="unknown command"):
        link.request_config("UNKNOWN COMMAND")


# --- Telemetry ---------------------------------------------------------------


def test_telemetry_feeds_the_state(link, board):
    board.emit_telemetry(500000)
    assert wait_for(lambda: link.telemetry is not None)
    assert link.telemetry.raw == 500000


def test_telemetry_is_not_taken_for_a_reply(link, board):
    """Telemetry arrives continuously: if it went through the replies
    queue, every command would receive a measurement instead of its
    acknowledgment."""
    board.emit_telemetry(111111)
    board.emit_telemetry(222222)
    assert wait_for(lambda: link.telemetry is not None)

    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_subscription(link, board):
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


def test_slow_subscriber_drops_older_measurements(link, board):
    """A subscriber that falls behind must not grow the queue without
    bound: the oldest measurements are dropped."""
    subscription = link.subscribe()
    for i in range(40):
        board.emit_telemetry(100000 + i)

    assert wait_for(lambda: subscription.full())
    time.sleep(0.2)
    assert subscription.qsize() <= subscription.maxsize


def test_multiple_subscribers(link, board):
    first, second = link.subscribe(), link.subscribe()
    board.emit_telemetry(424242)

    assert first.get(timeout=2.0).raw == 424242
    assert second.get(timeout=2.0).raw == 424242


# --- Errors ------------------------------------------------------------------


def test_error_remembered(link, board):
    link.request("UNKNOWN COMMAND")
    assert wait_for(lambda: link.last_error is not None)
    assert link.last_error == "unknown command"


def test_write_on_closed_port(link, board):
    board.close()
    with pytest.raises(LinkError, match="cannot write"):
        link.send(protocol.cmd_ping())


def test_close_is_idempotent(board):
    connection = SerialLink(board)
    connection.start()
    connection.close()
    connection.close()  # must not raise


def test_stray_lines_ignored(link, board):
    """A serial port emits stray bytes on open. They must neither crash
    the read thread nor be taken for replies."""
    board.emit_raw(b"\x00\xff noise\n")
    board.emit("")
    board.emit("not a known command")

    assert link.request(protocol.cmd_ping()) == Ack("PING")


def test_thread_survives_a_read_error():
    class Broken:
        def __init__(self):
            self.calls = 0

        def write(self, data):
            pass

        def readline(self):
            self.calls += 1
            raise OSError("board unplugged")

        def close(self):
            pass

    transport = Broken()
    connection = SerialLink(transport)
    connection.start()
    try:
        assert wait_for(lambda: connection.last_error is not None)
        assert "unplugged" in connection.last_error
    finally:
        connection.close()


# --- Dead link ---------------------------------------------------------------


def test_dead_after_read_thread_failure():
    """When the board is unplugged the read thread dies: the link must be
    observable as dead, not as 'connected but silent'."""
    class Broken:
        def write(self, data):
            pass

        def readline(self):
            raise OSError("board unplugged")

        def close(self):
            pass

    connection = SerialLink(Broken())
    connection.start()
    try:
        assert wait_for(lambda: connection.dead)
    finally:
        connection.close()


def test_dead_after_close():
    connection = SerialLink(FakeBoard())
    connection.start()
    assert not connection.dead
    connection.close()
    assert connection.dead


def test_request_raises_immediately_when_dead():
    connection = SerialLink(FakeBoard())
    connection.start()
    connection.close()
    with pytest.raises(LinkError, match="link is down"):
        connection.request(protocol.cmd_ping())
