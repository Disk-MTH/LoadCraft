# Progressive USB handbrake - design

Load-cell simracing handbrake, seen by the PC as a native USB HID device
(no driver, no software to keep running during gameplay).

**LoadCraft** is the project name; the handbrake is its first device.

## 1. Hardware

| Part | Reference | Role |
|---|---|---|
| Load cell | 20 kg, 4-wire strain gauge | Measures the force applied to the lever |
| Amplifier / ADC | HX711 module (24-bit) | Amplifies the gauge bridge and digitizes |
| Microcontroller | Pro Micro ATmega32u4, 5 V / 16 MHz, USB-C | Processing + USB HID enumeration |

### Why the ATmega32u4 and not an ESP8266

The ESP8266 (ESP-01, ESP-12F, NodeMCU...) has **no USB device controller**.
The micro-USB port of those boards is tied to a fixed-function USB-to-serial
bridge chip (CH340 / CP2102): it can only announce itself as a COM port,
never as a joystick. The ATmega32u4 has the USB controller built into the
main silicon: it is the firmware that decides the type of device presented
to the host.

Same reason to rule out "Nano USB-C" clones with a CH340 chip, despite their
"Pro Micro compatible" description.

## 2. Software architecture

```
Load cell 20 kg ──4 wires──> HX711 ──DT/SCK──> Pro Micro (ATmega32u4)
                                                  │
                                    ┌─────────────┴─────────────┐
                                    │      firmware C/C++       │
                                    │  1. raw 24-bit read       │
                                    │  2. EMA filter            │
                                    │  3. min/max normalization │
                                    │  4. response curve        │
                                    │  5. axis 0..1023          │
                                    └─────────────┬─────────────┘
                                                  │
                              ┌───────────────────┴───────────────────┐
                              │        USB composite (native)         │
                              │  ├─ HID joystick : 1 X axis           │
                              │  └─ CDC serial   : config protocol    │
                              └───────────────────┬───────────────────┘
                                    ┌─────────────┴─────────────┐
                                    │                           │
                              Games (DirectInput)        Calibration app
                                                            (Python, optional)
```

The firmware is **standalone**: the configuration lives in the 32u4's EEPROM,
so the handbrake works correctly plugged into any PC, app closed. The
calibration app is only for tuning, not for playing.

## 3. Signal processing chain

### 3.1 Acquisition

Home-grown HX711 driver, non-blocking (~40 lines). The HX711 protocol is
trivial (24 bits in synchronous serial + clock pulses to select the gain),
and a home-grown implementation avoids an external dependency while
guaranteeing that the main loop never blocks waiting for a conversion:
mandatory to keep serving the USB and the serial commands.

Channel A, gain 128 (25 clock pulses): the low-noise input, suited to a load
cell.

The module's `RATE` pin tied to VCC gives **80 samples per second** instead
of the default 10. On a handbrake latency matters: 12.5 ms instead of
100 ms.

### 3.2 Filtering

Exponential moving average (EMA): `y[n] = y[n-1] + α·(x[n] − y[n-1])`.

Chosen over a classic sliding average because it costs only one RAM value
and one multiplication, with no circular buffer. α = 0.5 at 80 SPS gives a
time constant of about 12.5 ms (90 % of a step in ~42 ms): the HX711 at gain
128 is very stable and the axis is only quantized to 1/1023, so the extra
noise that gets through stays imperceptible. A lower coefficient (0.25) felt
like a lag both on the pull and on the release.

### 3.3 Normalization

```
t = (raw − raw_min) / (raw_max − raw_min)   then clamped to [0, 1]
```

`raw_min` = lever at rest, `raw_max` = the maximum force wanted at full pull.
Both are captured by the user from the app, by feel.

This formula also handles **the `raw_max < raw_min` case**: if the cell is
wired with reversed polarity (A+ and A− swapped), just calibrate normally,
the sign cancels out by itself. No "invert axis" option is therefore needed.
Only degenerate case: `raw_min == raw_max`, which returns 0.

### 3.4 Response curve

`raw_min`/`raw_max` set the *range*, the curve sets the *feel* inside it.
Three shapes, one parameter `gamma`:

| Curve | Formula | Effect |
|---|---|---|
| `LINEAR` | `t` | Output proportional to the force |
| `POWER` | `t^gamma` | `gamma < 1`: bite from the start. `gamma > 1`: progressive, precision at the start of the travel |
| `SCURVE` | `t<0.5 : ½(2t)^g`<br>`t≥0.5 : 1−½(2(1−t))^g` | `g > 1`: soft at the ends, crisp in the middle. `g < 1`: the opposite |

`gamma = 1` makes the three curves identical (linear), which gives a neutral
reference point for comparison.

