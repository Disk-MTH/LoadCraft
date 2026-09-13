# Handbrake Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the intermittent freeze of the handbrake axis, make the calibration app fully automatic (detect / connect / reconnect the board by itself), replace the "set here" calibration buttons with editable fields, and bring the whole project to English.

**Architecture:** A pure-C stuck-value detector goes in the firmware core (natively tested); a server-side `LinkManager` background thread in the Python app owns the serial link lifecycle; the web page becomes a pure display (1 Hz status poll + one permanent EventSource); the serial protocol only gains an optional `s` field on telemetry lines.

**Tech Stack:** C99 (AVR target + native gcc tests), Python 3.9+ (Flask, pyserial, pytest), vanilla JS/HTML. No new dependencies anywhere.

**Spec:** `docs/superpowers/specs/2026-09-13-handbrake-overhaul-design.md` — read it first; the plan argues from it.

## Global Constraints

- All new code, comments, docstrings, messages and UI text is written in English (project rule). Legacy French text is translated in Tasks 8-11, never before.
- When editing an existing line, its adjacent comment is translated in the same edit; untouched French comments wait for Tasks 8-11.
- Commit messages: English, one line, `type(scope): summary` (matches the repo's existing shape).
- Stage only the files of the task (explicit paths, never `git add -A`). The working tree is clean at the start of each task.
- The serial protocol stays stable except for the optional `s` field on `T` lines; the bare `SET MIN` / `SET MAX` capture forms remain in the firmware.
- Verification gates: `make test-firmware` after C changes, `make test-app` after Python changes, `make build` for the sketch (Task 2), final accent grep in Task 12.
- Tests are TDD: the failing test is written and run before the implementation, in every code task.

---

### Task 1: Firmware — stuck-value detector (`hb_stuck_t`)

**Files:**
- Modify: `firmware/handbrake/hb_core.h` (after the filter section declarations)
- Modify: `firmware/handbrake/hb_core.c` (append at the end of the file)
- Modify: `firmware/handbrake/config.h` (in the `Cadences` section, after `HB_SENSOR_TIMEOUT_MS`)
- Test: `tests/test_hb_core.c` (new section before `main`, registered in the `RUN` list)

**Interfaces:**
- Consumes: nothing new.
- Produces: `hb_stuck_t` struct, `hb_stuck_init(hb_stuck_t *, uint32_t timeout_ms)`, `int hb_stuck_push(hb_stuck_t *, uint32_t now_ms, int32_t sample)` — used by Task 2 in the sketch. `HB_STUCK_TIMEOUT_MS` in `config.h`.

- [ ] **Step 1: Add the failing tests**

Append this section at the end of `tests/test_hb_core.c`, before `int main(void)`:

```c
/* --- Stuck-value detection ------------------------------------------------ */

/* A healthy HX711 at gain 128 has permanent LSB jitter: a bit-identical raw
 * value for the whole timeout is a failure signature (DOUT line stuck,
 * converter locked), never a quiet sensor. */
static void test_stuck_detects_a_frozen_value(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout - 1, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, 1000), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, 5 * timeout, 1000), 1);
}

static void test_stuck_recovers_on_a_different_value(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, 1000), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 2, 1001), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, 2 * timeout + 1, 1001), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, 2 * timeout + 2, 1001), 1);
}

/* A change before the threshold restarts the timer: two short episodes of
 * the same value must not add up to a stuck declaration. */
static void test_stuck_change_before_threshold_restarts_timer(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout / 2, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout / 2 + 1, 2000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + timeout / 2, 2000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + timeout / 2 + 1, 2000), 1);
}

static void test_stuck_with_negative_values(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, -5), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, -5), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 2, -4), 0);
}
```

And register them in `main()`, right after `RUN(test_ema_alpha_invalide_devient_transparent);`:

```c
    RUN(test_stuck_detects_a_frozen_value);
    RUN(test_stuck_recovers_on_a_different_value);
    RUN(test_stuck_change_before_threshold_restarts_timer);
    RUN(test_stuck_with_negative_values);
```

- [ ] **Step 2: Run the firmware tests, expect a compile failure**

Run: `make test-firmware`
Expected: compilation error, `hb_stuck_init` undeclared (the tests do not build yet).

- [ ] **Step 3: Add the constant, the declaration, and the implementation**

In `firmware/handbrake/config.h`, after the `HB_SENSOR_TIMEOUT_MS` block:

```c
/* The raw value has not changed at all for this long: the sensor is
 * declared stuck (DOUT line stuck, converter locked). A healthy HX711 at
 * gain 128 has permanent LSB jitter, so this is a failure signature at any
 * effective rate. */
#define HB_STUCK_TIMEOUT_MS 1000
```

In `firmware/handbrake/hb_core.h`, after the filter declarations (`hb_ema_value`):

```c
/* Stuck-value detection.
 *
 * A raw value that is bit-identical over a whole timeout is a failure
 * signature (DOUT line stuck, converter locked), never a quiet sensor: a
 * healthy HX711 at gain 128 has permanent LSB jitter. The threshold is in
 * time, not in sample count, so it behaves the same at any effective rate.
 */
typedef struct {
    int32_t   last;           /* last value seen */
    uint32_t  last_change_ms; /* timestamp of the last change */
    uint32_t  timeout_ms;     /* HB_STUCK_TIMEOUT_MS */
    int       primed;
} hb_stuck_t;

void hb_stuck_init(hb_stuck_t *s, uint32_t timeout_ms);

/* Feed a raw sample with its timestamp. Returns 1 while the value has not
 * changed for more than timeout_ms; the first different sample returns 0
 * and restarts the timer. */
int hb_stuck_push(hb_stuck_t *s, uint32_t now_ms, int32_t sample);
```

In `firmware/handbrake/hb_core.c`, at the end of the file:

```c
void hb_stuck_init(hb_stuck_t *s, uint32_t timeout_ms)
{
    s->last           = 0;
    s->last_change_ms = 0;
    s->timeout_ms     = timeout_ms;
    s->primed         = 0;
}

int hb_stuck_push(hb_stuck_t *s, uint32_t now_ms, int32_t sample)
{
    if (!s->primed || sample != s->last) {
        s->primed         = 1;
        s->last           = sample;
        s->last_change_ms = now_ms;
    }
    return (now_ms - s->last_change_ms) > s->timeout_ms;
}
```

- [ ] **Step 4: Run the firmware tests, expect green**

Run: `make test-firmware`
Expected: all suites pass; `hb_core` assertion count grows by 16 (four new tests). No new warnings.

- [ ] **Step 5: Commit**

```bash
git add firmware/handbrake/hb_core.h firmware/handbrake/hb_core.c \
        firmware/handbrake/config.h tests/test_hb_core.c
git commit -m "feat(firmware): stuck-value detector for the HX711 raw stream"
```

---

### Task 2: Firmware — sensor flag in telemetry + sketch integration

**Files:**
- Modify: `firmware/handbrake/hb_protocol.h` (signature of `hb_format_telemetry`)
- Modify: `firmware/handbrake/hb_protocol.c` (implementation)
- Modify: `firmware/handbrake/handbrake.ino` (stuck detector wiring, `send_telemetry`)
- Test: `tests/test_hb_protocol.c` (update `test_format_telemetry`, `test_format_tampon_trop_petit`, add one test)

**Interfaces:**
- Consumes: `hb_stuck_t`, `hb_stuck_init`, `hb_stuck_push`, `HB_STUCK_TIMEOUT_MS` (Task 1).
- Produces: `hb_format_telemetry(char *buf, size_t size, int32_t raw, float unit, uint16_t axis, int sensor_ok)` — the `T` line now ends with ` s=1|0`. Task 3 parses this field on the host side.

- [ ] **Step 1: Update the C tests for the new signature and field**

In `tests/test_hb_protocol.c`, replace `test_format_telemetry` with:

```c
static void test_format_telemetry(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.75f, 767, 1);
    CHECK_STR(buf, "T raw=123456 out=0.750 axis=767 s=1");

    hb_format_telemetry(buf, sizeof buf, -8388608L, 0.0f, 0, 1);
    CHECK_STR(buf, "T raw=-8388608 out=0.000 axis=0 s=1");
}

/* s=0 : no valid sample (stuck sensor or sensor-absent timeout). Old hosts
 * ignore the field; the host parser defaults a missing s to 1. */
static void test_format_telemetry_sans_capteur(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.0f, 0, 0);
    CHECK_STR(buf, "T raw=123456 out=0.000 axis=0 s=0");
}
```

In `test_format_tampon_trop_petit`, change the call to:

```c
    CHECK_EQ_INT(hb_format_telemetry(buf, sizeof buf, 123456, 0.5f, 512, 1), 0);
```

Register the new test in `main()` after `RUN(test_format_telemetry);`:

```c
    RUN(test_format_telemetry_sans_capteur);
```

- [ ] **Step 2: Run the firmware tests, expect a compile failure**

Run: `make test-firmware`
Expected: `hb_protocol` fails to compile (wrong number of arguments).

- [ ] **Step 3: Implement the new format**

In `firmware/handbrake/hb_protocol.h`, replace the declaration and its comment:

```c
/* "T raw=… out=… axis=… s=…" — s=1 with a valid sample, s=0 otherwise. */
size_t hb_format_telemetry(char *buf, size_t size, int32_t raw, float unit,
                           uint16_t axis, int sensor_ok);
```

In `firmware/handbrake/hb_protocol.c`, replace the implementation body's `snprintf` call:

```c
    hb_fmt_fixed(obuf, sizeof obuf, unit, 3);
    n = snprintf(buf, size, "T raw=%ld out=%s axis=%u s=%d", (long)raw,
                 obuf, (unsigned)axis, sensor_ok ? 1 : 0);
```

(Keep the NULL/size guards and the truncation handling as they are.)

- [ ] **Step 4: Wire the detector into the sketch**

In `firmware/handbrake/handbrake.ino`:

1. After `static hb_ema_t     filter;`, add:

```c
static hb_stuck_t   stuck;
```

2. In `setup()`, after `hb_ema_init(&filter, HB_EMA_ALPHA);`, add:

```c
    hb_stuck_init(&stuck, HB_STUCK_TIMEOUT_MS);
```

3. Replace the whole `poll_sensor()` function with:

```c
static void poll_sensor()
{
    int32_t raw;

    if (sensor.read(raw)) {
        last_sample_ms = millis();

        if (hb_stuck_push(&stuck, last_sample_ms, raw)) {
            /* The raw value has not moved at all for a timeout: the DOUT
             * line is stuck or the converter is locked. Same treatment as a
             * missing sensor: the axis falls back to zero instead of
             * freezing, and the warmup restarts. */
            have_sample = false;
            hb_ema_reset(&filter);
            warmup_left = WARMUP_SAMPLES;
            return;
        }

        if (warmup_left > 0) {
            warmup_left--;
            return;
        }

        filtered_raw = hb_ema_push(&filter, raw);
        have_sample  = true;
        return;
    }

    /* Silent sensor: the axis falls back to zero rather than staying frozen
     * on the last value, which could be a full brake. */
    if (have_sample && (millis() - last_sample_ms) > HB_SENSOR_TIMEOUT_MS) {
        have_sample = false;
        hb_ema_reset(&filter);
        warmup_left = WARMUP_SAMPLES;
    }
}
```

4. In `send_telemetry()`, pass the sensor state to the formatter:

```c
static void send_telemetry()
{
    char  buf[HB_REPLY_MAX];
    float unit = have_sample ? hb_process(&config, filtered_raw) : 0.0f;

    if (hb_format_telemetry(buf, sizeof buf, filtered_raw, unit,
                            hb_axis_from_unit(unit), have_sample)) {
        reply(buf);
    }
}
```

- [ ] **Step 5: Run the native tests and the AVR build**

Run: `make test-firmware && make build`
Expected: native suites green; the sketch compiles (flash usage still well under 100 %; expect roughly +200 bytes of flash and +16 bytes of RAM).

- [ ] **Step 6: Commit**

```bash
git add firmware/handbrake/hb_protocol.h firmware/handbrake/hb_protocol.c \
        firmware/handbrake/handbrake.ino tests/test_hb_protocol.c
git commit -m "feat(firmware): sensor flag in telemetry, stuck handling in the sketch"
```

---

### Task 3: App — parse the optional `sensor` field in Python

**Files:**
- Modify: `app/handbrake_tuner/protocol.py` (`Telemetry` dataclass, `parse_line`)
- Test: `app/tests/test_protocol.py` (two new tests)

**Interfaces:**
- Consumes: the `s` field produced by Task 2 (optional on the wire).
- Produces: `Telemetry(raw, out, axis, sensor: bool = True)` with `as_dict()` including `"sensor"` — consumed by the SSE payload (Task 6) and the UI warning (Task 7).

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_protocol.py`:

```python
def test_parse_telemetry_with_sensor_flag():
    message = protocol.parse_line("T raw=123456 out=0.750 axis=767 s=0")
    assert message == Telemetry(
        raw=123456, out=0.75, axis=767, sensor=False
    )


def test_parse_telemetry_sensor_defaults_to_present():
    """The field is optional on the wire: a board that predates it still
    parses, treated as having a valid sample."""
    message = protocol.parse_line("T raw=123456 out=0.750 axis=767")
    assert message.sensor is True
```

- [ ] **Step 2: Run the tests, expect failure**

Run: `app/.venv/bin/python -m pytest app/tests/test_protocol.py -q`
Expected: the two new tests fail (`Telemetry` has no `sensor` field / `TypeError`), the rest passes.

- [ ] **Step 3: Implement**

In `app/handbrake_tuner/protocol.py`, change the dataclass:

```python
@dataclass(frozen=True)
class Telemetry:
    """Mesure temps réel (ligne ``T …``)."""

    raw: int
    out: float
    axis: int
    sensor: bool = True

    def as_dict(self) -> dict:
        return {
            "raw": self.raw,
            "out": self.out,
            "axis": self.axis,
            "sensor": self.sensor,
        }
```

(In the translation pass this docstring becomes "Real-time measurement (line ``T ...``)." — for now only the `sensor` field changes; the docstring stays as-is to keep the diff focused.)

In `parse_line`, change the `T` branch to:

```python
    if tag == "T":
        fields = _fields(parts[1:])
        try:
            return Telemetry(
                raw=int(fields["raw"]),
                out=float(fields["out"]),
                axis=int(fields["axis"]),
                sensor=fields.get("s", "1") == "1",
            )
        except (KeyError, ValueError):
            return None
```

- [ ] **Step 4: Run the app tests, expect green**

Run: `app/.venv/bin/python -m pytest app/tests -q`
Expected: all pass, including the pre-existing `test_parse_telemetry` (dataclass equality still holds with the defaulted field).

- [ ] **Step 5: Commit**

```bash
git add app/handbrake_tuner/protocol.py app/tests/test_protocol.py
git commit -m "feat(app): parse the optional sensor flag in telemetry lines"
```

---

### Task 4: App — dead-link detection and port identifiers in the serial layer

**Files:**
- Modify: `app/handbrake_tuner/link.py` (`SerialLink.dead`, `request()`, `_describe`)
- Test: `app/tests/test_link.py` (three new tests), `app/tests/test_ports.py` (one new test)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SerialLink.dead: bool` (True when the read thread is gone), `request()` raising `LinkError("link is down")` immediately on a dead link, and the port dicts from `list_ports()` gaining `"vid"` / `"pid"` keys (`None` when unknown) — all consumed by the `LinkManager` in Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_link.py`:

```python
# --- Dead link -------------------------------------------------------------


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
```

(`FakeBoard` must be importable there: add `from fake_board import FakeBoard` to the imports if the file does not import it yet — it currently does not.)

Append to `app/tests/test_ports.py`:

```python
def test_port_dict_exposes_vid_pid(fake_comports):
    """The manager recognizes the board by its USB identifier."""
    fake_comports.append(
        FakePort("/dev/ttyACM0", "Pro Micro", vid=0x2341, pid=0x8037)
    )
    port = link.list_ports()[0]
    assert port["vid"] == 0x2341
    assert port["pid"] == 0x8037
```

- [ ] **Step 2: Run the tests, expect failure**

Run: `app/.venv/bin/python -m pytest app/tests/test_link.py app/tests/test_ports.py -q`
Expected: the four new tests fail (`dead` does not exist / `KeyError: 'vid'`), the rest passes.

- [ ] **Step 3: Implement**

In `app/handbrake_tuner/link.py`:

1. Add the property in the `# --- État ---` section:

```python
    @property
    def dead(self) -> bool:
        """Le thread de lecture est mort : le transport a échoué (carte
        débranchée) ou la liaison a été fermée. Elle est inutilisable ; le
        manager de liaison (manager.py) s'occupe du nettoyage."""
        thread = self._thread
        return thread is None or not thread.is_alive()
```

(The docstring is translated in Task 9; it is French here so the diff stays focused on behavior.)

2. At the top of `request()`, before the stale-reply drain:

```python
        if self.dead:
            raise LinkError("link is down")
```

3. In `_describe`, add the two fields:

```python
    return {
        "device": port.device,
        "description": label,
        "hwid": port.hwid or "",
        "usb": port.vid is not None,
        "vid": port.vid,
        "pid": port.pid,
    }
```

- [ ] **Step 4: Run the app tests, expect green**

Run: `app/.venv/bin/python -m pytest app/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/handbrake_tuner/link.py app/tests/test_link.py app/tests/test_ports.py
git commit -m "feat(app): dead-link detection and port identifiers in the serial layer"
```

---

### Task 5: App — the automatic `LinkManager`

**Files:**
- Create: `app/handbrake_tuner/manager.py`
- Modify: `app/tests/conftest.py` (two new fixtures: `available`, `clock`)
- Modify: `app/tests/fake_board.py` (`readline` raises once closed)
- Test: `app/tests/test_manager.py` (new file)

**Interfaces:**
- Consumes: `link.list_ports()` port dicts with `vid`/`pid` (Task 4), `SerialLink.dead` (Task 4), `link.connect(port)` and `SerialLink.request_config/subscribe` (existing).
- Produces: `LinkManager(list_ports_fn, connect_fn, scan_interval=2.0, poll_interval=0.5)` with:
  - `start()` / `stop()` — background watchdog thread (daemon);
  - `run_once(now: float)` — one deterministic watchdog iteration (tests drive this directly, no thread);
  - `status() -> dict` — the `GET /api/status` payload: `connected`, `state` ∈ `connected|searching|busy|error`, `port`, `port_description`, `config`, `telemetry`, `last_error`, `axis_max`, `gamma_min`, `gamma_max`;
  - `link` property — the current `SerialLink` or `None`;
  - `request_config(command)` / `subscribe()` — raise `LinkError("not connected")` when no link.

- [ ] **Step 1: Make the fake board faithful to an unplug**

In `app/tests/fake_board.py`, replace `readline`:

```python
    def readline(self) -> bytes:
        if self._closed.is_set():
            raise OSError("port closed")
        try:
            return self._out.get(timeout=0.05)
        except queue.Empty:
            return b""
```

Rationale: a real unplug makes the read fail; the read thread then dies and `SerialLink.dead` becomes true. (Verified safe for the existing suite in Step 5.)

- [ ] **Step 2: Add the shared fixtures**

Append to `app/tests/conftest.py`:

```python
@pytest.fixture
def available():
    """The USB port list the link manager scans: one handbrake board."""
    return [
        {
            "device": "/dev/fake0",
            "description": "Arduino Leonardo [2341:8036]",
            "hwid": "USB VID:PID=2341:8036",
            "usb": True,
            "vid": 0x2341,
            "pid": 0x8036,
        }
    ]


@pytest.fixture
def clock():
    """A fake monotonic clock: call it to advance and get the new time.

    Drives the link manager deterministically, without threads or sleeps.
    """
    state = {"now": 100.0}

    def tick(seconds: float = 0.5) -> float:
        state["now"] += seconds
        return state["now"]

    return tick
```

- [ ] **Step 3: Write the failing tests**

Create `app/tests/test_manager.py`:

```python
"""Tests of the link manager: automatic connect / disconnect / reconnect.

The state machine is driven through run_once with the fake `clock` fixture:
no thread, no sleep, fully deterministic.
"""

from __future__ import annotations

import time

import pytest

from handbrake_tuner import protocol
from handbrake_tuner.link import LinkError, SerialLink
from handbrake_tuner.manager import LinkManager

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
```

- [ ] **Step 4: Run the tests, expect failure**

Run: `app/.venv/bin/python -m pytest app/tests/test_manager.py -q`
Expected: collection error, `handbrake_tuner.manager` does not exist.

- [ ] **Step 5: Implement the manager**

Create `app/handbrake_tuner/manager.py`:

```python
"""Link manager: the automatic connect / disconnect lifecycle of the board.

A background thread owns the serial link: it watches the USB ports, connects
as soon as the board appears, detects a dead link, and reconnects when the
board comes back. The HTTP layer only observes the state and sends commands
through the manager, so no two tabs or processes can fight over the port.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from . import protocol
from .link import LinkError, SerialLink

# USB identifiers of the boards the handbrake firmware targets.
KNOWN_BOARD_IDS = {
    (0x2341, 0x8036),  # Arduino Leonardo (bootloader of most Pro Micros)
    (0x2341, 0x8037),  # Arduino Micro
}

SCAN_INTERVAL = 2.0  # port scan period while not connected
POLL_INTERVAL = 0.5  # dead-link watchdog period


class LinkManager:
    """Owns the serial link: detects the board, connects, watches, reconnects.

    `run_once` takes a monotonic timestamp so tests drive the state machine
    deterministically; the background thread only loops over it.
    """

    def __init__(
        self,
        list_ports_fn: Callable[[], List[dict]],
        connect_fn: Callable[[str], SerialLink],
        scan_interval: float = SCAN_INTERVAL,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self._list_ports = list_ports_fn
        self._connect = connect_fn
        self._scan_interval = scan_interval
        self._poll_interval = poll_interval

        self._lock = threading.Lock()
        self._link: Optional[SerialLink] = None
        self._state = "searching"  # connected | searching | busy | error
        self._last_error: Optional[str] = None
        self._port: Optional[str] = None
        self._port_description: Optional[str] = None
        self._last_scan = 0.0
        self._thread: Optional[threading.Thread] = None

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Starts the background watchdog thread (daemon)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="link-manager", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops the watchdog and closes the link if any."""
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self._drop_link()

    def _run(self) -> None:
        while True:
            self.run_once(time.monotonic())
            time.sleep(self._poll_interval)

    # --- State machine -----------------------------------------------------

    def run_once(self, now: float) -> None:
        """One watchdog iteration.

        With a live link: drop it if it died. Without: scan the ports on the
        scan cadence and try to connect to the handbrake.
        """
        with self._lock:
            link = self._link
            if link is not None:
                dead, scan_due = link.dead, False
            else:
                dead = False
                scan_due = now - self._last_scan >= self._scan_interval
                if scan_due:
                    self._last_scan = now

        if dead:
            self._drop_link()
        elif scan_due:
            self._try_connect()

    def _try_connect(self) -> None:
        try:
            ports = [p for p in self._list_ports() if p.get("usb")]
        except Exception:
            ports = []

        known = [p for p in ports if self._board_id(p) in KNOWN_BOARD_IDS]
        if known:
            target = known[0]
        elif len(ports) == 1:
            target = ports[0]  # a clone reported under another identifier
        elif len(ports) > 1:
            self._set_error("multiple serial devices, cannot pick one")
            return
        else:
            self._set_searching()
            return

        self._set_state("busy")
        try:
            link = self._connect(target["device"])
        except LinkError as exc:
            self._set_error(str(exc))
            return

        with self._lock:
            self._link = link
            self._state = "connected"
            self._last_error = None
            self._port = target["device"]
            self._port_description = target.get("description") or None

    def _drop_link(self) -> None:
        """Closes the current link (if any) and goes back to searching."""
        with self._lock:
            link, self._link = self._link, None
            self._state = "searching"
            self._last_error = None
        if link is not None:
            link.close()

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def _set_searching(self) -> None:
        with self._lock:
            self._state = "searching"
            self._last_error = None

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._last_error = message

    @staticmethod
    def _board_id(port: dict):
        vid, pid = port.get("vid"), port.get("pid")
        if vid is None or pid is None:
            return None
        return (vid, pid)

    # --- Observation -------------------------------------------------------

    @property
    def link(self) -> Optional[SerialLink]:
        with self._lock:
            return self._link

    def status(self) -> dict:
        """State payload for GET /api/status."""
        with self._lock:
            link = self._link
            state = self._state
            last_error = self._last_error
            port = self._port
            port_description = self._port_description

        base = {
            "port": port,
            "port_description": port_description,
            "last_error": None if link is not None else last_error,
            "axis_max": protocol.AXIS_MAX,
            "gamma_min": protocol.GAMMA_MIN,
            "gamma_max": protocol.GAMMA_MAX,
        }
        if link is None:
            base.update(
                {
                    "connected": False,
                    "state": state,
                    "config": None,
                    "telemetry": None,
                }
            )
        else:
            config = link.config
            telemetry = link.telemetry
            base.update(
                {
                    "connected": True,
                    "state": "connected",
                    "config": config.as_dict() if config else None,
                    "telemetry": telemetry.as_dict() if telemetry else None,
                }
            )
        return base

    # --- Commands ------------------------------------------------------------

    def request_config(self, command: str):
        """Sends a command expected to answer with a CFG.

        Raises LinkError when not connected or when the dialog fails.
        """
        link = self.link
        if link is None:
            raise LinkError("not connected")
        return link.request_config(command)

    def subscribe(self):
        """Subscribes to the telemetry stream of the current link."""
        link = self.link
        if link is None:
            raise LinkError("not connected")
        return link.subscribe()
```

- [ ] **Step 6: Run the manager tests and the full app suite**

Run: `app/.venv/bin/python -m pytest app/tests -q`
Expected: all pass, including the pre-existing `test_link.py` and `test_server.py` (the fake-board readline change must not break them — if one does, fix the test to match the new, more faithful behavior; do not weaken the change).

- [ ] **Step 7: Commit**

```bash
git add app/handbrake_tuner/manager.py app/tests/conftest.py \
        app/tests/fake_board.py app/tests/test_manager.py
git commit -m "feat(app): automatic link manager (detect, connect, reconnect)"
```

---

### Task 6: App — HTTP API driven by the manager

**Files:**
- Modify: `app/handbrake_tuner/server.py` (full rewrite of the routing layer)
- Modify: `app/handbrake_tuner/__main__.py` (build and start the manager)
- Rewrite: `app/tests/test_server.py` (manager-based fixtures, new API surface)

**Interfaces:**
- Consumes: `LinkManager` (Task 5) — `status()`, `link`, `request_config()`, `subscribe()`; `SerialLink.unsubscribe()` (existing).
- Produces: the final HTTP surface used by Task 7's page:
  - `GET /api/status` — manager payload;
  - `GET /api/stream` — SSE telemetry, 409 when not connected, the stream ends when the link is replaced;
  - `POST /api/calibrate/min|max` — `{"value": <int>}` required;
  - `POST /api/curve`, `POST /api/gamma`, `POST /api/save|load|reset`, `GET /api/curve/preview` — unchanged;
  - `GET /api/ports`, `POST /api/connect`, `POST /api/disconnect` — **removed**.

- [ ] **Step 1: Rewrite the server tests**

Replace the whole of `app/tests/test_server.py` with:

```python
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
    first = next(stream)
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
```

- [ ] **Step 2: Run the tests, expect failure**

Run: `app/.venv/bin/python -m pytest app/tests/test_server.py -q`
Expected: failures — `create_app` still expects `state`/`connect_fn`/`list_ports_fn`, `/api/ports` still exists, calibrate still accepts no value.

- [ ] **Step 3: Rewrite the routing layer**

Replace the whole of `app/handbrake_tuner/server.py` with:

```python
"""Local server of the calibration app.

Listens on the loopback only: it is the support of a desktop interface, not a
network service. The link with the board is owned by a LinkManager (built and
started by __main__.py); this module only exposes it over HTTP.
"""

from __future__ import annotations

import json
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import protocol
from .link import LinkError
from .manager import LinkManager

WEB_DIR = Path(__file__).parent / "web"

# Interval of the SSE keep-alive comments. Without them, an intermediary or
# the browser may close a connection that stayed silent.
SSE_KEEPALIVE_SECONDS = 1.0


def create_app(manager: LinkManager) -> Flask:
    app = Flask(__name__, static_folder=None)

    # --- Interface ---------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    # --- Status ------------------------------------------------------------

    @app.get("/api/status")
    def api_status():
        return jsonify(manager.status())

    # --- Telemetry ---------------------------------------------------------

    @app.get("/api/stream")
    def api_stream():
        current = manager.link
        if current is None:
            return _error("not connected", 409)

        subscription = current.subscribe()

        def events():
            try:
                while True:
                    # The manager replaced the link (board unplugged then
                    # back): stop, so the client's EventSource reconnects
                    # and re-subscribes to the new link.
                    if manager.link is not current:
                        break
                    try:
                        message = subscription.get(
                            timeout=SSE_KEEPALIVE_SECONDS
                        )
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(message.as_dict())}\n\n"
            finally:
                current.unsubscribe(subscription)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Calibration -------------------------------------------------------

    @app.post("/api/calibrate/<string:bound>")
    def api_calibrate(bound: str):
        if bound not in ("min", "max"):
            return _error("unknown bound")

        payload = request.get_json(silent=True) or {}
        value = payload.get("value")
        if value is None:
            return _error("value required")
        try:
            value = int(value)
        except (TypeError, ValueError):
            return _error("invalid value")

        builder = protocol.cmd_set_min if bound == "min" else protocol.cmd_set_max
        return _apply(manager, builder(value))

    @app.post("/api/curve")
    def api_curve():
        payload = request.get_json(silent=True) or {}
        curve = str(payload.get("curve") or "").upper()
        if curve not in protocol.CURVES:
            return _error("unknown curve")

        gamma = payload.get("gamma")
        if gamma is not None:
            try:
                gamma = protocol.clamp_gamma(float(gamma))
            except (TypeError, ValueError):
                return _error("invalid gamma")

        return _apply(manager, protocol.cmd_set_curve(curve, gamma))

    @app.post("/api/gamma")
    def api_gamma():
        payload = request.get_json(silent=True) or {}
        try:
            gamma = protocol.clamp_gamma(float(payload.get("gamma")))
        except (TypeError, ValueError):
            return _error("invalid gamma")

        return _apply(manager, protocol.cmd_set_gamma(gamma))

    @app.post("/api/<any(save,load,reset):action>")
    def api_action(action: str):
        builder = {
            "save": protocol.cmd_save,
            "load": protocol.cmd_load,
            "reset": protocol.cmd_reset,
        }[action]
        return _apply(manager, builder())

    # --- Curve preview -----------------------------------------------------

    @app.get("/api/curve/preview")
    def api_curve_preview():
        curve = str(request.args.get("curve", "LINEAR")).upper()
        if curve not in protocol.CURVES:
            return _error("unknown curve")

        try:
            gamma = protocol.clamp_gamma(float(request.args.get("gamma", 1.0)))
        except (TypeError, ValueError):
            return _error("invalid gamma")

        return jsonify(
            {
                "curve": curve,
                "gamma": gamma,
                "points": protocol.curve_points(curve, gamma),
            }
        )

    return app


# --- Utilities ---------------------------------------------------------------


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


def _apply(manager: LinkManager, command: str):
    """Sends a command and returns the resulting configuration."""
    if manager.link is None:
        return _error("not connected", 409)
    try:
        config = manager.request_config(command)
    except LinkError as exc:
        return _error(str(exc), 502)
    return jsonify({"config": config.as_dict()})
```

- [ ] **Step 4: Rewire the entry point**

Replace the whole of `app/handbrake_tuner/__main__.py` with:

```python
"""Entry point: starts the local server and opens the interface.

The native window goes through pywebview, which reuses the system web engine
(WebKitGTK on Linux, WebView2 on Windows). When pywebview is missing, the app
falls back to the default browser instead of refusing to start.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

from .link import connect as connect_board
from .link import list_ports
from .manager import LinkManager
from .server import create_app

WINDOW_TITLE = "Handbrake calibration"
WINDOW_SIZE = (1024, 720)


def _free_port() -> int:
    """Reserves a system-assigned free port.

    A fixed port would clash with another instance or service; letting the
    system pick avoids hunting for a "probably free" one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app, port: int) -> None:
    # threaded: the SSE stream holds a connection for its whole life; a
    # single-threaded server would stop answering anything else meanwhile.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="handbrake-tuner",
        description="Calibration app for the simracing handbrake.",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="local HTTP port (0 = automatic)"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="open in the browser instead of a native window",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="start the server alone, without opening an interface",
    )
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    manager = LinkManager(list_ports_fn=list_ports, connect_fn=connect_board)
    app = create_app(manager)
    url = f"http://127.0.0.1:{port}/"
    manager.start()

    if args.no_window:
        print(f"Interface available at {url}")
        _serve(app, port)
        return 0

    server = threading.Thread(target=_serve, args=(app, port), daemon=True)
    server.start()

    if not args.browser:
        try:
            import webview  # type: ignore

            window = webview.create_window(
                WINDOW_TITLE, url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1]
            )
            webview.start()
            del window
            return 0
        except ImportError:
            print(
                "pywebview missing, opening in the browser "
                "(pip install 'handbrake-tuner[desktop]' for a native window).",
                file=sys.stderr,
            )

    print(f"Interface available at {url}")
    webbrowser.open(url)
    try:
        server.join()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the app tests, expect green**

Run: `app/.venv/bin/python -m pytest app/tests -q`
Expected: all pass.

- [ ] **Step 6: Smoke-test the real entry point**

Run: `app/.venv/bin/python -m handbrake_tuner --no-window --port 8901` (background), then `curl -s http://127.0.0.1:8901/api/status` and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8901/`.
Expected: the status JSON shows `"connected": false` with `"state": "searching"` (no board) or `"connected": true` if the board is plugged in; the page answers 200. Then stop the background process.

- [ ] **Step 7: Commit**

```bash
git add app/handbrake_tuner/server.py app/handbrake_tuner/__main__.py \
        app/tests/test_server.py
git commit -m "feat(app): HTTP API driven by the link manager"
```

---

### Task 7: UI — status panel, editable range fields, English page

**Files:**
- Rewrite: `app/handbrake_tuner/web/index.html` (whole file)

**Interfaces:**
- Consumes: the HTTP surface of Task 6 — `GET /api/status` (polled at 1 Hz), `GET /api/stream` (one EventSource for the page life), `POST /api/calibrate/min|max` with `{"value": <int>}`, the unchanged curve/gamma/save/load/reset/preview endpoints.
- Produces: the page used by the user (Task 12 verifies it by hand on hardware).

- [ ] **Step 1: Replace the whole of `index.html`**

The file below is complete; it keeps the existing visual system (dark theme, panels) and the curve preview, drops the manual connection machinery, and adds the status panel, the editable range fields, and the sensor warning.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Handbrake calibration</title>
<style>
  :root {
    --bg: #12151a;
    --panel: #1a1e26;
    --panel-alt: #21262f;
    --line: #2c323d;
    --text: #e4e8ef;
    --muted: #8b95a7;
    --accent: #4da3ff;
    --accent-dim: #2d6ba8;
    --ok: #45c37a;
    --warn: #e0a33e;
    --err: #e05c5c;
    --mono: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    padding: 24px;
    background: var(--bg);
    color: var(--text);
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }

  h1 {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    margin: 0 0 20px;
    color: var(--muted);
  }

  h2 {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 0 0 14px;
  }

  .layout { display: grid; gap: 16px; max-width: 1100px; margin: 0 auto; }
  @media (min-width: 860px) { .layout { grid-template-columns: 1fr 1fr; } }
  .span-2 { grid-column: 1 / -1; }

  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px;
  }

  /* --- Status ------------------------------------------------------------ */

  #link-status { font-size: 14px; min-height: 20px; }
  #link-status.ok  { color: var(--ok); }
  #link-status.err { color: var(--err); }

  /* --- Live measurement ---------------------------------------------------- */

  .readouts { display: flex; gap: 28px; margin-bottom: 16px; flex-wrap: wrap; }
  .readout .label {
    font-size: 10px; letter-spacing: .1em; text-transform: uppercase;
    color: var(--muted);
  }
  .readout .value {
    font-family: var(--mono);
    font-size: 26px;
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
  }

  .sensor-warn { color: var(--warn); font-size: 12px; margin: 0 0 10px; }
  .hidden { display: none; }

  .bar {
    height: 30px;
    background: var(--panel-alt);
    border: 1px solid var(--line);
    border-radius: 6px;
    overflow: hidden;
    position: relative;
  }
  .bar-fill {
    height: 100%;
    width: 0;
    background: linear-gradient(90deg, var(--accent-dim), var(--accent));
    transition: width .05s linear;
  }
  .bar-pct {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono); font-size: 12px;
    text-shadow: 0 1px 3px rgba(0,0,0,.7);
  }

  /* --- Calibration ---------------------------------------------------------- */

  .calib-row {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }
  .calib-row:last-of-type { border-bottom: none; }
  .calib-row .name { width: 74px; color: var(--muted); font-size: 13px; }
  .calib-row input[type=number] {
    flex: 1;
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
    color: var(--text);
    background: var(--panel-alt);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 8px 10px;
  }
  .calib-row input[type=number]:focus { outline: none; border-color: var(--accent-dim); }
  .hint { color: var(--muted); font-size: 12px; margin: 12px 0 0; }

  /* --- Curve ----------------------------------------------------------------- */

  .curve-tabs { display: flex; gap: 6px; margin-bottom: 16px; }
  .curve-tabs button {
    flex: 1; font: inherit;
    color: var(--text);
    background: var(--panel-alt);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 8px 12px;
    cursor: pointer;
  }
  .curve-tabs button[aria-pressed="true"] {
    background: var(--accent-dim); border-color: var(--accent-dim);
  }
  .gamma-row { display: flex; align-items: center; gap: 12px; }
  .gamma-row input[type=range] { flex: 1; accent-color: var(--accent); }
  .gamma-value {
    font-family: var(--mono); font-variant-numeric: tabular-nums;
    min-width: 48px; text-align: right;
  }
  #curve-canvas {
    width: 100%; height: 200px; display: block; margin-top: 14px;
    background: var(--panel-alt);
    border: 1px solid var(--line); border-radius: 6px;
  }
  .gamma-note { color: var(--muted); font-size: 12px; margin: 10px 0 0; min-height: 32px; }

  /* --- Persistence ------------------------------------------------------------- */

  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .actions button {
    font: inherit;
    color: var(--text);
    background: var(--panel-alt);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 8px 12px;
    cursor: pointer;
  }
  .actions button:hover:not(:disabled) { border-color: var(--accent-dim); }
  .actions button:disabled { opacity: .4; cursor: not-allowed; }
  .actions button.primary { background: var(--accent-dim); border-color: var(--accent-dim); }
  .actions button.primary:hover:not(:disabled) { background: var(--accent); border-color: var(--accent); }
  .dirty-flag { color: var(--warn); font-size: 12px; margin-top: 12px; min-height: 18px; }

  /* --- Status bar ---------------------------------------------------------------- */

  #status {
    margin-top: 16px; padding: 10px 14px; border-radius: 6px;
    font-size: 13px; min-height: 40px;
    background: var(--panel); border: 1px solid var(--line);
  }
  #status.ok  { color: var(--ok);   border-color: #2a5a3f; }
  #status.err { color: var(--err);  border-color: #6a3232; }
  .offline { opacity: .45; pointer-events: none; }
