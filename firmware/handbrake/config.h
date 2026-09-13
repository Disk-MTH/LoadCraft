/*
 * Pinout and tuning constants.
 * See docs/wiring.md for the corresponding wiring diagram.
 */
#ifndef HB_BOARD_CONFIG_H
#define HB_BOARD_CONFIG_H

/* --- HX711 pinout ------------------------------------------------------- */

#define HB_PIN_HX711_DT  4
#define HB_PIN_HX711_SCK 5

/* --- Acquisition -------------------------------------------------------- */

/* Channel A, gain 128: low-noise input, suited to a load cell.
 * The gain is selected by the number of clock pulses after the 24 data
 * bits (25 = A/128, 26 = B/32, 27 = A/64). The data rate is set by the
 * HX711 RATE pin, not by the pulse count: with the pin at its default
 * (ground) the chip converts at 10 samples/s, one reading every 100 ms.
 * 80 samples/s needs the RATE pin tied to VCC; the chip has no faster rate. */
#define HB_HX711_GAIN_PULSES 25

/* --- Rates -------------------------------------------------------------- */

/* Telemetry emission period while streaming is active. Throttled so the CDC
 * must not take precedence over the HID loop; between two sensor readings it
 * simply resends the last filtered value. */
#define HB_TELEMETRY_PERIOD_MS 33 /* ~30 Hz */

/* The HID report is sent only when the axis value changed, with this
 * maximum delay between two sends to keep the host in step even while
 * at rest. */
#define HB_HID_KEEPALIVE_MS 100

/* Beyond this delay with no HX711 conversion, the sensor is considered
 * absent or miswired: the axis falls back to zero rather than staying
 * frozen on the last value read. */
#define HB_SENSOR_TIMEOUT_MS 500

/* The raw value has not changed at all for this long: the sensor is
 * declared stuck (DOUT line stuck, converter locked). A healthy HX711 at
 * gain 128 has permanent LSB jitter, so this is a failure signature at any
 * effective rate. */
#define HB_STUCK_TIMEOUT_MS 1000

/* --- Storage ------------------------------------------------------------ */

#define HB_EEPROM_ADDR    0
#define HB_EEPROM_MAGIC   0x48424B31UL /* "HBK1" */
#define HB_EEPROM_VERSION 1

/* --- HID output --------------------------------------------------------- */

/* A single X axis, no buttons, no hat: everything unnecessary is removed
 * from the descriptor. If a particular title refused to enumerate a
 * single-axis device, enabling the Y axis here would work around it. */
#define HB_JOYSTICK_ENABLE_Y false

#endif /* HB_BOARD_CONFIG_H */
