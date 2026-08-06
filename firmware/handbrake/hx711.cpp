#include "hx711.h"

HX711::HX711(uint8_t pin_data, uint8_t pin_clock, uint8_t gain_pulses)
    : _pin_data(pin_data), _pin_clock(pin_clock), _gain_pulses(gain_pulses)
{
}

void HX711::begin()
{
    /* Pull-up sur la ligne de données : capteur absent ou mal câblé, la
     * broche est lue au niveau haut, donc « pas de conversion prête », et
     * l'absence est signalée franchement. Sans lui, l'entrée flotte et peut
     * se lire au niveau bas au hasard : le firmware lirait alors 24 bits de
     * bruit et les présenterait comme une mesure.
     *
     * La sortie DOUT du HX711 est de type push-pull : elle impose son niveau
     * sans difficulté face au pull-up interne de l'AVR (20 à 50 kΩ). */
    pinMode(_pin_data, INPUT_PULLUP);
    pinMode(_pin_clock, OUTPUT);

    /* Horloge basse : une impulsion maintenue haut plus de 60 µs met le HX711
     * en veille. On sort de cet état en la ramenant à zéro. */
    digitalWrite(_pin_clock, LOW);
}

bool HX711::available() const
{
    /* Le HX711 signale une conversion prête en tirant DOUT au niveau bas. */
    return digitalRead(_pin_data) == LOW;
}

bool HX711::read(int32_t &out)
{
    if (!available()) {
        return false;
    }

    uint32_t value = 0;

    /*
     * Interruptions coupées pendant toute la trame.
     *
     * Le HX711 se met en veille si son horloge reste haute plus de 60 µs. Sur
     * un 32u4, l'interruption USB se déclenche à chaque milliseconde et peut
     * durer plusieurs dizaines de microsecondes : si elle tombe entre deux
     * fronts, elle étire l'impulsion et provoque une mise en veille en plein
     * milieu de la lecture, donc un échantillon corrompu.
     *
     * La trame complète dure environ 200 µs, soit moins de 2 % du temps à
     * 80 échantillons/s. Le contrôleur USB tamponne en matériel et ne perd
     * rien sur cette durée.
     */
    noInterrupts();

    for (uint8_t i = 0; i < 24; i++) {
        digitalWrite(_pin_clock, HIGH);
        digitalWrite(_pin_clock, LOW);
        value = (value << 1) | (uint32_t)(digitalRead(_pin_data) == HIGH);
    }

    /* Impulsions supplémentaires : elles fixent le canal et le gain de la
     * conversion suivante (25 = A/128, 26 = B/32, 27 = A/64). */
    for (uint8_t i = 24; i < _gain_pulses; i++) {
        digitalWrite(_pin_clock, HIGH);
        digitalWrite(_pin_clock, LOW);
    }

    interrupts();

    /* Complément à deux sur 24 bits : le bit 23 est le bit de signe, il faut
     * l'étendre aux 8 bits de poids fort pour obtenir un int32 correct. */
    if (value & 0x800000UL) {
        value |= 0xFF000000UL;
    }

    out = (int32_t)value;
    return true;
}
