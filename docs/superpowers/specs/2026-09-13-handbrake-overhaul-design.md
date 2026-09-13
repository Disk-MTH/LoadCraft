# Handbrake Overhaul — Design Spec

Date: 2026-09-13
Status: approved in brainstorming (sections 1-4), pending implementation

## 1. Context

The handbrake (load cell + HX711 + ATmega32u4 Pro Micro, USB HID + serial
calibration) now works on the replacement load cell: the axis tracks the
lever and calibration can be saved. Two problems remain:

1. **Intermittent freeze.** The measurement freezes on a fixed value for an
   unknown duration, then resumes on its own. Observed in the web UI; it is
   not known whether the in-game axis freezes too. Root-cause hypothesis
   (confirmed by code reading): when the HX711 DOUT line sticks LOW — or
   the chip locks on the same 24-bit output — `HX711::read()` "succeeds"
   with the same garbage value forever. The 500 ms no-conversion timeout in
   `handbrake.ino` never fires because `last_sample_ms` is refreshed on
   every (garbage) read, and `have_sample` stays true, so the axis is
   pinned. The existing timeout only covers DOUT stuck HIGH.
2. **Friction in the calibration app.** Manual Connect / Disconnect /
   Refresh buttons, a "set here" button that requires the lever to be in
   the exact state at click time, and a French UI despite the project's
   global rule (everything in English).

Requested work: a full audit of both code bases to simplify as much as
possible, an auto connect / auto disconnect layer with device detection,
editable calibration range fields, and an English pass over the whole
project.

## 2. Decisions (approved with the user, 2026-09-13)

| Decision | Choice |
|---|---|
| Auto-connect behavior | Full auto: detect by USB ID, connect on appearance, detect unplug, reconnect. No Connect/Disconnect/Refresh buttons in the UI. |
| Where the lifecycle lives | Server-side `LinkManager` in the Python app (background thread), not browser-driven. |
| Freeze fix | Firmware stuck-value detector (time-based) plus app-side dead-link detection (comes with the LinkManager). Both sides protected. |
| Calibration range | Editable numeric min/max fields, commit on Enter/blur; the "set here" buttons are removed. |
| Language | Everything in English (UI, comments, docs, tests, Makefiles). Git history untouched. |
| Serial protocol | Stable; only addition: an optional `s` field on telemetry lines. The bare `SET MIN` / `SET MAX` capture-current forms stay in the protocol for serial-monitor debugging; the app requires an explicit value. |

## 3. Design

### 3.1 Firmware — stuck sensor detection

Pure-C detector in `hb_core.c` (natively tested, like the rest of the core):

```c
typedef struct {
    int32_t   last;           /* last value seen */
    uint32_t  last_change_ms; /* timestamp of the last change */
    uint32_t  timeout_ms;     /* HB_STUCK_TIMEOUT_MS */
    int       primed;
} hb_stuck_t;

void hb_stuck_init(hb_stuck_t *s, uint32_t timeout_ms);
/* Feed a raw sample with its timestamp. Returns 1 while the value has
 * not changed for more than timeout_ms. */
int hb_stuck_push(hb_stuck_t *s, uint32_t now_ms, int32_t sample);
```

- **Time-based threshold, not a sample count.** A healthy HX711 at gain
  128 has permanent LSB jitter, so "raw value bit-identical for 1 s"
  (`HB_STUCK_TIMEOUT_MS 1000` in `config.h`) is a failure signature, never
  a quiet sensor. A sample-count threshold would take ~60 s to trigger at
  a 4 Hz effective rate on marginal hardware.
- While the value stays identical the push keeps returning 1; the first
  different sample returns 0 and resets the timer. No extra hysteresis.
- Integration in `handbrake.ino::poll_sensor`: on a valid read, feed the
  detector with `millis()`. If it reports stuck, treat it exactly like a
  missing sensor (`have_sample = 0`, EMA reset, warmup restart) → the axis
  drops to 0 instead of freezing, and recovers by itself once the value
  varies again. `SET MIN` / `SET MAX` already refuse to capture without a
  valid sample, so a stuck sensor can no longer poison calibration.
