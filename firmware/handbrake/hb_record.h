/*
 * hb_record - serialization of the persistent configuration.
 *
 * Kept separate from hb_storage to stay pure C99 and therefore natively
 * testable: corruption detection is precisely the kind of logic that breaks
 * silently and is only noticed once the calibration is gone.
 *
 * Explicitly little-endian layout, compiler-independent: no struct written
 * as-is, so no padding or alignment surprise between the AVR target and the
 * test machine.
 */
#ifndef HB_RECORD_H
#define HB_RECORD_H

#include <stddef.h>
#include <stdint.h>

#include "hb_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HB_RECORD_MAGIC   0x48424B31UL /* "HBK1" */
#define HB_RECORD_VERSION 2
#define HB_RECORD_SIZE    26

/* Serializes cfg into a buffer of exactly HB_RECORD_SIZE bytes, CRC
 * included. */
void hb_record_pack(uint8_t *buf, const hb_config_t *cfg);

/* Deserializes. Returns 1 if the magic, the version and the CRC match, and
 * fills cfg then (already validated by hb_config_sanitize). Returns 0
 * otherwise, leaving cfg untouched. */
int hb_record_unpack(const uint8_t *buf, hb_config_t *cfg);

/* CRC-16/CCITT-FALSE (polynomial 0x1021, initial value 0xFFFF). */
uint16_t hb_crc16(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* HB_RECORD_H */
