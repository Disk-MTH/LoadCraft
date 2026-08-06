#include "hb_record.h"

#include <string.h>

/*
 * Disposition (petit-boutiste) :
 *   0..3   magic        u32
 *   4      version      u8
 *   5      curve        u8
 *   6..9   raw_min      i32
 *   10..13 raw_max      i32
 *   14..17 gamma        float (bits IEEE-754)
 *   18     calibrated   u8
 *   19     réservé      u8, à zéro
 *   20..21 crc16        u16, sur les octets 0..19
 */
#define OFF_MAGIC      0
#define OFF_VERSION    4
#define OFF_CURVE      5
#define OFF_RAW_MIN    6
#define OFF_RAW_MAX    10
#define OFF_GAMMA      14
#define OFF_CALIBRATED 18
#define OFF_RESERVED   19
#define OFF_CRC        20

static void put_u32(uint8_t *buf, uint32_t v)
{
    buf[0] = (uint8_t)(v & 0xFFU);
    buf[1] = (uint8_t)((v >> 8) & 0xFFU);
    buf[2] = (uint8_t)((v >> 16) & 0xFFU);
    buf[3] = (uint8_t)((v >> 24) & 0xFFU);
}

static uint32_t get_u32(const uint8_t *buf)
{
    return (uint32_t)buf[0] | ((uint32_t)buf[1] << 8) |
           ((uint32_t)buf[2] << 16) | ((uint32_t)buf[3] << 24);
}

static void put_u16(uint8_t *buf, uint16_t v)
{
    buf[0] = (uint8_t)(v & 0xFFU);
    buf[1] = (uint8_t)((v >> 8) & 0xFFU);
}

static uint16_t get_u16(const uint8_t *buf)
{
    return (uint16_t)((uint16_t)buf[0] | ((uint16_t)buf[1] << 8));
}

/* Le flottant transite par ses bits bruts. AVR et x86 utilisent tous deux des
 * flottants IEEE-754 32 bits petit-boutistes, l'enregistrement est donc lu à
 * l'identique par les tests natifs et par la cible. */
static void put_f32(uint8_t *buf, float v)
{
    uint32_t bits;
    memcpy(&bits, &v, sizeof bits);
    put_u32(buf, bits);
}

static float get_f32(const uint8_t *buf)
{
    uint32_t bits = get_u32(buf);
    float    v;
    memcpy(&v, &bits, sizeof v);
    return v;
}

uint16_t hb_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFU;
    size_t   i;
    uint8_t  bit;

    for (i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (bit = 0; bit < 8; bit++) {
            uint16_t shifted = (uint16_t)(crc << 1);
            crc = (crc & 0x8000U) ? (uint16_t)(shifted ^ 0x1021U) : shifted;
        }
    }
    return crc;
}

void hb_record_pack(uint8_t *buf, const hb_config_t *cfg)
{
    put_u32(buf + OFF_MAGIC, HB_RECORD_MAGIC);
    buf[OFF_VERSION]    = (uint8_t)HB_RECORD_VERSION;
    buf[OFF_CURVE]      = cfg->curve;
    put_u32(buf + OFF_RAW_MIN, (uint32_t)cfg->raw_min);
    put_u32(buf + OFF_RAW_MAX, (uint32_t)cfg->raw_max);
    put_f32(buf + OFF_GAMMA, cfg->gamma);
    buf[OFF_CALIBRATED] = cfg->calibrated;
    buf[OFF_RESERVED]   = 0;
    put_u16(buf + OFF_CRC, hb_crc16(buf, OFF_CRC));
}

int hb_record_unpack(const uint8_t *buf, hb_config_t *cfg)
{
    hb_config_t parsed;

    if (get_u32(buf + OFF_MAGIC) != HB_RECORD_MAGIC) {
        return 0;
    }
    if (buf[OFF_VERSION] != (uint8_t)HB_RECORD_VERSION) {
        return 0;
    }
    if (get_u16(buf + OFF_CRC) != hb_crc16(buf, OFF_CRC)) {
        return 0;
    }

    parsed.curve      = buf[OFF_CURVE];
    parsed.raw_min    = (int32_t)get_u32(buf + OFF_RAW_MIN);
    parsed.raw_max    = (int32_t)get_u32(buf + OFF_RAW_MAX);
    parsed.gamma      = get_f32(buf + OFF_GAMMA);
    parsed.calibrated = buf[OFF_CALIBRATED];

    /* Un CRC correct ne garantit que l'intégrité, pas la validité : un
     * enregistrement écrit par une version au domaine plus large resterait
     * intact tout en contenant un gamma inexploitable. */
    hb_config_sanitize(&parsed);

    *cfg = parsed;
    return 1;
}