- Cost: ~16 bytes RAM, a few hundred bytes of flash.

### 3.2 Firmware — telemetry sensor flag

The telemetry line gains an optional sensor field:

```
T raw=... out=... axis=... s=1
```

`s=0` when there is no valid sample (stuck, or sensor-absent timeout). Old
hosts ignore unknown fields; the Python parser treats a missing `s` as 1.
This lets the UI show an explicit "Sensor: no valid data" warning instead
of a mysterious 0 % bar.

### 3.3 App — server-side LinkManager

A new module `manager.py` with a background thread owning the whole link
lifecycle. `TunerState` is removed.

**Detector (every ~2 s)** — scan USB serial ports (pyserial, existing
USB-only filter):

| Condition | Action |
|---|---|
| VID:PID `2341:8036` (Leonardo) or `2341:8037` (Micro) present | connect to it |
| no known board, exactly one USB serial port | connect to it (clone reported under another ID) |
| several unknown USB serial ports | do not connect; state `error`: "multiple serial devices, cannot pick one" |
| no USB serial port | state `searching` |

**Connect:** open port → start read thread → `GET` (2 s timeout) →
`STREAM 1`. Any failure (port busy, unresponsive board, board in bootloader
after a flash) → retry on the next scan; no aggressive retry loop. A board
sitting in bootloader mode answers nothing, attempts time out, and its
natural ~8 s auto-reboot leads to a successful connect.

**Dead-link watchdog (every ~0.5 s):** read thread dead or transport error
→ the link is declared dead, the transport is closed cleanly, state goes
back to `searching` (last port kept for diagnostics). Worst case ~4-6 s to
reconnect after a replug.

**Browser-independent:** the board stays connected even when the browser
is closed (the firmware works fine without serial, and the next page load
finds the link alive).

**HTTP API surface after the change:**

| Endpoint | Before | After |
|---|---|---|
| `GET /api/ports` | manual port list | removed |
| `POST /api/connect` | manual connect | removed |
| `POST /api/disconnect` | manual disconnect | removed |
| `GET /api/status` | connection state | kept; gains `state` ∈ `connected` / `searching` / `busy` (connect attempt in progress) / `error`, plus `last_error` and `port` + `port_description` when connected |
| `GET /api/stream` | SSE telemetry, 409 when not connected | unchanged (the EventSource retries on its own and picks the link up as soon as the manager reconnects) |
| `POST /api/calibrate/min\|max` | optional value (capture-current) | value **required**: `{"value": <int>}` |
| `POST /api/curve`, `POST /api/gamma`, `POST /api/save\|load\|reset`, `GET /api/curve/preview` | — | unchanged |

The manager takes injectable `list_ports_fn` and `connect_fn` (same
scheme as today) so the full lifecycle is testable without hardware.

### 3.4 UI — status panel, editable fields

The page becomes a pure display: it polls `/api/status` at 1 Hz and keeps
one `EventSource` open for the whole page life.

**Connection panel → "Status" (read-only):**

- `Connected — /dev/ttyACM0 (Arduino Leonardo [2341:8036])` (ok color)
- `Searching for the board…`
- `Connecting…`
- `Board not responding: <last_error>` / `Multiple serial devices, cannot pick one` (error color)

The bottom status bar keeps its role: action feedback (saved, applied,
command errors). The other panels stay dimmed (`.offline`) until the link
is live, and light up automatically when the board appears.

