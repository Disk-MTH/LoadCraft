# LoadCraft — progressive handbrake for simracing

Load-cell handbrake, seen by the PC as a **native USB HID device**: no
driver, no software to keep running during gameplay. It appears in
Windows "Game Controllers" like a store-bought handbrake, and can be
mapped like any other axis.

**LoadCraft** is the project name; the handbrake is its first device.

```
Load cell 20 kg ──> HX711 ──> Pro Micro (ATmega32u4) ──USB-C──> PC
                                                           │
                                  joystick HID (game) + serial (calibration)
```

## Status

| Part | Status |
|---|---|
| Firmware core (curves, filter, protocol, EEPROM) | ✅ 3445 native assertions |
| Hardware layer + sketch | ✅ compiles, 63% flash / 27% RAM |
| Calibration app | ✅ 138 tests |
| **Flashed and recognized board** | ✅ one `ABS_X` axis, on `/dev/input/js2` |
| **Serial protocol on real hardware** | ✅ PING/GET/STREAM/SET/RESET verified |
| Load cell reading | ⏳ HX711 not wired yet |
| In-game test | ⏳ |

The board works and talks. What remains to be validated comes down to the
sensor itself: real HX711 noise, useful range, mechanical durability, and
the in-game feel that will decide the curve. Details in `docs/design.md` §11.

## Hardware

| Part | Detail |
|---|---|
| 20 kg load cell | 4 wires, with HX711 module |
| HX711 module | Amplifier + 24-bit converter |
| **Pro Micro ATmega32u4** | 5 V / 16 MHz, USB-C |

⚠️ **An ESP8266 board, or one with a CH340 chip, is not suitable.** Their
USB port is tied to a fixed-function USB-to-serial bridge, incapable of
presenting itself as a joystick. You need a microcontroller whose USB
controller is in the main chip. Details in `docs/design.md` §1.

Full wiring: `docs/wiring.md`.

## Structure

```
firmware/handbrake/   firmware ATmega32u4
  hb_core.c           curves, normalization, filter         ← pure C99, tested
  hb_protocol.c       serial protocol                       ← pure C99, tested
  hb_record.c         EEPROM serialization + CRC            ← pure C99, tested
  hx711.cpp           sensor driver                         ← hardware
  hb_storage.cpp      EEPROM access                         ← hardware
  handbrake.ino       main loop, HID                        ← hardware
app/                  calibration app (Python, package loadcraft)
tests/                native tests of the firmware core (gcc)
docs/                 design and wiring
```

The firmware is split into a **pure core** and a **hardware layer**: all
the logic that could be wrong is in C99 with no Arduino dependency, so it
is compiled and tested on the PC in a second. What remains in the hardware
layer can only be validated with the board plugged in anyway.

## Tests

```bash
make test            # both suites
make test-firmware   # firmware core, native (gcc)
make test-app        # calibration app (pytest)
```

Neither suite needs the board.

## Building and flashing the firmware

### Dependency: the Joystick library

⚠️ **It is not in the Arduino library manager.** Another library named
"Joystick" (Giuseppe Martini) is listed there; it is for *reading* an
analog joystick module, not for emulating one. Installing it leads to the
error `'Joystick_' does not name a type`.

You need the one by **MHeironimus**, installed from GitHub:

```bash
# With arduino-cli
ARDUINO_LIBRARY_ENABLE_UNSAFE_INSTALL=true \
  arduino-cli lib install --git-url https://github.com/MHeironimus/ArduinoJoystickLibrary.git

# With the Arduino IDE: download the .zip of the repo, then
# Sketch > Include a library > Add .ZIP library
```

### Compilation

```bash
make detect                      # identifies the board and its FQBN
make build                       # arduino:avr:leonardo by default
make flash PORT=/dev/ttyACM0     # upload
```

Observed usage: 18112 bytes of flash (63%), 707 bytes of RAM (27%).

**The FQBN depends on the clone's bootloader.** Many Pro Micros ship with
the Leonardo bootloader and identify as `2341:8036`. Others present as
Arduino Micro (`2341:8037`) or SparkFun Pro Micro (`1B4F:...`). `make
detect` gives the right one; to use another one:

```bash
make build FQBN=arduino:avr:micro
```

Under the Arduino IDE, choose the matching board (**Arduino Leonardo** or
**Arduino Micro**, same ATmega32u4) and open
`firmware/handbrake/handbrake.ino`.

### If the upload fails

The 32u4 must switch to bootloader mode to be flashed. Normally the tool
takes care of it by opening the port at 1200 bauds, but a sketch that
crashes the USB stack prevents this mechanism. Manual solution: **quick
double press of RESET**, then start the upload within the ~8 seconds where
the bootloader is active.

## Prerequisites per system

### Linux

Access to the serial port goes through the `dialout` group:

```bash
sudo usermod -aG dialout $USER   # then log out and back in
```

Without this, `/dev/ttyACM0` stays as `root:dialout` and both the app and
the upload fail with permission denied.

### Windows

Nothing to install: Windows 10/11 provides the CDC driver for the
ATmega32u4 with Arduino identifiers, and the HID device is recognized
natively.

The port is a `COM...` instead of `/dev/ttyACM0`; the app detects it the
same way. The `Makefile` assumes a Unix environment; on Windows, run the
commands directly:

```
cd app
uv venv .venv
uv pip install --python .venv -e ".[dev]"
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m loadcraft
```

The firmware is strictly identical on both systems: a calibration saved
under Linux remains valid once the board is plugged into the gaming PC,
since it lives in the board's EEPROM and not on the PC.

## Verifying that the axis is seen by the system

### Linux

```bash
sudo dnf install evtest joystick   # Fedora
jstest /dev/input/jsX              # the axis must move when you pull
```

`jsX` is not guaranteed to be `js0`: every gamepad the PC sees gets its
own `jsX`. The handbrake is the device that appears when the board is
plugged in. It enumerates as **Arduino Leonardo** (the board's FQBN name,
USB id `2341:8036`) and presents a single X axis with no buttons:

```bash
for i in /sys/class/input/input*; do echo "$i $(cat $i/name 2>/dev/null)"; done
```

The name is fixed by the board's FQBN and cannot be changed from the
sketch; on a machine with several Arduino boards, the handbrake is the
one at `2341:8036` that shows up when it is plugged in.

### Windows

`Win+R` → `joy.cpl` → select **Arduino Leonardo** (the handbrake:
`2341:8036`, one axis, no buttons) → **Properties**. The X axis must move
when you pull the lever.

Once visible here, any game can map it as a handbrake.

## Board LEDs

The firmware does not program the LEDs: on the ATmega32u4, the Arduino
core drives the RX and TX LEDs as a side effect of USB traffic (a 100 ms
pulse per event), and the green LED is plain hardware. That is why the
board "lights up" on its own - the table is about USB activity, not about
the handbrake logic.

| State | Green (USB) | RX LED | TX LED |
|---|---|---|---|
| Board idle, no app | on | off | 100 ms pulse per axis report (~1 Hz: looks like a fast blink or a steady glow) |
| App connected, streaming | on | short flash when the app sends a command (GET, SET, SAVE...) | on (telemetry ~10 Hz + axis reports) |
| App closed | on | off | back to the ~1 Hz pulse |
| Flashing from the app | may flicker during the ~8 s bootloader window, then steady | off | off |
| **Faulty USB state** | **may blink** | **flickers randomly** | **flickers randomly** |

Notes:

- Which LED is RX and which is TX (and their colors) depends on the
  board. On the standard Leonardo-family Pro Micro the core drives the RX
  LED from pin D17 (PB0) and the TX LED from the XCK pin (PD5).
- The "fast blink with no app connected" is the **normal idle state**, not
  a fault: the TX LED pulses once per HID keep-alive report.
- The **faulty USB state** row is the one that needs action: the host's
  USB power management can leave the board with a dead or crawling serial
  endpoint while the HID axis still works. Power-cycle the board (unplug,
  wait 2 s, replug) and it recovers. See **Troubleshooting** below.