</style>
</head>
<body>

<div class="layout">

  <h1 class="span-2">Handbrake — calibration</h1>

  <section class="panel span-2">
    <h2>Status</h2>
    <div id="link-status">Connecting…</div>
  </section>

  <section class="panel span-2" id="live-panel">
    <h2>Measurement</h2>
    <p class="sensor-warn hidden" id="sensor-warn">Sensor: no valid data</p>
    <div class="readouts">
      <div class="readout">
        <div class="label">Raw value</div>
        <div class="value" id="raw">—</div>
      </div>
      <div class="readout">
        <div class="label">HID axis</div>
        <div class="value" id="axis">—</div>
      </div>
      <div class="readout">
        <div class="label">Output</div>
        <div class="value" id="out">—</div>
      </div>
    </div>
    <div class="bar"><div class="bar-fill" id="bar"></div><div class="bar-pct" id="bar-pct"></div></div>
  </section>

  <section class="panel" id="calib-panel">
    <h2>Range</h2>
    <div class="calib-row">
      <span class="name">Minimum</span>
      <input type="number" id="raw-min" min="-8388608" max="8388607" step="1" disabled>
    </div>
    <div class="calib-row">
      <span class="name">Maximum</span>
      <input type="number" id="raw-max" min="-8388608" max="8388607" step="1" disabled>
    </div>
    <p class="hint">
      Type the raw value each end of the stroke should map to: lever at rest
      for the minimum, full braking force for the maximum. The live raw value
      is in the Measurement panel above.
    </p>
  </section>

  <section class="panel" id="curve-panel">
    <h2>Response curve</h2>
    <div class="curve-tabs">
      <button data-curve="LINEAR" aria-pressed="false">Linear</button>
      <button data-curve="POWER" aria-pressed="false">Power</button>
      <button data-curve="SCURVE" aria-pressed="false">S-curve</button>
    </div>
    <div class="gamma-row">
      <span style="color:var(--muted)">gamma</span>
      <input type="range" id="gamma" min="0.10" max="5.00" step="0.05" value="1.00">
      <span class="gamma-value" id="gamma-value">1.00</span>
    </div>
    <p class="gamma-note" id="gamma-note"></p>
    <canvas id="curve-canvas" width="600" height="400"></canvas>
  </section>

  <section class="panel span-2" id="persist-panel">
    <h2>Storage</h2>
    <div class="actions">
      <button id="save" class="primary">Save to the board</button>
      <button id="load">Reload last save</button>
      <button id="reset">Defaults</button>
    </div>
    <div class="dirty-flag" id="dirty"></div>
    <p class="hint">
      Changes apply immediately but live in RAM only. Without a save they are
      lost when the board is unplugged — the EEPROM is written on demand only,
      so it is not worn out by every slider move.
    </p>
  </section>

  <div class="span-2" id="status">—</div>
