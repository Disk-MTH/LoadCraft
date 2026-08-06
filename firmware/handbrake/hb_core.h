/*
 * hb_core — logique de traitement du handbrake.
 *
 * C99 pur, sans dépendance Arduino : ce fichier est compilé à l'identique par
 * le compilateur AVR et par les tests natifs (tests/).
 */
#ifndef HB_CORE_H
#define HB_CORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Plage de l'axe HID transmis à l'hôte. */
#define HB_AXIS_MIN 0
#define HB_AXIS_MAX 1023

/* Bornes du paramètre de courbe. Au-delà, la courbe devient inexploitable
 * (plateau quasi total à une extrémité) sans rien apporter. */
#define HB_GAMMA_MIN 0.10f
#define HB_GAMMA_MAX 5.00f

/* Plage par défaut, EEPROM vierge : volontairement très large pour que l'axe
 * bouge à peine, ce qui rend l'absence de calibration évidente. */
#define HB_DEFAULT_RAW_MIN 0L
#define HB_DEFAULT_RAW_MAX 8000000L

typedef enum {
    HB_CURVE_LINEAR = 0,
    HB_CURVE_POWER  = 1,
    HB_CURVE_SCURVE = 2
} hb_curve_t;

typedef struct {
    int32_t raw_min;    /* lecture brute, levier au repos */
    int32_t raw_max;    /* lecture brute, force maximale voulue */
    uint8_t curve;      /* hb_curve_t */
    float   gamma;      /* paramètre de courbe, ignoré si LINEAR */
    uint8_t calibrated; /* 0 tant que l'utilisateur n'a pas calibré */
} hb_config_t;

/* Filtre exponentiel : une valeur d'état, pas de tampon circulaire. */
typedef struct {
    float   alpha;
    float   value;
    uint8_t primed;
} hb_ema_t;

/* --- Configuration ----------------------------------------------------- */

void hb_config_defaults(hb_config_t *cfg);

/* Ramène les champs hors bornes dans le domaine valide. Renvoie 1 si quelque
 * chose a été corrigé. Appliqué après chargement EEPROM et après toute
 * commande de configuration. */
int hb_config_sanitize(hb_config_t *cfg);

/* --- Traitement du signal ---------------------------------------------- */

/* Position dans la plage calibrée, bornée à [0,1].
 *
 * Fonctionne aussi quand raw_max < raw_min (cellule câblée en polarité
 * inverse) : le signe s'annule. raw_min == raw_max renvoie 0. */
float hb_normalize(int32_t raw, int32_t raw_min, int32_t raw_max);

/* Applique la courbe de réponse. t et le retour sont dans [0,1].
 * gamma == 1 rend les trois courbes identiques à LINEAR. */
float hb_curve_apply(uint8_t curve, float gamma, float t);

/* Chaîne complète : brut filtré -> sortie [0,1]. */
float hb_process(const hb_config_t *cfg, int32_t raw);

/* Sortie [0,1] -> valeur d'axe HID entière, bornée. */
uint16_t hb_axis_from_unit(float unit);

/* --- Filtre ------------------------------------------------------------ */

void    hb_ema_init(hb_ema_t *f, float alpha);
void    hb_ema_reset(hb_ema_t *f);
int32_t hb_ema_push(hb_ema_t *f, int32_t sample);
int32_t hb_ema_value(const hb_ema_t *f);

#ifdef __cplusplus
}
#endif

#endif /* HB_CORE_H */
