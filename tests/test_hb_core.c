#include "config.h"
#include "hb_core.h"
#include "test_harness.h"

/* --- Normalization ------------------------------------------------------ */

static void test_normalize_normal_range(void)
{
    CHECK_NEAR(hb_normalize(1000, 1000, 2000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1500, 1000, 2000), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(2000, 1000, 2000), 1.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1250, 1000, 2000), 0.25f, 1e-6);
}

static void test_normalize_clamps_out_of_range(void)
{
    CHECK_NEAR(hb_normalize(500, 1000, 2000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(9999, 1000, 2000), 1.0f, 1e-6);
}

/* A cell wired with reversed polarity produces a descending range.
 * That is what lets us not expose an "invert axis" option. */
static void test_normalize_inverted_range(void)
{
    CHECK_NEAR(hb_normalize(2000, 2000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1500, 2000, 1000), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(1000, 2000, 1000), 1.0f, 1e-6);
    CHECK_NEAR(hb_normalize(2500, 2000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(0, 2000, 1000), 1.0f, 1e-6);
}

static void test_normalize_zero_range(void)
{
    CHECK_NEAR(hb_normalize(1000, 1000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(5000, 1000, 1000), 0.0f, 1e-6);
}

static void test_normalize_negative_values(void)
{
    CHECK_NEAR(hb_normalize(-500, -1000, 0), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(-8388608L, -8388608L, 8388607L), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(8388607L, -8388608L, 8388607L), 1.0f, 1e-6);
    /* Case where (raw - raw_min) would overflow an int32 if it were
     * computed in integer: the computation goes through floats for that
     * reason. */
    CHECK_NEAR(hb_normalize(0, -8388608L, 8388607L), 0.5f, 1e-3);
}

/* --- Curves ------------------------------------------------------------- */

static void test_curve_linear(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 0.37f), 0.37f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 1.0f), 1.0f, 1e-6);
    /* gamma is ignored in linear */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 3.0f, 0.5f), 0.5f, 1e-6);
}

static void test_curve_power(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, 0.5f), 0.25f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 0.5f, 0.25f), 0.5f, 1e-6);
    /* The ends are fixed points whatever gamma */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.5f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.5f, 1.0f), 1.0f, 1e-6);
}

static void test_curve_s(void)
{
    /* Fixed points: 0, 0.5 and 1 whatever gamma */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.5f), 0.5f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 1.0f), 1.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 0.4f, 0.5f), 0.5f, 1e-6);

    /* gamma > 1: soft at the ends, so below the diagonal before 0.5 */
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.25f) < 0.25f);
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.75f) > 0.75f);

    /* gamma < 1: reverse behavior */
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 0.5f, 0.25f) > 0.25f);
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 0.5f, 0.75f) < 0.75f);

    /* Symmetry around (0.5, 0.5) */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.3f)
                   + hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.7f),
               1.0f, 1e-5);
}

/* gamma = 1 must make the three curves identical: it is the neutral
 * reference announced to the user in the app. */
static void test_gamma_one_neutralizes_curves(void)
{
    float t;
    for (t = 0.0f; t <= 1.0f; t += 0.1f) {
        CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 1.0f, t), t, 1e-6);
        CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 1.0f, t), t, 1e-6);
    }
}

static void test_curves_are_monotonic(void)
{
    const uint8_t curves[] = {HB_CURVE_LINEAR, HB_CURVE_POWER, HB_CURVE_SCURVE};
    const float   gammas[] = {0.2f, 0.5f, 1.0f, 2.0f, 4.0f};
    size_t        c, g;
    int           i;

    for (c = 0; c < sizeof curves / sizeof curves[0]; c++) {
        for (g = 0; g < sizeof gammas / sizeof gammas[0]; g++) {
            float previous = -1.0f;
            for (i = 0; i <= 100; i++) {
                float t   = (float)i / 100.0f;
                float out = hb_curve_apply(curves[c], gammas[g], t);
                CHECK(out >= previous - 1e-6f);
                CHECK(out >= 0.0f && out <= 1.0f);
                previous = out;
            }
        }
    }
}

static void test_unknown_curve_falls_back_to_linear(void)
{
    CHECK_NEAR(hb_curve_apply(99, 2.0f, 0.42f), 0.42f, 1e-6);
}

static void test_curve_clamps_its_input(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, -1.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, 5.0f), 1.0f, 1e-6);
}

/* --- HID axis ----------------------------------------------------------- */