</div>

<script>
"use strict";

const el = (id) => document.getElementById(id);

const state = {
  status: null,     /* last /api/status payload */
  config: null,
  telemetry: null,
  dirty: false,
  events: null,
};

/* HX711 24-bit signed range: the same bounds the firmware clamps to. */
const RAW_MIN = -8388608;
const RAW_MAX = 8388607;

const GAMMA_NOTES = {
  LINEAR: "Output proportional to force. The neutral reference point.",
  POWER: "gamma < 1: biting from the start of the stroke. " +
         "gamma > 1: progressive, more precision at the start.",
  SCURVE: "gamma > 1: soft at the ends, firm in the middle. " +
          "gamma < 1: the reverse.",
};

/* --- API calls ---------------------------------------------------------- */

async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `error ${response.status}`);
  }
  return payload;
}

const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

function setStatus(message, kind) {
  const node = el("status");
  node.textContent = message;
  node.className = kind || "";
}

async function guard(action, successMessage) {
  try {
    const result = await action();
    if (successMessage) setStatus(successMessage, "ok");
    return result;
  } catch (error) {
    setStatus(error.message, "err");
    return null;
  }
}

/* --- Rendering ----------------------------------------------------------- */

function renderStatus() {
  const status = state.status;
  const node = el("link-status");
  if (!status) return;

  if (status.connected) {
    const extra = status.port_description ? ` (${status.port_description})` : "";
    node.textContent = `Connected: ${status.port}${extra}`;
    node.className = "ok";
  } else if (status.state === "busy") {
    node.textContent = "Connecting…";
    node.className = "";
  } else if (status.state === "searching") {
    node.textContent = "Searching for the board…";
    node.className = "";
  } else {
    node.textContent = status.last_error || "Not connected.";
    node.className = "err";
  }

  const offline = !status.connected;
  for (const id of ["live-panel", "calib-panel", "curve-panel", "persist-panel"]) {
    el(id).classList.toggle("offline", offline);
  }
  el("raw-min").disabled = offline;
  el("raw-max").disabled = offline;
}

