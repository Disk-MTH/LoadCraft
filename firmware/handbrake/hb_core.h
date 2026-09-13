/*
 * hb_core - handbrake processing logic.
 *
 * Pure C99, no Arduino dependency: this file compiles identically with the
 * AVR compiler and with the native tests (tests/).
 */
#ifndef HB_CORE_H
#define HB_CORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Range of the HID axis sent to the host. */
#define HB_AXIS_MIN 0
#define HB_AXIS_MAX 1023

/* Bounds of the curve parameter. Beyond them the curve becomes unusable
 * (a near-total plateau at one end) and buys nothing. */
#define HB_GAMMA_MIN 0.10f
#define HB_GAMMA_MAX 5.00f

/* Default range, blank EEPROM: deliberately very wide so the axis barely
 * moves, which makes the absence of calibration obvious. */
#define HB_DEFAULT_RAW_MIN 0L
#define HB_DEFAULT_RAW_MAX 8000000L

typedef enum {
    HB_CURVE_LINEAR = 0,
    HB_CURVE_POWER  = 1,
    HB_CURVE_SCURVE = 2
} hb_curve_t;

typedef struct {
    int32_t raw_min;    /* raw reading, lever at rest */
    int32_t raw_max;    /* raw reading, desired maximum force */
    uint8_t curve;      /* hb_curve_t */
    float   gamma;      /* curve parameter, ignored if LINEAR */
    uint8_t calibrated; /* 0 until the user has calibrated */
} hb_config_t;

/* Exponential filter: a state value, not a circular buffer. */
typedef struct {
    float   alpha;
    float   value;
    uint8_t primed;
} hb_ema_t;

/* --- Configuration ----------------------------------------------------- */

void hb_config_defaults(hb_config_t *cfg);

/* Brings out-of-bounds fields back into the valid domain. Returns 1 if
 * anything was corrected. Applied after an EEPROM load and after every
 * configuration command. */
int hb_config_sanitize(hb_config_t *cfg);

/* --- Signal processing -------------------------------------------------- */

/* Position within the calibrated range, clamped to [0,1].
 *
 * Also works when raw_max < raw_min (cell wired with reversed polarity):
 * the signs cancel. raw_min == raw_max returns 0. */
float hb_normalize(int32_t raw, int32_t raw_min, int32_t raw_max);

/* Applies the response curve. t and the return value are in [0,1].
 * gamma == 1 makes the three curves identical to LINEAR. */
float hb_curve_apply(uint8_t curve, float gamma, float t);

/* Full chain: filtered raw -> [0,1] output. */
float hb_process(const hb_config_t *cfg, int32_t raw);

/* [0,1] output -> bounded integer HID axis value. */
uint16_t hb_axis_from_unit(float unit);

/* --- Filter ------------------------------------------------------------- */

void    hb_ema_init(hb_ema_t *f, float alpha);
void    hb_ema_reset(hb_ema_t *f);
int32_t hb_ema_push(hb_ema_t *f, int32_t sample);
int32_t hb_ema_value(const hb_ema_t *f);

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
 * changed for at least timeout_ms; the first different sample returns 0
 * and restarts the timer. */
int hb_stuck_push(hb_stuck_t *s, uint32_t now_ms, int32_t sample);

#ifdef __cplusplus
}
#endif

#endif /* HB_CORE_H */
