#include "hb_protocol.h"
#include "test_harness.h"

static hb_cmd_t parse(const char *line)
{
    hb_cmd_t cmd;
    hb_parse_command(line, &cmd);
    return cmd;
}

/* --- Commands without argument ------------------------------------------ */

static void test_simple_commands(void)
{
    CHECK_EQ_INT(parse("PING").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("GET").kind, HB_CMD_GET);
    CHECK_EQ_INT(parse("SAVE").kind, HB_CMD_SAVE);
    CHECK_EQ_INT(parse("LOAD").kind, HB_CMD_LOAD);
    CHECK_EQ_INT(parse("RESET").kind, HB_CMD_RESET);
}

static void test_case_insensitive(void)
{
    CHECK_EQ_INT(parse("ping").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("PiNg").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("set curve power 2.0").kind, HB_CMD_SET_CURVE);
}

static void test_spaces_ignored(void)
{
    CHECK_EQ_INT(parse("   PING").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("\tGET\t").kind, HB_CMD_GET);
    CHECK_EQ_INT(parse("SET    MIN     1234").kind, HB_CMD_SET_MIN);
}

/* An empty line is not an unknown command: it must not trigger any reply,
 * otherwise a simple Enter press would generate an error. */
static void test_empty_line(void)
{
    hb_cmd_t cmd;
    CHECK_EQ_INT(hb_parse_command("", &cmd), 0);
    CHECK_EQ_INT(hb_parse_command("   ", &cmd), 0);
    CHECK_EQ_INT(hb_parse_command("\t \t", &cmd), 0);
}

