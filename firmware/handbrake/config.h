/*
 * Brochage et constantes de réglage.
 * Voir docs/wiring.md pour le schéma de câblage correspondant.
 */
#ifndef HB_BOARD_CONFIG_H
#define HB_BOARD_CONFIG_H

/* --- Brochage HX711 ----------------------------------------------------- */

#define HB_PIN_HX711_DT  4
#define HB_PIN_HX711_SCK 5

/* --- Acquisition -------------------------------------------------------- */

/* Canal A, gain 128 : entrée bas bruit, adaptée à une cellule de charge.
 * Le gain se choisit par le nombre d'impulsions d'horloge après les 24 bits
 * de données (25 = A/128, 26 = B/32, 27 = A/64). */
#define HB_HX711_GAIN_PULSES 25

/* Coefficient du filtre exponentiel. À 80 échantillons/s, 0,5 donne une
 * constante de temps d'environ 12,5 ms et 90 % d'un pas en ~42 ms : le HX711
 * en gain 128 est très stable et l'axe n'est quantifié qu'à 1/1023, donc le
 * bruit qui passe en plus reste imperceptible, sans latence sensible à la
 * main au tirage comme au relâchement. 0,25 se sentait mou. */
#define HB_EMA_ALPHA 0.5f

/* --- Cadences ----------------------------------------------------------- */

/* Période d'émission de la télémétrie quand le flux est actif. Volontairement
 * plus lente que l'acquisition : l'affichage n'a pas besoin de 80 Hz, et le
 * CDC ne doit pas prendre le pas sur la boucle HID. */
#define HB_TELEMETRY_PERIOD_MS 33 /* ~30 Hz */

/* Le rapport HID n'est envoyé que si la valeur d'axe a changé, avec ce délai
 * maximal entre deux envois pour garder l'hôte en phase même à l'arrêt. */
#define HB_HID_KEEPALIVE_MS 100

/* Au-delà de ce délai sans conversion HX711, le capteur est considéré absent
 * ou mal câblé : l'axe retombe à zéro plutôt que de rester figé sur la
 * dernière valeur lue. */
#define HB_SENSOR_TIMEOUT_MS 500

/* --- Stockage ----------------------------------------------------------- */

#define HB_EEPROM_ADDR    0
#define HB_EEPROM_MAGIC   0x48424B31UL /* "HBK1" */
#define HB_EEPROM_VERSION 1

/* --- Sortie HID --------------------------------------------------------- */

/* Un seul axe X, aucun bouton, aucun hat : tout ce qui est inutile est retiré
 * du descripteur. Si un titre particulier refusait d'énumérer un périphérique
 * à un seul axe, activer l'axe Y ici suffirait à contourner le problème. */
#define HB_JOYSTICK_ENABLE_Y false

#endif /* HB_BOARD_CONFIG_H */
