# Wiring - test setup on a breadboard

## Hardware

- 20 kg load cell (4 wires)
- HX711 module
- Pro Micro ATmega32u4, 5 V / 16 MHz, USB-C
- Breadboard + straps
- USB-C cable

Everything is powered by the Pro Micro's USB-C port. No external power
supply.

## Diagram

```
         LOAD CELL 20 kg
        ┌──────────────────────┐
        │  red     E+ ─────────┼───► E+  ┐
        │  black   E- ─────────┼───► E-  │  screw terminal
        │  green   A+ ─────────┼───► A+  │  of the HX711 module
        │  white   A- ─────────┼───► A-  ┘
        └──────────────────────┘

              MODULE HX711                    PRO MICRO 32u4
        ┌──────────────────────┐          ┌──────────────────┐
        │  VCC  ───────────────┼──────────┤ VCC   (5 V)      │
        │  GND  ───────────────┼──────────┤ GND              │
        │  DT   ───────────────┼──────────┤ 4   (data)       │
        │  SCK  ───────────────┼──────────┤ 5   (clock)      │
        │  RATE ───────────────┼──────────┤ VCC   (→ 80 SPS) │
        └──────────────────────┘          └────────┬─────────┘
                                                   │ USB-C
                                                   ▼  to the PC
```

## Pin mapping

### Load cell → HX711

| Cell wire | HX711 pin |
| --- | --- |
| E+ | E+ |
| E− | E− |
| A+ | A+ |
| A− | A− |

⚠️ **Wire colors vary by manufacturer.** The most common convention is red =
E+, black = E−, green = A+, white = A−, but check the datasheet provided with
the cell.

Mixing up A+ and A− has no consequence here: the sign flips, and the min/max
normalization absorbs it automatically (see `docs/design.md` §3.3). Reversing
E+ and E− is to be avoided, however.

### HX711 → Pro Micro

| HX711 | Pro Micro | Defined in |
| --- | --- | --- |
| VCC | `VCC` | - |
| GND | `GND` | - |
| DT | pin 4 | `config.h` → `HB_PIN_HX711_DT` |
| SCK | pin 5 | `config.h` → `HB_PIN_HX711_SCK` |
| RATE | `VCC` | - |

**`VCC` and not `RAW`**: on a Pro Micro, `RAW` is a *power input* (before the
regulator). The usable 5 V regulated output is the `VCC` pin.

**`RATE` → `VCC`** switches the HX711 from 10 to 80 samples per second. On
some modules this pin is not broken out on the connector: a solder bridge is
then needed on the `RATE` pad on the back of the board. If it is not done,
the setup still works, but with a latency of ~100 ms instead of ~12.5 ms:
clearly noticeable in a game.

Pins 4 and 5 are free GPIOs, with no conflict with the USB or anything else.
They are changeable in `firmware/handbrake/config.h`.

## Checks before first power-up

1. No short circuit between `VCC` and `GND`.
2. The 4 cell wires are firmly tightened in the terminal block (thin wires
   pop out easily).
3. `RATE` is indeed on `VCC`, not on `GND`.
4. The cell is mounted **the right way** mechanically: the arrow engraved on
   its side indicates the direction of the force. A cell mounted backwards
   still works but works in compression instead of tension: the sign is
   inverted (no software consequence) but the mechanical hold is weaker.

## First startup

```bash
# 1. Check that the raw reading reacts
#    (flash the firmware first, then:)
python -m loadcraft

# 2. Lever at rest                → type the shown raw value into the Minimum field
# 3. Pull with the maximum force  → type that raw value into the Maximum field
# 4. Adjust the curve by feel     → click "Save to the board"
```

If the raw value does not move at all when you press on the cell: check
DT/SCK, then the 4 cell wires. If it jumps erratically between extreme
values: bad ground or unstable power supply.

## Moving to the final build

The "green grids full of holes" mentioned for the final version are called
**perfboards** (veroboard). The wiring above transfers to them identically,
with soldered connections instead of straps.