**Range panel — two editable numeric fields** (replace the "value + set
here" rows):

- show the configured `raw_min` / `raw_max` (mono font);
- commit on Enter or blur, only when the value changed →
  `POST /api/calibrate/min {"value": 336500}` → adopt the returned
  config, dirty flag on;
- client-side validation: integer within the HX711 24-bit range
  (−8 388 608 … 8 388 607); invalid → status error, nothing sent (the
  firmware clamps regardless);
- the fields resync when the config changes (reconnect, SAVE/LOAD/RESET)
  except the field currently focused;
- disabled while the link is down.

**Telemetry:** on `s=0` the measurement panel shows a yellow
"Sensor: no valid data" warning above the bar; it disappears when data
returns.

**Removed from the JavaScript:** `refreshPorts`, `connect`, `disconnect`,
the port select, and SSE orchestration tied to clicks.

### 3.5 English pass

Everything in English, per the project global rule:

- Python: docstrings, comments, user-facing strings (error hints, window
  title, CLI help);
- `web/index.html`: `lang="en"`, all visible text and JS strings;
- firmware: all comments (`.ino`, `.c`, `.h`, `.cpp`);
- C tests: comments **and test function names**
  (`test_ema_reactivite_constante_production` →
  `test_ema_reactive_constant_production`);
- docs: `README.md`, `docs/design.md`, `docs/wiring.md`;
- `Makefile`s (echoes, comments) and `.vscode/tasks.json` labels if
  French.

Not translated: git history, the serial protocol (already English), code
identifiers (already English).

Order: functional changes first (written directly in English), then the
translation pass over the remaining French text, so the translation diff
stays clean and reviewable. Final check: a grep for accented characters
(`é à ç œ …`) across the repo returns nothing outside git history.

### 3.6 Audit verdict

The code base is already lean; the simplification wins come from removing
the manual connection machinery, not from a rewrite. Explicitly kept:

| Element | Verdict |
|---|---|
| JS curve mirror (~10 lines, third copy of the C/Python curves) | kept: a fetch + cache of the preview API would add moving parts for the same weight |
| `hb_fmt_fixed` (hand-rolled float formatting) | kept: AVR necessity, no `%f` in avr-libc |
| Serial protocol (9 commands, one-line ASCII) | kept: minimal |
| Pure core / hardware layer split | kept: it is what makes 1-second native tests possible |
| Linebuf overflow detection, EEPROM CRC + sanitize, stale-reply drain | kept: safety, not complexity |

## 4. Testing

**Native C (`make test-firmware`):**

- stuck detector: first sample not stuck; identical +999 ms not stuck;
  +1001 ms stuck; still identical stays stuck; different sample →
  unstuck + timer reset; a change before the threshold restarts the timer;
- `T` line formatting with and without `s`;
- the existing ~3425 assertions stay green.

**Python (`make test-app`):**

- new `tests/test_manager.py` on `fake_board.py` with injected
  `list_ports_fn` / `connect_fn`: board appears → auto-connect; single
  unknown USB port fallback; multiple unknown ports → no connect;
  dead link → searching; board returns → reconnect; status transitions
  and `last_error` surfacing;
- `test_protocol.py`: `s` field optional (default 1 when absent);
- `test_server.py`: new API surface (connect/disconnect/ports gone,
  `state` in status, calibrate requires a value).

**Hardware (manual, user):**

- app started with no board → "Searching…" → plug the board →
  auto-connect, telemetry flowing;
- unplug mid-session → status searching + sensor warning; replug →
  auto-reconnect, config re-read from EEPROM;
- editable fields verified against a serial monitor (`GET` after a
  commit);
- if the freeze happens again, the UI shows "Sensor: no valid data" and
  the axis drops to 0 — which side was at fault becomes unambiguous;
- in-game check with `jstest` / a game: the axis behaves, no more frozen
  axis.

**Gates:** `make test` (both suites), `make build` (flash/RAM budget),
accent grep = 0.

## 5. Out of scope

- Serial protocol rework beyond the optional `s` field;
- acquisition rate / EMA tuning (freshly validated by the user on
  hardware, committed separately before this work starts);
- multi-board support (one handbrake per app);
- Windows-specific work beyond what the existing code already handles.
