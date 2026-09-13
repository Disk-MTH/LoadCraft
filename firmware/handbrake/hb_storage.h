/*
 * Persistence of the configuration in the internal EEPROM of the 32u4.
 *
 * The record carries a magic, a version and a CRC: a blank, corrupted or
 * incompatible-version EEPROM is detected and replaced by the defaults,
 * instead of being taken for a valid calibration.
 */
#ifndef HB_STORAGE_H
#define HB_STORAGE_H

#include <stdint.h>

#include "hb_core.h"

/* Loads the configuration.
 * Returns true if a valid record was found. Otherwise, cfg receives the
 * defaults and it returns false. In both cases, cfg is usable on output. */
bool hb_storage_load(hb_config_t &cfg);

/* Writes the configuration. Only the bytes that change are actually written:
 * the AVR EEPROM is rated for ~100,000 cycles per byte. */
void hb_storage_save(const hb_config_t &cfg);

#endif /* HB_STORAGE_H */
