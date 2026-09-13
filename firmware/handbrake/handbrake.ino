/*
 * Handbrake progressif USB — firmware ATmega32u4 (Pro Micro).
 *
 * Le PC voit un joystick USB HID à un axe, plus un port série virtuel pour la
 * configuration. Aucun logiciel n'a besoin de tourner pendant le jeu : la
 * calibration vit en EEPROM.
 *
 * Dépendance : bibliothèque Joystick de MHeironimus
 *   https://github.com/MHeironimus/ArduinoJoystickLibrary
 *
 * Voir docs/design.md pour la conception et docs/wiring.md pour le câblage.
 */

#include <Joystick.h>

#include "config.h"
#include "hb_core.h"
#include "hb_protocol.h"
#include "hb_storage.h"
#include "hx711.h"

/* Un seul axe X. Tout le reste est retiré du descripteur HID : rapport plus
 * court et meilleure compatibilité hôte. */
static Joystick_ joystick(JOYSTICK_DEFAULT_REPORT_ID, JOYSTICK_TYPE_JOYSTICK,
                          0,                          /* boutons */
                          0,                          /* hat switches */
                          true, HB_JOYSTICK_ENABLE_Y, /* X, Y */
                          false, false, false, false, /* Z, Rx, Ry, Rz */
                          false, false,               /* rudder, throttle */
                          false, false, false); /* accel, frein, direction */

static HX711 sensor(HB_PIN_HX711_DT, HB_PIN_HX711_SCK, HB_HX711_GAIN_PULSES);

static hb_config_t  config;
static hb_ema_t     filter;
static hb_stuck_t   stuck;
static hb_linebuf_t line;

static int32_t  filtered_raw   = 0;
static bool     have_sample    = false;
static uint16_t last_axis      = 0xFFFF;
static bool     streaming      = false;
static uint32_t last_sample_ms = 0;
static uint32_t last_report_ms = 0;
static uint32_t last_telem_ms  = 0;

/* Les toutes premières conversions suivant la mise sous tension sortent avant
 * que l'étage d'entrée du HX711 ne soit stabilisé. Les ignorer évite qu'un
 * « SET MIN » lancé trop tôt ne fige une calibration fausse. */
static const uint8_t WARMUP_SAMPLES = 8;
static uint8_t       warmup_left    = WARMUP_SAMPLES;

/* --- Sorties ------------------------------------------------------------ */

static void reply(const char *text)
{
    /* Écrire alors qu'aucun hôte n'a ouvert le port remplirait le tampon CDC
     * et finirait par bloquer la boucle, donc l'axe HID avec elle. */
    if (Serial) {
        Serial.println(text);
    }
}

static void send_config()
{
    char buf[HB_REPLY_MAX];
    if (hb_format_config(buf, sizeof buf, &config)) {
        reply(buf);
    }
}

static void update_axis()
{
    float    unit = have_sample ? hb_process(&config, filtered_raw) : 0.0f;
    uint16_t axis = hb_axis_from_unit(unit);
    uint32_t now  = millis();

    /* Rapport envoyé au changement, et sinon périodiquement pour garder
     * l'hôte en phase même levier immobile. */
    if (axis != last_axis || (now - last_report_ms) >= HB_HID_KEEPALIVE_MS) {
        joystick.setXAxis((int)axis);
        joystick.sendState();
        last_axis      = axis;
        last_report_ms = now;
    }
}

static void send_telemetry()
{
    char  buf[HB_REPLY_MAX];
    float unit = have_sample ? hb_process(&config, filtered_raw) : 0.0f;

    if (hb_format_telemetry(buf, sizeof buf, filtered_raw, unit,
                            hb_axis_from_unit(unit), have_sample)) {
        reply(buf);
    }
}

/* --- Commandes ---------------------------------------------------------- */

static void ack(const char *what)
{
    char buf[HB_REPLY_MAX];
    snprintf(buf, sizeof buf, "OK %s", what);
    reply(buf);
}

static void ack_long(const char *what, long value)
{
    char buf[HB_REPLY_MAX];
    snprintf(buf, sizeof buf, "OK %s %ld", what, value);
    reply(buf);
}