The choice of the right curve depends on the feel and the mechanical setup:
hence live tuning in the app rather than a value frozen in the code.

### 3.5 HID output

A single X axis, range `0..1023`, joystick type, 0 buttons, 0 hat.
Everything that is useless is removed from the HID descriptor: shorter report
and better host compatibility.

1024 steps over the lever travel far exceed the modulation finesse of a foot
or a hand, and stay below the HX711's residual noise: going to a higher
resolution would only bring more noise.

`begin(false)` + explicit `sendState()`: the state is sent as one atomic
report, never partially updated. The report is only emitted on value change,
with a periodic resend to keep the host in phase even with the lever still.

The HID stack is **MHeironimus/ArduinoJoystickLibrary**, which allows
declaring exactly the wanted axes and fixing their range. It **is not in the
Arduino library manager**: another library named "Joystick" is listed there,
meant for *reading* an analog joystick module. Installing it produces the
error `'Joystick_' does not name a type`. See the README for installation
from GitHub.

## 4. Zero and drift

No automatic tare at startup. `raw_min` from the calibration *is* the zero,
and it is persistent.

Accepted consequence: the slow drift of a load cell's zero (thermal,
mechanical settling) will eventually shift the rest point slightly. The fix
is typing the current raw value into the app's Minimum field, two seconds.

The alternative, retaring at boot, was ruled out: it produces a wrong zero
if the USB is plugged in while the lever is pulled, and that failure mode is
more painful than the drift it corrects.

## 5. Persistence

Internal EEPROM of the 32u4 (1 KB), address 0, record of 22 bytes:

| Offset | Field | Type |
|---|---|---|
| 0-3 | magic `"HBK1"` | u32 |
| 4 | version | u8 |
| 5 | curve | u8 |
| 6-9 | raw_min | i32 |
| 10-13 | raw_max | i32 |
| 14-17 | gamma | float |
| 18 | calibrated | u8 |
| 19 | reserved | u8 |
| 20-21 | CRC-16/CCITT | u16 |

Little-endian layout written byte by byte, not a `struct` serialized as-is:
no dependence on the packing or alignment chosen by the compiler, so the same
record reads back identically on the AVR target and in the native tests.

Magic + version + CRC16: a blank, corrupted, or incompatible older-version
EEPROM is detected and replaced by the defaults, rather than interpreted as a
valid calibration.

A correct CRC however only proves integrity: an authentic record can still
contain unusable values, a NaN `gamma` would poison the whole axis
computation. `hb_config_sanitize` is therefore applied systematically after
every read-back.

Writing **only on an explicit `SAVE` command**. Live settings (gamma slider)
stay in RAM: the AVR EEPROM is rated for ~100,000 write cycles, a slider
writing on every move would wear it out in a few sessions.

Defaults, blank EEPROM: `calibrated = 0`, deliberately very wide range. The
axis therefore barely moves, which makes the missing calibration obvious
instead of producing erratic, hard-to-diagnose behavior.

## 6. Configuration protocol (CDC serial)

ASCII lines terminated with `\n`, in both directions. Text rather than
binary: readable in any serial monitor, debuggable without tools.

### Host → device

| Command | Effect |
|---|---|
| `PING` | Presence test |
| `GET` | Returns the current configuration |
| `SET MIN` / `SET MAX` | Captures the current filtered value |
| `SET MIN <v>` / `SET MAX <v>` | Sets an explicit value |
| `SET CURVE LINEAR\|POWER\|SCURVE` | Changes the curve shape |
| `SET GAMMA <f>` | Changes the curve parameter |
| `SAVE` | Writes to EEPROM |
| `LOAD` | Reloads the EEPROM (discards unsaved settings) |
| `RESET` | Defaults in RAM |
| `STREAM 0\|1` | Disables / enables telemetry |

### Device → host

- Replies: `OK <command> [value]` or `ERR <reason>`
- Configuration: `CFG min=<i32> max=<i32> curve=<name> gamma=<f> calibrated=<0|1>`
- Telemetry (if `STREAM 1`): `T raw=<i32> out=<f> axis=<0..1023> s=<0|1>`

**Telemetry off by default**, enabled by the app on connect. A firmware
emitting continuously would risk saturating the CDC buffer when nobody
listens, at the expense of the HID loop.

### AVR constraint: no `%f`

The `printf` implementation in avr-libc **does not include floating-point
support** without a specific linking option. A `snprintf("%f")` produces
empty or wrong text on this target, without a compile error, the classic
silent failure.

Float formatting therefore goes through a home-grown fixed-point helper
(`hb_fmt_fixed`), tested natively. Parsing uses `strtod`, which avr-libc does
provide.

## 7. Code layout

The firmware is split into a **pure core** and a **hardware layer**, so the
logic is testable on a PC without the board:

