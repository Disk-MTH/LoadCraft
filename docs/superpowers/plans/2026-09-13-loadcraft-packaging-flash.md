# LoadCraft Packaging and In-App Firmware Flash — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the LoadCraft calibration app as portable Windows `.exe` and Linux AppImage artifacts that open a browser tab (close tab = app exits), report firmware versions, and flash the handbrake firmware through the built-in ATmega32u4 bootloader.

**Architecture:** The app stays Flask + pyserial with the server-side `LinkManager`. Three new modules carry the feature: `lifecycle.py` (keep-alive SSE client set + exit watchdog), `flash.py` (1200-baud bootloader touch + avrdude runner), plus the `ver` field on the firmware's CFG line. The version flows from `app/pyproject.toml` into generated `firmware/handbrake/version.h` and `app/loadcraft/_version.py`. PyInstaller builds the artifacts; GitHub Actions releases them on tag.

**Tech Stack:** Python 3.9+ (flask, pyserial, optional pywebview), avrdude (vendored in `dist-tools/`), PyInstaller, appimagetool, arduino-cli, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-loadcraft-packaging-flash-design.md`

## Global Constraints

- **Language:** all code, comments, UI strings, docs, and commit messages in English (project rule).
- **Naming:** app/product = LoadCraft — package `loadcraft`, CLI `loadcraft`, UI title `LoadCraft`, artifacts `LoadCraft-<ver>-windows-x64.exe` and `LoadCraft-<ver>-linux.AppImage`. The firmware keeps the handbrake name (`firmware/handbrake/`, `handbrake.ino`, `HB_*`).
- **Version:** single source of truth is `version` in `app/pyproject.toml` (bumped to `1.0.0` in Task 1). Release tag `v<version>` must equal it. `firmware/handbrake/version.h` and `app/loadcraft/_version.py` are generated, gitignored build artifacts.
- **Runtime dependencies:** `flask` + `pyserial` only. `pywebview` stays an optional `[desktop]` extra, excluded from packaged artifacts.
- **Serial protocol:** only the optional `ver=` field is added to the CFG reply. The app must parse CFG lines with and without `ver`, and ignore unknown fields.
- **Flash:** `-U flash:w:` only — the EEPROM (calibration) is never written. At most one flash at a time (single-flight).
- **Lifecycle:** keep-alive grace is exactly `10.0 s`; `--no-window` disables auto-exit entirely.
- **Quality gates:** `make test` green (native firmware assertions + app pytest) after every task that touches code; `make build` compiles (flash/RAM budget unchanged, ~63% / ~27%).
- **Commits:** conventional style, lowercase subject (`feat(app): ...`, `build: ...`, `docs: ...`).

## File Structure

**Renamed (Task 1):** `app/handbrake_tuner/` → `app/loadcraft/` (all modules and `web/` inside).

**Created:**

| File | Responsibility |
|---|---|
| `app/loadcraft/lifecycle.py` | `KeepAlive`: live-client set + exit watchdog (close tab = quit) |
| `app/loadcraft/flash.py` | `flash()`, `Flasher`, avrdude/hex resolution, 1200-baud touch, port candidates |
| `app/tests/test_lifecycle.py` | keep-alive tests (injected clock/exit) |
| `app/tests/test_flash.py` | flasher tests (fake avrdude runner, fake port list) |
| `app/tests/test_firmware_api.py` | `/api/firmware`, `/api/flash`, `/api/keepalive` endpoint tests |
| `app/tests/test_main.py` | CLI flag tests for `__main__.build_parser` |
| `app/loadcraft/_version.py` | generated `__version__` (gitignored) |
| `firmware/handbrake/version.h` | generated `HB_FW_VERSION` (gitignored) |
| `dist-tools/avrdude/avrdude`, `avrdude.exe`, `avrdude.conf` | vendored avrdude (committed) |
| `dist-tools/LoadCraft.desktop`, `dist-tools/LoadCraft.png` | AppImage metadata |
| `scripts/make_icon.py` | stdlib-only PNG generator for the placeholder icon |
| `.github/workflows/release.yml` | tag-driven release pipeline |

**Modified:**

| File | Change |
|---|---|
| `app/pyproject.toml` | name `loadcraft`, console script `loadcraft`, version `1.0.0` |
| `app/loadcraft/__main__.py` | browser default, `--window` / `--no-window`, keep-alive wiring, startup log |
| `app/loadcraft/server.py` | + `/api/keepalive`, `/api/firmware`, `/api/flash`; `create_app` gains `keepalive` / `flasher` |
| `app/loadcraft/manager.py` | `pause_for_flash()` / `resume_flash()`, scan suppression while flashing |
| `app/loadcraft/protocol.py` | `Config.ver` (optional), parser tolerance |
| `app/loadcraft/web/index.html` | title, keep-alive EventSource, Firmware panel, flash button |
| `app/tests/conftest.py`, `fake_board.py`, `test_*.py` | import rename; `FakeBoard.ver` |
| `firmware/handbrake/hb_protocol.{h,c}` | `hb_format_config` gains a `version` parameter |
| `firmware/handbrake/handbrake.ino` | include `version.h`, pass `HB_FW_VERSION` |
| `tests/test_hb_protocol.c` | + version tests, updated call sites |
| `Makefile` | `version`, `build-hex`, `package-win`, `package-linux`, `package`; `version.h` as build prerequisite |
| `.gitignore` | generated files, `app/loadcraft/data/`, `dist/` |
| `.vscode/launch.json` | `module: loadcraft` |
| `README.md`, `docs/design.md` | LoadCraft rename + packaging/flash docs (Tasks 2 and 14) |

Tasks are sequential (1 → 15); later tasks rely on earlier signatures.

---

### Task 1: Rename the package and product to `loadcraft`

**Files:**
- Rename: `app/handbrake_tuner/` → `app/loadcraft/`
- Modify: `app/pyproject.toml`, `app/tests/*.py`, `app/tests/conftest.py`, `app/tests/fake_board.py`, `.vscode/launch.json`, `README.md`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the importable package `loadcraft` (modules `protocol`, `link`, `manager`, `server`, `__main__`, `web/`), console script `loadcraft`, pyproject version `1.0.0`. Every later task imports `loadcraft.*`.

- [ ] **Step 1: Move the package directory**

```bash
git mv app/handbrake_tuner app/loadcraft
```

- [ ] **Step 2: Rewrite the old identifiers**

Replace both spellings everywhere except git history and the design docs (which quote the rename as history):

```bash
grep -rl "handbrake_tuner" --exclude-dir=.git --exclude-dir=superpowers . \
  | xargs -r sed -i "s/handbrake_tuner/loadcraft/g"
grep -rl "handbrake-tuner" --exclude-dir=.git --exclude-dir=superpowers . \
  | xargs -r sed -i "s/handbrake-tuner/loadcraft/g"
```

This covers: `app/pyproject.toml` (name, console script, `packages.find`, `package-data`), all `app/tests/*.py` imports, `.vscode/launch.json` (`"module"`), `README.md` (`python -m loadcraft`).

- [ ] **Step 3: Bump the version to the first LoadCraft release**

In `app/pyproject.toml`, change:

```toml
version = "0.1.0"
```

to:

```toml
version = "1.0.0"
```

- [ ] **Step 4: Refresh the editable install and run the full test suite**

The venv still has the old editable install registered:

```bash
rm -rf app/.venv/lib/python3*/site-packages/handbrake_tuner-* \
       app/.venv/lib/python3*/site-packages/__editable__* 2>/dev/null || true
cd app && uv pip install --python .venv -e ".[dev,desktop]"
make test
```

Expected: firmware core suite green (3445 assertions) and app pytest green (138 tests). No behavior changed — only names.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(app): rename the package and product to loadcraft"
```

---

### Task 2: Docs rename pass

**Files:**
- Modify: `README.md`, `docs/design.md`, `docs/wiring.md` (only where the project name appears)

**Interfaces:**
- Consumes: Task 1 (code already renamed).
- Produces: docs consistent with the LoadCraft naming; no `simracing-handbrake` references left outside `.git/` and `docs/superpowers/`.

- [ ] **Step 1: Rename the project title and wording**

In `README.md`, change the title:

```markdown
# Progressive handbrake for simracing
```

to:

```markdown
# LoadCraft — progressive handbrake for simracing
```

and add this one line right after the intro paragraph:

```markdown
**LoadCraft** is the project name; the handbrake is its first device.
```

In `docs/design.md`, add the same one-liner to its introduction. `docs/wiring.md`: fix the project name only if a grep in Step 2 shows it.

- [ ] **Step 2: Verify no stale project name remains**

```bash
grep -rn "simracing-handbrake" --exclude-dir=.git --exclude-dir=superpowers .
```

Expected: no output. (If a hit remains, fix it and re-run.)

- [ ] **Step 3: Commit**

```bash
git add README.md docs/
git commit -m "docs: rename the project to LoadCraft in the docs"
```

---

### Task 3: App protocol — optional `ver` field on CFG

**Files:**
- Modify: `app/loadcraft/protocol.py`
- Test: `app/tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.ver: Optional[str]` (attribute name `ver`), `Config.as_dict()` includes `"ver"`. Later tasks read `link.config.ver` (Task 9) and the UI reads `config.ver` via `/api/status` (Task 11).

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_protocol.py` (match its existing import style — it imports `from loadcraft import protocol`):

```python
CFG_NO_VER = (
    "CFG min=100 max=900 curve=LINEAR gamma=1.000 alpha=0.500 calibrated=1"
)


def test_config_ver_parsed():
    msg = protocol.parse_line(CFG_NO_VER + " ver=1.0.0")
    assert msg.ver == "1.0.0"


def test_config_ver_absent_is_none():
    msg = protocol.parse_line(CFG_NO_VER)
    assert msg.ver is None


def test_config_as_dict_includes_ver():
    msg = protocol.parse_line(CFG_NO_VER + " ver=2.1.0")
    assert msg.as_dict()["ver"] == "2.1.0"


def test_config_unknown_fields_ignored():
    msg = protocol.parse_line(CFG_NO_VER + " ver=1.0.0 extra=42")
    assert msg is not None
    assert msg.ver == "1.0.0"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_protocol.py -q
