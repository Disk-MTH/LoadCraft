#include "hb_protocol.h"
#include "test_harness.h"

static hb_cmd_t parse(const char *line)
{
    hb_cmd_t cmd;
    hb_parse_command(line, &cmd);
    return cmd;
}

/* --- Commandes sans argument -------------------------------------------- */

static void test_commandes_simples(void)
{
    CHECK_EQ_INT(parse("PING").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("GET").kind, HB_CMD_GET);
    CHECK_EQ_INT(parse("SAVE").kind, HB_CMD_SAVE);
    CHECK_EQ_INT(parse("LOAD").kind, HB_CMD_LOAD);
    CHECK_EQ_INT(parse("RESET").kind, HB_CMD_RESET);
}

static void test_insensible_a_la_casse(void)
{
    CHECK_EQ_INT(parse("ping").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("PiNg").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("set curve power 2.0").kind, HB_CMD_SET_CURVE);
}

static void test_espaces_ignores(void)
{
    CHECK_EQ_INT(parse("   PING").kind, HB_CMD_PING);
    CHECK_EQ_INT(parse("\tGET\t").kind, HB_CMD_GET);
    CHECK_EQ_INT(parse("SET    MIN     1234").kind, HB_CMD_SET_MIN);
}

/* Une ligne vide n'est pas une commande inconnue : elle ne doit provoquer
 * aucune réponse, sinon un simple appui sur Entrée génère une erreur. */
static void test_ligne_vide(void)
{
    hb_cmd_t cmd;
    CHECK_EQ_INT(hb_parse_command("", &cmd), 0);
    CHECK_EQ_INT(hb_parse_command("   ", &cmd), 0);
    CHECK_EQ_INT(hb_parse_command("\t \t", &cmd), 0);
}

static void test_commande_inconnue(void)
{
    CHECK_EQ_INT(parse("BLAH").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("PIN").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("PINGG").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET FOO").kind, HB_CMD_UNKNOWN);
}

/* --- STREAM -------------------------------------------------------------- */

static void test_stream(void)
{
    hb_cmd_t on  = parse("STREAM 1");
    hb_cmd_t off = parse("STREAM 0");

    CHECK_EQ_INT(on.kind, HB_CMD_STREAM);
    CHECK_EQ_INT(on.ivalue, 1);
    CHECK_EQ_INT(off.kind, HB_CMD_STREAM);
    CHECK_EQ_INT(off.ivalue, 0);
}

static void test_stream_invalide(void)
{
    CHECK_EQ_INT(parse("STREAM").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM 2").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM -1").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("STREAM oui").kind, HB_CMD_UNKNOWN);
}

/* --- SET MIN / SET MAX --------------------------------------------------- */

/* Sans argument : capture la valeur filtrée courante. C'est le mode utilisé
 * par les boutons de l'app. */
static void test_set_min_max_sans_argument(void)
{
    hb_cmd_t mn = parse("SET MIN");
    hb_cmd_t mx = parse("SET MAX");

    CHECK_EQ_INT(mn.kind, HB_CMD_SET_MIN);
    CHECK_EQ_INT(mn.has_value, 0);
    CHECK_EQ_INT(mx.kind, HB_CMD_SET_MAX);
    CHECK_EQ_INT(mx.has_value, 0);
}

static void test_set_min_max_avec_argument(void)
{
    hb_cmd_t mn  = parse("SET MIN 123456");
    hb_cmd_t mx  = parse("SET MAX -98765");

    CHECK_EQ_INT(mn.kind, HB_CMD_SET_MIN);
    CHECK_EQ_INT(mn.has_value, 1);
    CHECK_EQ_INT(mn.ivalue, 123456);

    CHECK_EQ_INT(mx.kind, HB_CMD_SET_MAX);
    CHECK_EQ_INT(mx.has_value, 1);
    CHECK_EQ_INT(mx.ivalue, -98765);
}

/* Un argument illisible doit être rejeté, pas silencieusement traité comme
 * une capture de la valeur courante : l'utilisateur perdrait sa calibration
 * sans comprendre pourquoi. */
