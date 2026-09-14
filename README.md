# Progressive handbrake for simracing

Load-cell handbrake, seen by the PC as a **native USB HID device**: no
driver, no software to keep running during gameplay. It appears in
Windows "Game Controllers" like a store-bought handbrake, and can be
mapped like any other axis.

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
app/                  calibration app (Python)
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
jstest /dev/input/js0              # the axis must move when you pull
```

### Windows

`Win+R` → `joy.cpl` → select the device → **Properties**. The X axis must
move when you pull the lever.

Once visible here, any game can map it as a handbrake.

## Calibration app

```bash
make setup-app
app/.venv/bin/python -m loadcraft
```

Options: `--browser` (open in the browser), `--no-window` (server only),
`--port N` (fixed HTTP port). The server only listens on `127.0.0.1`.

`make setup-app` installs `pywebview`, which displays the interface in a
native window. If it is absent, the app falls back to the default browser
instead of refusing to start: handy for troubleshooting, but that is also
what happens if the native window installation failed without you
noticing.

Under **Linux**, this window relies on WebKitGTK via PyGObject. PyGObject
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
