# LoadCraft Packaging and In-App Firmware Flash — Design Spec

Date: 2026-09-13
Status: approved in brainstorming (all sections), pending implementation

## 1. Context

The handbrake project is renamed **LoadCraft** (GitHub:
`https://github.com/Disk-MTH/LoadCraft.git`; the local repo does not have an
`origin` remote yet). The calibration app (currently `handbrake_tuner`) is
functional: server-side `LinkManager` with auto connect / auto reconnect,
editable calibration fields, full-auto UX. The firmware reports its
configuration over the serial protocol and stores calibration in the board
EEPROM.

Two distribution gaps remain:

1. **No distributable app.** Installing the app requires a Python toolchain
   (uv, venv) and, for the native window, system web libraries. People who
   want to rebuild the project hit setup friction, and the firmware flash
   requires `arduino-cli` + `make` on the machine.
2. **No way to flash the firmware from the app.** Flashing today goes
   through `make flash` with arduino-cli, which assumes the board can be
   reset into its bootloader by the tooling.

Requested work (brainstormed 2026-09-13):

- A standalone, portable app for **Windows** (single `.exe`) and **Linux**
  (single **AppImage**), no installer and no uninstaller (delete the file).
  The project is meant to be published on GitHub Releases so that people
  who want to rebuild the project can grab the exact app version.
- The app **flashes the handbrake firmware itself**, using the board's
  built-in ATmega32u4 bootloader (the 1200-baud touch / RESET programming
  mode already documented in the README). No external programmer, no manual
  button press.
- Version coupling: **one project version = one app that contains the
  matching firmware** and can flash it.
- Identical behavior on both OSes: the app opens the interface in a
  **browser tab** and **exits when the tab is closed**.
- Rename the app and the product to LoadCraft (the firmware keeps the
  "handbrake" name, which is the device name).

## 2. Decisions (approved with the user, 2026-09-13)

| Decision | Choice |
|---|---|
| Distribution format | Portable single files: PyInstaller onefile `.exe` (Windows), AppImage (Linux). No installer, no uninstaller. |
| Distribution channel | Public GitHub Releases, built by GitHub Actions on tag push (`v*`). |
| UI on both OSes | Browser tab (default browser). `pywebview` remains a development-only option (`--window`), excluded from the packaged artifacts. |
| App lifecycle | Close the tab, the app exits (keep-alive SSE + 10 s grace). `--no-window` disables auto-exit. |
| Flash hardware path | Built-in 32u4 bootloader, fully automated: the app performs the 1200-baud touch itself; no manual RESET, no external programmer. |
| Flash tool | `avrdude` binary vendored in `dist-tools/` and embedded in the artifacts, with fallback to a system `avrdude` on `PATH`. |
| Version coupling | Single source of truth: `version` in `app/pyproject.toml`. Generated `version.h` (firmware) and `_version.py` (app) at build time. Release tag must equal the pyproject version (CI check). |
| Rename scope | App + product level: repo, Python package `loadcraft`, CLI, UI title, artifacts, docs. Firmware keeps the `handbrake` name (`firmware/handbrake/`, `handbrake.ino`, `HB_*` identifiers). |
| Packaging approach | PyInstaller + GitHub Actions (approaches Briefcase and Nuitka were considered and rejected in brainstorming). |

## 3. Design

### 3.1 Rename (app + product level)

Done as an independent commit before the packaging work, so the folder
rename (performed by the user afterwards) stays friction-free.

| Item | Before | After |
|---|---|---|
| Repo / folder | simracing-handbrake | LoadCraft (folder renamed by the user) |
| `pyproject.toml` name | handbrake-tuner | loadcraft |
| Python package dir | `app/handbrake_tuner/` | `app/loadcraft/` |
| Console script | `handbrake-tuner` | `loadcraft = loadcraft.__main__:main` |
| UI title (tab / window) | Handbrake calibration | LoadCraft |
| Windows artifact | — | `LoadCraft-<ver>-windows-x64.exe` |
| Linux artifact | — | `LoadCraft-<ver>-linux.AppImage` |
| Firmware | `firmware/handbrake/`, `handbrake.ino`, `HB_*` | **unchanged** |
| Serial protocol | — | unchanged, except the `ver` field (3.3) |