static void test_set_min_argument_invalide_rejete(void)
{
    CHECK_EQ_INT(parse("SET MIN abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET MIN 12abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET MAX 1 2").kind, HB_CMD_UNKNOWN);
}

/* --- SET CURVE ----------------------------------------------------------- */

static void test_set_curve(void)
{
    hb_cmd_t lin = parse("SET CURVE LINEAR");
    hb_cmd_t pow = parse("SET CURVE POWER");
    hb_cmd_t scv = parse("SET CURVE SCURVE");

    CHECK_EQ_INT(lin.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(lin.curve, HB_CURVE_LINEAR);
    CHECK_EQ_INT(lin.has_gamma, 0);

    CHECK_EQ_INT(pow.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(pow.curve, HB_CURVE_POWER);

    CHECK_EQ_INT(scv.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(scv.curve, HB_CURVE_SCURVE);
}

static void test_set_curve_avec_gamma(void)
{
    hb_cmd_t cmd = parse("SET CURVE POWER 1.8");

    CHECK_EQ_INT(cmd.kind, HB_CMD_SET_CURVE);
    CHECK_EQ_INT(cmd.curve, HB_CURVE_POWER);
    CHECK_EQ_INT(cmd.has_gamma, 1);
    CHECK_NEAR(cmd.fvalue, 1.8f, 1e-5);
}

static void test_set_curve_invalide(void)
{
    CHECK_EQ_INT(parse("SET CURVE").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET CURVE PARABOLE").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET CURVE POWER abc").kind, HB_CMD_UNKNOWN);
}

/* --- SET GAMMA ----------------------------------------------------------- */

static void test_set_gamma(void)
{
    hb_cmd_t cmd = parse("SET GAMMA 2.5");

    CHECK_EQ_INT(cmd.kind, HB_CMD_SET_GAMMA);
    CHECK_NEAR(cmd.fvalue, 2.5f, 1e-5);

    CHECK_NEAR(parse("SET GAMMA 0.4").fvalue, 0.4f, 1e-5);
    CHECK_NEAR(parse("SET GAMMA 1").fvalue, 1.0f, 1e-5);
}

static void test_set_gamma_invalide(void)
{
    CHECK_EQ_INT(parse("SET GAMMA").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET GAMMA abc").kind, HB_CMD_UNKNOWN);
    CHECK_EQ_INT(parse("SET GAMMA 1.5 2").kind, HB_CMD_UNKNOWN);
}

/* --- Noms de courbes ----------------------------------------------------- */

static void test_noms_de_courbes(void)
{
    uint8_t c;

    CHECK_STR(hb_curve_name(HB_CURVE_LINEAR), "LINEAR");
    CHECK_STR(hb_curve_name(HB_CURVE_POWER), "POWER");
    CHECK_STR(hb_curve_name(HB_CURVE_SCURVE), "SCURVE");
    CHECK_STR(hb_curve_name(99), "LINEAR");

    CHECK_EQ_INT(hb_curve_from_name("linear", &c), 1);
    CHECK_EQ_INT(c, HB_CURVE_LINEAR);
    CHECK_EQ_INT(hb_curve_from_name("SCURVE", &c), 1);
    CHECK_EQ_INT(c, HB_CURVE_SCURVE);
    CHECK_EQ_INT(hb_curve_from_name("nope", &c), 0);
}

/* Tout nom rendu par hb_curve_name doit être relu par hb_curve_from_name :
 * sinon un GET produirait une configuration que l'app ne sait pas renvoyer. */
static void test_aller_retour_des_noms_de_courbes(void)
{
    uint8_t i;
    for (i = 0; i <= HB_CURVE_SCURVE; i++) {
        uint8_t back = 255;
        CHECK_EQ_INT(hb_curve_from_name(hb_curve_name(i), &back), 1);
        CHECK_EQ_INT(back, i);
    }
}

/* --- Formatage des flottants --------------------------------------------- */

/* avr-libc n'implémente pas %f dans printf : ce formateur maison est la seule
 * voie de sortie pour un flottant côté firmware. */
static void test_fmt_fixed(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, 1.0f, 3);
    CHECK_STR(buf, "1.000");

    hb_fmt_fixed(buf, sizeof buf, 0.0f, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, 0.5f, 3);
    CHECK_STR(buf, "0.500");

    hb_fmt_fixed(buf, sizeof buf, 1.8f, 3);
    CHECK_STR(buf, "1.800");

    hb_fmt_fixed(buf, sizeof buf, 0.125f, 3);
    CHECK_STR(buf, "0.125");

    hb_fmt_fixed(buf, sizeof buf, 12.25f, 2);
    CHECK_STR(buf, "12.25");

    hb_fmt_fixed(buf, sizeof buf, 42.0f, 0);
    CHECK_STR(buf, "42");
}

static void test_fmt_fixed_negatifs(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, -1.5f, 3);
    CHECK_STR(buf, "-1.500");

    /* Pas de "-0.000" : un zéro reste un zéro une fois arrondi. */
    hb_fmt_fixed(buf, sizeof buf, -0.0001f, 3);
    CHECK_STR(buf, "0.000");
}

static void test_fmt_fixed_arrondi(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, 0.9999f, 3);
    CHECK_STR(buf, "1.000");

    hb_fmt_fixed(buf, sizeof buf, 0.0005f, 3);
    CHECK_STR(buf, "0.001");
}

