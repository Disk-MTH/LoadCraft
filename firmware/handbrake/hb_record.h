/*
 * hb_record — sérialisation de la configuration persistante.
 *
 * Séparé de hb_storage pour rester du C99 pur et donc testable nativement :
 * la détection de corruption est précisément le genre de logique qui casse
 * sans bruit et ne se remarque qu'une fois la calibration perdue.
 *
 * Disposition explicitement petit-boutiste, indépendante du compilateur : pas
 * de struct écrite telle quelle, donc pas de surprise de bourrage ou
 * d'alignement entre la cible AVR et la machine de test.
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
#define HB_RECORD_VERSION 1
#define HB_RECORD_SIZE    22

/* Sérialise cfg dans un tampon d'exactement HB_RECORD_SIZE octets, CRC
 * compris. */
void hb_record_pack(uint8_t *buf, const hb_config_t *cfg);

/* Désérialise. Renvoie 1 si le magic, la version et le CRC concordent, et
 * remplit alors cfg (déjà validé par hb_config_sanitize). Renvoie 0 sinon,
 * sans toucher à cfg. */
int hb_record_unpack(const uint8_t *buf, hb_config_t *cfg);

/* CRC-16/CCITT-FALSE (polynôme 0x1021, valeur initiale 0xFFFF). */
uint16_t hb_crc16(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* HB_RECORD_H */
