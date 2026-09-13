#include "hb_record.h"
#include "test_harness.h"

static hb_config_t sample_config(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    cfg.raw_min    = 123456;
    cfg.raw_max    = -78910;
    cfg.curve      = HB_CURVE_SCURVE;
    cfg.gamma      = 1.75f;
    cfg.calibrated = 1;
    return cfg;
}

/* --- Round trip ---------------------------------------------------------- */

static void test_round_trip(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);

    CHECK_EQ_INT(dst.raw_min, src.raw_min);
    CHECK_EQ_INT(dst.raw_max, src.raw_max);
    CHECK_EQ_INT(dst.curve, src.curve);
    CHECK_EQ_INT(dst.calibrated, src.calibrated);
    /* The float goes through its raw bits: it must come back bit-identical,
     * not merely "close". */
    CHECK(dst.gamma == src.gamma);
}

static void test_round_trip_default_values(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_EQ_INT(dst.raw_min, src.raw_min);
    CHECK_EQ_INT(dst.raw_max, src.raw_max);
    CHECK(dst.gamma == src.gamma);
}

static void test_round_trip_extremes(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.raw_min = -8388608L;
    src.raw_max = 8388607L;
    src.gamma   = HB_GAMMA_MIN;

    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_EQ_INT(dst.raw_min, -8388608L);
    CHECK_EQ_INT(dst.raw_max, 8388607L);
    CHECK_NEAR(dst.gamma, HB_GAMMA_MIN, 1e-6);
}

/* --- Corruption detection ------------------------------------------------ */

/* A blank EEPROM reads 0xFF everywhere. Without the magic, it would be
 * interpreted as a valid calibration and the axis would go anywhere. */
static void test_bare_eeprom_rejected(void)
{
    hb_config_t cfg;
    uint8_t     buf[HB_RECORD_SIZE];
    size_t      i;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0xFF;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0x00;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);
}

static void test_bad_magic_rejected(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    buf[0] ^= 0xFF;
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
}

/* An older version may have written a different layout at the same
 * address: it must be rejected, not misread. */
static void test_bad_version_rejected(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    buf[4] = 99;
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
}

/* Every useful byte must be covered by the CRC: an ignored byte would be
 * a field that can be corrupted without being detected. */
static void test_every_byte_is_covered_by_the_crc(void)
{
    hb_config_t src = sample_config();
    size_t      i;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        hb_config_t dst;
        uint8_t     buf[HB_RECORD_SIZE];

        hb_record_pack(buf, &src);
        buf[i] ^= 0x01; /* a single bit flipped */
        CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
    }
}

static void test_cfg_untouched_on_reject(void)
{
    hb_config_t cfg;
    uint8_t     buf[HB_RECORD_SIZE];
    size_t      i;

    hb_config_defaults(&cfg);
    cfg.raw_min = 4242;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0xFF;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);
    CHECK_EQ_INT(cfg.raw_min, 4242); /* not overwritten */
}

/* --- Validation after reload --------------------------------------------- */

/* A correct CRC proves integrity only. An authentic record with unusable
 * content must still be brought back into the valid domain, otherwise a NaN
 * gamma would contaminate the whole axis. */
static void test_out_of_range_values_repaired(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.gamma = 999.0f;
    src.curve = 77;
    hb_record_pack(buf, &src);

    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_NEAR(dst.gamma, HB_GAMMA_MAX, 1e-6);
    CHECK_EQ_INT(dst.curve, HB_CURVE_LINEAR);
}

static void test_gamma_nan_repaired(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.gamma = (float)NAN;
    hb_record_pack(buf, &src);

    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_NEAR(dst.gamma, 1.0f, 1e-6);
}

/* --- CRC ------------------------------------------------------------------ */

/* CRC-16/CCITT-FALSE reference vector: guarantees the implementation is
 * really the announced algorithm, and not a close variant. */
static void test_crc16_reference_vector(void)
{
    const uint8_t check[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    CHECK_EQ_INT(hb_crc16(check, sizeof check), 0x29B1);
}

static void test_crc16_detects_differences(void)
{
    const uint8_t a[] = {1, 2, 3, 4};
    const uint8_t b[] = {1, 2, 3, 5};
    const uint8_t c[] = {1, 2, 4, 3};

    CHECK(hb_crc16(a, sizeof a) != hb_crc16(b, sizeof b));
    CHECK(hb_crc16(a, sizeof a) != hb_crc16(c, sizeof c)); /* order included */
    CHECK_EQ_INT(hb_crc16(a, 0), 0xFFFF);                  /* initial value */
}

int main(void)
{
    RUN(test_round_trip);
    RUN(test_round_trip_default_values);
    RUN(test_round_trip_extremes);

    RUN(test_bare_eeprom_rejected);
    RUN(test_bad_magic_rejected);
    RUN(test_bad_version_rejected);
    RUN(test_every_byte_is_covered_by_the_crc);
    RUN(test_cfg_untouched_on_reject);

    RUN(test_out_of_range_values_repaired);
    RUN(test_gamma_nan_repaired);

    RUN(test_crc16_reference_vector);
    RUN(test_crc16_detects_differences);

    TEST_SUMMARY("hb_record");
}