## Calibration app

```bash
make setup-app
app/.venv/bin/python -m loadcraft
```

The browser is the default interface on both systems: closing the tab
closes the app (about 10 s grace). Options: `--window` (native window,
needs the `desktop` extra), `--no-window` (server only, never auto-exits),
`--port N` (fixed HTTP port, 0 = automatic). The server only listens on
`127.0.0.1`.

`make setup-app` installs `pywebview` for the `--window` mode. Without
the extra, `--window` falls back to the default browser with a stderr
note instead of refusing to start.

Under **Linux**, the `--window` mode relies on WebKitGTK via PyGObject.
PyGObject
does not install cleanly via pip without a full build toolchain, while the
system library is almost always already present: that is why the virtual
environment is created with `--system-site-packages`. If the native window
does not open anyway:

```bash
sudo dnf install python3-gobject webkit2gtk4.1   # Fedora
python3 -c "import gi; gi.require_version('Gtk','3.0')"  # must pass
```

Under **Windows**, nothing to do: pywebview uses WebView2 there, which
ships with Edge.

### Calibration procedure

1. Plug the board and start the app: the status panel shows
   "Searching for the board..." until it connects (a few seconds). No
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

### Available curves

| Curve | Effect |
|---|---|
| Linear | Output proportional to the force |
| Power | `gamma < 1`: bite from the start. `gamma > 1`: progressive, precision at the start of the travel |
| S curve | `gamma > 1`: soft at the ends, crisp in the middle. `gamma < 1`: the opposite |

`gamma = 1` makes all three identical: it is the neutral reference for
comparison.

The right setting depends on the feel and the mechanical setup: hence live
tuning rather than a value frozen in the code.

## Serial protocol

Useful for debugging without the app, from any serial monitor:

```
PING                     → OK PING
GET                      → CFG min=... max=... curve=... gamma=... calibrated=...
SET MIN | SET MAX        captures the current filtered value
SET MIN <v> | SET MAX <v>
SET CURVE LINEAR|POWER|SCURVE [gamma]
SET GAMMA <f>
SAVE | LOAD | RESET
STREAM 0|1               telemetry: T raw=... out=... axis=... s=1|0
```

Telemetry is off by default. s=0 when there is no valid sample (stuck
sensor or sensor absent); older boards omit the field. Details in
`docs/design.md` §6.

## VS Code

The shared configuration is versioned in `.vscode/`.

**Tasks** (`Ctrl+Shift+P` → *Run Task*): run the tests (all / firmware /
app), build, detect the board, upload (asks for the port), launch the app,
install the Python environment. `Ctrl+Shift+B` builds the firmware,
`Ctrl+Shift+P` → *Run Test Task* runs the full suite.

**Debugging** (F5): the app in a native window, in the browser, or server
only; the pytest tests (all or the current file); and the three native
test executables under gdb: the firmware core being ordinary C99, it
debugs like any other program, with breakpoints and inspection.

**IntelliSense**: two C/C++ configurations in `c_cpp_properties.json`.
The first, *Firmware core (native)*, is for `hb_core`/`hb_protocol`/
`hb_record` and the tests. The second, *Firmware AVR*, adds the Arduino
headers for the `.ino` and the drivers. Switch via the status bar at the
bottom right. The paths follow the default arduino-cli installation; if
you update the AVR core, adjust the version number.

## Documentation

- `docs/design.md`: design, technical choices and their reasons
- `docs/wiring.md`: wiring, checks, first startup

## Packaging and release

The app ships as a portable single file per OS, built by GitHub Actions on
tag push (`v<version>`):

- `LoadCraft-<ver>-windows-x64.exe` (Windows)
- `LoadCraft-<ver>-linux.AppImage` (Linux)

**Install:** copy the file anywhere and run it. **Uninstall:** delete it.
No installer, no local state — the calibration lives in the board EEPROM.

- The app opens your default browser; **closing the tab closes the app**
  (about 10 s grace).
- The `.exe` is unsigned: the first launch shows the Windows SmartScreen
  warning — *More info → Run*.
