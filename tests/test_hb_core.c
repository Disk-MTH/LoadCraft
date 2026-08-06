#include "hb_core.h"
#include "test_harness.h"

/* --- Normalisation ------------------------------------------------------ */

static void test_normalize_plage_normale(void)
{
    CHECK_NEAR(hb_normalize(1000, 1000, 2000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1500, 1000, 2000), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(2000, 1000, 2000), 1.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1250, 1000, 2000), 0.25f, 1e-6);
}

static void test_normalize_borne_hors_plage(void)
{
    CHECK_NEAR(hb_normalize(500, 1000, 2000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(9999, 1000, 2000), 1.0f, 1e-6);
}

/* Une cellule câblée en polarité inverse produit une plage décroissante.
 * C'est ce qui permet de ne pas exposer d'option « inverser l'axe ». */
static void test_normalize_plage_inversee(void)
{
    CHECK_NEAR(hb_normalize(2000, 2000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(1500, 2000, 1000), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(1000, 2000, 1000), 1.0f, 1e-6);
    CHECK_NEAR(hb_normalize(2500, 2000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(0, 2000, 1000), 1.0f, 1e-6);
}

static void test_normalize_plage_nulle(void)
{
    CHECK_NEAR(hb_normalize(1000, 1000, 1000), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(5000, 1000, 1000), 0.0f, 1e-6);
}

static void test_normalize_valeurs_negatives(void)
{
    CHECK_NEAR(hb_normalize(-500, -1000, 0), 0.5f, 1e-6);
    CHECK_NEAR(hb_normalize(-8388608L, -8388608L, 8388607L), 0.0f, 1e-6);
    CHECK_NEAR(hb_normalize(8388607L, -8388608L, 8388607L), 1.0f, 1e-6);
    /* Cas où (raw - raw_min) déborderait un int32 s'il était calculé en
     * entier : le calcul passe par des flottants pour cette raison. */
    CHECK_NEAR(hb_normalize(0, -8388608L, 8388607L), 0.5f, 1e-3);
}

/* --- Courbes ------------------------------------------------------------ */

static void test_courbe_lineaire(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 0.37f), 0.37f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 1.0f, 1.0f), 1.0f, 1e-6);
    /* gamma est ignoré en linéaire */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_LINEAR, 3.0f, 0.5f), 0.5f, 1e-6);
}

static void test_courbe_puissance(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, 0.5f), 0.25f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 0.5f, 0.25f), 0.5f, 1e-6);
    /* Les extrémités sont des points fixes quel que soit gamma */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.5f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.5f, 1.0f), 1.0f, 1e-6);
}

static void test_courbe_s(void)
{
    /* Points fixes : 0, 0,5 et 1 quel que soit gamma */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.5f), 0.5f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 1.0f), 1.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 0.4f, 0.5f), 0.5f, 1e-6);

    /* gamma > 1 : douce aux extrémités, donc sous la diagonale avant 0,5 */
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.25f) < 0.25f);
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.75f) > 0.75f);

    /* gamma < 1 : comportement inverse */
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 0.5f, 0.25f) > 0.25f);
    CHECK(hb_curve_apply(HB_CURVE_SCURVE, 0.5f, 0.75f) < 0.75f);

    /* Symétrie autour de (0,5 ; 0,5) */
    CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.3f)
                   + hb_curve_apply(HB_CURVE_SCURVE, 2.0f, 0.7f),
               1.0f, 1e-5);
}

/* gamma = 1 doit rendre les trois courbes identiques : c'est le repère neutre
 * annoncé à l'utilisateur dans l'app. */
static void test_gamma_un_neutralise_les_courbes(void)
{
    float t;
    for (t = 0.0f; t <= 1.0f; t += 0.1f) {
        CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 1.0f, t), t, 1e-6);
        CHECK_NEAR(hb_curve_apply(HB_CURVE_SCURVE, 1.0f, t), t, 1e-6);
    }
}

