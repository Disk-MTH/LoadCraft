/*
 * Persistance de la configuration en EEPROM interne du 32u4.
 *
 * L'enregistrement porte un magic, une version et un CRC : une EEPROM vierge,
 * corrompue ou écrite par une version incompatible est détectée et remplacée
 * par les valeurs par défaut, au lieu d'être prise pour une calibration
 * valide.
 */
#ifndef HB_STORAGE_H
#define HB_STORAGE_H

#include <stdint.h>

#include "hb_core.h"

/* Charge la configuration.
 * Renvoie true si un enregistrement valide a été trouvé. Sinon, cfg reçoit
 * les valeurs par défaut et renvoie false. Dans les deux cas, cfg est
 * exploitable en sortie. */
bool hb_storage_load(hb_config_t &cfg);

/* Écrit la configuration. N'écrit réellement que les octets qui changent :
 * l'EEPROM AVR est donnée pour ~100 000 cycles par octet. */
void hb_storage_save(const hb_config_t &cfg);

#endif /* HB_STORAGE_H */