function renderConfig() {
  const config = state.config;
  if (!config) return;

  /* Resync from the board, except the field currently being edited. */
  if (document.activeElement !== el("raw-min")) {
    el("raw-min").value = config.raw_min;
  }
  if (document.activeElement !== el("raw-max")) {
    el("raw-max").value = config.raw_max;
  }

  for (const button of document.querySelectorAll(".curve-tabs button")) {
    button.setAttribute("aria-pressed", String(button.dataset.curve === config.curve));
  }

  el("gamma").value = config.gamma.toFixed(2);
  el("gamma-value").textContent = config.gamma.toFixed(2);
  el("gamma").disabled = config.curve === "LINEAR";
  el("gamma-note").textContent = GAMMA_NOTES[config.curve] || "";

  if (!config.calibrated) {
    setStatus("Board not calibrated: set the minimum and the maximum first.", "err");
  }
  drawCurve();
}

function renderTelemetry() {
  const telemetry = state.telemetry;
  if (!telemetry) return;

  el("raw").textContent = telemetry.raw.toLocaleString("en-US");
  el("axis").textContent = telemetry.axis;
  el("out").textContent = telemetry.out.toFixed(3);
  el("sensor-warn").classList.toggle("hidden", telemetry.sensor !== false);

  const percent = telemetry.out * 100;
  el("bar").style.width = percent + "%";
  el("bar-pct").textContent = percent.toFixed(1) + " %";
  drawCurve();
}