static void test_hid_axis(void)
{
    CHECK_EQ_INT(hb_axis_from_unit(0.0f), 0);
    CHECK_EQ_INT(hb_axis_from_unit(1.0f), HB_AXIS_MAX);
    CHECK_EQ_INT(hb_axis_from_unit(0.5f), 512);
    /* Bounded, never a wraparound to an unsigned integer */
    CHECK_EQ_INT(hb_axis_from_unit(-0.5f), 0);
    CHECK_EQ_INT(hb_axis_from_unit(2.0f), HB_AXIS_MAX);
}

/* --- Configuration ------------------------------------------------------ */

static void test_config_defaults(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);

    CHECK_EQ_INT(cfg.curve, HB_CURVE_LINEAR);
    CHECK_NEAR(cfg.gamma, 1.0f, 1e-6);
    CHECK_NEAR(cfg.alpha, HB_DEFAULT_ALPHA, 1e-6);
    CHECK_EQ_INT(cfg.calibrated, 0);
    /* Nothing to correct on the default values */
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 0);
}

/* Default range so wide the axis stays nearly still: the absence of
 * calibration must jump out at the user rather than produce an erratic
 * axis. */
static void test_default_uncalibrated_barely_moves(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    CHECK(hb_axis_from_unit(hb_process(&cfg, 50000)) < 10);
}

static void test_sanitize_clamps_gamma(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.gamma = 99.0f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MAX, 1e-6);

    hb_config_defaults(&cfg);
    cfg.gamma = 0.001f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MIN, 1e-6);

    hb_config_defaults(&cfg);
    cfg.gamma = -3.0f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MIN, 1e-6);
}

/* A NaN gamma coming from a corrupted EEPROM must not propagate through the
 * processing chain, otherwise the whole axis becomes NaN. */
static void test_sanitize_recovers_nan(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    cfg.gamma = (float)NAN;

    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, 1.0f, 1e-6);
}

/* The configurable alpha is bounded the same way: below the floor it would
 * freeze the axis, above it it is just the unfiltered reading. */
static void test_sanitize_clamps_alpha(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.alpha = 5.0f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.alpha, HB_ALPHA_MAX, 1e-6);

    hb_config_defaults(&cfg);
    cfg.alpha = 0.001f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.alpha, HB_ALPHA_MIN, 1e-6);

    hb_config_defaults(&cfg);
    cfg.alpha = (float)NAN;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.alpha, HB_DEFAULT_ALPHA, 1e-6);
}

static void test_sanitize_clamps_curve_and_range(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.curve = 42;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.curve, HB_CURVE_LINEAR);

    hb_config_defaults(&cfg);
    cfg.raw_min = 99999999L; /* beyond the HX711's 24 bits */
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.raw_min, 8388607L);

    hb_config_defaults(&cfg);
    cfg.calibrated = 200;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.calibrated, 1);
}

/* --- Full chain --------------------------------------------------------- */

static void test_process_end_to_end(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.raw_min    = 100000;
    cfg.raw_max    = 900000;
    cfg.calibrated = 1;

    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 100000)), 0);
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 900000)), HB_AXIS_MAX);
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 500000)), 512);

    /* Below the minimum: the axis stays at zero, the lever is at rest. */
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 50000)), 0);
    /* Beyond the maximum: saturated, no return to zero. */
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 2000000)), HB_AXIS_MAX);

    cfg.curve = HB_CURVE_POWER;
    cfg.gamma = 2.0f;
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 500000)), 256);
}

/* --- EMA filter --------------------------------------------------------- */

/* The first sample is adopted as-is, otherwise the filter would take dozens
 * of readings to reach the real level starting from zero. */
static void test_ema_adopts_the_first_sample(void)
{
    hb_ema_t f;
    hb_ema_init(&f, 0.25f);

    CHECK_EQ_INT(hb_ema_value(&f), 0);
    CHECK_EQ_INT(hb_ema_push(&f, 500000), 500000);
    CHECK_EQ_INT(hb_ema_value(&f), 500000);
}

static void test_ema_converge(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 0);
    for (i = 0; i < 200; i++) {
        hb_ema_push(&f, 1000);
    }
    CHECK_EQ_INT(hb_ema_value(&f), 1000);
}

/* Responsiveness of the default constant: a step (pulling) and a release
 * must both be followed within a few samples, otherwise the handbrake feels
 * "mushy". 90% of a step in 4 samples, whatever the effective rate. */