- Startup problems (the tab says "connection refused") are logged to
  `%TEMP%\loadcraft.log` (Windows) or `/tmp/loadcraft.log` (Linux).
- Linux: `dialout` group access is still required for the serial port
  (`sudo usermod -aG dialout $USER`), as for the source build.

## Flashing the firmware from the app

The app bundles the matching firmware (app version = firmware version) and
can flash the board through its built-in bootloader:

1. Connect the board, open the **Firmware** panel.
2. The panel shows the app and board versions and a status badge
   (*Up to date* / *Flash recommended* / *Unknown board version*).
3. Click **Flash firmware**: the app resets the board into the bootloader
   (1200-baud touch), writes the firmware with the bundled avrdude, and the
   board reboots with the new version. The app reconnects automatically.

The flash writes flash memory only: the EEPROM calibration is preserved.
If the flash fails: close any serial monitor holding the port, check the
`dialout` group (Linux), or double-tap the RESET button right before the
flash starts (manual bootloader entry, ~8 s window).

The vendored avrdude 8.0-arduino.1 is the same avrdude arduino-cli's AVR
package ships (pinned by Arduino AVR Boards 1.8.8), vendored from
arduino.cc's official tool downloads into `dist-tools/avrdude/` (GPLv2)
and embedded in the artifacts; on Windows it is a 32-bit PE (i686), which
runs on Windows x64 via WOW64. A system `avrdude` on `PATH` is used as a
fallback.

## Troubleshooting

### The app stays on "Connecting..." or the measurement panel shows "—"

The HID axis does not need the app: the joystick can work perfectly while
the serial link is not up. Read the status bar first - it names the cause:

- `access to /dev/ttyACM0 denied` (Linux): `sudo usermod -aG dialout
  $USER`, then log out and back in. A running instance keeps its old
  credentials and must be fully restarted.
- `already open by another program` (Windows): another LoadCraft instance
  (or a serial monitor) still holds the COM port. Closing the tab ends
  the app only a few seconds later; a second launch inside that window
  finds the port taken. Close the other window and relaunch.
- the board is in the faulty USB state (below): replug it, then relaunch.

### The board stops talking after closing the app (Windows)

Symptoms: the LEDs start flickering at random and the handbrake no longer
answers - the app cannot connect, the joystick axis is frozen or gone -
until the board is unplugged and replugged (see the **faulty USB state**
row of the LED table).

Cause: with no program holding the COM port, Windows USB power management
(selective suspend) can put the port into a low-power state, and the
32u4's USB state machine does not always survive that transition.

To make it stop happening, on the gaming PC:

1. Control Panel → Power Options → *Change plan settings* → *Change
   advanced power settings* → **USB settings** → *USB selective suspend
   setting*: **Disabled**.
2. Device Manager → *Universal Serial Bus controllers* → the board's
   composite device, and the USB hub/root it is plugged into →
   Properties → *Power Management* → uncheck *Allow the computer to turn
   off this device to save power*.

The firmware side is hardened too: telemetry stops when the port is
closed (DTR drop) instead of streaming into the void, and the app sends
`STREAM 0` before releasing the port, so a close leaves the board in its
idle state instead of a half-open one.

### Raw value blinks between the real value and 0

A 0 in the measurement panel means the board reported no valid sensor
sample: the first ~100 ms after every reset (converter warm-up), a sensor
that went silent (wiring, power), or a board in the faulty USB state
above. The telemetry line carries an `s=` field (`s=0` = no valid
sample); check the axis too - if the HID axis is frozen as well, the
board is the suspect, not the sensor. A power-cycle clears the USB
states; a persistent 0 with a dead axis points at the HX711 wiring
(`docs/wiring.md`).

## Versioning

The version in `app/pyproject.toml` is the single source of truth. Release
tags must equal it (the CI gate fails otherwise). `make build-hex`
generates `firmware/handbrake/version.h` and `app/loadcraft/_version.py`
from it; the firmware reports the version in the `CFG` line (`ver=...`) and
the app compares it with the bundled firmware.
