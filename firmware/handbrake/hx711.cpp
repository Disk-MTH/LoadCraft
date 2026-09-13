#include "hx711.h"

HX711::HX711(uint8_t pin_data, uint8_t pin_clock, uint8_t gain_pulses)
    : _pin_data(pin_data), _pin_clock(pin_clock), _gain_pulses(gain_pulses)
{
}

void HX711::begin()
{
    /* Pull-up on the data line: sensor absent or miswired, the pin reads
     * high, i.e. "no conversion ready", and the absence is reported cleanly.
     * Without it, the input floats and can read low at random: the firmware
     * would then read 24 bits of noise and present them as a measurement.
     *
     * The HX711 DOUT output is push-pull: it imposes its level without
     * trouble against the AVR's internal pull-up (20 to 50 kohms). */
    pinMode(_pin_data, INPUT_PULLUP);
    pinMode(_pin_clock, OUTPUT);

    /* Clock low: a pulse held high for more than 60us puts the HX711 to
     * sleep. Leaving that state means bringing it back to zero. */
    digitalWrite(_pin_clock, LOW);
}

bool HX711::available() const
{
    /* The HX711 signals a ready conversion by pulling DOUT low. */
    return digitalRead(_pin_data) == LOW;
}

bool HX711::read(int32_t &out)
{
    if (!available()) {
        return false;
    }

    uint32_t value = 0;

    /*
     * Interrupts off for the whole frame.
     *
     * The HX711 goes to sleep if its clock stays high for more than 60us.
     * On a 32u4, the USB interrupt fires every millisecond and can last
     * several tens of microseconds: if it lands between two edges, it
     * stretches the pulse and triggers a sleep right in the middle of the
     * read, hence a corrupted sample.
     *
     * The full frame lasts about 200us, i.e. less than 2% of the time at
     * 80 samples/s. The USB controller buffers in hardware and loses
     * nothing over that span.
     */
    noInterrupts();

    for (uint8_t i = 0; i < 24; i++) {
        digitalWrite(_pin_clock, HIGH);
        digitalWrite(_pin_clock, LOW);
        value = (value << 1) | (uint32_t)(digitalRead(_pin_data) == HIGH);
    }

    /* Extra pulses: they set the channel and gain of the next conversion
     * (25 = A/128, 26 = B/32, 27 = A/64). */
    for (uint8_t i = 24; i < _gain_pulses; i++) {
        digitalWrite(_pin_clock, HIGH);
        digitalWrite(_pin_clock, LOW);
    }

    interrupts();

    /* Two's complement on 24 bits: bit 23 is the sign bit, it must be
     * extended into the top 8 bits to get a correct int32. */
    if (value & 0x800000UL) {
        value |= 0xFF000000UL;
    }

    out = (int32_t)value;
    return true;
}