static void test_courbes_sont_monotones(void)
{
    const uint8_t curves[] = {HB_CURVE_LINEAR, HB_CURVE_POWER, HB_CURVE_SCURVE};
    const float   gammas[] = {0.2f, 0.5f, 1.0f, 2.0f, 4.0f};
    size_t        c, g;
    int           i;

    for (c = 0; c < sizeof curves / sizeof curves[0]; c++) {
        for (g = 0; g < sizeof gammas / sizeof gammas[0]; g++) {
            float previous = -1.0f;
            for (i = 0; i <= 100; i++) {
                float t   = (float)i / 100.0f;
                float out = hb_curve_apply(curves[c], gammas[g], t);
                CHECK(out >= previous - 1e-6f);
                CHECK(out >= 0.0f && out <= 1.0f);
                previous = out;
            }
        }
    }
}

static void test_courbe_inconnue_retombe_en_lineaire(void)
{
    CHECK_NEAR(hb_curve_apply(99, 2.0f, 0.42f), 0.42f, 1e-6);
}

static void test_courbe_borne_son_entree(void)
{
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, -1.0f), 0.0f, 1e-6);
    CHECK_NEAR(hb_curve_apply(HB_CURVE_POWER, 2.0f, 5.0f), 1.0f, 1e-6);
}

/* --- Axe HID ------------------------------------------------------------ */

static void test_axe_hid(void)
{
    CHECK_EQ_INT(hb_axis_from_unit(0.0f), 0);
    CHECK_EQ_INT(hb_axis_from_unit(1.0f), HB_AXIS_MAX);
    CHECK_EQ_INT(hb_axis_from_unit(0.5f), 512);
    /* Borné, jamais de repli sur un entier non signé */
    CHECK_EQ_INT(hb_axis_from_unit(-0.5f), 0);
    CHECK_EQ_INT(hb_axis_from_unit(2.0f), HB_AXIS_MAX);
}

/* --- Configuration ------------------------------------------------------ */

static void test_config_par_defaut(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);

    CHECK_EQ_INT(cfg.curve, HB_CURVE_LINEAR);
    CHECK_NEAR(cfg.gamma, 1.0f, 1e-6);
    CHECK_EQ_INT(cfg.calibrated, 0);
    /* Rien à corriger sur les valeurs par défaut */
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 0);
}

/* Plage par défaut si large que l'axe reste quasi immobile : l'absence de
 * calibration doit sauter aux yeux plutôt que produire un axe erratique. */
static void test_defaut_non_calibre_bouge_a_peine(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    CHECK(hb_axis_from_unit(hb_process(&cfg, 50000)) < 10);
}

static void test_sanitize_borne_gamma(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.gamma = 99.0f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MAX, 1e-6);

    hb_config_defaults(&cfg);
    cfg.gamma = 0.001f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MIN, 1e-6);

    hb_config_defaults(&cfg);
    cfg.gamma = -3.0f;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, HB_GAMMA_MIN, 1e-6);
}

/* Un gamma NaN venant d'une EEPROM corrompue ne doit pas se propager dans la
 * chaîne de traitement, sinon l'axe entier devient NaN. */
static void test_sanitize_rattrape_nan(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    cfg.gamma = (float)NAN;

    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_NEAR(cfg.gamma, 1.0f, 1e-6);
}

static void test_sanitize_borne_courbe_et_plage(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.curve = 42;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.curve, HB_CURVE_LINEAR);

    hb_config_defaults(&cfg);
    cfg.raw_min = 99999999L; /* au-delà des 24 bits du HX711 */
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.raw_min, 8388607L);

    hb_config_defaults(&cfg);
    cfg.calibrated = 200;
    CHECK_EQ_INT(hb_config_sanitize(&cfg), 1);
    CHECK_EQ_INT(cfg.calibrated, 1);
}

/* --- Chaîne complète ---------------------------------------------------- */