static void test_unknown_command(void)
{
    CHECK_EQ_INT(parse("BLAH").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("PIN").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("PINGG").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET FOO").kind, HB_CMD_UNKNOWN);
}

/* --- STREAM -------------------------------------------------------------- */

static void test_stream(void)
{
    hb_cmd_t on  = parse("STREAM 1");
    hb_cmd_t off = parse("STREAM 0");

    CHECK_EQ_INT(on.kind, HB_CMD_STREAM);
    CHECK_EQ_INT(on.ivalue, 1);
    CHECK_EQ_INT(off.kind, HB_CMD_STREAM);
    CHECK_EQ_INT(off.ivalue, 0);
}

static void test_stream_invalid(void)
{
    CHECK_EQ_INT(parse("STREAM").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM 2").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM -1").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM oui").kind, HB_CMD_UNKNOWN);
}

/* --- SET MIN / SET MAX --------------------------------------------------- */

/* Without argument: capture the current filtered value. This is the mode
 * used by the app's buttons. */
static void test_set_min_max_without_argument(void)
{
    hb_cmd_t mn = parse("SET MIN");
    hb_cmd_t mx = parse("SET MAX");

    CHECK_EQ_INT(mn.kind, HB_CMD_SET_MIN);
    CHECK_EQ_INT(mn.has_value, 0);
    CHECK_EQ_INT(mx.kind, HB_CMD_SET_MAX);
    CHECK_EQ_INT(mx.has_value, 0);
}

static void test_set_min_max_with_argument(void)
{
    hb_cmd_t mn  = parse("SET MIN 123456");
    hb_cmd_t mx  = parse("SET MAX -98765");

    CHECK_EQ_INT(mn.kind, HB_CMD_SET_MIN);
    CHECK_EQ_INT(mn.has_value, 1);
    CHECK_EQ_INT(mn.ivalue, 123456);

    CHECK_EQ_INT(mx.kind, HB_CMD_SET_MAX);
    CHECK_EQ_INT(mx.has_value, 1);
    CHECK_EQ_INT(mx.ivalue, -98765);
}

/* An unreadable argument must be rejected, not silently treated as a
 * capture of the current value: the user would lose their calibration
 * without understanding why. */
static void test_set_min_invalid_argument_rejected(void)
{
    CHECK_EQ_INT(parse("SET MIN abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET MIN 12abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET MAX 1 2").kind, HB_CMD_UNKNOWN);
}

/* --- SET CURVE ----------------------------------------------------------- */

static void test_set_curve(void)
{
    hb_cmd_t lin = parse("SET CURVE LINEAR");
    hb_cmd_t pow = parse("SET CURVE POWER");
    hb_cmd_t scv = parse("SET CURVE SCURVE");

    CHECK_EQ_INT(lin.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(lin.curve, HB_CURVE_LINEAR);
    CHECK_EQ_INT(lin.has_gamma, 0);

    CHECK_EQ_INT(pow.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(pow.curve, HB_CURVE_POWER);

    CHECK_EQ_INT(scv.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(scv.curve, HB_CURVE_SCURVE);
}

static void test_set_curve_with_gamma(void)
{
    hb_cmd_t cmd = parse("SET CURVE POWER 1.8");

    CHECK_EQ_INT(cmd.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(cmd.curve, HB_CURVE_POWER);
    CHECK_EQ_INT(cmd.has_gamma, 1);
    CHECK_NEAR(cmd.fvalue, 1.8f, 1e-5);
}

static void test_set_curve_invalid(void)
{
    CHECK_EQ_INT(parse("SET CURVE").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET CURVE PARABOLE").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET CURVE POWER abc").kind, HB_CMD_UNKNOWN);
}

/* --- SET GAMMA ----------------------------------------------------------- */

static void test_set_gamma(void)
{
    hb_cmd_t cmd = parse("SET GAMMA 2.5");

    CHECK_EQ_INT(cmd.kind, HB_CMD_SET_GAMMA);
    CHECK_NEAR(cmd.fvalue, 2.5f, 1e-5);

    CHECK_NEAR(parse("SET GAMMA 0.4").fvalue, 0.4f, 1e-5);
    CHECK_NEAR(parse("SET GAMMA 1").fvalue, 1.0f, 1e-5);
}

static void test_set_gamma_invalid(void)
{
    CHECK_EQ_INT(parse("SET GAMMA").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET GAMMA abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET GAMMA 1.5 2").kind, HB_CMD_UNKNOWN);
}

/* --- SET ALPHA ----------------------------------------------------------- */

static void test_set_alpha(void)
{
    hb_cmd_t cmd = parse("SET ALPHA 0.75");

    CHECK_EQ_INT(cmd.kind, HB_CMD_SET_ALPHA);
    CHECK_NEAR(cmd.fvalue, 0.75f, 1e-5);

    CHECK_NEAR(parse("SET ALPHA 1").fvalue, 1.0f, 1e-5);
    CHECK_NEAR(parse("SET ALPHA 0.1").fvalue, 0.1f, 1e-5);
}

static void test_set_alpha_invalid(void)
{
    CHECK_EQ_INT(parse("SET ALPHA").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET ALPHA abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET ALPHA 0.5 2").kind, HB_CMD_UNKNOWN);
}

/* --- Curve names --------------------------------------------------------- */

static void test_curve_names(void)
{
    uint8_t c;

    CHECK_STR(hb_curve_name(HB_CURVE_LINEAR), "LINEAR");
    CHECK_STR(hb_curve_name(HB_CURVE_POWER), "POWER");
    CHECK_STR(hb_curve_name(HB_CURVE_SCURVE), "SCURVE");
    CHECK_STR(hb_curve_name(99), "LINEAR");

    CHECK_EQ_INT(hb_curve_from_name("linear", &c), 1);
    CHECK_EQ_INT(c, HB_CURVE_LINEAR);
    CHECK_EQ_INT(hb_curve_from_name("SCURVE", &c), 1);
    CHECK_EQ_INT(c, HB_CURVE_SCURVE);
    CHECK_EQ_INT(hb_curve_from_name("nope", &c), 0);
}

/* Every name returned by hb_curve_name must be readable back by
 * hb_curve_from_name: otherwise a GET would produce a configuration the
 * app cannot send back. */
static void test_curve_names_round_trip(void)
{
    uint8_t i;
    for (i = 0; i <= HB_CURVE_SCURVE; i++) {
        uint8_t back = 255;
        CHECK_EQ_INT(hb_curve_from_name(hb_curve_name(i), &back), 1);
        CHECK_EQ_INT(back, i);
    }
}

/* --- Float formatting ---------------------------------------------------- */

/* avr-libc does not implement %f in printf: this home-grown formatter is
 * the only way out for a float on the firmware side. */
static void test_fmt_fixed(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, 1.0f, 3);
    CHECK_STR(buf, "1.000");

    hb_fmt_fixed(buf, sizeof buf, 0.0f, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, 0.5f, 3);
    CHECK_STR(buf, "0.500");

    hb_fmt_fixed(buf, sizeof buf, 1.8f, 3);
    CHECK_STR(buf, "1.800");

    hb_fmt_fixed(buf, sizeof buf, 0.125f, 3);
    CHECK_STR(buf, "0.125");

    hb_fmt_fixed(buf, sizeof buf, 12.25f, 2);
    CHECK_STR(buf, "12.25");

    hb_fmt_fixed(buf, sizeof buf, 42.0f, 0);
    CHECK_STR(buf, "42");
}

static void test_fmt_fixed_negatives(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, -1.5f, 3);
    CHECK_STR(buf, "-1.500");

    /* No "-0.000": a zero stays a zero once rounded. */
    hb_fmt_fixed(buf, sizeof buf, -0.0001f, 3);
    CHECK_STR(buf, "0.000");
}

static void test_fmt_fixed_rounding(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, 0.9999f, 3);
    CHECK_STR(buf, "1.000");

    hb_fmt_fixed(buf, sizeof buf, 0.0005f, 3);
    CHECK_STR(buf, "0.001");
}

static void test_fmt_fixed_buffer_too_small(void)
{
    char buf[4];

    CHECK_EQ_INT(hb_fmt_fixed(buf, sizeof buf, 1.234f, 3), 0);
    CHECK_STR(buf, ""); /* nothing truncated: empty string rather than "1.2" */
    CHECK_EQ_INT(hb_fmt_fixed(buf, 0, 1.0f, 3), 0);
}

/* A non-finite value coming from a corrupted EEPROM must never produce a
 * line the app cannot parse. */
static void test_fmt_fixed_non_finite_value(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, (float)NAN, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, (float)INFINITY, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, -(float)INFINITY, 3);
    CHECK_STR(buf, "0.000");
}

/* --- Reply formatting ---------------------------------------------------- */

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

/* HB_REPLY_MAX must cover the worst case, otherwise the reply would be
 * silently truncated at the least convenient moment. */
static void test_format_config_worst_case(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    cfg.raw_min    = -8388608L;
    cfg.raw_max    = -8388608L;
    cfg.curve      = HB_CURVE_SCURVE;
    cfg.gamma      = HB_GAMMA_MAX;
    cfg.alpha      = HB_ALPHA_MAX;
    cfg.calibrated = 1;

    CHECK(hb_format_config(buf, sizeof buf, &cfg, NULL) > 0);
}

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

static void test_format_telemetry(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.75f, 767, 1);
    CHECK_STR(buf, "T raw=123456 out=0.750 axis=767 s=1");

    hb_format_telemetry(buf, sizeof buf, -8388608L, 0.0f, 0, 1);
    CHECK_STR(buf, "T raw=-8388608 out=0.000 axis=0 s=1");
}

/* s=0 : no valid sample (stuck sensor or sensor-absent timeout). Old hosts
 * ignore the field; the host parser defaults a missing s to 1. */
static void test_format_telemetry_without_sensor(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.0f, 0, 0);
    CHECK_STR(buf, "T raw=123456 out=0.000 axis=0 s=0");
}