function setDirty(value) {
  state.dirty = value;
  el("dirty").textContent = value
    ? "Unsaved changes on the board."
    : "";
}

/* --- Range fields ---------------------------------------------------------- */

/* Commits the edited bound. `change` fires on Enter or on blur, and only
   when the value actually changed. */
async function commitBound(id, bound) {
  const field = el(id);
  const text = field.value.trim();
  if (!/^-?\d+$/.test(text)) {
    setStatus("Range value must be an integer.", "err");
    return;
  }
  const value = parseInt(text, 10);
  if (value < RAW_MIN || value > RAW_MAX) {
    setStatus("Range value outside the HX711 24-bit range.", "err");
    return;
  }
  const current = state.config
    ? (bound === "min" ? state.config.raw_min : state.config.raw_max)
    : null;
  if (value === current) return;

  const data = await guard(() => post(`/api/calibrate/${bound}`, { value }));
  if (!data) {
    field.value = current === null ? "" : current; /* revert */
    return;
  }
  state.config = data.config;
  renderConfig();
  setDirty(true);
}

/* --- Curve preview --------------------------------------------------------- */

/* Mirror of hb_curve_apply (firmware) and protocol.apply_curve (server):
   the preview must show exactly what the board computes. */
function applyCurve(curve, gamma, t) {
  t = Math.max(0, Math.min(1, t));
  if (curve === "POWER") return Math.pow(t, gamma);
  if (curve === "SCURVE") {
    return t < 0.5
      ? 0.5 * Math.pow(2 * t, gamma)
      : 1 - 0.5 * Math.pow(2 * (1 - t), gamma);
  }
  return t;
}