static void test_process_bout_en_bout(void)
{
    hb_config_t cfg;

    hb_config_defaults(&cfg);
    cfg.raw_min    = 100000;
    cfg.raw_max    = 900000;
    cfg.calibrated = 1;

    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 100000)), 0);
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 900000)), HB_AXIS_MAX);
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 500000)), 512);

    /* Sous le minimum : l'axe reste à zéro, le levier est au repos. */
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 50000)), 0);
    /* Au-delà du maximum : saturé, pas de retour à zéro. */
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 2000000)), HB_AXIS_MAX);

    cfg.curve = HB_CURVE_POWER;
    cfg.gamma = 2.0f;
    CHECK_EQ_INT(hb_axis_from_unit(hb_process(&cfg, 500000)), 256);
}

/* --- Filtre EMA --------------------------------------------------------- */

/* Le premier échantillon est adopté tel quel, sinon le filtre mettrait des
 * dizaines de lectures à rejoindre le niveau réel depuis zéro. */
static void test_ema_adopte_le_premier_echantillon(void)
{
    hb_ema_t f;
    hb_ema_init(&f, 0.25f);

    CHECK_EQ_INT(hb_ema_value(&f), 0);
    CHECK_EQ_INT(hb_ema_push(&f, 500000), 500000);
    CHECK_EQ_INT(hb_ema_value(&f), 500000);
}

static void test_ema_converge(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 0);
    for (i = 0; i < 200; i++) {
        hb_ema_push(&f, 1000);
    }
    CHECK_EQ_INT(hb_ema_value(&f), 1000);
}

static void test_ema_lisse_le_bruit(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 1000);
    /* Bruit symétrique : la sortie doit rester proche du niveau réel */
    for (i = 0; i < 100; i++) {
        hb_ema_push(&f, (i % 2 == 0) ? 1050 : 950);
    }
    CHECK(hb_ema_value(&f) > 970 && hb_ema_value(&f) < 1030);
}

static void test_ema_gere_les_valeurs_negatives(void)
{
    hb_ema_t f;
    int      i;

    hb_ema_init(&f, 0.5f);
    hb_ema_push(&f, -1000);
    for (i = 0; i < 100; i++) {
        hb_ema_push(&f, -2000);
    }
    CHECK_EQ_INT(hb_ema_value(&f), -2000);
}

static void test_ema_alpha_invalide_devient_transparent(void)
{
    hb_ema_t f;

    hb_ema_init(&f, 0.0f);
    hb_ema_push(&f, 100);
    CHECK_EQ_INT(hb_ema_push(&f, 900), 900);

    hb_ema_init(&f, 5.0f);
    hb_ema_push(&f, 100);
    CHECK_EQ_INT(hb_ema_push(&f, 900), 900);
}

static void test_ema_reset(void)
{
    hb_ema_t f;

    hb_ema_init(&f, 0.25f);
    hb_ema_push(&f, 500000);
    hb_ema_reset(&f);
    CHECK_EQ_INT(hb_ema_value(&f), 0);
    CHECK_EQ_INT(hb_ema_push(&f, 123), 123);
}

int main(void)
{
    RUN(test_normalize_plage_normale);
    RUN(test_normalize_borne_hors_plage);
    RUN(test_normalize_plage_inversee);
    RUN(test_normalize_plage_nulle);
    RUN(test_normalize_valeurs_negatives);

    RUN(test_courbe_lineaire);
    RUN(test_courbe_puissance);
    RUN(test_courbe_s);
    RUN(test_gamma_un_neutralise_les_courbes);
    RUN(test_courbes_sont_monotones);
    RUN(test_courbe_inconnue_retombe_en_lineaire);
    RUN(test_courbe_borne_son_entree);

    RUN(test_axe_hid);

    RUN(test_config_par_defaut);
    RUN(test_defaut_non_calibre_bouge_a_peine);
    RUN(test_sanitize_borne_gamma);
    RUN(test_sanitize_rattrape_nan);
    RUN(test_sanitize_borne_courbe_et_plage);

    RUN(test_process_bout_en_bout);

    RUN(test_ema_adopte_le_premier_echantillon);
    RUN(test_ema_converge);
    RUN(test_ema_lisse_le_bruit);
    RUN(test_ema_gere_les_valeurs_negatives);
    RUN(test_ema_alpha_invalide_devient_transparent);
    RUN(test_ema_reset);

    TEST_SUMMARY("hb_core");
}
