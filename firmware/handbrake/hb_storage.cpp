#include "hb_storage.h"

#include <EEPROM.h>

#include "config.h"
#include "hb_record.h"

bool hb_storage_load(hb_config_t &cfg)
{
    uint8_t buf[HB_RECORD_SIZE];

    for (uint16_t i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = EEPROM.read(HB_EEPROM_ADDR + i);
    }

    if (hb_record_unpack(buf, &cfg)) {
        return true;
    }

    /* Blank, corrupted, or written by an incompatible version. */
    hb_config_defaults(&cfg);
    return false;
}

void hb_storage_save(const hb_config_t &cfg)
{
    uint8_t buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &cfg);

    /* update() and not write(): the byte is only rewritten if it changes.
     * A save that modifies a single field therefore does not consume a write
     * cycle on all 26 bytes. */
    for (uint16_t i = 0; i < HB_RECORD_SIZE; i++) {
        EEPROM.update(HB_EEPROM_ADDR + i, buf[i]);
    }
}