```
firmware/handbrake/
  hb_core.h/.c       pure C99: config, normalization, curves, EMA filter
  hb_protocol.h/.c   pure C99: command parsing, formatting, line buffer
  hb_record.h/.c     pure C99: EEPROM record serialization + CRC16
  hx711.h/.cpp       non-blocking hardware driver
  hb_storage.h/.cpp  EEPROM read/write
  config.h           pinout and constants
  handbrake.ino      assembly: loop, HID, serial
```

`hb_core`, `hb_protocol` and `hb_record` depend only on the libc and
`math.h`: they are compiled as-is by the native tests (`tests/`, gcc) and by
the AVR compiler. All the logic that could be wrong is thus covered by tests
that run in a second, without hardware.

Serialization is separated from EEPROM access precisely for this reason:
corruption detection failing quietly would only be noticed once the
calibration is lost. `hb_storage` then reduces to a read loop and a write
loop.

`hb_storage`, `hx711` and the `.ino` are deliberately thin: what they
contain can only be validated with the board in hand.

## 8. Stuck-sensor detection

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

## 9. Calibration app

Python. Local Flask server + web interface, shown in a native window via
`pywebview`: a real Linux/Windows desktop application, without bundling a
browser (pywebview reuses the system web engine, where Electron would add
~100 MB).

- `protocol.py`: mirror of the firmware protocol, pure, tested
- `link.py`: serial port, read thread, telemetry queue
- `server.py`: local HTTP API + SSE for real-time telemetry
- `web/index.html`: live plot, raw/mapped values, editable min/max fields,
  curve selector, gamma slider, save button

SSE rather than WebSocket: a one-way server→page stream only, so SSE
suffices and stays in the browser standard library, with no extra
server-side dependency.

The serial transport is **injected** into `SerialLink` rather than created
by it: the tests provide a simulated board and cover the whole dialog (order
of replies, effect of the commands, resistance to stray bytes), without
hardware or pyserial.

The curves are reimplemented on the host side rather than requested from the
board, so the drawn preview shows exactly what the firmware computes. The
Python tests repeat the properties verified on the C side (fixed points,
monotonicity, symmetry, neutrality of `gamma = 1`).

Port enumeration keeps only USB devices: on Linux, pyserial also lists the
thirty or so inherited 8250 ports (`/dev/ttyS*`), where the board would be
unfindable. Fallback to the full list if no USB port is detected: better a
crowded choice than no choice.

## 10. Link manager

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

## 11. Validation plan

| Step | Verifies | Status |
|---|---|---|
| Native C tests | Curves, normalization, filter, protocol, formatting, EEPROM | ✅ 3445 assertions |
| pytest tests | Host protocol, serial dialog, server API, ports | ✅ 138 tests |
| AVR compile | The firmware compiles for the ATmega32u4 | ✅ 63% flash, 27% RAM |
| HID enumeration | The system sees a one-axis joystick | ✅ Linux, `ABS_X` only |
| Protocol on hardware | PING, GET, STREAM, SET, RESET, errors | ✅ |
| Blank EEPROM | Fallback to the defaults, `calibrated=0` | ✅ |
| Raw HX711 read | Wiring, noise, range, sign | ⏳ sensor required |
| EEPROM persistence | Write then read back after unplug | ⏳ |
| HID enumeration, Windows | `joy.cpl` sees the axis move | ⏳ |
| In-game test | Feel, final curve choice | ⏳ |

The simulated-board tests validate the *dialog*, not the hardware: they say
nothing about the real HX711 noise, the mechanical stability of the setup, or
the way a given game interprets the axis.

Observed at first plug-in, sensor not wired: the telemetry stably returns
`raw=0 out=0.000 axis=0`. It is the pull-up on the DT line that produces
this result; without it, the floating input would have surfaced noise
presented as a measurement (see §3.1).

## 12. Packaging and in-app flash (2026-09-13)

The app is distributed as a portable Windows `.exe` and a Linux AppImage
(browser-tab UI, close-tab-exit lifecycle), and can flash the firmware
through the built-in bootloader via the bundled avrdude. The firmware
reports its version in the CFG line; the version flows from
`app/pyproject.toml` into both the firmware and the app. Full design:
`docs/superpowers/specs/2026-09-13-loadcraft-packaging-flash-design.md`.

## 13. Out of scope (v1)

- **Bluetooth / wireless**: the ATmega32u4 has no radio. A complete wireless
  handbrake would require another MCU (ESP32 and BLE HID) and another
  architecture.
- **Buttons / LED**: ruled out deliberately: the app covers the calibration
  need, an LED would add nothing more.
- **Free curve editor (splines, points)**: the three parametric shapes cover
  the useful feel space. Reconsider only if the in-game test shows that none
  fits.