function currentPosition() {
  const config = state.config;
  const telemetry = state.telemetry;
  if (!config || !telemetry) return null;

  const span = config.raw_max - config.raw_min;
  if (span === 0) return null;
  const t = Math.max(0, Math.min(1, (telemetry.raw - config.raw_min) / span));
  return { t, out: telemetry.out };
}

function drawCurve() {
  const canvas = el("curve-canvas");
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = 28;

  const curve = state.config ? state.config.curve : "LINEAR";
  const gamma = parseFloat(el("gamma").value);

  const x = (t) => pad + t * (width - 2 * pad);
  const y = (v) => height - pad - v * (height - 2 * pad);

  context.clearRect(0, 0, width, height);

  // Quarter grid
  context.strokeStyle = "#2c323d";
  context.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const f = i / 4;
    context.beginPath();
    context.moveTo(x(f), y(0)); context.lineTo(x(f), y(1));
    context.moveTo(x(0), y(f)); context.lineTo(x(1), y(f));
    context.stroke();
  }

  // Reference diagonal: visual mark of the linear response
  context.strokeStyle = "#3a424f";
  context.setLineDash([5, 5]);
  context.beginPath();
  context.moveTo(x(0), y(0));
  context.lineTo(x(1), y(1));
  context.stroke();
  context.setLineDash([]);

  // Curve
  context.strokeStyle = "#4da3ff";
  context.lineWidth = 2.5;
  context.beginPath();
  for (let i = 0; i <= 100; i++) {
    const t = i / 100;
    const point = applyCurve(curve, gamma, t);
    if (i === 0) context.moveTo(x(t), y(point));
    else context.lineTo(x(t), y(point));
  }
  context.stroke();

  // Current position
  const position = currentPosition();
  if (position) {
    context.strokeStyle = "#45c37a";
    context.lineWidth = 1;
    context.setLineDash([3, 3]);
    context.beginPath();
    context.moveTo(x(position.t), y(0)); context.lineTo(x(position.t), y(position.out));
    context.moveTo(x(0), y(position.out)); context.lineTo(x(position.t), y(position.out));
    context.stroke();
    context.setLineDash([]);

    context.fillStyle = "#45c37a";
    context.beginPath();
    context.arc(x(position.t), y(position.out), 5, 0, Math.PI * 2);
    context.fill();
  }

  // Axis labels
  context.fillStyle = "#8b95a7";
  context.font = "11px system-ui, sans-serif";
  context.fillText("force →", x(0.5) - 20, height - 8);
  context.save();
  context.translate(11, y(0.5) + 22);
  context.rotate(-Math.PI / 2);
  context.fillText("output →", 0, 0);
  context.restore();
}

/* --- Actions ---------------------------------------------------------------- */

function adoptConfig(data, message) {
  if (!data) return;
  state.config = data.config;
  renderConfig();
  setDirty(true);
  if (message) setStatus(message, "ok");
}

for (const button of document.querySelectorAll(".curve-tabs button")) {
  button.addEventListener("click", async () => {
    const curve = button.dataset.curve;
    adoptConfig(
      await guard(() => post("/api/curve", {
        curve,
        gamma: parseFloat(el("gamma").value),
      })),
      `Curve: ${button.textContent}.`
    );
  });
}

/* The slider redraws the preview on every pixel but only writes to the
   serial port on release: sending on every move would saturate the link
   without any perceptible gain. */
el("gamma").addEventListener("input", () => {
  el("gamma-value").textContent = parseFloat(el("gamma").value).toFixed(2);
  drawCurve();
});

