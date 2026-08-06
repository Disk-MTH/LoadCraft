#include "hb_protocol.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- Outils de découpage ----------------------------------------------- */

static int is_space(char c)
{
    return c == ' ' || c == '\t';
}

static const char *skip_ws(const char *p)
{
    while (is_space(*p)) {
        p++;
    }
    return p;
}

static size_t token_len(const char *p)
{
    size_t n = 0;
    while (p[n] != '\0' && !is_space(p[n])) {
        n++;
    }
    return n;
}

/* Comparaison insensible à la casse d'un jeton de longueur connue avec une
 * référence terminée par \0. Écrite ici plutôt qu'avec strncasecmp pour ne
 * dépendre d'aucune extension au-delà de C99. */
static int tok_eq(const char *tok, size_t len, const char *ref)
{
    size_t i;
    for (i = 0; i < len; i++) {
        char a = tok[i];
        if (a >= 'a' && a <= 'z') {
            a = (char)(a - 'a' + 'A');
        }
        if (ref[i] == '\0' || a != ref[i]) {
            return 0;
        }
    }
    return ref[len] == '\0';
}

static int parse_i32(const char *p, int32_t *out, const char **end)
{
    char *stop = NULL;
    long  v    = strtol(p, &stop, 10);

    if (stop == p) {
        return 0;
    }
    *out = (int32_t)v;
    *end = stop;
    return 1;
}

static int parse_f32(const char *p, float *out, const char **end)
{
    char  *stop = NULL;
    double v    = strtod(p, &stop);

    if (stop == p) {
        return 0;
    }
    *out = (float)v;
    *end = stop;
    return 1;
}

/* 1 si la ligne est terminée après p (hors espaces). */
static int at_end(const char *p)
{
    return *skip_ws(p) == '\0';
}

/* --- Courbes ------------------------------------------------------------ */

const char *hb_curve_name(uint8_t curve)
{
    switch (curve) {
    case HB_CURVE_POWER:  return "POWER";
    case HB_CURVE_SCURVE: return "SCURVE";
    case HB_CURVE_LINEAR:
    default:              return "LINEAR";
    }
}

int hb_curve_from_name(const char *name, uint8_t *out)
{
    size_t n = token_len(name);

    if (tok_eq(name, n, "LINEAR")) {
        *out = (uint8_t)HB_CURVE_LINEAR;
        return 1;
    }
    if (tok_eq(name, n, "POWER")) {
        *out = (uint8_t)HB_CURVE_POWER;
        return 1;
    }
    if (tok_eq(name, n, "SCURVE")) {
        *out = (uint8_t)HB_CURVE_SCURVE;
        return 1;
    }
    return 0;
}

/* --- Analyse des commandes ---------------------------------------------- */

static int parse_set(const char *p, hb_cmd_t *out)
{
    size_t      n = token_len(p);
    const char *rest;
    const char *end;

    if (tok_eq(p, n, "MIN") || tok_eq(p, n, "MAX")) {
        out->kind = (uint8_t)(tok_eq(p, n, "MIN") ? HB_CMD_SET_MIN
                                                  : HB_CMD_SET_MAX);
        rest = skip_ws(p + n);
        if (*rest == '\0') {
            return 1; /* sans argument : capture la valeur courante */
        }
        if (!parse_i32(rest, &out->ivalue, &end) || !at_end(end)) {
            out->kind = (uint8_t)HB_CMD_UNKNOWN;
            return 1;
        }
        out->has_value = 1;
        return 1;
    }

    if (tok_eq(p, n, "CURVE")) {
        rest = skip_ws(p + n);
        if (!hb_curve_from_name(rest, &out->curve)) {
            out->kind = (uint8_t)HB_CMD_UNKNOWN;
            return 1;
        }
        out->kind = (uint8_t)HB_CMD_SET_CURVE;

        /* Un gamma peut accompagner la courbe : SET CURVE POWER 1.8 */
        rest = skip_ws(rest + token_len(rest));
        if (*rest == '\0') {
            return 1;
        }
        if (!parse_f32(rest, &out->fvalue, &end) || !at_end(end)) {
            out->kind = (uint8_t)HB_CMD_UNKNOWN;
            return 1;
        }
        out->has_gamma = 1;
        return 1;
    }

    if (tok_eq(p, n, "GAMMA")) {
        rest = skip_ws(p + n);
        if (!parse_f32(rest, &out->fvalue, &end) || !at_end(end)) {
            out->kind = (uint8_t)HB_CMD_UNKNOWN;
            return 1;
        }
        out->kind = (uint8_t)HB_CMD_SET_GAMMA;
        return 1;
    }

    out->kind = (uint8_t)HB_CMD_UNKNOWN;
    return 1;
}

