/*
 * Non-blocking HX711 driver.
 *
 * Hand-written rather than using an existing library: the protocol fits in
 * a few lines, and the usual implementations actively wait for the
 * conversion to be ready. Here the main loop must stay free to serve USB and
 * serial commands between two samples.
 */
#ifndef HB_HX711_H
#define HB_HX711_H

#include <Arduino.h>
#include <stdint.h>

class HX711 {
public:
    HX711(uint8_t pin_data, uint8_t pin_clock, uint8_t gain_pulses);

    void begin();

    /* True when a conversion is ready to be read. */
    bool available() const;

    /* Reads the pending conversion. Returns false if none is ready, without
     * waiting. The value is the converter's signed 24-bit integer. */
    bool read(int32_t &out);

private:
    uint8_t _pin_data;
    uint8_t _pin_clock;
    uint8_t _gain_pulses;
};

#endif /* HB_HX711_H */