static void test_format_buffer_too_small(void)
{
    hb_config_t cfg;
    char        buf[8];

    hb_config_defaults(&cfg);
    CHECK_EQ_INT(hb_format_config(buf, sizeof buf, &cfg, NULL), 0);
    CHECK_STR(buf, "");
    CHECK_EQ_INT(hb_format_telemetry(buf, sizeof buf, 123456, 0.5f, 512, 1), 0);
    CHECK_STR(buf, "");
}

/* A version with a buffer that does not even fit the base line must not
 * write past the buffer: the reply is empty and the return is 0. */
static void test_format_buffer_too_small_with_version(void)
{
    hb_config_t cfg;
    char        buf[8];

    hb_config_defaults(&cfg);
    CHECK_EQ_INT(hb_format_config(buf, sizeof buf, &cfg, "1.0.0"), 0);
    CHECK_STR(buf, "");
}

/* --- Line accumulation --------------------------------------------------- */

static int push_str(hb_linebuf_t *lb, const char *s)
{
    int done = 0;
    while (*s) {
        done = hb_linebuf_push(lb, *s++);
    }
    return done;
}

static void test_linebuf_simple_line(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_STR(lb.buf, "PING");
    CHECK_EQ_INT(lb.overflow, 0);
}

static void test_linebuf_crlf(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "GET\r\n"), 1);
    CHECK_STR(lb.buf, "GET");
}

