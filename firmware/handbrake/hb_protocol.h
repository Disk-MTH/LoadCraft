/*
 * hb_protocol - configuration serial protocol.
 *
 * ASCII lines terminated by \n in both directions. Pure C99: compiled
 * identically by the AVR compiler and by the native tests.
 *
 * Float formatting does not use printf: the avr-libc implementation does
 * not handle %f without a specific link option, and fails silently. See
 * hb_fmt_fixed().
 */
#ifndef HB_PROTOCOL_H
#define HB_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#include "hb_core.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Enough for the longest command, with margin. A longer line is rejected
 * rather than silently truncated. */
#define HB_LINE_MAX 64

/* Enough for the longest reply (full CFG). */
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
    uint8_t has_value; /* SET MIN/MAX: 1 if an explicit value is provided */
    int32_t ivalue;    /* SET MIN/MAX <v>, STREAM <0|1> */
    float   fvalue;    /* SET GAMMA <f>, SET CURVE POWER <f> */
    uint8_t curve;     /* SET CURVE : hb_curve_t */
    uint8_t has_gamma; /* SET CURVE: 1 if a gamma accompanies the curve */
} hb_cmd_t;

/* Parses a line (without its final \n).
 * Returns 0 for an empty or spaces-only line, 1 otherwise.
 * An unrecognized command returns 1 with kind == HB_CMD_UNKNOWN. */
int hb_parse_command(const char *line, hb_cmd_t *out);

/* Textual name of a curve, as used in the protocol. */
const char *hb_curve_name(uint8_t curve);

/* Parses a curve name, case-insensitively.
 * Returns 1 and fills *out if recognized, 0 otherwise. */
int hb_curve_from_name(const char *name, uint8_t *out);

/* Writes a float in fixed decimal notation, without printf.
 * Returns the number of characters written (excluding \0), or 0 if the
 * buffer is too small - in which case buf receives an empty string. */
size_t hb_fmt_fixed(char *buf, size_t size, float value, uint8_t decimals);

/* "CFG min=... max=... curve=... gamma=... calibrated=..." */
size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg);

/* "T raw=... out=... axis=... s=..." - s=1 with a valid sample, s=0 otherwise. */
size_t hb_format_telemetry(char *buf, size_t size, int32_t raw, float unit,
                           uint16_t axis, int sensor_ok);

/* --- Line accumulation --------------------------------------------------- */

typedef struct {
    char    buf[HB_LINE_MAX];
    uint8_t len;
    uint8_t overflow;
    uint8_t ready;
} hb_linebuf_t;

void hb_linebuf_init(hb_linebuf_t *lb);

/* Feeds a received character.
 * Returns 1 when a full line is available in lb->buf (terminated by \0),
 * 0 otherwise. A line that is too long is flagged by lb->overflow at the
 * moment it is returned: the caller must then reject it.
 *
 * The buffer re-arms itself on the next call: the caller reads buf and
 * overflow right after a return of 1, without having to reset anything. */
int hb_linebuf_push(hb_linebuf_t *lb, char ch);

#ifdef __cplusplus
}
#endif

#endif /* HB_PROTOCOL_H */