static void test_fmt_fixed_tampon_trop_petit(void)
{
    char buf[4];

    CHECK_EQ_INT(hb_fmt_fixed(buf, sizeof buf, 1.234f, 3), 0);
    CHECK_STR(buf, ""); /* rien de tronqué : chaîne vide plutôt que "1.2" */
    CHECK_EQ_INT(hb_fmt_fixed(buf, 0, 1.0f, 3), 0);
}

/* Une valeur non finie issue d'une EEPROM corrompue ne doit jamais produire
 * une ligne que l'app n'arrive pas à analyser. */
static void test_fmt_fixed_valeur_non_finie(void)
{
    char buf[16];

    hb_fmt_fixed(buf, sizeof buf, (float)NAN, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, (float)INFINITY, 3);
    CHECK_STR(buf, "0.000");

    hb_fmt_fixed(buf, sizeof buf, -(float)INFINITY, 3);
    CHECK_STR(buf, "0.000");
}

/* --- Formatage des réponses ---------------------------------------------- */

static void test_format_config(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    hb_config_defaults(&cfg);
    cfg.raw_min    = 12345;
    cfg.raw_max    = 987654;
    cfg.curve      = HB_CURVE_POWER;
    cfg.gamma      = 1.8f;
    cfg.calibrated = 1;

    hb_format_config(buf, sizeof buf, &cfg);
    CHECK_STR(buf,
              "CFG min=12345 max=987654 curve=POWER gamma=1.800 calibrated=1");
}

/* HB_REPLY_MAX doit couvrir le pire cas, sinon la réponse serait tronquée
 * silencieusement au moment le moins pratique. */
static void test_format_config_pire_cas(void)
{
    hb_config_t cfg;
    char        buf[HB_REPLY_MAX];

    cfg.raw_min    = -8388608L;
    cfg.raw_max    = -8388608L;
    cfg.curve      = HB_CURVE_SCURVE;
    cfg.gamma      = HB_GAMMA_MAX;
    cfg.calibrated = 1;

    CHECK(hb_format_config(buf, sizeof buf, &cfg) > 0);
}

static void test_format_telemetry(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.75f, 767, 1);
    CHECK_STR(buf, "T raw=123456 out=0.750 axis=767 s=1");

    hb_format_telemetry(buf, sizeof buf, -8388608L, 0.0f, 0, 1);
    CHECK_STR(buf, "T raw=-8388608 out=0.000 axis=0 s=1");
}

/* s=0 : no valid sample (stuck sensor or sensor-absent timeout). Old hosts
 * ignore the field; the host parser defaults a missing s to 1. */
static void test_format_telemetry_sans_capteur(void)
{
    char buf[HB_REPLY_MAX];

    hb_format_telemetry(buf, sizeof buf, 123456, 0.0f, 0, 0);
    CHECK_STR(buf, "T raw=123456 out=0.000 axis=0 s=0");
}

