/*
 * Driver HX711 non bloquant.
 *
 * Écrit à la main plutôt que d'utiliser une bibliothèque existante : le
 * protocole tient en quelques lignes, et les implémentations courantes
 * attendent activement que la conversion soit prête. Ici la boucle principale
 * doit rester libre de servir l'USB et les commandes série entre deux
 * échantillons.
 */
#ifndef HB_HX711_H
#define HB_HX711_H

#include <Arduino.h>
#include <stdint.h>

class HX711 {
public:
    HX711(uint8_t pin_data, uint8_t pin_clock, uint8_t gain_pulses);

    void begin();

    /* Vrai quand une conversion est prête à être lue. */
    bool available() const;

    /* Lit la conversion en attente. Renvoie false si aucune n'est prête, sans
     * attendre. La valeur est l'entier signé 24 bits du convertisseur. */
    bool read(int32_t &out);

private:
    uint8_t _pin_data;
    uint8_t _pin_clock;
    uint8_t _gain_pulses;
};

#endif /* HB_HX711_H */