el("gamma").addEventListener("change", async () => {
  adoptConfig(
    await guard(() => post("/api/gamma", { gamma: parseFloat(el("gamma").value) }))
  );
});

el("save").addEventListener("click", async () => {
  const data = await guard(() => post("/api/save"));
  if (!data) return;
  state.config = data.config;
  renderConfig();
  setDirty(false);
  setStatus("Configuration saved to the board.", "ok");
});

el("load").addEventListener("click", async () => {
  const data = await guard(() => post("/api/load"));
  if (!data) return;
  state.config = data.config;
  renderConfig();
  setDirty(false);
  setStatus("Last save reloaded.", "ok");
});

el("reset").addEventListener("click", async () => {
  const data = await guard(() => post("/api/reset"));
  if (!data) return;
  state.config = data.config;
  renderConfig();
  setDirty(true);
  setStatus("Defaults loaded. Save to keep them.", "ok");
});

for (const [id, bound] of [["raw-min", "min"], ["raw-max", "max"]]) {
  el(id).addEventListener("change", () => commitBound(id, bound));
}

/* --- Telemetry stream --------------------------------------------------------- */

function openStream() {
  state.events = new EventSource("/api/stream");
  state.events.onmessage = (event) => {
    state.telemetry = JSON.parse(event.data);
    renderTelemetry();
  };
  /* onerror: the EventSource reconnects by itself. The server answers 409
     until the link manager is back up; the next retry picks the link up. */
}

/* --- Status polling ----------------------------------------------------------- */

async function pollStatus() {
  let data;
  try {
    data = await api("/api/status");
  } catch (error) {
    return; /* server unreachable: keep the current UI */
  }

  const wasConnected = state.status ? state.status.connected : false;
  state.status = data;
  state.config = data.config;
  if (wasConnected && !data.connected) {
    setDirty(false); /* the RAM settings were lost with the board */
  }
  renderStatus();
  renderConfig();
}

/* --- Boot ---------------------------------------------------------------------- */

(async function boot() {
  openStream();
  await pollStatus();
  drawCurve();
  setInterval(pollStatus, 1000);
})();

window.addEventListener("beforeunload", () => {
  if (state.events) {
    state.events.close();
    state.events = null;
  }
});
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the page and the server together**

Run: `app/.venv/bin/python -m pytest app/tests -q` (must stay green), then start `app/.venv/bin/python -m handbrake_tuner --no-window --port 8902` in the background and check:

- `curl -s http://127.0.0.1:8902/ | grep -c 'lang="en"'` returns 1;
- `grep -c "Définir ici" app/handbrake_tuner/web/index.html` returns 0;
- `curl -s http://127.0.0.1:8902/api/status` shows the manager state.

With the real board plugged in, the status line flips to `Connected: …` within a few seconds without any click. Stop the background process.

- [ ] **Step 3: Commit**

```bash
git add app/handbrake_tuner/web/index.html
git commit -m "feat(app): auto-connect UI with editable calibration range"
```

---

### Task 8: Docs — README in English, updated for the automatic link

**Files:**
- Modify: `README.md` (full translation + content updates)

**Interfaces:**
- Consumes: the behavior of Tasks 1-7 (automatic link, `s` field, editable fields, no manual endpoints).
- Produces: the user-facing documentation. The test-count table is refreshed in Task 12 (the counts move while the suites evolve).

- [ ] **Step 1: Translate and update the README**

Translate the whole of `README.md` to English, keeping the structure, the tables, the code blocks, and every command exactly as they are (commands, paths, and identifiers are not translated). Then apply these content updates:

1. **État table** → rename to **Status**; keep the rows, translate them. Do not touch the numeric test counts yet (Task 12 refreshes them).
2. **App de calibration → "Calibration app"**: the startup commands are unchanged; the *Procédure de calibration* section becomes:

   ```markdown
   ### Calibration procedure

   1. Plug the board and start the app: the status panel shows
      "Searching for the board…" until it connects (a few seconds). No
      connect/disconnect buttons anymore.
   2. Lever at rest: type the raw value shown in the Measurement panel into
      the **Minimum** field, then press Enter.
   3. Pull with the force that should mean full brake: type that raw value
      into the **Maximum** field, then press Enter.
   4. Try the curves and the gamma slider until the feel is right.
   5. **Save to the board**.

   Without step 5, the settings are lost when the board is unplugged: the
   EEPROM is written on demand only, so it is not worn out by every slider
   move.
   ```
3. **Protocole série → "Serial protocol"**: translate the table, and change the telemetry line to `T raw=… out=… axis=… s=1|0` with a note: "s=0 when there is no valid sample (stuck sensor or sensor absent); older boards omit the field."
4. The curve table, the flashing / prerequisites / VS Code sections: faithful translation, no content change.

- [ ] **Step 2: Check for leftovers**

