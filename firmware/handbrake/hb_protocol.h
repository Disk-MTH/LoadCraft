/*
 * hb_protocol — protocole série de configuration.
 *
 * Lignes ASCII terminées par \n dans les deux sens. C99 pur : compilé à
 * l'identique par le compilateur AVR et par les tests natifs.
 *
 * Le formatage des flottants n'utilise pas printf : l'implémentation
 * d'avr-libc ne gère pas %f sans option d'édition de liens spécifique, et
 * échoue silencieusement. Voir hb_fmt_fixed().
 */
#ifndef HB_PROTOCOL_H
#define HB_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#include "hb_core.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Assez pour la plus longue commande, avec de la marge. Une ligne plus longue
 * est rejetée plutôt que tronquée silencieusement. */
#define HB_LINE_MAX 64

/* Assez pour la plus longue réponse (CFG complète). */
#define HB_REPLY_MAX 96

typedef enum {
    HB_CMD_UNKNOWN = 0,
    HB_CMD_PING,
    HB_CMD_GET,
    HB_CMD_SAVE,
    HB_CMD_LOAD,
    HB_CMD_RESET,
    HB_CMD_STREAM,
    HB_CMD_SET_MIN,
    HB_CMD_SET_MAX,
    HB_CMD_SET_CURVE,
    HB_CMD_SET_GAMMA
} hb_cmd_kind_t;

typedef struct {
    uint8_t kind;      /* hb_cmd_kind_t */
    uint8_t has_value; /* SET MIN/MAX : 1 si une valeur explicite est fournie */
    int32_t ivalue;    /* SET MIN/MAX <v>, STREAM <0|1> */
    float   fvalue;    /* SET GAMMA <f>, SET CURVE POWER <f> */
    uint8_t curve;     /* SET CURVE : hb_curve_t */
    uint8_t has_gamma; /* SET CURVE : 1 si un gamma accompagne la courbe */
} hb_cmd_t;

/* Analyse une ligne (sans le \n final).
 * Renvoie 0 pour une ligne vide ou uniquement composée d'espaces, 1 sinon.
 * Une commande non reconnue renvoie 1 avec kind == HB_CMD_UNKNOWN. */
int hb_parse_command(const char *line, hb_cmd_t *out);

/* Nom textuel d'une courbe, tel qu'utilisé dans le protocole. */
const char *hb_curve_name(uint8_t curve);

/* Analyse un nom de courbe, insensible à la casse.
 * Renvoie 1 et remplit *out si reconnu, 0 sinon. */
int hb_curve_from_name(const char *name, uint8_t *out);

/* Écrit un flottant en notation décimale fixe, sans printf.
 * Renvoie le nombre de caractères écrits (hors \0), ou 0 si le tampon est
 * trop petit — auquel cas buf reçoit une chaîne vide. */
size_t hb_fmt_fixed(char *buf, size_t size, float value, uint8_t decimals);

/* "CFG min=… max=… curve=… gamma=… calibrated=…" */
size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg);

/* "T raw=… out=… axis=… s=…" — s=1 with a valid sample, s=0 otherwise. */
size_t hb_format_telemetry(char *buf, size_t size, int32_t raw, float unit,
                           uint16_t axis, int sensor_ok);

/* --- Accumulation de ligne --------------------------------------------- */

typedef struct {
    char    buf[HB_LINE_MAX];
    uint8_t len;
    uint8_t overflow;
    uint8_t ready;
} hb_linebuf_t;

void hb_linebuf_init(hb_linebuf_t *lb);

/* Ajoute un caractère reçu.
 * Renvoie 1 quand une ligne complète est disponible dans lb->buf (terminée
 * par \0), 0 sinon. Une ligne trop longue est signalée par lb->overflow au
 * moment où elle est rendue : l'appelant doit alors la rejeter.
 *
 * Le tampon se réarme tout seul à l'appel suivant : l'appelant lit buf et
 * overflow juste après un retour à 1, sans avoir à réinitialiser. */
int hb_linebuf_push(hb_linebuf_t *lb, char ch);

#ifdef __cplusplus
}
#endif

#endif /* HB_PROTOCOL_H */