static void apply_command(const hb_cmd_t &cmd)
{
    switch (cmd.kind) {
    case HB_CMD_PING:
        ack("PING");
        break;

    case HB_CMD_GET:
        send_config();
        break;

    case HB_CMD_SET_MIN:
    case HB_CMD_SET_MAX: {
        int32_t value;

        if (cmd.has_value) {
            value = cmd.ivalue;
        } else if (have_sample) {
            value = filtered_raw;
        } else {
            /* Capturer sans lecture valide figerait un zéro faux, que rien
             * ne signalerait ensuite à l'utilisateur. */
            reply("ERR no sensor reading");
            break;
        }

        if (cmd.kind == HB_CMD_SET_MIN) {
            config.raw_min = value;
        } else {
            config.raw_max = value;
        }
        config.calibrated = 1;
        hb_config_sanitize(&config);
        ack_long(cmd.kind == HB_CMD_SET_MIN ? "SET MIN" : "SET MAX",
                 (long)value);
        break;
    }

    case HB_CMD_SET_CURVE:
        config.curve = cmd.curve;
        if (cmd.has_gamma) {
            config.gamma = cmd.fvalue;
        }
        hb_config_sanitize(&config);
        send_config();
        break;

    case HB_CMD_SET_GAMMA:
        config.gamma = cmd.fvalue;
        hb_config_sanitize(&config);
        send_config();
        break;

    case HB_CMD_SAVE:
        /* L'écriture n'a lieu que sur demande explicite : un curseur de gamma
         * qui sauvegarderait à chaque mouvement userait l'EEPROM en quelques
         * séances de réglage. */
        hb_storage_save(config);
        ack("SAVE");
        break;

    case HB_CMD_LOAD:
        hb_storage_load(config);
        send_config();
        break;

    case HB_CMD_RESET:
        hb_config_defaults(&config);
        send_config();
        break;

    case HB_CMD_STREAM:
        streaming     = (cmd.ivalue != 0);
        last_telem_ms = millis();
        ack_long("STREAM", (long)cmd.ivalue);
        break;

    case HB_CMD_UNKNOWN:
    default:
        reply("ERR unknown command");
        break;
    }
}

static void poll_serial()
{
    while (Serial.available() > 0) {
        if (!hb_linebuf_push(&line, (char)Serial.read())) {
            continue;
        }

        if (line.overflow) {
            /* Exécuter une ligne tronquée reviendrait à obéir à une commande
             * que personne n'a envoyée. */
            reply("ERR line too long");
            continue;
        }

        hb_cmd_t cmd;
        if (hb_parse_command(line.buf, &cmd)) {
            apply_command(cmd);
        }
    }
}

/* --- Acquisition -------------------------------------------------------- */

static void poll_sensor()
{
    int32_t raw;

    if (sensor.read(raw)) {
        last_sample_ms = millis();

        if (hb_stuck_push(&stuck, last_sample_ms, raw)) {
            /* The raw value has not moved at all for a timeout: the DOUT
             * line is stuck or the converter is locked. Same treatment as a
             * missing sensor: the axis falls back to zero instead of
             * freezing, and the warmup restarts. */
            have_sample = false;
            hb_ema_reset(&filter);
            warmup_left = WARMUP_SAMPLES;
            return;
        }

        if (warmup_left > 0) {
            warmup_left--;
            return;
        }

        filtered_raw = hb_ema_push(&filter, raw);
        have_sample  = true;
        return;
    }

    /* Silent sensor: the axis falls back to zero rather than staying frozen
     * on the last value, which could be a full brake. */
    if (have_sample && (millis() - last_sample_ms) > HB_SENSOR_TIMEOUT_MS) {
        have_sample = false;
        hb_ema_reset(&filter);
        warmup_left = WARMUP_SAMPLES;
    }
}

/* --- Arduino ------------------------------------------------------------ */

void setup()
{
    Serial.begin(115200); /* débit ignoré sur CDC, présent par convention */

    hb_storage_load(config);
    hb_ema_init(&filter, HB_EMA_ALPHA);
    hb_stuck_init(&stuck, HB_STUCK_TIMEOUT_MS);
    hb_linebuf_init(&line);

    sensor.begin();
    last_sample_ms = millis();

    /* begin(false) : l'état est transmis par sendState() explicite, en un
     * rapport atomique, jamais partiellement mis à jour. */
    joystick.setXAxisRange(HB_AXIS_MIN, HB_AXIS_MAX);
    joystick.begin(false);

    joystick.setXAxis(0);
    joystick.sendState();
}

void loop()
{
    poll_sensor();
    poll_serial();
    update_axis();

    if (streaming) {
        uint32_t now = millis();
        if ((now - last_telem_ms) >= HB_TELEMETRY_PERIOD_MS) {
            last_telem_ms = now;
            send_telemetry();
        }
    }
}