/* The buffer re-arms itself: the caller does not have to think about
 * resetting it between two commands. */
static void test_linebuf_resets_itself(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_STR(lb.buf, "PING");
    CHECK_EQ_INT(push_str(&lb, "GET\n"), 1);
    CHECK_STR(lb.buf, "GET");
    CHECK_EQ_INT(lb.len, 3);
}

static void test_linebuf_empty_line(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(hb_linebuf_push(&lb, '\n'), 1);
    CHECK_STR(lb.buf, "");
}

/* A line that is too long is flagged rather than executed truncated:
 * otherwise "SET MIN 123456789..." could become an unintended "SET MIN". */
static void test_linebuf_overflow(void)
{
    hb_linebuf_t lb;
    int          i;

    hb_linebuf_init(&lb);
    for (i = 0; i < HB_LINE_MAX * 2; i++) {
        CHECK_EQ_INT(hb_linebuf_push(&lb, 'A'), 0);
    }
    CHECK_EQ_INT(hb_linebuf_push(&lb, '\n'), 1);
    CHECK_EQ_INT(lb.overflow, 1);
    CHECK(lb.len < HB_LINE_MAX);

    /* The overflow does not stick to the next line */
    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_EQ_INT(lb.overflow, 0);
    CHECK_STR(lb.buf, "PING");
}

int main(void)
{
    RUN(test_simple_commands);
    RUN(test_case_insensitive);
    RUN(test_spaces_ignored);
    RUN(test_empty_line);
    RUN(test_unknown_command);

    RUN(test_stream);
    RUN(test_stream_invalid);

    RUN(test_set_min_max_without_argument);
    RUN(test_set_min_max_with_argument);
    RUN(test_set_min_invalid_argument_rejected);

    RUN(test_set_curve);
    RUN(test_set_curve_with_gamma);
    RUN(test_set_curve_invalid);

    RUN(test_set_gamma);
    RUN(test_set_gamma_invalid);

    RUN(test_set_alpha);
    RUN(test_set_alpha_invalid);

    RUN(test_curve_names);
    RUN(test_curve_names_round_trip);

    RUN(test_fmt_fixed);
    RUN(test_fmt_fixed_negatives);
    RUN(test_fmt_fixed_rounding);
    RUN(test_fmt_fixed_buffer_too_small);
    RUN(test_fmt_fixed_non_finite_value);

    RUN(test_format_config);
    RUN(test_format_config_worst_case);
    RUN(test_format_config_with_version);
    RUN(test_format_config_worst_case_with_version);
    RUN(test_format_telemetry);
    RUN(test_format_telemetry_without_sensor);
    RUN(test_format_buffer_too_small);
    RUN(test_format_buffer_too_small_with_version);

    RUN(test_linebuf_simple_line);
    RUN(test_linebuf_crlf);
    RUN(test_linebuf_resets_itself);
    RUN(test_linebuf_empty_line);
    RUN(test_linebuf_overflow);

    TEST_SUMMARY("hb_protocol");
}