```

Expected: the 4 new tests FAIL (`TypeError: Config.__init__() got an unexpected keyword argument 'ver'` — or the `as_dict` key missing), existing tests pass.

- [ ] **Step 3: Implement**

In `app/loadcraft/protocol.py`, add `ver` to the `Config` dataclass (after `calibrated`, with a default so existing constructors keep working):

```python
@dataclass(frozen=True)
class Config:
    """Configuration returned by the board (``CFG ...`` line)."""

    raw_min: int
    raw_max: int
    curve: str
    gamma: float
    alpha: float
    calibrated: bool
    ver: Optional[str] = None  # firmware version (absent on older boards)

    def as_dict(self) -> dict:
        return {
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "curve": self.curve,
            "gamma": self.gamma,
            "alpha": self.alpha,
            "calibrated": self.calibrated,
            "ver": self.ver,
        }
```

In `parse_line`, the CFG branch, add `ver` to the constructor call (a missing field stays `None`):

```python
            return Config(
                raw_min=int(fields["min"]),
                raw_max=int(fields["max"]),
                curve=curve,
                gamma=float(fields["gamma"]),
                alpha=float(fields["alpha"]),
                calibrated=fields["calibrated"] == "1",
                ver=fields.get("ver"),
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass (the 4 new ones included; the others are untouched by an additive field).

- [ ] **Step 5: Commit**

```bash
git add app/loadcraft/protocol.py app/tests/test_protocol.py
git commit -m "feat(app): parse the optional ver field of the CFG line"
```

---

### Task 4: Firmware — report the version in the CFG line

**Files:**
- Modify: `firmware/handbrake/hb_protocol.h` (signature), `firmware/handbrake/hb_protocol.c`, `firmware/handbrake/handbrake.ino`, `tests/test_hb_protocol.c`, `Makefile` (root: `version.h` as build prerequisite — the generated file itself is created by Task 5's rule, which this task also adds)

**Interfaces:**
- Consumes: `hb_config_t` (existing), `HB_FW_VERSION` macro (provided by the generated `firmware/handbrake/version.h`, content `#define HB_FW_VERSION "1.0.0"`).
- Produces: `size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg, const char *version);` — `version == NULL` or `""` omits the field; otherwise the line ends with ` ver=<version>`. The on-the-wire format (Task 3's parser): `CFG min=... max=... curve=... gamma=... alpha=... calibrated=... ver=1.0.0`.

- [ ] **Step 1: Write the failing native tests**

In `tests/test_hb_protocol.c`, update the three existing `hb_format_config` call sites to pass `NULL` (the signature change):

```c
static void test_format_config(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    hb_config_defaults(&cfg);
    cfg.raw_min    = 12345;
    cfg.raw_max    = 987654;
    cfg.curve      = HB_CURVE_POWER;
    cfg.gamma      = 1.8f;
    cfg.alpha      = 0.75f;
    cfg.calibrated = 1;

    hb_format_config(buf, sizeof buf, &cfg, NULL);
    CHECK_STR(buf,
              "CFG min=12345 max=987654 curve=POWER gamma=1.800 "
              "alpha=0.750 calibrated=1");
}
```

(`test_format_config_worst_case` and `test_format_buffer_too_small`: same one-argument addition — pass `NULL` where they currently call `hb_format_config(buf, sizeof buf, &cfg)`.)

Add the new tests after `test_format_config_worst_case`:

```c
/* The version travels in the CFG line so the app can compare it with the
 * firmware version it bundles and offer a flash when they differ. */
static void test_format_config_with_version(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    hb_config_defaults(&cfg);
    cfg.raw_min    = 12345;
    cfg.raw_max    = 987654;
    cfg.curve      = HB_CURVE_POWER;
    cfg.gamma      = 1.8f;
    cfg.alpha      = 0.75f;
    cfg.calibrated = 1;

    hb_format_config(buf, sizeof buf, &cfg, "1.0.0");
    CHECK_STR(buf,
              "CFG min=12345 max=987654 curve=POWER gamma=1.800 "
              "alpha=0.750 calibrated=1 ver=1.0.0");
}

/* A long version must still fit HB_REPLY_MAX in the worst-case config,
 * otherwise the reply would truncate at the least convenient moment. */
static void test_format_config_worst_case_with_version(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    cfg.raw_min    = -8388608L;
    cfg.raw_max    = -8388608L;
    cfg.curve      = HB_CURVE_SCURVE;
    cfg.gamma      = HB_GAMMA_MAX;
    cfg.alpha      = HB_ALPHA_MAX;
    cfg.calibrated = 1;

    CHECK(hb_format_config(buf, sizeof buf, &cfg, "999.999.999") > 0);
}
```

In `main()`, register them after `RUN(test_format_config_worst_case);`:

```c
    RUN(test_format_config_with_version);
    RUN(test_format_config_worst_case_with_version);
```

- [ ] **Step 2: Run the native tests to verify they fail**

```bash
make -C tests
```

Expected: a compile error — `hb_format_config` called with 4 arguments but declared with 3 (the new tests fail to build).

- [ ] **Step 3: Implement**

In `firmware/handbrake/hb_protocol.h`, change the declaration (and its doc comment):

```c
/* "CFG min=... max=... curve=... gamma=... alpha=... calibrated=..."
 * With a version: append " ver=<version>" (version NULL or empty: omitted). */
size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg,
                        const char *version);
```

In `firmware/handbrake/hb_protocol.c`, replace the `hb_format_config` body:

```c
size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg,
                        const char *version)
{
    char gbuf[16];
    char abuf[16];
    int  n;
    int  extra;

    if (buf == NULL || size == 0) {
        return 0;
    }

    hb_fmt_fixed(gbuf, sizeof gbuf, cfg->gamma, 3);
    hb_fmt_fixed(abuf, sizeof abuf, cfg->alpha, 3);
    n = snprintf(buf, size,
                 "CFG min=%ld max=%ld curve=%s gamma=%s alpha=%s calibrated=%u",
                 (long)cfg->raw_min, (long)cfg->raw_max,
                 hb_curve_name(cfg->curve), gbuf, abuf,
                 (unsigned)cfg->calibrated);

    if (version != NULL && version[0] != '\0') {
        extra = snprintf(buf + n, size - (size_t)n, " ver=%s", version);
        if (extra < 0) {
            buf[0] = '\0';
            return 0;
        }
        n += extra;
    }

    if (n < 0 || (size_t)n >= size) {
        buf[0] = '\0';
        return 0;
    }
    return (size_t)n;
}
```

In `firmware/handbrake/handbrake.ino`, add the include next to the others and pass the version:

```c
#include "version.h"
```

```c
static void send_config()
{
    char buf[HB_REPLY_MAX];
    if (hb_format_config(buf, sizeof buf, &config, HB_FW_VERSION)) {
        reply(buf);
    }
}
```

- [ ] **Step 4: Add the generated `version.h` build rule (root `Makefile`)**

`version.h` is generated from the pyproject version (gitignored, so a fresh clone must regenerate it before compiling). Add near the existing variable block:

```make
VERSION_H = firmware/handbrake/version.h
VERSION   := $(shell sed -n 's/^version = "\(.*\)"/\1/p' app/pyproject.toml)
```

Replace the existing `build:` target with:

```make
$(VERSION_H): app/pyproject.toml
	@printf '/* Generated by make - do not edit. */\n#define HB_FW_VERSION "%s"\n' "$(VERSION)" > $@

build: $(VERSION_H)
	arduino-cli compile --fqbn $(FQBN) $(SKETCH)
```

Also add to the `clean:` target:

```make
clean:
	@$(MAKE) -C tests clean
	rm -rf $(SKETCH)/build
	rm -f $(VERSION_H)
```

And add to `.gitignore` (under `# Build artifacts`):

```
firmware/handbrake/version.h
```

- [ ] **Step 5: Run the tests**

```bash
make -C tests
```

Expected: `hb_protocol: N assertions, 0 failure(s)` (N = previous count + the new assertions), all other suites green. Then:

```bash
make build
```

Expected: firmware compiles (version.h auto-generated first), same flash/RAM budget as before (~63% / ~27%).

- [ ] **Step 6: Commit**

```bash
git add firmware/handbrake/hb_protocol.h firmware/handbrake/hb_protocol.c \
        firmware/handbrake/handbrake.ino tests/test_hb_protocol.c Makefile .gitignore
git commit -m "feat(firmware): report the firmware version in the CFG line"
```

---

### Task 5: Build pipeline — `version` and `build-hex` targets

**Files:**
- Modify: `Makefile` (root), `.gitignore`

**Interfaces:**
- Consumes: `app/pyproject.toml` (version), Task 4's `$(VERSION_H)` rule.
- Produces: `make version` (prints the pyproject version), `make build-hex [RELEASE_VERSION=v]` (writes `firmware/handbrake/version.h` and `app/loadcraft/_version.py`, compiles, copies the hex to `app/loadcraft/data/handbrake.hex`). CI (Task 13) and `package-*` (Task 12) call `build-hex`. `_version.py` content: `__version__ = "<version>"` — read by `server._app_version()` (Task 9) with a `"dev"` fallback.

- [ ] **Step 1: Add the targets (root `Makefile`)**

After the `build:`/`flash:` block, add:

```make
# --- Versioning and packaging ---------------------------------------------
# The single source of truth for the version is app/pyproject.toml.
# build-hex writes the generated version files, compiles, and places the
# hex where the app expects it. RELEASE_VERSION= overrides and must equal
# the pyproject version (the CI release tag) - a mismatch is an error.
APP_DATA = app/loadcraft/data
APP_VERSION_PY = app/loadcraft/_version.py
RELEASE_VERSION ?=

version:
	@echo "$(VERSION)"

build-hex:
	@if [ -n "$(RELEASE_VERSION)" ] && [ "$(RELEASE_VERSION)" != "$(VERSION)" ]; then \
	    echo "error: RELEASE_VERSION='$(RELEASE_VERSION)' does not match the pyproject version '$(VERSION)'"; \
	    exit 1; fi; \
	v="$(RELEASE_VERSION)"; [ -n "$$v" ] || v="$(VERSION)"; \
	printf '/* Generated by make build-hex - do not edit. */\n#define HB_FW_VERSION "%s"\n' "$$v" > $(VERSION_H); \
	printf '"""Generated by make build-hex - do not edit."""\n__version__ = "%s"\n' "$$v" > $(APP_VERSION_PY); \
	arduino-cli compile --fqbn $(FQBN) --output-dir $(SKETCH)/build $(SKETCH); \
	mkdir -p $(APP_DATA); \
	cp "$(SKETCH)/build/$(notdir $(SKETCH)).ino.$(FQBN).hex" $(APP_DATA)/handbrake.hex; \
	echo "Firmware $$v hex -> $(APP_DATA)/handbrake.hex"
```

Note: `arduino-cli compile --output-dir` requires arduino-cli ≥ 1.0. If `make build-hex` fails on an older arduino-cli, the error is explicit — upgrade arduino-cli.

Add to the `help:` target's echo block:

```make
	@echo "make version          print the project version (pyproject)"
	@echo "make build-hex        build the firmware hex into app data"
	@echo "make package-win      package the Windows exe (run on Windows)"
	@echo "make package-linux    package the Linux AppImage (run on Linux)"
```

- [ ] **Step 2: Gitignore the app data and generated files**

Add to `.gitignore`:

```
# Generated app data (populated by `make build-hex` / `make package-*`)
app/loadcraft/_version.py
app/loadcraft/data/
dist/
```

- [ ] **Step 3: Verify**

```bash
make version
make build-hex
head -2 firmware/handbrake/version.h app/loadcraft/_version.py
ls -la app/loadcraft/data/handbrake.hex
make build-hex RELEASE_VERSION=9.9.9
```

Expected: `1.0.0` printed; both generated files contain `1.0.0`; the hex exists (~18 KB); the last command prints `error: RELEASE_VERSION='9.9.9' does not match the pyproject version '1.0.0'` and exits 1. Then re-run `make build-hex` (no argument) to restore a good state.

- [ ] **Step 4: Commit**

```bash
git add Makefile .gitignore
git commit -m "build: add version and build-hex targets"
```

---

### Task 6: LinkManager — pause/resume for flashing

**Files:**
- Modify: `app/loadcraft/manager.py`
- Test: `app/tests/test_manager.py`

**Interfaces:**
- Consumes: existing `LinkManager` (states, `run_once(now)`, `_drop_link`).
- Produces: `pause_for_flash()` — sets the flash flag, closes the current link (frees the port), suppresses scans; `resume_flash()` — clears the flag and forces an immediate scan. While paused, `run_once` returns without scanning or connecting. Task 9's `/api/flash` calls these around the flash.

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_manager.py` (it already imports `LinkManager`, `SerialLink`, `FakeBoard` — reuse whatever fixture names it has for a manager wired to `FakeBoard` + an `available` ports list; if it has none equivalent, add this self-contained fixture at the top of the file):

```python
@pytest.fixture
def flash_fixtures(available, clock):
    """A manager wired to a fake board, for the flash pause/resume tests."""
    board = FakeBoard()

    def connect_fn(port: str):
        connection = SerialLink(board, port=port)
        connection.start()
        connection.request_config("GET")
        return connection

    manager = LinkManager(
        list_ports_fn=lambda: available,
        connect_fn=connect_fn,
        scan_interval=2.0,
        poll_interval=0.5,
    )
    yield manager, board, clock
    manager.stop()
```

Tests:

```python
def test_pause_for_flash_closes_the_link_and_blocks_scans(flash_fixtures):
    manager, _, clock = flash_fixtures
    manager.run_once(clock())
    assert manager.status()["connected"] is True

    manager.pause_for_flash()
    assert manager.link is None
    assert manager.status()["connected"] is False

    # Far past the scan cadence: a paused manager must not reconnect.
    manager.run_once(clock(5.0))
    assert manager.link is None


def test_resume_flash_reconnects(flash_fixtures):
    manager, _, clock = flash_fixtures
    manager.run_once(clock())
    assert manager.status()["connected"] is True

    manager.pause_for_flash()
    manager.resume_flash()

    manager.run_once(clock(2.0))  # scan cadence elapsed: reconnect
    assert manager.status()["connected"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_manager.py -q
```

Expected: the 2 new tests FAIL with `AttributeError: 'LinkManager' has no attribute 'pause_for_flash'`.

- [ ] **Step 3: Implement**

In `app/loadcraft/manager.py`:

In `__init__`, next to the other state fields:

```python
        self._flash_active = False
```

At the very top of `run_once` (before the existing `with self._lock:` block):

```python
    def run_once(self, now: float) -> None:
        """One watchdog iteration.

        With a live link: drop it if it died. Without: scan the ports on the
        scan cadence and try to connect to the handbrake. Suppressed while a
        flash is in progress: the port belongs to the flashing tool.
        """
        with self._lock:
            flash_active = self._flash_active
        if flash_active:
            return

        with self._lock:
            ...  # (the existing body is unchanged from here on)
```

After `_drop_link`, add:

```python
    def pause_for_flash(self) -> None:
        """Stops the scans and closes the link.

        The serial port is released to the flashing tool (flash.py); the
        manager stays out of the way until resume_flash().
        """
        with self._lock:
            self._flash_active = True
        self._drop_link()

    def resume_flash(self) -> None:
        """Ends the flash window: the next iteration scans immediately."""
        with self._lock:
            self._flash_active = False
            self._last_scan = 0.0
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/loadcraft/manager.py app/tests/test_manager.py
git commit -m "feat(app): add flash pause/resume to the link manager"
```

---

### Task 7: `flash.py` — 1200-baud touch and avrdude runner

**Files:**
- Create: `app/loadcraft/flash.py`
- Test: `app/tests/test_flash.py`

**Interfaces:**
- Consumes: `link.list_ports()` (port dicts with `device`, `usb`, `vid`, `pid`), `manager.KNOWN_BOARD_IDS`.
- Produces (exact signatures — Task 9 imports these):
  - `class FlashError(RuntimeError)`
  - `avrdude_path() -> str` (bundled `data/avrdude/avrdude[.exe]`, else system `avrdude`, else `FlashError`)
  - `hex_path() -> str` (bundled `data/handbrake.hex`, else `FlashError`)
  - `trigger_bootloader(port: str, opener=_real_open, hold_seconds: float = TOUCH_HOLD_SECONDS) -> None`
  - `bootloader_candidates(before: list, after: list, board_port: str) -> list` (ordered, at most 2)
  - `flash(board_port: str, *, avrdude: str | None = None, hexfile: str | None = None, list_ports_fn=link.list_ports, runner=_run, sleeper=time.sleep, touch=trigger_bootloader) -> str` (returns the combined avrdude log; raises `FlashError`)
  - `class Flasher` — `Flasher(flash_fn=flash)`, `run(board_port: str) -> str` (single-flight, raises `FlashError("flash in progress")`), `busy: bool` property.
  - Constants: `TOUCH_HOLD_SECONDS = 1.0`, `BOOTLOADER_SETTLE_SECONDS = 2.0`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_flash.py`:

```python
"""Tests of the flasher with a fake avrdude and a fake port list.

No hardware, no avrdude binary: the runner, the port scanner, the sleeper,
and the 1200-baud touch are all injected.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from loadcraft import flash
from loadcraft.flash import FlashError

PORT_BOARD = {"device": "/dev/ttyACM0", "usb": True, "vid": 0x2341, "pid": 0x8036}
PORT_BOOTLOADER = {"device": "/dev/ttyACM1", "usb": True, "vid": 0x2341, "pid": 0x0043}


def ok_log() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="Writing flash: 18112 bytes written, verified.",
        stderr="",
    )


def fail_log() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout="avrdude: no device in expected position",
        stderr="",
    )


def run_flash(list_ports_fn, runner, touch=lambda port: None):
    return flash.flash(
        "/dev/ttyACM0",
        avrdude="/fake/avrdude",
        hexfile="/fake/handbrake.hex",
        list_ports_fn=list_ports_fn,
        runner=runner,
        sleeper=lambda s: None,
        touch=touch,
    )


# --- flash() -----------------------------------------------------------------


def test_flash_success_on_the_same_port():
    touched = []
    log = run_flash(
        lambda: [PORT_BOARD],
        lambda cmd: ok_log(),
        touch=lambda port: touched.append(port),
    )
    assert "verified" in log
    assert touched == ["/dev/ttyACM0"]


def test_flash_command_uses_avr11_and_flash_w():
    cmds = []
    run_flash(lambda: [PORT_BOARD],
              lambda cmd: (cmds.append(list(cmd)), ok_log())[1])
    cmd = cmds[0]
    assert cmd[0] == "/fake/avrdude"
    assert cmd[cmd.index("-p") + 1] == "m32u4"
    assert cmd[cmd.index("-c") + 1] == "avr11"
    assert cmd[cmd.index("-P") + 1] == "/dev/ttyACM0"
    assert cmd[-1] == "flash:w:/fake/handbrake.hex"


def test_flash_falls_back_to_the_new_bootloader_port():
    def runner(cmd):
        port = cmd[cmd.index("-P") + 1]
        return ok_log() if port == "/dev/ttyACM1" else fail_log()

    def ports():
        return [PORT_BOARD, PORT_BOOTLOADER]

    log = run_flash(ports, runner)
    assert "verified" in log


def test_flash_no_candidate_raises():
    with pytest.raises(FlashError):
        run_flash(lambda: [], lambda cmd: ok_log())


def test_flash_all_candidates_fail_raises_with_log():
    with pytest.raises(FlashError) as excinfo:
        run_flash(lambda: [PORT_BOARD, PORT_BOOTLOADER], lambda cmd: fail_log())
    assert "no device in expected position" in str(excinfo.value)


# --- Path resolution -----------------------------------------------------------


def test_avrdude_path_prefers_the_bundled_binary(tmp_path, monkeypatch):
    avrdude_dir = tmp_path / "loadcraft" / "data" / "avrdude"
    avrdude_dir.mkdir(parents=True)
    bundled = avrdude_dir / ("avrdude.exe" if os.name == "nt" else "avrdude")
    bundled.write_text("fake")
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path / "loadcraft" / "data")
    assert flash.avrdude_path() == str(bundled)


def test_avrdude_path_falls_back_to_the_system(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(flash.shutil, "which", lambda name: "/usr/bin/avrdude")
    assert flash.avrdude_path() == "/usr/bin/avrdude"


def test_avrdude_path_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(flash.shutil, "which", lambda name: None)
    with pytest.raises(FlashError):
        flash.avrdude_path()


def test_hex_path_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    with pytest.raises(FlashError):
        flash.hex_path()


# --- Single-flight ---------------------------------------------------------------


def test_flasher_rejects_a_concurrent_flash():
    import threading

    release = threading.Event()

    def blocking_flash(port):
        release.wait(timeout=5.0)
        return "log"

    flasher = flash.Flasher(flash_fn=blocking_flash)
    first = threading.Thread(target=flasher.run, args=("/dev/ttyACM0",))
    first.start()
    try:
        with pytest.raises(FlashError, match="in progress"):
            flasher.run("/dev/ttyACM0")
    finally:
        release.set()
        first.join()


def test_flasher_reports_busy_while_running():
    import threading

    release = threading.Event()
    flasher = flash.Flasher(flash_fn=lambda port: release.wait(timeout=5.0) or "log")
    first = threading.Thread(target=flasher.run, args=("/dev/ttyACM0",))
    first.start()
    try:
        assert flasher.busy is True
    finally:
        release.set()
        first.join()
    assert flasher.busy is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_flash.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'loadcraft.flash'`.

- [ ] **Step 3: Implement**

Create `app/loadcraft/flash.py`:

```python
"""Firmware flashing through the built-in ATmega32u4 bootloader.

Sequence: the app opens the board's port at 1200 baud - the touch that makes
the chip reset into its bootloader - waits for the bootloader to re-appear as
a serial port, then runs avrdude against it. avrdude writes flash only
(-U flash:w:), so the EEPROM - and with it the calibration - survives.

avrdude is invoked with the plain ``avr11`` (stk500v1) programmer type: the
1200-baud touch is done by this module rather than by avrdude's ``arduino``
programmer type, so any avrdude build works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from . import link
from .manager import KNOWN_BOARD_IDS

BAUD_BOOTLOADER_TOUCH = 1200
TOUCH_HOLD_SECONDS = 1.0
BOOTLOADER_SETTLE_SECONDS = 2.0
AVRDUDE_TIMEOUT_SECONDS = 60.0
MAX_FLASH_ATTEMPTS = 2
MCU = "m32u4"
BOOTLOADER_BAUD = 57600


class FlashError(RuntimeError):
    """Flash failure with an actionable message (avrdude log included)."""


# --- Path resolution ----------------------------------------------------------


def _data_dir() -> Path:
    """Where the bundled data (hex, avrdude) lives.

    A PyInstaller onefile build extracts to sys._MEIPASS; a normal
    installation reads from the package directory.
    """
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "loadcraft" / "data"
    return Path(__file__).parent / "data"


def avrdude_path() -> str:
    name = "avrdude.exe" if os.name == "nt" else "avrdude"
    bundled = _data_dir() / "avrdude" / name
    if bundled.is_file():
        return str(bundled)
    system = shutil.which("avrdude")
    if system:
        return system
    raise FlashError(
        "avrdude not found: no bundled binary and no avrdude on PATH "
        "(on Linux: dnf install avrdude)"
    )


def hex_path() -> str:
    path = _data_dir() / "handbrake.hex"
    if not path.is_file():
        raise FlashError("firmware not bundled - run `make build-hex` first")
    return str(path)


# --- Bootloader touch ------------------------------------------------------------


def _real_open(port: str, baud: int):
    import serial

    return serial.Serial(port=port, baudrate=baud)


def trigger_bootloader(
    port: str,
    opener: Callable[[str, int], object] = _real_open,
    hold_seconds: float = TOUCH_HOLD_SECONDS,
) -> None:
    """Resets the chip into its bootloader.

    Opening the CDC port at 1200 baud is the standard touch of the 32u4
    bootloaders (the same mechanism the Arduino tooling uses). The chip
    re-enumerates in bootloader mode while the port stays open; it stays
    there for about 8 seconds.
    """
    serial = opener(port, BAUD_BOOTLOADER_TOUCH)
    try:
        time.sleep(hold_seconds)
    finally:
        serial.close()


# --- Port discovery ----------------------------------------------------------------


def _usb_ports(list_ports_fn: Callable[[], List[dict]]) -> List[dict]:
    try:
        return [p for p in list_ports_fn() if p.get("usb")]
    except Exception:
        return []


def bootloader_candidates(
    before: List[dict], after: List[dict], board_port: str
) -> List[str]:
    """Ports to try for the bootloader, ordered by likelihood.

    The bootloader usually reuses the board's port name; on some systems it
    appears as a new device with a bootloader PID (typically 2341:0043 or
    2341:0001, clone-dependent).
    """
    candidates: List[str] = []
    if any(p["device"] == board_port for p in after):
        candidates.append(board_port)

    before_devices = {p["device"] for p in before}
    for p in after:
        if p["device"] in candidates or p["device"] in before_devices:
            continue
        vid, pid = p.get("vid"), p.get("pid")
        if vid is None or pid is None:
            continue
        if (vid, pid) in KNOWN_BOARD_IDS:
            continue  # a handbrake in app mode, not the bootloader
        candidates.append(p["device"])

    return candidates[:MAX_FLASH_ATTEMPTS]


# --- Flash -----------------------------------------------------------------------


def _run(cmd: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(
        list(cmd), capture_output=True, text=True,
        timeout=AVRDUDE_TIMEOUT_SECONDS,
    )


def _conf_for(avrdude_bin: str) -> Optional[str]:
    """The avrdude.conf next to the binary, if present.

    The vendored binary is passed -C explicitly: a bare standalone avrdude
    may not find its configuration file from an arbitrary working directory.
    """
    conf = Path(avrdude_bin).resolve().parent / "avrdude.conf"
    return str(conf) if conf.is_file() else None


def flash(
    board_port: str,
    *,
    avrdude: Optional[str] = None,
    hexfile: Optional[str] = None,
    list_ports_fn: Callable[[], List[dict]] = link.list_ports,
    runner: Callable[[List[str]], "subprocess.CompletedProcess"] = _run,
    sleeper: Callable[[float], None] = time.sleep,
    touch: Callable[[str], None] = trigger_bootloader,
) -> str:
    """Flashes the bundled firmware and returns the combined avrdude log.

    Raises FlashError when the bootloader cannot be found or no candidate
    port accepted the write.
    """
    avrdude_bin = avrdude or avrdude_path()
    hexfile_ = hexfile or hex_path()

    before = _usb_ports(list_ports_fn)
    touch(board_port)
    sleeper(BOOTLOADER_SETTLE_SECONDS)
    after = _usb_ports(list_ports_fn)

    candidates = bootloader_candidates(before, after, board_port)
    if not candidates:
        raise FlashError(
            "bootloader port not found after the 1200-baud touch "
            "(double-tap RESET manually and retry)"
        )

    conf = _conf_for(avrdude_bin)
    logs: List[str] = []
    for port in candidates:
        cmd: List[str] = [avrdude_bin]
        if conf is not None:
            cmd += ["-C", conf]
        cmd += [
            "-q", "-p", MCU, "-c", "avr11",
            "-b", str(BOOTLOADER_BAUD), "-P", port,
            "-U", f"flash:w:{hexfile_}",
        ]
        try:
            proc = runner(cmd)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"[{port}] {exc}")
            continue
        log = (proc.stdout or "") + (proc.stderr or "")
        logs.append(f"[{port}] {log}")
        if proc.returncode == 0:
            return "\n".join(logs)

    raise FlashError(
        "flash failed on all candidate ports:\n" + "\n".join(logs)
    )


# --- Single-flight wrapper ---------------------------------------------------------


class Flasher:
    """At most one flash at a time (the second request gets a 409)."""

    def __init__(self, flash_fn: Callable[[str], str] = flash) -> None:
        self._flash = flash_fn
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def run(self, board_port: str) -> str:
        with self._lock:
            if self._busy:
                raise FlashError("flash in progress")
            self._busy = True
        try:
            return self._flash(board_port)
        finally:
            with self._lock:
                self._busy = False
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass (the 11 new flash tests included).

- [ ] **Step 5: Commit**

```bash
git add app/loadcraft/flash.py app/tests/test_flash.py
git commit -m "feat(app): add the avrdude-based flasher"
```

---

### Task 8: `lifecycle.py` — keep-alive watchdog

**Files:**
- Create: `app/loadcraft/lifecycle.py`
- Test: `app/tests/test_lifecycle.py`

**Interfaces:**
- Consumes: nothing.
- Produces (Task 9 and Task 10 import these):
  - `KEEPALIVE_GRACE_SECONDS = 10.0`
  - `class KeepAlive` — `KeepAlive(now_fn=time.monotonic, exit_fn=None, grace_seconds=KEEPALIVE_GRACE_SECONDS)`; methods `start()`, `stop()`, `register()`, `unregister()`, `check(now: float | None = None)`; properties `clients: int`, `exited: bool`. `exit_fn` defaults to `os._exit(0)` (the watchdog runs in a daemon thread where `sys.exit` would only end that thread); tests inject a capturing function and a controllable `now_fn`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_lifecycle.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_lifecycle.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'loadcraft.lifecycle'`.

- [ ] **Step 3: Implement**

Create `app/loadcraft/lifecycle.py`:

```python
"""Application lifecycle: the app lives as long as its interface does.

The interface is a browser tab. The page keeps an SSE channel open for its
whole life (see the /api/keepalive endpoint); when the tab closes the
channel dies with it. After a grace period - long enough to absorb
EventSource reconnects and laptop sleep/wake - the process exits. Closing
the tab is the uninstall-free way to stop the app, with no orphan server.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

KEEPALIVE_GRACE_SECONDS = 10.0
WATCHDOG_INTERVAL = 1.0


def _default_exit() -> None:
    # The watchdog runs in a daemon thread: sys.exit would only end that
    # thread, so the process is terminated outright. All state worth saving
    # (calibration) lives in the board EEPROM, not here.
    os._exit(0)


class KeepAlive:
    """Tracks live UI clients and exits when the last one is gone.

    now_fn and exit_fn are injected so tests drive the clock and capture
    the exit instead of killing the test process.
    """

    def __init__(
        self,
        now_fn: Optional[Callable[[], float]] = None,
        exit_fn: Optional[Callable[[], None]] = None,
        grace_seconds: float = KEEPALIVE_GRACE_SECONDS,
    ) -> None:
        self._now = now_fn if now_fn is not None else time.monotonic
        self._exit = exit_fn if exit_fn is not None else _default_exit
        self._grace = float(grace_seconds)

        self._lock = threading.Lock()
        self._clients = 0
        self._lost_at: Optional[float] = None
        self._exited = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Starts the watchdog thread (daemon)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="keepalive", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check()
            self._stop.wait(WATCHDOG_INTERVAL)

    # --- Client tracking ------------------------------------------------------

    def register(self) -> None:
        with self._lock:
            self._clients += 1
            self._lost_at = None

    def unregister(self) -> None:
        with self._lock:
            if self._clients > 0:
                self._clients -= 1
            if self._clients == 0:
                self._lost_at = self._now()

    @property
    def clients(self) -> int:
        with self._lock:
            return self._clients

    @property
    def exited(self) -> bool:
        with self._lock:
            return self._exited

    # --- Watchdog -------------------------------------------------------------

    def check(self, now: Optional[float] = None) -> None:
        """One watchdog iteration.

        Arms the timer on the first absence, then exits once the clients
        have been absent for the whole grace period. A returning client
        (register) restarts the window.
        """
        with self._lock:
            if self._exited:
                return
            if self._clients > 0:
                return
            if self._lost_at is None:
                self._lost_at = self._now() if now is None else now
                return
            gone = (self._now() if now is None else now) - self._lost_at
            fire = gone >= self._grace
        if fire:
            with self._lock:
                if self._exited:
                    return
                self._exited = True
            self._exit()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/loadcraft/lifecycle.py app/tests/test_lifecycle.py
git commit -m "feat(app): add the keep-alive lifecycle watchdog"
```

---

### Task 9: Server — keep-alive, firmware and flash endpoints

**Files:**
- Modify: `app/loadcraft/server.py`, `app/tests/fake_board.py`
- Test: `app/tests/test_firmware_api.py`

**Interfaces:**
- Consumes: `lifecycle.KeepAlive` (Task 8), `flash.Flasher` / `flash.FlashError` (Task 7), `manager.pause_for_flash/resume_flash` (Task 6), `Config.ver` (Task 3).
- Produces:
  - `create_app(manager, keepalive=None, flasher=None) -> Flask` (new optional parameters; existing callers/tests keep working).
  - `GET /api/keepalive` — SSE, 1-s keep-alive comments; registers a client on connect, unregisters on disconnect; 503 when `keepalive` is None.
  - `GET /api/firmware` — `{"app_version": str, "board_fw_version": str | null, "status": "up-to-date" | "mismatch" | "board-unknown" | "not-connected"}`.
  - `POST /api/flash` — 409 not connected / 409 flash in progress; 200 `{"ok": true, "log": str}`; 502 `{"error": str}` on FlashError; pauses the manager before and resumes after (finally).
  - `_app_version() -> str` — the version from the generated `loadcraft/_version.py`, or `"dev"`.

- [ ] **Step 1: Extend `FakeBoard` to emit `ver`**

In `app/tests/fake_board.py`, add a `ver` constructor parameter and emit it in the CFG line:

```python
    def __init__(self, calibrated: bool = True, ver: str | None = "1.0.0"):
        ...
        self.ver = ver
```

Replace `emit_config` with:

```python
    def emit_config(self) -> None:
        line = (
            f"CFG min={self.raw_min} max={self.raw_max} curve={self.curve} "
            f"gamma={self.gamma:.3f} alpha={self.alpha:.3f} "
            f"calibrated={1 if self.calibrated else 0}"
        )
        if self.ver is not None:
            line += f" ver={self.ver}"
        self.emit(line)
```

- [ ] **Step 2: Write the failing endpoint tests**

Create `app/tests/test_firmware_api.py`:

```python
"""Tests of the keep-alive, firmware and flash endpoints."""

from __future__ import annotations

import pytest

from loadcraft.flash import Flasher
from loadcraft.lifecycle import KeepAlive
from loadcraft.link import SerialLink
from loadcraft.manager import LinkManager
from loadcraft.server import create_app

from fake_board import FakeBoard


@pytest.fixture
def firmware_app(available, clock):
    """App with keep-alive and a stubbed flasher, wired to a fake board."""
    holder = {"board": FakeBoard()}
    calls = {"flash": 0, "port": None, "fail": False}

    def connect_fn(port: str) -> SerialLink:
        connection = SerialLink(holder["board"], port=port)
        connection.start()
        connection.request_config("GET")
        return connection

    def fake_flash_fn(port: str) -> str:
        calls["flash"] += 1
        calls["port"] = port
        if calls["fail"]:
            from loadcraft.flash import FlashError
            raise FlashError("stub avrdude failure log")
        return "stub avrdude log: verified"

    manager = LinkManager(
        list_ports_fn=lambda: available,
        connect_fn=connect_fn,
        scan_interval=2.0,
        poll_interval=0.5,
    )
    keepalive = KeepAlive()
    flasher = Flasher(flash_fn=fake_flash_fn)
    app = create_app(manager, keepalive=keepalive, flasher=flasher)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, manager, holder, available, keepalive, flasher, calls

    manager.stop()


def connect_manager(firmware_app, clock):
    client, manager, *rest = firmware_app
    manager.run_once(clock())
    assert client.get("/api/status").json["connected"] is True
    return client, manager, firmware_app[4:]


# --- /api/firmware -------------------------------------------------------------


def test_firmware_not_connected(firmware_app, monkeypatch):
    client, *_ = firmware_app
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body == {
        "app_version": "1.0.0",
        "board_fw_version": None,
        "status": "not-connected",
    }


def test_firmware_up_to_date(firmware_app, clock, monkeypatch):
    connect_manager(firmware_app, clock)
    client, *_ = firmware_app
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body == {
        "app_version": "1.0.0",
        "board_fw_version": "1.0.0",
        "status": "up-to-date",
    }


def test_firmware_mismatch(firmware_app, clock, monkeypatch):
    client, manager, holder, *rest = firmware_app
    holder["board"].ver = "0.9.0"
    manager.run_once(clock())
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    assert client.get("/api/firmware").json["status"] == "mismatch"


def test_firmware_board_unknown(firmware_app, clock, monkeypatch):
    client, manager, holder, *rest = firmware_app
    holder["board"].ver = None  # old firmware: no ver field
    manager.run_once(clock())
    monkeypatch.setattr(
        "loadcraft.server._app_version", lambda: "1.0.0"
    )
    body = client.get("/api/firmware").json
    assert body["board_fw_version"] is None
    assert body["status"] == "board-unknown"


# --- POST /api/flash -------------------------------------------------------------


def test_flash_refused_when_not_connected(firmware_app):
    client, *_ = firmware_app
    response = client.post("/api/flash")
    assert response.status_code == 409
    assert response.json["error"] == "not connected"


def test_flash_success_and_reconnect(firmware_app, clock):
    client, manager, holder, _, _, _, calls = firmware_app
    manager.run_once(clock())

    response = client.post("/api/flash")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert "verified" in response.json["log"]
    assert calls["flash"] == 1
    assert calls["port"] == "/dev/fake0"

    # The pause closed the link; after resume the manager reconnects.
    manager.run_once(clock(2.0))
    assert client.get("/api/status").json["connected"] is True


def test_flash_failure_returns_502_with_log(firmware_app, clock):
    client, manager, holder, _, _, _, calls = firmware_app
    manager.run_once(clock())
    calls["fail"] = True

    response = client.post("/api/flash")
    assert response.status_code == 502
    assert "stub avrdude failure log" in response.json["error"]

    # The failure path must resume the manager too.
    manager.run_once(clock(2.0))
    assert client.get("/api/status").json["connected"] is True


# --- GET /api/keepalive ------------------------------------------------------------


def test_keepalive_registers_and_unregisters(firmware_app):
    client, _, _, _, keepalive, _, _ = firmware_app
    response = client.get("/api/keepalive")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert keepalive.clients == 1

    first = next(response.response).decode("utf-8")
    assert first.startswith(": keepalive")

    response.response.close()  # client gone: the generator's finally runs
    assert keepalive.clients == 0
    response.close()
```

Note on the last test: `response.response` is the SSE generator itself; calling `.close()` on it simulates the client leaving and triggers the `finally` (unregister) deterministically, without sleeping.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_firmware_api.py -q
```

Expected: FAIL — `create_app() got an unexpected keyword argument 'keepalive'` (and the endpoints 404).

- [ ] **Step 4: Implement**

In `app/loadcraft/server.py`:

Add imports at the top:

```python
import time
from typing import Optional

from .flash import FlashError, Flasher
from .lifecycle import KeepAlive
```

Change the factory signature:

```python
def create_app(
    manager: LinkManager,
    keepalive: Optional[KeepAlive] = None,
    flasher: Optional[Flasher] = None,
) -> Flask:
```

Add the three endpoints and the version helper (place them after the telemetry section, before the calibration section):

```python
    # --- Keep-alive ------------------------------------------------------------

    @app.get("/api/keepalive")
    def api_keepalive():
        if keepalive is None:
            return _error("keep-alive disabled", 503)
        keepalive.register()

        def events():
            try:
                while True:
                    yield ": keepalive\n\n"
                    time.sleep(SSE_KEEPALIVE_SECONDS)
            finally:
                # The client left (tab closed, server shutting down):
                # unregister so the lifecycle watchdog can fire.
                keepalive.unregister()

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Firmware ----------------------------------------------------------------

    @app.get("/api/firmware")
    def api_firmware():
        app_version = _app_version()
        link = manager.link
        board_version = (
            link.config.ver if (link is not None and link.config is not None)
            else None
        )
        if link is None:
            status = "not-connected"
        elif board_version is None:
            status = "board-unknown"  # older firmware, no ver field
        elif board_version == app_version:
            status = "up-to-date"
        else:
            status = "mismatch"
        return jsonify(
            {
                "app_version": app_version,
                "board_fw_version": board_version,
                "status": status,
            }
        )

    # --- Flash --------------------------------------------------------------------

    @app.post("/api/flash")
    def api_flash():
        if flasher is None:
            return _error("flash not available", 503)
        if manager.link is None:
            return _error("not connected", 409)
        if flasher.busy:
            return _error("flash in progress", 409)

        port = manager.status()["port"]
        manager.pause_for_flash()
        try:
            try:
                log = flasher.run(port)
            except FlashError as exc:
                return _error(str(exc), 502)
            return jsonify({"ok": True, "log": log})
        finally:
            # Success or failure: the manager takes the port back and
            # reconnects to the board once the bootloader has reset it.
            manager.resume_flash()
```

At module level (near the `_error` helper):

```python
def _app_version() -> str:
    """The app version from the generated _version.py, or "dev"."""
    try:
        from . import _version

        return _version.__version__
    except ImportError:
        return "dev"
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass (the 8 new endpoint tests included; the existing `test_server.py` tests are unaffected by the new optional parameters).

- [ ] **Step 6: Commit**

```bash
git add app/loadcraft/server.py app/tests/fake_board.py \
        app/tests/test_firmware_api.py
git commit -m "feat(app): add keepalive, firmware and flash endpoints"
```

---

### Task 10: Entry point — browser default, flags, keep-alive wiring

**Files:**
- Modify: `app/loadcraft/__main__.py`
- Test: `app/tests/test_main.py`

**Interfaces:**
- Consumes: `lifecycle.KeepAlive` (Task 8), `flash.Flasher` (Task 7), `create_app(manager, keepalive, flasher)` (Task 9).
- Produces: CLI `loadcraft` with flags `--port N`, `--window`, `--no-window` (`--browser` is removed — the browser is the default). `build_parser() -> argparse.ArgumentParser` is importable for tests. Behavior: default = server + browser tab + keep-alive auto-exit; `--window` = pywebview (falls back to the browser when the `[desktop]` extra is missing, with no keep-alive — webview owns the lifecycle); `--no-window` = server only, never auto-exits.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_main.py`:

```python
"""CLI flag tests (the browser/webview themselves are not tested here)."""

from __future__ import annotations

import pytest

from loadcraft.__main__ import build_parser


def test_default_is_browser():
    args = build_parser().parse_args([])
    assert args.window is False
    assert args.no_window is False
    assert args.port == 0


def test_window_flag():
    args = build_parser().parse_args(["--window"])
    assert args.window is True
    assert args.no_window is False


def test_no_window_flag_with_port():
    args = build_parser().parse_args(["--no-window", "--port", "8123"])
    assert args.no_window is True
    assert args.port == 8123


def test_browser_flag_removed():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--browser"])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
app/.venv/bin/python -m pytest app/tests/test_main.py -q
```

Expected: FAIL — `ImportError: cannot import name 'build_parser'` (the module only has `main`).

- [ ] **Step 3: Rewrite `app/loadcraft/__main__.py`**

Replace the whole file with:

```python
"""Entry point: starts the local server and opens the interface.

The default interface is the user's browser, on both Windows and Linux.
The process lives as long as the interface does: closing the tab ends the
app (see lifecycle.py). The native window (pywebview, `[desktop]` extra)
remains available with --window for development.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from .flash import Flasher
from .lifecycle import KeepAlive
from .link import connect as connect_board
from .link import list_ports
from .manager import LinkManager
from .server import create_app

WINDOW_TITLE = "LoadCraft"
WINDOW_SIZE = (1024, 720)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loadcraft",
        description="LoadCraft calibration app.",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="local HTTP port (0 = automatic)"
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="open a native window instead of the browser "
        "(needs the 'desktop' extra)",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="start the server alone: no interface is opened and the app "
        "never auto-exits",
    )
    return parser


def _free_port() -> int:
    """Reserves a system-assigned free port.

    A fixed port would clash with another instance or service; letting the
    system pick avoids hunting for a "probably free" one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app, port: int) -> None:
    # threaded: the SSE streams hold a connection for its whole life; a
    # single-threaded server would stop answering anything else meanwhile.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


class _Tee:
    """Writes to two streams: the console (when there is one) and the log."""

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def write(self, data) -> None:
        self._primary.write(data)
        try:
            self._secondary.write(data)
            self._secondary.flush()
        except Exception:
            pass

    def flush(self) -> None:
        self._primary.flush()


def _attach_startup_log() -> None:
    """Packaged builds have no console: mirror stdout/stderr to a log file.

    Without this, a failed start (port bind, crash) would show up in the
    browser as a bare "connection refused" with nothing to diagnose.
    """
    try:
        log = open(
            Path(tempfile.gettempdir()) / "loadcraft.log", "a", encoding="utf-8"
        )
    except OSError:
        return
    sys.stdout = _Tee(sys.stdout, log)
    sys.stderr = _Tee(sys.stderr, log)


def main(argv: list[str] | None = None) -> int:
    _attach_startup_log()
    args = build_parser().parse_args(argv)

    port = args.port or _free_port()
    manager = LinkManager(list_ports_fn=list_ports, connect_fn=connect_board)

    # The keep-alive watchdog exits the process when the last UI client is
    # gone. Window mode does not use it: webview.start() blocks until the
    # window closes, which is the lifecycle there.
    keepalive = None
    if not args.no_window and not args.window:

        def shutdown() -> None:
            manager.stop()
            os._exit(0)  # watchdog thread: sys.exit would end only it

        keepalive = KeepAlive(exit_fn=shutdown)
        keepalive.start()

    app = create_app(manager, keepalive=keepalive, flasher=Flasher())
    url = f"http://127.0.0.1:{port}/"
    manager.start()

    if args.no_window:
        print(f"Interface available at {url}")
        _serve(app, port)
        return 0

    server = threading.Thread(
        target=_serve, args=(app, port), daemon=True
    )
    server.start()

    if args.window:
        try:
            import webview

            window = webview.create_window(
                WINDOW_TITLE, url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1]
            )
            webview.start()
            del window
            return 0
        except ImportError:
            print(
                "pywebview missing, opening in the browser "
                "(pip install 'loadcraft[desktop]' for a native window).",
                file=sys.stderr,
            )

    print(f"Interface available at {url}")
    webbrowser.open(url)

    # The browser keeps the app alive through /api/keepalive: closing the
    # tab ends the process from the watchdog thread after the grace period.
    try:
        server.join()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
app/.venv/bin/python -m pytest app/tests -q
```

Expected: all app tests pass.

- [ ] **Step 5: Manual smoke test**

```bash
app/.venv/bin/python -m loadcraft --no-window
```

Expected: prints `Interface available at http://127.0.0.1:<port>/` and stays running (Ctrl+C stops it). In a browser, the page loads with the title **LoadCraft**. Then close the tab and restart with the default flags:

```bash
app/.venv/bin/python -m loadcraft
```

Open the tab, wait for it to load, close the tab, and watch the process: it must exit on its own within ~12 s (check with `ps` / the shell prompt returning).

- [ ] **Step 6: Commit**

```bash
git add app/loadcraft/__main__.py app/tests/test_main.py
git commit -m "feat(app): default to the browser UI with close-tab exit"
```

---

### Task 11: UI — keep-alive channel and Firmware panel

**Files:**
- Modify: `app/loadcraft/web/index.html`

**Interfaces:**
- Consumes: `GET /api/keepalive` (Task 9), `GET /api/firmware` (`app_version`, `board_fw_version`, `status`), `POST /api/flash` (200 `{ok, log}` / 409 / 502 `{error}`).
- Produces: the user-facing feature. No automated JS tests in this project — verification is manual (Step 4).

- [ ] **Step 1: Title**

In `app/loadcraft/web/index.html`, change:

```html
<title>Handbrake calibration</title>
```

to:

```html
<title>LoadCraft</title>
```

and the page heading:

```html
  <h1 class="span-2">Handbrake — calibration</h1>
```

to:

```html
  <h1 class="span-2">LoadCraft — handbrake calibration</h1>
```

- [ ] **Step 2: CSS for the Firmware panel**

After the `/* --- Persistence --- */` CSS block (before `/* --- Status bar --- */`), add:

```css
  /* --- Firmware ------------------------------------------------------------ */

  .firmware-row { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  .firmware-cell { display: flex; flex-direction: column; gap: 2px; }
  .firmware-cell .label {
    font-size: 10px; letter-spacing: .1em; text-transform: uppercase;
    color: var(--muted);
  }
  .firmware-cell .value { font-family: var(--mono); font-size: 16px; }
  .firmware-cell .value.ok   { color: var(--ok); }
  .firmware-cell .value.warn { color: var(--warn); }
  .firmware-cell .value.muted{ color: var(--muted); }
  #flash-btn { margin-left: auto; }
  #flash-log {
    font-family: var(--mono); font-size: 12px;
    background: var(--panel-alt); border: 1px solid var(--line);
    border-radius: 6px; padding: 10px; margin: 12px 0 0;
    white-space: pre-wrap; max-height: 180px; overflow: auto;
  }
```

- [ ] **Step 3: HTML — the Firmware panel**

After the `persist-panel` section (before `<div class="span-2" id="status">`), add:

```html
  <section class="panel span-2" id="firmware-panel">
    <h2>Firmware</h2>
    <div class="firmware-row">
      <div class="firmware-cell"><span class="label">App</span><span class="value" id="fw-app">—</span></div>
      <div class="firmware-cell"><span class="label">Board</span><span class="value" id="fw-board">—</span></div>
      <div class="firmware-cell"><span class="label">Status</span><span class="value" id="fw-status">—</span></div>
      <button id="flash-btn" class="primary">Flash firmware</button>
    </div>
    <pre id="flash-log" class="hidden"></pre>
    <p class="hint">
      The flash reboots the board for a few seconds; the app reconnects on
      its own. The calibration (EEPROM) is not touched. If the flash fails:
      close any serial monitor, check the dialout group on Linux, or
      double-tap RESET right before the flash starts.
    </p>
  </section>
```

- [ ] **Step 4: JS — keep-alive, firmware polling, flash button**

In the script block:

Add to the `state` object:

```js
const state = {
  status: null,     /* last /api/status payload */
  config: null,
  telemetry: null,
  firmware: null,   /* last /api/firmware payload */
  flashing: false,
  events: null,
};
```

Right after the `state` definition:

```js
/* --- Keep-alive: the app process exits when the page goes away ------------- */

const keepalive = new EventSource("/api/keepalive");
/* onerror: the EventSource reconnects by itself. */
```

Add the firmware functions (after the `setStatus` / `guard` helpers):

```js
/* --- Firmware ----------------------------------------------------------------- */

const FW_STATUS = {
  "up-to-date": ["Up to date", "ok"],
  mismatch: ["Flash recommended", "warn"],
  "board-unknown": ["Unknown board version", "muted"],
  "not-connected": ["Not connected", "muted"],
};

async function pollFirmware() {
  let data;
  try {
    data = await api("/api/firmware");
  } catch (error) {
    return; /* server unreachable: keep the current UI */
  }
  state.firmware = data;
  renderFirmware();
}

function renderFirmware() {
  const fw = state.firmware;
  if (!fw) return;
  el("fw-app").textContent = fw.app_version;
  el("fw-board").textContent = fw.board_fw_version || "—";
  const [label, color] = FW_STATUS[fw.status] || [fw.status, "muted"];
  const node = el("fw-status");
  node.textContent = label;
  node.className = "value " + color;
  el("flash-btn").disabled = fw.status === "not-connected" || state.flashing;
}

el("flash-btn").addEventListener("click", async () => {
  state.flashing = true;
  el("flash-btn").textContent = "Flashing...";
  renderFirmware(); /* disables the button */
  el("flash-log").classList.add("hidden");
  setStatus("Flashing the board: the handbrake drops for a few seconds...", "ok");
  try {
    const response = await fetch("/api/flash", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (response.ok) {
      setStatus("Firmware flashed. The board reboots with the new version.", "ok");
      await pollFirmware();
    } else {
      setStatus("Flash failed - details below.", "err");
      el("flash-log").textContent = payload.error || `error ${response.status}`;
      el("flash-log").classList.remove("hidden");
    }
  } catch (error) {
    setStatus(error.message, "err");
  }
  state.flashing = false;
  el("flash-btn").textContent = "Flash firmware";
  renderFirmware();
});
```

In the `boot()` function, add the firmware polling:

```js
(async function boot() {
  openStream();
  await pollStatus();
  drawCurve();
  pollFirmware();
  setInterval(pollStatus, 1000);
  setInterval(pollFirmware, 2000);
})();
```

In the `beforeunload` handler, also close the keep-alive:

```js
window.addEventListener("beforeunload", () => {
  if (state.events) {
    state.events.close();
    state.events = null;
  }
  if (keepalive) {
    keepalive.close();
  }
});
```

- [ ] **Step 5: Manual verification**

Start the app with a board connected (or without — the panel still works):

```bash
app/.venv/bin/python -m loadcraft
```

Check in the browser:
1. Tab title is **LoadCraft**.
2. The Firmware panel shows the app version (`1.0.0` after a `make build-hex`, else `dev`), the board version when connected (e.g. `1.0.0` after flashing a board built with Task 4's firmware), and a green **Up to date** badge when they match (an old board shows **Unknown board version**).
3. With the board connected: click **Flash firmware** → "Flashing..." → the board drops for a few seconds → success message; the badge updates (see Task 15 for the real-hardware flash).
4. Without a board: the button is disabled and the status reads **Not connected**.
5. Close the tab → the server process exits within ~12 s.

- [ ] **Step 6: Commit**

```bash
git add app/loadcraft/web/index.html
git commit -m "feat(app): add the firmware panel and keep-alive to the UI"
```

---

### Task 12: Vendored avrdude, icon, and packaging targets

**Files:**
- Create: `dist-tools/avrdude/` (binaries), `dist-tools/LoadCraft.desktop`, `scripts/make_icon.py`, `dist-tools/LoadCraft.png` (generated)
- Modify: `Makefile` (root: `package-win`, `package-linux`, `package`)

**Interfaces:**
- Consumes: `build-hex` (Task 5), PyInstaller, appimagetool.
- Produces: `make package-win` → `dist/LoadCraft-<ver>-windows-x64.exe`; `make package-linux` → `dist/LoadCraft-<ver>-linux.AppImage`. The layout `app/loadcraft/data/{handbrake.hex, avrdude/avrdude[.exe], avrdude/avrdude.conf}` that `flash._data_dir()` (Task 7) resolves.

- [ ] **Step 1: Vendor the avrdude binaries**

Get the same avrdude arduino-cli uses (version pinned by the AVR package index):

```bash
curl -fsSL https://downloads.arduino.cc/packages/avr/package_avr_index.json \
  -o /tmp/avr_index.json
python3 - <<'EOF'
import json
index = json.load(open("/tmp/avr_index.json"))
pkg = [p for p in index["packages"] if p["name"] == "avr"][0]
avrdude = [t for t in pkg["tools"] if t["name"] == "avrdude"][-1]
print("version:", avrdude["version"])
for f in avrdude["files"]:
    print(f["name"], "->", f["url"])
EOF
```

Download the `avrdude-<version>-linux.tar.gz` and `avrdude-<version>-windows.tar.gz` files it lists, extract both, and place the results in `dist-tools/avrdude/` (the linux tarball provides `avrdude` and `avrdude.conf`; the windows one provides `avrdude.exe`):

```bash
mkdir -p dist-tools/avrdude
# after extracting the two tarballs into /tmp/avrdude-linux and /tmp/avrdude-windows:
find /tmp/avrdude-linux -type f -name avrdude -not -name '*.exe' \
  -exec cp {} dist-tools/avrdude/avrdude \;
cp /tmp/avrdude-linux/avrdude.conf dist-tools/avrdude/ 2>/dev/null \
  || find /tmp/avrdude-linux -name avrdude.conf -exec cp {} dist-tools/avrdude/ \;
find /tmp/avrdude-windows -type f -name avrdude.exe \
  -exec cp {} dist-tools/avrdude/avrdude.exe \;
chmod +x dist-tools/avrdude/avrdude
ls -la dist-tools/avrdude/
```

Expected: `avrdude` (Linux ELF), `avrdude.exe`, `avrdude.conf` all present. Verify the Linux binary runs: `dist-tools/avrdude/avrdude --version` prints the avrdude version. If the index layout differs, fall back to the system package source: `dnf download --source avrdude` / the distro's avrdude build — the pin is "the avrdude arduino-cli ships", document the actual version in the README (Task 14).

- [ ] **Step 2: Icon generator and desktop file**

Create `scripts/make_icon.py` (stdlib only — no PIL):

```python
"""Generates a placeholder LoadCraft icon (solid accent-blue square).

Stdlib only: hand-rolls the PNG so the build needs no image library.
Replace with a real icon later - the build only needs a same-named PNG.
"""

import struct
import sys
import zlib


def chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(
        ">I", zlib.crc32(body) & 0xFFFFFFFF
    )


def make_png(path: str, size: int = 256, rgb=(45, 163, 255)) -> None:
    raw = b"".join(
        b"\x00" + bytes(rgb) * size for _ in range(size)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    make_png(sys.argv[1] if len(sys.argv) > 1 else "LoadCraft.png")
```

Create `dist-tools/LoadCraft.desktop`:

```ini
[Desktop Entry]
Name=LoadCraft
Comment=LoadCraft handbrake calibration
Exec=LoadCraft
Icon=LoadCraft
Type=Application
Categories=Utility;
```

Generate the icon:

```bash
python3 scripts/make_icon.py dist-tools/LoadCraft.png
file dist-tools/LoadCraft.png
```

Expected: `PNG image data, 256 x 256, 8-bit/color RGB`.

- [ ] **Step 3: Packaging targets (root `Makefile`)**

Add after `build-hex` (the `pyinstaller` step runs inside the app venv; `package-linux` needs `appimagetool` and `package-win` must run on Windows — under Git Bash/MSYS make, or by hand; CI automates both, see Task 13):

```make
# --- Packaging ----------------------------------------------------------------
# package-linux: PyInstaller onedir -> AppImage (appimagetool required).
# package-win:   PyInstaller onefile (Windows only: no cross-compilation).
PYI = $(VENV_PY) -m PyInstaller

package-linux: build-hex $(VENV)
	@command -v appimagetool >/dev/null || { \
	  echo "appimagetool not found - install it from https://github.com/AppImage/appimagetool/releases"; \
	  exit 1; }
	mkdir -p $(APP_DATA)/avrdude
	cp dist-tools/avrdude/avrdude dist-tools/avrdude/avrdude.conf $(APP_DATA)/avrdude/
	cd app && uv pip install --python .venv pyinstaller
	cd app && $(PYI) --noconfirm --onedir --name LoadCraft \
		--add-data "loadcraft/data:loadcraft/data" loadcraft/__main__.py
	python3 scripts/make_icon.py dist-tools/LoadCraft.png
	rm -rf app/dist/LoadCraft.AppDir
	mkdir -p app/dist/LoadCraft.AppDir/usr/bin
	cp -r app/dist/LoadCraft/. app/dist/LoadCraft.AppDir/usr/bin/
	cp dist-tools/LoadCraft.desktop dist-tools/LoadCraft.png app/dist/LoadCraft.AppDir/
	appimagetool app/dist/LoadCraft.AppDir
	mkdir -p dist
	mv LoadCraft-x86_64.AppImage "dist/LoadCraft-$(VERSION)-linux.AppImage"
	@echo "AppImage -> dist/LoadCraft-$(VERSION)-linux.AppImage"

package-win: build-hex $(VENV)
	mkdir -p $(APP_DATA)/avrdude
	cp dist-tools/avrdude/avrdude.exe dist-tools/avrdude/avrdude.conf $(APP_DATA)/avrdude/
	cd app && uv pip install --python .venv pyinstaller
	cd app && $(PYI) --noconfirm --onefile --windowed --name LoadCraft \
		--add-data "loadcraft/data;loadcraft/data" loadcraft/__main__.py
	mkdir -p dist
	mv app/dist/LoadCraft.exe "dist/LoadCraft-$(VERSION)-windows-x64.exe"
	@echo "Exe -> dist/LoadCraft-$(VERSION)-windows-x64.exe"

package: package-linux package-win
```

Note: `package-win` under Linux will fail at the PyInstaller step (no cross-compile) — that is expected; it exists for local Windows builds and parity with CI. `package` runs both and is best-effort.

- [ ] **Step 4: Verify on this machine (Linux)**

```bash
make package-linux
ls -la dist/
```

Expected: `dist/LoadCraft-1.0.0-linux.AppImage` exists (~30-40 MB). Smoke test (optional but recommended):

```bash
./dist/LoadCraft-1.0.0-linux.AppImage
```

Expected: a tab opens titled **LoadCraft**, the UI loads, and closing the tab exits the process within ~12 s.

- [ ] **Step 5: Commit**

```bash
git add dist-tools/ scripts/make_icon.py Makefile
git commit -m "build: vendor avrdude and add the packaging targets"
```

---

### Task 13: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `make build-hex RELEASE_VERSION=` (Task 5), the PyInstaller recipes of Task 12, `dist-tools/` (Task 12).
- Produces: on tag push `v*`, a GitHub Release with `LoadCraft-<ver>-windows-x64.exe` and `LoadCraft-<ver>-linux.AppImage`.

- [ ] **Step 1: Configure the origin remote (one-time)**

```bash
git remote -v
```

Expected: no remotes (verified at planning time). Then:

```bash
git remote add origin https://github.com/Disk-MTH/LoadCraft.git
git remote -v
```

Do NOT push anything in this task — pushing is a user action (it makes the repo's content public on GitHub).

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/release.yml`:

```yaml
name: release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

defaults:
  run:
    shell: bash

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check the tag matches the pyproject version
        id: check
        run: |
          pyver=$(sed -n 's/^version = "\(.*\)"/\1/p' app/pyproject.toml)
          tag=${GITHUB_REF_NAME#v}
          if [ "$pyver" != "$tag" ]; then
            echo "::error::tag $GITHUB_REF_NAME does not match the pyproject version $pyver"
            exit 1
          fi
          echo "version=$tag" >> "$GITHUB_OUTPUT"

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the app with its test extra
        run: |
          python -m pip install --upgrade pip
          python -m pip install "app[dev]"
      - name: Firmware core tests (native)
        run: make -C tests
      - name: App tests (pytest)
        run: python -m pytest app/tests -q

  firmware:
    runs-on: ubuntu-latest
    needs: gate
    steps:
      - uses: actions/checkout@v4
      - name: Install arduino-cli
        run: |
          curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
            | sh -s -- -b /usr/local/bin
      - name: Install the AVR core and the Joystick library
        run: |
          arduino-cli core update-index
          arduino-cli core install arduino:avr
          ARDUINO_LIBRARY_ENABLE_UNSAFE_INSTALL=true \
            arduino-cli lib install --git-url https://github.com/MHeironimus/ArduinoJoystickLibrary.git
      - name: Build the hex and the generated version files
        run: make build-hex RELEASE_VERSION="${{ needs.gate.outputs.version }}"
      - uses: actions/upload-artifact@v4
        with:
          name: app-data
          path: app/loadcraft/data/

  windows:
    runs-on: windows-latest
    needs: [gate, test, firmware]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/download-artifact@v4
        with:
          name: app-data
          path: app/loadcraft/data/
      - name: Install the build dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install pyinstaller flask pyserial
      - name: Build the onefile exe
        run: |
          cd app
          pyinstaller --noconfirm --onefile --windowed --name LoadCraft \
            --add-data "loadcraft/data;loadcraft/data" loadcraft/__main__.py
      - name: Publish the artifact
        run: |
          mkdir -p dist
          mv app/dist/LoadCraft.exe "dist/LoadCraft-${{ needs.gate.outputs.version }}-windows-x64.exe"
      - uses: actions/upload-artifact@v4
        with:
          name: win-exe
          path: dist/LoadCraft-*.exe

  linux:
    runs-on: ubuntu-latest
    needs: [gate, test, firmware]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/download-artifact@v4
        with:
          name: app-data
          path: app/loadcraft/data/
      - name: Install the build dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install pyinstaller flask pyserial
      - name: Build the onedir bundle
        run: |
          cd app
          pyinstaller --noconfirm --onedir --name LoadCraft \
            --add-data "loadcraft/data:loadcraft/data" loadcraft/__main__.py
      - name: Install appimagetool and libfuse
        run: |
          curl -fsSL -o /tmp/appimagetool \
            https://github.com/AppImage/appimagetool/releases/latest/download/appimagetool-x86_64.AppImage
          chmod +x /tmp/appimagetool
          sudo apt-get update
          sudo apt-get install -y libfuse2t64 2>/dev/null \
            || sudo apt-get install -y libfuse2
      - name: Assemble the AppImage
        run: |
          rm -rf LoadCraft.AppDir
          mkdir -p LoadCraft.AppDir/usr/bin
          cp -r app/dist/LoadCraft/. LoadCraft.AppDir/usr/bin/
          cp dist-tools/LoadCraft.desktop dist-tools/LoadCraft.png LoadCraft.AppDir/
          /tmp/appimagetool LoadCraft.AppDir
      - name: Publish the artifact
        run: |
          mkdir -p dist
          mv LoadCraft-x86_64.AppImage "dist/LoadCraft-${{ needs.gate.outputs.version }}-linux.AppImage"
      - uses: actions/upload-artifact@v4
        with:
          name: linux-appimage
          path: dist/LoadCraft-*.AppImage

  release:
    runs-on: ubuntu-latest
    needs: [gate, test, firmware, windows, linux]
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: win-exe
          path: dist/
      - uses: actions/download-artifact@v4
        with:
          name: linux-appimage
          path: dist/
      - name: Create the GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/LoadCraft-*-windows-x64.exe
            dist/LoadCraft-*-linux.AppImage
          generate_release_notes: true
```

- [ ] **Step 3: Validate the workflow syntax**

If `actionlint` is available, run it:

```bash
command -v actionlint >/dev/null && actionlint .github/workflows/release.yml || echo "actionlint not installed - skipped"
```

Otherwise, verify by inspection: every `needs` refers to a defined job; artifact names (`app-data`, `win-exe`, `linux-appimage`) match between upload and download.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add the tag-driven release workflow"
```

- [ ] **Step 5: Hand over the push + first release to the user**

Tell the user (do not do it yourself): push the repo (`git push -u origin master`) and, when satisfied, tag and push `git tag v1.0.0 && git push origin v1.0.0` — the workflow then builds both artifacts and publishes the Release. To exercise the pipeline first, push a deliberately mismatched tag (e.g. `v9.9.9-test`): the gate job must fail with the version-mismatch error (and no Release is created), then `git push origin :refs/tags/v9.9.9-test` to remove it, and only then tag the real `v1.0.0`.

---

### Task 14: README and docs — packaging, flashing, release

**Files:**
- Modify: `README.md`, `docs/design.md`

**Interfaces:**
- Consumes: everything built so far (this task only documents it).
- Produces: the public documentation of the new capabilities.

- [ ] **Step 1: New README sections**

Append these sections to `README.md` (adjust the avrdude version string to the one vendored in Task 12):

```markdown
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

The vendored avrdude (see `dist-tools/avrdude/`, GPLv2, the same version
arduino-cli ships) is embedded in the artifacts; a system `avrdude` on
`PATH` is used as a fallback.

## Versioning

The version in `app/pyproject.toml` is the single source of truth. Release
tags must equal it (the CI gate fails otherwise). `make build-hex`
generates `firmware/handbrake/version.h` and `app/loadcraft/_version.py`
from it; the firmware reports the version in the `CFG` line (`ver=...`) and
the app compares it with the bundled firmware.
```

Also update the README **Structure** section: the `app/` line now reads `app/                  calibration app (Python, package loadcraft)`, and the **Calibration app** section's command examples keep `python -m loadcraft` (already renamed in Task 1).

- [ ] **Step 2: design.md pointer**

Append a short section to `docs/design.md`:

```markdown
## 12. Packaging and in-app flash (2026-09-13)

The app is distributed as a portable Windows `.exe` and a Linux AppImage
(browser-tab UI, close-tab-exit lifecycle), and can flash the firmware
through the built-in bootloader via the bundled avrdude. The firmware
reports its version in the CFG line; the version flows from
`app/pyproject.toml` into both the firmware and the app. Full design:
`docs/superpowers/specs/2026-09-13-loadcraft-packaging-flash-design.md`.
```

- [ ] **Step 3: Consistency check**

```bash
grep -rn "handbrake_tuner\|handbrake-tuner" --exclude-dir=.git --exclude-dir=superpowers .
```

Expected: no output (all code references use `loadcraft`).

- [ ] **Step 4: Commit**

```bash
git add README.md docs/design.md
git commit -m "docs: document packaging, in-app flashing and the release process"
```

---

### Task 15: Manual hardware validation

**Files:**
- None (verification only; fix-forward commits as needed, e.g. `fix(app): ...`)

**Interfaces:**
- Consumes: the complete feature.
- Produces: confidence that the flash loop, the lifecycle, and both artifacts work on real hardware.

- [ ] **Step 1: Flash the real board from the dev app (Linux, first)**

This is the early validation of the riskiest step (bootloader port behavior), done before relying on CI:

```bash
make build-hex
app/.venv/bin/python -m loadcraft
```

With the handbrake connected: wait for **Up to date** (or **Unknown board version** — the board still runs the pre-`ver` firmware), click **Flash firmware**. Expected: ~5-8 s, the board drops, reconnects, and the badge flips to **Up to date** showing `1.0.0`. Verify `GET` from a serial monitor shows `ver=1.0.0`, and that the calibration (min/max/curve) survived (EEPROM untouched).

- [ ] **Step 2: Validate the close-tab lifecycle**

- Close the tab → the process exits within ~12 s (watch the shell prompt / `ps`).
- Open two tabs → closing one leaves the app running; closing both exits it.
- With the app running, lock/unlock the laptop (sleep/wake): the app must survive (the 10 s grace absorbs the reconnect).

- [ ] **Step 3: Validate the failure path**

Unplug the board, wait for **Not connected**, then replug *during* a flash attempt (or simulate: run the flash, unplug right after the touch). Expected: a 502 with the avrdude log and hints in the UI; the app stays usable (status returns to searching, then connected on replug). No zombie process, no stuck manager.

- [ ] **Step 4: Validate the AppImage**

```bash
make package-linux
./dist/LoadCraft-1.0.0-linux.AppImage
```

Expected: tab opens (title LoadCraft), flash works from the AppImage (bundled avrdude + hex), close-tab exits.

- [ ] **Step 5: Validate the Windows exe (on the gaming PC)**

Copy `dist/LoadCraft-1.0.0-windows-x64.exe` (built on Windows via Task 12's `make package-win` or CI) and run it:

- First launch: SmartScreen *More info → Run* (expected, unsigned).
- The tab opens, the board auto-connects, the HID axis works in-game.
- Flash from the `.exe`: works, board reboots, calibration preserved.
- Close the tab: the `LoadCraft.exe` process disappears from the task manager.

- [ ] **Step 6: Final gate**

```bash
make test
make build
```

Expected: both suites green, firmware compiles within budget. Report the results honestly (including any fix-forward commits made during Steps 1-5).