static void test_format_tampon_trop_petit(void)
{
    hb_config_t cfg;
    char        buf[8];

    hb_config_defaults(&cfg);
    CHECK_EQ_INT(hb_format_config(buf, sizeof buf, &cfg), 0);
    CHECK_STR(buf, "");
    CHECK_EQ_INT(hb_format_telemetry(buf, sizeof buf, 123456, 0.5f, 512, 1), 0);
    CHECK_STR(buf, "");
}

/* --- Accumulation de ligne ------------------------------------------------ */

static int push_str(hb_linebuf_t *lb, const char *s)
{
    int done = 0;
    while (*s) {
        done = hb_linebuf_push(lb, *s++);
    }
    return done;
}

static void test_linebuf_ligne_simple(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_STR(lb.buf, "PING");
    CHECK_EQ_INT(lb.overflow, 0);
}

static void test_linebuf_crlf(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "GET\r\n"), 1);
    CHECK_STR(lb.buf, "GET");
}

/* Le tampon se réarme seul : l'appelant n'a pas à penser à le réinitialiser
 * entre deux commandes. */
static void test_linebuf_se_rearme(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_STR(lb.buf, "PING");
    CHECK_EQ_INT(push_str(&lb, "GET\n"), 1);
    CHECK_STR(lb.buf, "GET");
    CHECK_EQ_INT(lb.len, 3);
}

static void test_linebuf_ligne_vide(void)
{
    hb_linebuf_t lb;
    hb_linebuf_init(&lb);

    CHECK_EQ_INT(hb_linebuf_push(&lb, '\n'), 1);
    CHECK_STR(lb.buf, "");
}

/* Une ligne trop longue est signalée plutôt qu'exécutée tronquée : sinon
 * "SET MIN 123456789…" pourrait devenir un "SET MIN" involontaire. */
static void test_linebuf_depassement(void)
{
    hb_linebuf_t lb;
    int          i;

    hb_linebuf_init(&lb);
    for (i = 0; i < HB_LINE_MAX * 2; i++) {
        CHECK_EQ_INT(hb_linebuf_push(&lb, 'A'), 0);
    }
    CHECK_EQ_INT(hb_linebuf_push(&lb, '\n'), 1);
    CHECK_EQ_INT(lb.overflow, 1);
    CHECK(lb.len < HB_LINE_MAX);

    /* Le dépassement ne colle pas à la ligne suivante */
    CHECK_EQ_INT(push_str(&lb, "PING\n"), 1);
    CHECK_EQ_INT(lb.overflow, 0);
    CHECK_STR(lb.buf, "PING");
}

int main(void)
{
    RUN(test_commandes_simples);
    RUN(test_insensible_a_la_casse);
    RUN(test_espaces_ignores);
    RUN(test_ligne_vide);
    RUN(test_commande_inconnue);

    RUN(test_stream);
    RUN(test_stream_invalide);

    RUN(test_set_min_max_sans_argument);
    RUN(test_set_min_max_avec_argument);
    RUN(test_set_min_argument_invalide_rejete);

    RUN(test_set_curve);
    RUN(test_set_curve_avec_gamma);
    RUN(test_set_curve_invalide);

    RUN(test_set_gamma);
    RUN(test_set_gamma_invalide);

    RUN(test_noms_de_courbes);
    RUN(test_aller_retour_des_noms_de_courbes);

    RUN(test_fmt_fixed);
    RUN(test_fmt_fixed_negatifs);
    RUN(test_fmt_fixed_arrondi);
    RUN(test_fmt_fixed_tampon_trop_petit);
    RUN(test_fmt_fixed_valeur_non_finie);

    RUN(test_format_config);
    RUN(test_format_config_pire_cas);
    RUN(test_format_telemetry);
    RUN(test_format_telemetry_sans_capteur);
    RUN(test_format_tampon_trop_petit);

    RUN(test_linebuf_ligne_simple);
    RUN(test_linebuf_crlf);
    RUN(test_linebuf_se_rearme);
    RUN(test_linebuf_ligne_vide);
    RUN(test_linebuf_depassement);

    TEST_SUMMARY("hb_protocol");
}
