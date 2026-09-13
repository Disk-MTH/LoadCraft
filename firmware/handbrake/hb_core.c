#include "hb_core.h"

#include <math.h>

/* HX711 domain: signed 24-bit output. */
#define HB_RAW_LIMIT_MIN (-8388608L)
#define HB_RAW_LIMIT_MAX (8388607L)

/*
 * avr-libc has not always exposed powf. On AVR, double is a 32-bit float
 * (unless -fno-short-double), so pow() is already the single-precision
 * implementation: going through it costs nothing and removes the risk.
 */
static float hb_powf(float base, float exponent)
{
#if defined(__AVR__)
    return (float)pow((double)base, (double)exponent);
#else
    return powf(base, exponent);
#endif
}

static float hb_clamp_unit(float v)
{
    if (!(v >= 0.0f)) { /* also catches NaN */
        return 0.0f;
    }
    if (v > 1.0f) {
        return 1.0f;
    }
    return v;
}

static int32_t hb_round_i32(float v)
{
    return (int32_t)(v >= 0.0f ? v + 0.5f : v - 0.5f);
}

static int32_t hb_clamp_raw(int32_t v)
{
    if (v < HB_RAW_LIMIT_MIN) {
        return HB_RAW_LIMIT_MIN;
    }
    if (v > HB_RAW_LIMIT_MAX) {
        return HB_RAW_LIMIT_MAX;
    }
    return v;
}

void hb_config_defaults(hb_config_t *cfg)
{
    cfg->raw_min    = HB_DEFAULT_RAW_MIN;
    cfg->raw_max    = HB_DEFAULT_RAW_MAX;
    cfg->curve      = (uint8_t)HB_CURVE_LINEAR;
    cfg->gamma      = 1.0f;
    cfg->calibrated = 0;
}

int hb_config_sanitize(hb_config_t *cfg)
{
    int changed = 0;
    int32_t clamped;

    clamped = hb_clamp_raw(cfg->raw_min);
    if (clamped != cfg->raw_min) {
        cfg->raw_min = clamped;
        changed = 1;
    }

    clamped = hb_clamp_raw(cfg->raw_max);
    if (clamped != cfg->raw_max) {
        cfg->raw_max = clamped;
        changed = 1;
    }

    if (cfg->curve > (uint8_t)HB_CURVE_SCURVE) {
        cfg->curve = (uint8_t)HB_CURVE_LINEAR;
        changed = 1;
    }

    if (!(cfg->gamma >= HB_GAMMA_MIN && cfg->gamma <= HB_GAMMA_MAX)) {
        if (cfg->gamma > HB_GAMMA_MAX) {
            cfg->gamma = HB_GAMMA_MAX;
        } else if (cfg->gamma < HB_GAMMA_MIN) {
            cfg->gamma = HB_GAMMA_MIN;
        } else {
            /* Neither greater nor less: NaN. Back to neutral. */
            cfg->gamma = 1.0f;
        }
        changed = 1;
    }

    if (cfg->calibrated > 1) {
        cfg->calibrated = 1;
        changed = 1;
    }

    return changed;
}

float hb_normalize(int32_t raw, int32_t raw_min, int32_t raw_max)
{
    float span = (float)raw_max - (float)raw_min;

    if (span == 0.0f) {
        return 0.0f;
    }

    /* The division carries the sign: a reversed range (cell wired with
     * reversed polarity) yields the right result with no special handling. */
    return hb_clamp_unit(((float)raw - (float)raw_min) / span);
}

float hb_curve_apply(uint8_t curve, float gamma, float t)
{
    t = hb_clamp_unit(t);

    switch (curve) {
    case HB_CURVE_POWER:
        return hb_clamp_unit(hb_powf(t, gamma));

    case HB_CURVE_SCURVE:
        /* Two symmetric halves: soft at the ends and steep in the middle
         * for gamma > 1, the reverse for gamma < 1. Both branches evaluate
         * to 0.5 at t = 0.5, so the curve is continuous. */
        if (t < 0.5f) {
            return hb_clamp_unit(0.5f * hb_powf(2.0f * t, gamma));
        }
        return hb_clamp_unit(1.0f - 0.5f * hb_powf(2.0f * (1.0f - t), gamma));

    case HB_CURVE_LINEAR:
    default:
        return t;
    }
}

float hb_process(const hb_config_t *cfg, int32_t raw)
{
    float t = hb_normalize(raw, cfg->raw_min, cfg->raw_max);
    return hb_curve_apply(cfg->curve, cfg->gamma, t);
}

uint16_t hb_axis_from_unit(float unit)
{
    return (uint16_t)(hb_clamp_unit(unit) * (float)HB_AXIS_MAX + 0.5f);
}

void hb_ema_init(hb_ema_t *f, float alpha)
{
    if (!(alpha > 0.0f && alpha <= 1.0f)) {
        alpha = 1.0f; /* invalid alpha: the filter becomes transparent */
    }
    f->alpha  = alpha;
    f->value  = 0.0f;
    f->primed = 0;
}

void hb_ema_reset(hb_ema_t *f)
{
    f->value  = 0.0f;
    f->primed = 0;
}

int32_t hb_ema_push(hb_ema_t *f, int32_t sample)
{
    if (!f->primed) {
        /* First sample adopted as-is: otherwise the filter would take dozens
         * of readings to reach the real level starting from 0. */
        f->value  = (float)sample;
        f->primed = 1;
    } else {
        f->value += f->alpha * ((float)sample - f->value);
    }
    return hb_round_i32(f->value);
}

int32_t hb_ema_value(const hb_ema_t *f)
{
    return f->primed ? hb_round_i32(f->value) : 0;
}

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
    return (now_ms - s->last_change_ms) >= s->timeout_ms;
}