static void test_ema_reactive_constant_production(void)
{
    hb_ema_t f;
    int      i;

    /* Pull: 0 -> 100000 */
    hb_ema_init(&f, HB_DEFAULT_ALPHA);
    hb_ema_push(&f, 0);
    for (i = 0; i < 4; i++) {
        hb_ema_push(&f, 100000);
    }
    CHECK(hb_ema_value(&f) >= 90000);

    /* Release: 100000 -> 0, same time budget */
    hb_ema_init(&f, HB_DEFAULT_ALPHA);
    hb_ema_push(&f, 100000);
    for (i = 0; i < 4; i++) {
        hb_ema_push(&f, 0);
    }
    CHECK(hb_ema_value(&f) <= 10000);
}

static void test_ema_smooths_noise(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 1000);
    /* Symmetric noise: the output must stay close to the real level */
    for (i = 0; i < 100; i++) {
        hb_ema_push(&f, (i % 2 == 0) ? 1050 : 950);
    }
    CHECK(hb_ema_value(&f) > 970 && hb_ema_value(&f) < 1030);
}

static void test_ema_handles_negative_values(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.5f);
    hb_ema_push(&f, -1000);
    for (i = 0; i < 100; i++) {
        hb_ema_push(&f, -2000);
    }
    CHECK_EQ_INT(hb_ema_value(&f), -2000);
}

static void test_ema_invalid_alpha_becomes_transparent(void)
{
    hb_ema_t f;

    hb_ema_init(&f, 0.0f);
    hb_ema_push(&f, 100);
    CHECK_EQ_INT(hb_ema_push(&f, 900), 900);

    hb_ema_init(&f, 5.0f);
    hb_ema_push(&f, 100);
    CHECK_EQ_INT(hb_ema_push(&f, 900), 900);
}

static void test_ema_reset(void)
{
    hb_ema_t f;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 500000);
    hb_ema_reset(&f);
    CHECK_EQ_INT(hb_ema_value(&f), 0);
    CHECK_EQ_INT(hb_ema_push(&f, 123), 123);
}

/* --- Stuck-value detection ------------------------------------------------ */

/* A healthy HX711 at gain 128 has permanent LSB jitter: a bit-identical raw
 * value for the whole timeout is a failure signature (DOUT line stuck,
 * converter locked), never a quiet sensor. */
static void test_stuck_detects_a_frozen_value(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout - 1, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, 1000), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, 5 * timeout, 1000), 1);
}

static void test_stuck_recovers_on_a_different_value(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, 1000), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 2, 1001), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, 2 * timeout + 1, 1001), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, 2 * timeout + 2, 1001), 1);
}

/* A change before the threshold restarts the timer: two short episodes of
 * the same value must not add up to a stuck declaration. */
static void test_stuck_change_before_threshold_restarts_timer(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout / 2, 1000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout / 2 + 1, 2000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + timeout / 2, 2000), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + timeout / 2 + 1, 2000), 1);
}

static void test_stuck_with_negative_values(void)
{
    hb_stuck_t s;
    uint32_t   timeout = HB_STUCK_TIMEOUT_MS;

    hb_stuck_init(&s, timeout);
    CHECK_EQ_INT(hb_stuck_push(&s, 0, -5), 0);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 1, -5), 1);
    CHECK_EQ_INT(hb_stuck_push(&s, timeout + 2, -4), 0);
}

int main(void)
{
    RUN(test_normalize_normal_range);
    RUN(test_normalize_clamps_out_of_range);
    RUN(test_normalize_inverted_range);
    RUN(test_normalize_zero_range);
    RUN(test_normalize_negative_values);

    RUN(test_curve_linear);
    RUN(test_curve_power);
    RUN(test_curve_s);
    RUN(test_gamma_one_neutralizes_curves);
    RUN(test_curves_are_monotonic);
    RUN(test_unknown_curve_falls_back_to_linear);
    RUN(test_curve_clamps_its_input);

    RUN(test_hid_axis);

    RUN(test_config_defaults);
    RUN(test_default_uncalibrated_barely_moves);
    RUN(test_sanitize_clamps_gamma);
    RUN(test_sanitize_recovers_nan);
    RUN(test_sanitize_clamps_alpha);
    RUN(test_sanitize_clamps_curve_and_range);

    RUN(test_process_end_to_end);

    RUN(test_ema_adopts_the_first_sample);
    RUN(test_ema_converge);
    RUN(test_ema_reactive_constant_production);
    RUN(test_ema_smooths_noise);
    RUN(test_ema_handles_negative_values);
    RUN(test_ema_invalid_alpha_becomes_transparent);
    RUN(test_stuck_detects_a_frozen_value);
    RUN(test_stuck_recovers_on_a_different_value);
    RUN(test_stuck_change_before_threshold_restarts_timer);
    RUN(test_stuck_with_negative_values);
    RUN(test_ema_reset);

    TEST_SUMMARY("hb_core");
}