int hb_parse_command(const char *line, hb_cmd_t *out)
{
    const char *p;
    const char *rest;
    const char *end;
    size_t      n;

    out->kind      = (uint8_t)HB_CMD_UNKNOWN;
    out->has_value = 0;
    out->ivalue    = 0;
    out->fvalue    = 0.0f;
    out->curve     = (uint8_t)HB_CURVE_LINEAR;
    out->has_gamma = 0;

    p = skip_ws(line);
    if (*p == '\0') {
        return 0;
    }

    n = token_len(p);

    if (tok_eq(p, n, "PING")) {
        out->kind = (uint8_t)HB_CMD_PING;
        return 1;
    }
    if (tok_eq(p, n, "GET")) {
        out->kind = (uint8_t)HB_CMD_GET;
        return 1;
    }
    if (tok_eq(p, n, "SAVE")) {
        out->kind = (uint8_t)HB_CMD_SAVE;
        return 1;
    }
    if (tok_eq(p, n, "LOAD")) {
        out->kind = (uint8_t)HB_CMD_LOAD;
        return 1;
    }
    if (tok_eq(p, n, "RESET")) {
        out->kind = (uint8_t)HB_CMD_RESET;
        return 1;
    }

    if (tok_eq(p, n, "STREAM")) {
        rest = skip_ws(p + n);
        if (!parse_i32(rest, &out->ivalue, &end) || !at_end(end)) {
            return 1;
        }
        if (out->ivalue != 0 && out->ivalue != 1) {
            return 1;
        }
        out->kind = (uint8_t)HB_CMD_STREAM;
        return 1;
    }

    if (tok_eq(p, n, "SET")) {
        return parse_set(skip_ws(p + n), out);
    }

    return 1; /* HB_CMD_UNKNOWN */
}

/* --- Formatage ---------------------------------------------------------- */

size_t hb_fmt_fixed(char *buf, size_t size, float value, uint8_t decimals)
{
    char     tmp[24];
    char     digits[12];
    uint32_t scale = 1;
    uint32_t scaled;
    uint32_t ipart;
    uint32_t fpart;
    size_t   len      = 0;
    int      negative = 0;
    uint8_t  nd       = 0;
    uint8_t  i;

    if (buf == NULL || size == 0) {
        return 0;
    }
    buf[0] = '\0';

    if (decimals > 6) {
        decimals = 6;
    }
    for (i = 0; i < decimals; i++) {
        scale *= 10U;
    }

    /* Domaine tel que value * scale tienne dans un uint32. Hors domaine ou non
     * fini — impossible après hb_config_sanitize, mais la sortie doit rester
     * analysable par l'hôte quoi qu'il arrive. */
    {
        float limit = 4000000000.0f / (float)scale;
        if (!(value >= -limit && value <= limit)) {
            value = 0.0f;
        }
    }
    if (value < 0.0f) {
        negative = 1;
        value    = -value;
    }

    scaled = (uint32_t)(value * (float)scale + 0.5f);
    ipart  = scaled / scale;
    fpart  = scaled % scale;

    /* Pas de "-0.000" : le signe ne s'écrit que si la valeur arrondie est
     * réellement non nulle. */
    if (negative && scaled != 0U) {
        tmp[len++] = '-';
    }

    do {
        digits[nd++] = (char)('0' + (ipart % 10U));
        ipart /= 10U;
    } while (ipart != 0U);
    while (nd > 0U) {
        tmp[len++] = digits[--nd];
    }

    if (decimals > 0) {
        tmp[len++] = '.';
        for (i = 0; i < decimals; i++) {
            digits[nd++] = (char)('0' + (fpart % 10U));
            fpart /= 10U;
        }
        while (nd > 0U) {
            tmp[len++] = digits[--nd];
        }
    }
    tmp[len] = '\0';

    if (len + 1U > size) {
        return 0;
    }
    memcpy(buf, tmp, len + 1U);
    return len;
}

size_t hb_format_config(char *buf, size_t size, const hb_config_t *cfg)
{
    char gbuf[16];
    int  n;

    if (buf == NULL || size == 0) {
        return 0;
    }

    hb_fmt_fixed(gbuf, sizeof gbuf, cfg->gamma, 3);
    n = snprintf(buf, size,
                 "CFG min=%ld max=%ld curve=%s gamma=%s calibrated=%u",
                 (long)cfg->raw_min, (long)cfg->raw_max,
                 hb_curve_name(cfg->curve), gbuf,
                 (unsigned)cfg->calibrated);

    if (n < 0 || (size_t)n >= size) {
        buf[0] = '\0';
        return 0;
    }
    return (size_t)n;
}

size_t hb_format_telemetry(char *buf, size_t size, int32_t raw, float unit,
                           uint16_t axis)
{
    char obuf[16];
    int  n;

    if (buf == NULL || size == 0) {
        return 0;
    }

    hb_fmt_fixed(obuf, sizeof obuf, unit, 3);
    n = snprintf(buf, size, "T raw=%ld out=%s axis=%u", (long)raw, obuf,
                 (unsigned)axis);

    if (n < 0 || (size_t)n >= size) {
        buf[0] = '\0';
        return 0;
    }
    return (size_t)n;
}

/* --- Accumulation de ligne ---------------------------------------------- */

void hb_linebuf_init(hb_linebuf_t *lb)
{
    lb->buf[0]  = '\0';
    lb->len     = 0;
    lb->overflow = 0;
    lb->ready   = 0;
}

int hb_linebuf_push(hb_linebuf_t *lb, char ch)
{
    if (lb->ready) {
        lb->len      = 0;
        lb->overflow = 0;
        lb->ready    = 0;
    }

    if (ch == '\r') {
        return 0; /* CRLF toléré */
    }

    if (ch == '\n') {
        lb->buf[lb->len] = '\0';
        lb->ready        = 1;
        return 1;
    }

    if ((size_t)lb->len + 1U >= sizeof lb->buf) {
        /* Ligne trop longue : on cesse d'accumuler et on marque le
         * dépassement. Elle sera rendue tronquée, avec overflow à 1, pour que
         * l'appelant la rejette au lieu d'exécuter une commande amputée. */
        lb->overflow = 1;
        return 0;
    }

    lb->buf[lb->len++] = ch;
    return 0;
}