Concretely: `git mv app/handbrake_tuner app/loadcraft`; update every import,
`pyproject.toml` (name, console script, `packages.find`, `package-data`),
the root `Makefile` (`-m loadcraft`), `app/tests/` imports, the `.vscode/`
launch/tasks references, `README.md` and `docs/` (title and product name;
the device is still called the handbrake). The root folder rename is done by
the user after this commit.

### 3.2 Browser-tab UI and "close the tab = quit the app"

**Entry point (`loadcraft/__main__.py`).** The browser becomes the default
interface on both OSes:

- `--port N` — unchanged;
- `--browser` — **removed** (now the default);
- `--window` — opens the pywebview window instead (requires the `[desktop]`
  extra; when it is missing, warn and fall back to the browser, as today);
- `--no-window` — server only, and **auto-exit disabled** (explicit
  server-managed lifecycle, e.g. for headless debugging).

**Keep-alive (`loadcraft/lifecycle.py`, new).** The page opens a second,
always-on SSE channel `GET /api/keepalive` on load, independent of the board
connection. The server tracks live keep-alive clients in a thread-safe set:

- register on connection; unregister when the SSE generator ends (the
  client died: the next keep-alive write to the dead socket fails, the
  generator is torn down, and the `finally` block unregisters). Keep-alive
  comments every 1 s, so a dead tab is detected within ~1-2 s;