Run: `grep -nP '[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ…«»]' README.md`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README in English, updated for the automatic link"
```

---

### Task 9: English pass — app (Python, tests, pyproject, Makefile, VS Code)

**Files:**
- Modify: `app/handbrake_tuner/{__init__.py,link.py,protocol.py}`, `app/tests/{conftest.py,fake_board.py,test_link.py,test_protocol.py,test_ports.py,test_open_errors.py,test_curve.py}`, `app/pyproject.toml`, `Makefile`, `.vscode/*.json` (the files that contain French)

**Interfaces:**
- Consumes: the English error strings below (the tests assert on them).
- Produces: no new behavior. The test count must be identical before and after (the gate below).

- [ ] **Step 1: Record the baseline test count**

Run: `app/.venv/bin/python -m pytest app/tests -q --collect-only | tail -1`
Note the number of tests collected.

- [ ] **Step 2: Translate `link.py`**

- Module docstring → "Serial link with the board." plus the existing rationale in English.
- All inline comments → English.
- User-facing strings, exactly these:
  - `send()`: `f"cannot write: {exc}"`
  - `request()` timeout: `f"no reply to {command}"` (keep the `link is down` message from Task 4)
  - `request_config()`: `"the board did not answer"`, `"unreadable configuration"`
  - `open_serial()` ImportError: `"pyserial is not installed (pip install pyserial)"`
  - `connect()`: `"the board did not answer"`
  - `_open_failure_hint()`:

    ```python
    def _open_failure_hint(port: str, exc: Exception) -> str:
        """Actionable open-failure message.

        Each open error has a dominant cause and a known fix. Returning the
        raw error ("[Errno 13] Permission denied") leaves the user hunting
        for what the program already knows.
        """
        code = getattr(exc, "errno", None)

        if code == errno.EACCES:
            if sys.platform.startswith("linux"):
                return (
                    f"access to {port} denied. On Linux, serial port access "
                    "goes through the dialout group: "
                    "sudo usermod -aG dialout $USER, then log out and log "
                    "back in. An application started before that step keeps "
                    "its old credentials and must be fully restarted."
                )
            return f"access to {port} denied. Check the port permissions."

        if code == errno.EBUSY:
            return (
                f"{port} is already open by another program "
                "(serial monitor, another app instance...)."
            )

        if code == errno.ENOENT:
            return (
                f"{port} does not exist. Was the board unplugged, or did "
                "the port change its name?"
            )

        return f"cannot open {port}: {exc}"
    ```

- [ ] **Step 3: Translate `protocol.py` and `__init__.py`**

- Module docstrings and all comments → English (the header must keep the note that the file mirrors `hb_protocol.c` and that the curves are re-implemented on purpose).
- `cmd_set_curve` error: `f"unknown curve: {curve}"`.
- `clamp_gamma` docstring → "Applies the same bounds as ``hb_config_sanitize``."
- `__init__.py` docstring → "Calibration app for the simracing handbrake."

- [ ] **Step 4: Translate the tests (names + docstrings + asserted strings)**

For each file, rename the French test functions to English snake_case (e.g. `test_telemetrie_alimente_l_etat` → `test_telemetry_feeds_the_state`, `test_insensible_a_la_casse` → `test_case_insensitive`), translate docstrings and comments, and rename local French names (the `Cassé` class in `test_link.py` becomes `Broken`; the message `"carte débranchée"` becomes `"board unplugged"`).

The assertions that track the strings of Step 2 must be updated:

- `test_link.py`: `match="cannot write"`, `match="no reply"`, `"unplugged" in connection.last_error`
- `test_open_errors.py`: `"dialout" in message`, `"usermod" in message`, `"restarted" in message`, `"another program" in message`, `"does not exist" in message`, `"boom" in message`, `"/dev/ttyACM0" in message`; the `FakeSerialException` and `RuntimeError` fake messages become English (`"boom"`, `"error"`)
- `fake_board.py`: docstrings → English; the `write()` error message → `"port closed"` (the `readline()` message from Task 5 is already English)
- `test_ports.py`, `test_protocol.py`, `test_curve.py`, `conftest.py`: docstrings and comments only (the `available`/`clock` fixtures added in Task 5 are already English).

- [ ] **Step 5: Translate `pyproject.toml`, the root `Makefile`, and the VS Code files**

- `pyproject.toml`: `description = "Calibration app for the simracing handbrake"`; the `desktop` extra comment → English.
- `Makefile`: all comments and echo strings → English (e.g. `@echo "make test           run both test suites"`, the `dialout`-free help lines, `Indiquez le port` → "Specify the port: make flash PORT=/dev/ttyACM0", `Création de l'environnement Python…` → "Creating the Python environment...").
- `.vscode/tasks.json` / `launch.json` / `c_cpp_properties.json`: grep for French labels/descriptions and translate them (keep the `type` and tooling fields untouched).

- [ ] **Step 6: Verify behavior is unchanged**

Run:
- `app/.venv/bin/python -m pytest app/tests -q` → all pass, and the collected count equals the Step 1 baseline;
- `grep -rnP '[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ…«»]' app/ Makefile .vscode/ --exclude-dir=.venv --exclude-dir=.pytest_cache` → no output.

- [ ] **Step 7: Commit**

```bash
git add app/handbrake_tuner app/tests app/pyproject.toml Makefile .vscode
git commit -m "chore(app): English pass over the app, its tests, and the Makefile"
```

---

### Task 10: English pass — firmware and C tests

**Files:**
- Modify: `firmware/handbrake/{config.h,handbrake.ino,hb_core.h,hb_core.c,hb_protocol.h,hb_protocol.c,hb_record.h,hb_record.c,hb_storage.h,hb_storage.cpp,hx711.h,hx711.cpp}`, `tests/{test_hb_core.c,test_hb_protocol.c,test_hb_record.c,test_harness.h,Makefile}`

**Interfaces:**
- Consumes: nothing.
- Produces: no behavior change. The assertion counts printed by `TEST_SUMMARY` are identical before and after; the compiler catches any RUN-list mismatch.

- [ ] **Step 1: Record the baseline assertion counts**

Run: `make -C tests test 2>&1 | grep -E 'assertions'`
Note the three counts.

- [ ] **Step 2: Translate the firmware comments**

Translate every French comment in the 12 firmware files to English, preserving the technical reasoning (the comments carry the design rationale: why the pull-up, why interrupts are off during the HX711 frame, why `EEPROM.update`, why no `%f`, etc.). Code, identifiers, and macro values are untouched. Comments added by Tasks 1-2 are already English.

- [ ] **Step 3: Translate the C tests (comments + function names)**

In `tests/test_hb_core.c`, `test_hb_protocol.c`, and `test_hb_record.c`: translate comments and docstring-style headers, and rename every French `test_*` function to English snake_case, updating the matching `RUN(...)` line in the same file (the compiler catches a forgotten rename). Examples of the expected style:

- `test_commandes_simples` → `test_simple_commands`
- `test_insensible_a_la_casse` → `test_case_insensitive`
- `test_set_min_max_sans_argument` → `test_set_min_max_without_argument`
- `test_fmt_fixed_tampon_trop_petit` → `test_fmt_fixed_buffer_too_small`
- `test_linebuf_depassement` → `test_linebuf_overflow`
- `test_ema_reactivite_constante_production` → `test_ema_reactive_constant_production`

New tests from Tasks 1-2 are already English. In `test_harness.h`: translate the header comment and the `TEST_SUMMARY` format string (`"%s: %d assertions, %d failure(s)\n"`). In `tests/Makefile`: translate the header comment.

- [ ] **Step 4: Verify**

Run:
- `make test-firmware` → all pass, the three assertion counts equal the Step 1 baseline;
- `make build` → the sketch still compiles;
- `grep -rP '[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ…«»]' firmware/ tests/` → no output.

- [ ] **Step 5: Commit**

```bash
git add firmware tests
git commit -m "chore(firmware): English pass over the firmware and its tests"
```

---

### Task 11: English pass — design and wiring docs (+ new sections)

**Files:**
- Modify: `docs/design.md`, `docs/wiring.md`

**Interfaces:**
- Consumes: the mechanisms of Tasks 1-2 (stuck detection, `s` field) and 5-6 (link manager).
- Produces: the English design documentation with two new sections.

- [ ] **Step 1: Translate `docs/wiring.md`**

Faithful translation; the wiring tables, commands, and component names are untouched.

- [ ] **Step 2: Translate `docs/design.md`**

Faithful translation of the whole document (keep the section numbering scheme, the ASCII diagrams, and all code snippets).

- [ ] **Step 3: Add the two new sections**

Add the following as new top-level sections at the end of the firmware part and the app part of `docs/design.md` (numbered to continue the existing scheme; move them earlier if the document is organized by layer):

Firmware part:

```markdown
## Stuck-sensor detection

A raw value that is bit-identical for `HB_STUCK_TIMEOUT_MS` (1 s) is
declared a stuck sensor. Rationale: a healthy HX711 at gain 128 has
permanent LSB jitter, so a value that does not move at all for a second is
a failure signature (DOUT line stuck low, converter locked), never a quiet
sensor. The threshold is in time, not in sample count, so it behaves the
same at any effective rate.

When stuck, the firmware treats the sensor as absent: the axis falls to 0
instead of freezing, the EMA is reset and a warmup restarts. The first
different sample clears the condition automatically. `SET MIN` / `SET MAX`
already refuse to capture without a valid sample, so a stuck sensor cannot
poison a calibration.

The telemetry line reports the condition with the `s` field (`s=0`: no
valid sample, stuck or absent). The field is optional on the wire: old
hosts ignore it, and the app parser defaults a missing `s` to 1.
```

App part:

```markdown
## Link manager

The app owns the serial link through a background thread (`LinkManager`):

- every ~2 s it scans the USB serial ports and connects to the board,
  recognized by its USB identifier (Arduino 2341:8036 / 2341:8037), or by
  the lone USB serial port when no known board is present; several unknown
  ports are refused with an explicit error;
- a watchdog checks the read thread every ~0.5 s: when the board is
  unplugged the link is dropped and the manager goes back to searching;
- when the board comes back it is reconnected automatically (worst case a
  few seconds after the replug).

The web page only observes: it polls `/api/status` at 1 Hz and keeps one
EventSource on `/api/stream`. When the link is replaced, the old stream
ends and the browser's EventSource re-subscribes to the new link on its
own. Manual connect/disconnect endpoints no longer exist.
```

- [ ] **Step 4: Verify**

Run: `grep -rP '[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ…«»]' docs/design.md docs/wiring.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add docs/design.md docs/wiring.md
git commit -m "docs: design and wiring docs in English, new sensor and link sections"
```

---

### Task 12: Final gates — full suites, build, accent sweep, README counts

**Files:**
- Modify: `README.md` (test counts only, if they moved)

- [ ] **Step 1: Run both test suites and the firmware build**

Run: `make test && make build`
Expected: all native assertions pass, all pytest tests pass, the sketch compiles.

- [ ] **Step 2: Refresh the README test counts**

The README's Status table quotes assertion and test counts. Update them to the numbers printed in Step 1 (e.g. the `hb_*` suite totals and the pytest count).

- [ ] **Step 3: Full accent sweep**

Run:

```bash
grep -rP '[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ…«»]' \
  --include='*.py' --include='*.c' --include='*.h' --include='*.cpp' \
  --include='*.ino' --include='*.html' --include='*.md' \
  --include='*.toml' --include='*.json' --include='Makefile' . \
  | grep -v '^\./\.git/' | grep -v '^\./app/\.venv/' \
  | grep -v '^\./app/\.pytest_cache/' | grep -v '^\./\.remember/'
```

Expected: no output. (The `→` arrow in the curve canvas labels is deliberate and is not in the search set.)

- [ ] **Step 4: Check the tree is clean**

Run: `git status --short`
Expected: only the README count change (if any).

- [ ] **Step 5: Commit the count refresh, if changed**

```bash
git add README.md
git commit -m "docs: refresh test counts"
```

- [ ] **Step 6: Report**

Report to the user: the two suites and the build are green, the accent sweep is clean, the full English state of the repo, and the hardware verification checklist left for the user (from the spec): start the app with no board (status: "Searching for the board…"), plug the board (auto-connect), unplug / replug (auto-reconnect), calibrate with the editable fields (check with `GET` in a serial monitor), and if a freeze happens again, note whether the UI shows "Sensor: no valid data" and the axis falls to 0 — that tells us which side was at fault.
