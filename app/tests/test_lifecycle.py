"""Tests of the keep-alive watchdog with an injected clock and exit hook."""

from __future__ import annotations

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