- a watchdog (same pattern as `LinkManager`'s background thread) exits the
  process cleanly when there is **no live client for 10 s**
  (`KEEPALIVE_GRACE_SECONDS = 10`): `manager.stop()`, then exit 0. The grace
  period absorbs EventSource auto-reconnects, background-tab suspension, and
  laptop sleep/wake;
- multiple tabs: the set holds them all; the app exits only when the last
  one is gone;
- testability: injectable clock and injectable exit hook (tests assert the
  "should exit now" signal instead of killing the test process).

The SSE implementation reuses the exact pattern of the existing
`/api/stream` (werkzeug threaded server, keep-alive comments).

**Packaged artifact behavior.** The Windows exe is built `--windowed` (no
console). Startup errors (port bind failure, crash) go to a log file
(`%TEMP%\loadcraft.log` on Windows, `/tmp/loadcraft.log` on Linux); the
browser tab shows "connection refused", and the log file is documented in
the README troubleshooting section. Closing the tab kills the process, so
no orphan server remains.

### 3.3 Firmware version reporting (`ver` field)

**Version source.** The `version` in `app/pyproject.toml` is the single
source of truth. At build time (Makefile `build-hex` and CI, see 3.6-3.7):

- `firmware/handbrake/version.h` is generated:
  `#define HB_FW_VERSION "1.0.0"` (gitignored build artifact);
- `app/loadcraft/_version.py` is generated: `__version__ = "1.0.0"`
  (gitignored build artifact). The app reads it with a guarded import and
  falls back to `"dev"` when the file is absent (fresh clone without a
  build).

**Protocol.** The CFG reply line gains a trailing optional field:

```
CFG min=... max=... curve=... gamma=... alpha=... calibrated=... ver=1.0.0
```

- Firmware: the CFG formatter in `hb_protocol.c` takes the version as a
  `const char *` parameter (the core stays pure C, no `config.h`/`version.h`
  coupling); `handbrake.ino` passes `HB_FW_VERSION`.
- App: `Config` gains `ver: Optional[str]` (absent when the field is not
  present). The parser must tolerate a **missing** `ver` (old boards,
  backward compatibility) and **unknown** extra fields (forward
  compatibility) — both covered by tests.

**API and UI.** New endpoint:

```
GET /api/firmware
→ { "app_version": "1.0.0", "board_fw_version": "1.0.0" | null,
    "status": "up-to-date" | "mismatch" | "board-unknown" | "not-connected" }
```

- `board_fw_version` comes from the live link's `Config.ver`;
- `status`: link down → `not-connected`; link up but `ver` absent →
  `board-unknown` (old firmware); equal → `up-to-date`; different →
  `mismatch`.

The UI gains a **Firmware** block in the board/status area: app version,
board version, a status badge (green "Up to date" / amber "Flash
recommended" / gray "Unknown board version"), and the Flash button (3.4).

### 3.4 Flashing the firmware from the app

**New module `loadcraft/flash.py`.** All pieces injectable for tests:

- `avrdude_path()` — bundled `data/avrdude/avrdude[.exe]` (resolved under
  `sys._MEIPASS` when frozen, else relative to the package), fallback to
  `shutil.which("avrdude")`; neither → `FlashError` with an actionable hint;
- `hex_path()` — `data/handbrake.hex`, same resolution scheme;
- `trigger_bootloader(port)` — open the port at **1200 baud** (pyserial),
  wait ~1 s, close: the 32u4 resets into its bootloader. The app does this
  itself rather than relying on avrdude's `arduino` programmer type, so any
  avrdude build works (the vendored binary is invoked with `-c avr11`);
- `detect_candidates(before, after)` — after the touch, the bootloader
  appears as a (usually same-name) serial port with a different PID
  (typical: `2341:0043` Leonardo / `2341:0001` Micro bootloaders; clones
  vary). Ordered candidates: (1) the previous board port if still present;
  (2) any USB serial port whose VID:PID is **not** in `KNOWN_BOARD_IDS` and
  appeared after the touch;
- `flash(candidates, avrdude, hex, runner=subprocess)` — for each candidate
  (at most 2): run
  `[avrdude, -q, -p, m32u4, -c, avr11, -b, 57600, -P <port>, -U, flash:w:<hex>]`
  with a 60 s timeout, capturing combined output. Exit 0 = written and
  verified. Failure → next candidate; all fail → `FlashError` with the
  combined log.

**Manager.** Two methods on `LinkManager`:

- `pause_for_flash()` — set a `_flash_active` flag, close the current link
  (frees the port for avrdude). While the flag is set, `run_once` skips the
  port scan (the existing `busy`/dead-link handling stays intact for the
  other paths);
- `resume_flash()` — clear the flag; the existing auto-connect picks the
  board up again within one scan (~2 s) once the bootloader has reset the
  chip.

**Server.** `POST /api/flash` (no body), executed on a worker thread:

1. 409 when the link is not connected (the board port must be known);
   409 when a flash is already running (single-flight flag);
2. capture the board port, `pause_for_flash()`, take a "before" port scan;
3. `trigger_bootloader(port)`, wait ~2 s, "after" port scan,
   `detect_candidates(...)`;
4. `flash(...)` on the candidates;
5. `resume_flash()`, then 200 `{ "ok": true, "log": ... }` or
   502 `{ "ok": false, "error": ..., "log": ... }`.

On success the bootloader resets the chip with the new firmware
automatically; the HID re-enumerates and the `LinkManager` reconnects on its
own. The next `GET /api/firmware` shows the new `ver` and the badge flips to
"Up to date".

**Timing constraint.** The 32u4 bootloader stays active for ~8 s. The whole
sequence (touch 1 s + wait/scan 2 s + avrdude start) fits; if the window is
missed the board reboots normally and the flash simply reports a failure —
the user retries.

**UI.** The **Flash firmware** button in the Firmware block: disabled when
not connected or while a flash is running; spinner during the 3-8 s
operation; on success a status refresh; on failure the avrdude log plus a
short hint list (Linux `dialout` group, close any serial monitor holding the
port, manual double-tap of RESET as a last resort, replug the board).

**EEPROM.** `-U flash:w:` writes flash only: the calibration stored in the
EEPROM survives a flash, so **no recalibration is required** after flashing.
If a future firmware bumps the EEPROM record version, the existing
invalidation behavior applies unchanged.

### 3.5 Packaging

**Runtime dependencies** stay `flask` + `pyserial`. `pywebview` remains an
optional `[desktop]` extra, excluded from the packaged artifacts.

**Vendored avrdude.** `dist-tools/avrdude/` (committed): `avrdude.exe`
(Windows x64) and `avrdude` (Linux x86_64) — the same avrdude version that
arduino-cli ships, pinned and documented in the README with its download
provenance. GPLv2, compatible with the project. Committing the binaries keeps
release builds deterministic (no download step).

**Windows.** `pyinstaller --onefile --windowed --name LoadCraft
loadcraft/__main__.py` (run from `app/`), with `--add-data` for
`loadcraft/data` (the hex and `avrdude.exe`). Output renamed to
`LoadCraft-<ver>-windows-x64.exe` (~20 MB).

**Linux.** `pyinstaller --onedir --name LoadCraft`, then assembled into an
AppImage with `appimagetool`: `AppRun` (execs the onedir binary),
`LoadCraft.desktop` (`Name=LoadCraft`, `Exec=AppRun`, icon), and a `.png`
icon. Output `LoadCraft-<ver>-linux.AppImage` (~30-40 MB). No GTK/WebKit is
bundled (the UI is a browser tab), which keeps the image small and
distribution-agnostic.

**Artifact behavior.** Portable: copy the file, run it, delete it to
uninstall. No local state (calibration lives in the board EEPROM; the only
file written is the startup log in the temp dir). Unsigned: the first launch
of the `.exe` on Windows triggers SmartScreen ("More info → Run");
documented in the README and the release notes.

### 3.6 Local build pipeline (Makefile)

New targets at the repo root:

- `version` — prints the version parsed from `app/pyproject.toml`;
- `build-hex [VERSION=]` — writes `firmware/handbrake/version.h` and
  `app/loadcraft/_version.py` from the version (default: parsed from
  pyproject; `VERSION=` overrides for CI tags), compiles with arduino-cli,
  copies the hex to `app/loadcraft/data/handbrake.hex`;
- `package-win` / `package-linux` — copy the matching avrdude from
  `dist-tools/` into `app/loadcraft/data/avrdude/`, run the PyInstaller
  recipe of 3.5, rename the output with the version. `package-win` must run
  on Windows (PyInstaller does not cross-compile);
- `package` — both (best effort, documented per-OS).

`.gitignore` gains: `firmware/handbrake/version.h`, `app/loadcraft/_version.py`,
`app/loadcraft/data/`.

The existing dev flow (`make setup-app`, `python -m loadcraft`, `make test`)
is unchanged. When `data/handbrake.hex` is absent (fresh clone), the Flash
button reports "firmware not bundled — run `make build-hex`".

### 3.7 CI/CD (GitHub Actions release)

`.github/workflows/release.yml`, triggered on tag push matching `v*`:

0. **Gate:** the tag must equal the `pyproject.toml` version, otherwise the
   workflow fails immediately (no version drift).
1. **`test`** (ubuntu): `make test` (native firmware core + app pytest).
2. **`firmware`** (ubuntu): install arduino-cli,
   `arduino-cli core install arduino:avr`,
   `ARDUINO_LIBRARY_ENABLE_UNSAFE_INSTALL=true arduino-cli lib install
   --git-url https://github.com/MHeironimus/ArduinoJoystickLibrary.git`,
   then `make build-hex VERSION=<tag>`; upload `app/loadcraft/data/` as a
   CI artifact.
3. **`windows`** (windows-latest, needs test + firmware): checkout, Python
   setup, `pip install pyinstaller flask pyserial`, place the data artifact
   in `app/loadcraft/data/`, run the PyInstaller onefile recipe, rename to
   `LoadCraft-<ver>-windows-x64.exe`, upload the release artifact.
4. **`linux`** (ubuntu-latest, needs test + firmware): same inputs, PyInstaller
   onedir + appimagetool (runtime downloaded from the AppImage project
   releases), output `LoadCraft-<ver>-linux.AppImage`.
5. **`release`** (needs test): `softprops/action-gh-release` creates the
   GitHub Release with both artifacts and templated notes: version, artifact
   list, "install = copy the file and run it", the SmartScreen note,
   "uninstall = delete the file", and the bundled firmware version.

Fallback if the AppImage tooling turns out flaky on the runner: build the
AppImage on a Fedora machine via the `make package-linux` target (the CI
still produces the Windows exe and the hex).

**One-time setup (during implementation):** add the remote
`git remote add origin https://github.com/Disk-MTH/LoadCraft.git`. Pushing is
a user action, not part of the automated flow.

## 4. Testing

**Python (pytest, no hardware, fake doubles — existing pattern):**

- `lifecycle`: injected clock + exit hook — no exit while a client is
  connected; exit after the 10 s grace once the last client is gone; two
  clients → exit only when both are gone; `--no-window` → no auto-exit;
- `flash` (fake avrdude runner script): success; failure returns the
  avrdude log; first candidate fails → retry succeeds on the second;
  both fail → `FlashError` with combined log; missing binary → actionable
  error; missing hex → "firmware not bundled";
- `server`: `GET /api/firmware` in all four states; `POST /api/flash`
  (not connected → 409, flash in progress → 409, success → 200, avrdude
  failure → 502 + log); `/api/keepalive` SSE open/close registration;
- `protocol`: `ver` parsed when present, `None` when absent, unknown fields
  ignored (backward/forward compatibility);
- `manager`: `pause_for_flash` / `resume_flash` (no scan while paused,
  reconnect after resume);
- existing suites (firmware ~3445 native assertions, 138 app tests) stay
  green.

**Native C (`make test-firmware`):** CFG line formatting with and without a
version argument; existing assertions untouched.

**Manual hardware validation (user's machine, after implementation):**

1. Full flash on real hardware, Linux then Windows: click → 1200 touch →
   bootloader → avrdude → auto-reconnect → badge "Up to date" with the new
   version; calibration (EEPROM) verified intact.
2. Close the tab → process exits within ~10-12 s; two tabs → exit only when
   both are closed; laptop sleep/wake does not kill the app;
3. Failure path: flash with the board unplugged mid-sequence → 502 with
   avrdude log + hints, app stays usable (manager resumes scanning);
4. Windows `.exe` on the gaming PC: SmartScreen first launch, HID still
   works after a flash, axis behaves in-game;
5. AppImage on Fedora: one-click start, tab opens, flash works;
6. CI: full run on a throwaway test tag → inspect the generated Release
   (artifacts, notes) → delete the test release.

**Gates:** `make test` (both suites), `make build` (flash/RAM budget
unchanged), CI green on a real tag.

## 5. Out of scope (v1)

- Live streaming of avrdude output to the UI (final result + log instead);
- custom application icons (PyInstaller default; placeholder `.desktop`
  icon) — follow-up polish;
- multi-device support (the app targets the handbrake, as today);
- code signing (unsigned `.exe`; SmartScreen note documented);
- installers / uninstallers (portable by design);
- pywebview in the packaged artifacts (development only);
- any firmware logic change beyond the `ver` field (acquisition, curves,
  storage untouched).

## 6. Risks and early validation

1. **Bootloader port rename.** Between CDC mode and bootloader mode the port
   device may be renamed (Linux udev numbering, Windows COM assignment).
   Mitigated by the candidate fallback (3.4). **Validated first on real
   hardware** — the very first implementation step flashes the user's board
   from the dev app before any CI work.
2. **Port contention during the 1200 touch.** The app pauses the manager
   (closing its own link) before touching; a third-party serial monitor
   still holding the port produces a clear error hint instead of a hang.
3. **AppImage toolchain on the CI runner.** Known-good recipes exist
   (appimagetool + runtime from the AppImage project releases); the
   documented fallback is building the AppImage on Fedora via
   `make package-linux` (3.7).
4. **Antivirus false positives** on PyInstaller onefile binaries
   (occasional, unrelated to the code): documented; signing is out of scope.
5. **1200-baud touch reliability on clones.** The touch is a bootloader-side
   feature of the 32u4 and is not clone-dependent, but the manual double-tap
   RESET fallback is documented in the failure hints.
