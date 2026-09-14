"""Tests of the keep-alive watchdog with an injected clock and exit hook."""

from __future__ import annotations

import time

from loadcraft import lifecycle


def make_clock(start: float = 100.0):
    state = {"now": start}

    def tick(seconds: float = 0.0) -> float:
        state["now"] += seconds
        return state["now"]

    return tick


def make_ka(clock):
    exited = []
    ka = lifecycle.KeepAlive(
        now_fn=lambda: clock(0.0), exit_fn=lambda: exited.append(1)
    )
    return ka, exited


def test_exit_after_full_grace_of_absence():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.check()  # arms the timer
    for _ in range(9):
        clock(1.0)
        ka.check()
    assert not exited  # 9 seconds without any client
    clock(1.0)
    ka.check()
    assert exited == [1]  # 10 seconds


def test_no_exit_while_a_client_is_connected():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.register()
    for _ in range(30):
        clock(1.0)
        ka.check()
    assert not exited
    assert ka.clients == 1


def test_exit_fires_only_once():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.check()
    for _ in range(10):
        clock(1.0)
        ka.check()
    ka.check()
    assert exited == [1]
    assert ka.exited is True


def test_returning_client_restarts_the_grace():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.check()
    for _ in range(4):
        clock(1.0)
        ka.check()
    ka.register()  # client back (t=5)
    for _ in range(4):
        clock(1.0)
        ka.check()
    ka.unregister()  # gone again (t=9): a fresh 10 s window starts
    for _ in range(9):
        clock(1.0)
        ka.check()
    assert not exited
    clock(1.0)
    ka.check()
    assert exited == [1]


def test_multiple_clients_exit_only_when_all_gone():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.register()
    ka.register()
    ka.unregister()
    for _ in range(12):
        clock(1.0)
        ka.check()
    assert not exited  # one client still connected
    ka.unregister()
    for _ in range(10):
        clock(1.0)
        ka.check()
    assert exited == [1]


# --- Goodbye fast path ------------------------------------------------------------


def test_goodbye_exits_fast_when_last_client_is_gone():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.register()
    ka.announce_leave()
    time.sleep(0.4)  # the watcher runs while the client is still present
    ka.unregister()  # the tab's SSE is torn down on the server side
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not exited:
        clock(0.5)  # settle window elapses on the (fake) clock
        time.sleep(0.1)
    assert exited == [1]
    assert ka.exited is True


def test_goodbye_cancelled_when_a_client_comes_back():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.register()
    ka.announce_leave()
    time.sleep(0.4)
    ka.unregister()
    clock(0.5)
    time.sleep(0.3)  # the watcher has recorded the absence
    ka.register()  # page reload: a new client within the settle window
    for _ in range(6):
        clock(0.5)
        time.sleep(0.1)
    assert not exited
    assert ka.clients == 1
    ka.unregister()
    ka.stop()  # quiet the goodbye watcher for the next tests


def test_goodbye_does_not_exit_while_another_tab_is_open():
    clock = make_clock()
    ka, exited = make_ka(clock)
    ka.register()
    ka.register()
    ka.announce_leave()
    ka.unregister()  # one of the two tabs closed
    for _ in range(8):
        clock(0.5)
        time.sleep(0.1)
    assert not exited  # the other tab is still connected
    ka.stop()
