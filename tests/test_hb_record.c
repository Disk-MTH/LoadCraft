#include "hb_record.h"
#include "test_harness.h"

static hb_config_t sample_config(void)
{
    hb_config_t cfg;
    hb_config_defaults(&cfg);
    cfg.raw_min    = 123456;
    cfg.raw_max    = -78910;
    cfg.curve      = HB_CURVE_SCURVE;
    cfg.gamma      = 1.75f;
    cfg.calibrated = 1;
    return cfg;
}

/* --- Aller-retour -------------------------------------------------------- */

static void test_aller_retour(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);

    CHECK_EQ_INT(dst.raw_min, src.raw_min);
    CHECK_EQ_INT(dst.raw_max, src.raw_max);
    CHECK_EQ_INT(dst.curve, src.curve);
    CHECK_EQ_INT(dst.calibrated, src.calibrated);
    /* Le flottant transite par ses bits bruts : il doit revenir à l'identique
     * au bit près, pas seulement « proche ». */
    CHECK(dst.gamma == src.gamma);
}

static void test_aller_retour_valeurs_par_defaut(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_EQ_INT(dst.raw_min, src.raw_min);
    CHECK_EQ_INT(dst.raw_max, src.raw_max);
    CHECK(dst.gamma == src.gamma);
}

static void test_aller_retour_extremes(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.raw_min = -8388608L;
    src.raw_max = 8388607L;
    src.gamma   = HB_GAMMA_MIN;

    hb_record_pack(buf, &src);
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_EQ_INT(dst.raw_min, -8388608L);
    CHECK_EQ_INT(dst.raw_max, 8388607L);
    CHECK_NEAR(dst.gamma, HB_GAMMA_MIN, 1e-6);
}

/* --- Détection de corruption --------------------------------------------- */

/* Une EEPROM vierge sort à 0xFF partout. Sans magic, elle serait interprétée
 * comme une calibration valide et l'axe partirait n'importe où. */
static void test_eeprom_vierge_rejetee(void)
{
    hb_config_t cfg;
    uint8_t     buf[HB_RECORD_SIZE];
    size_t      i;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0xFF;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0x00;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);
}

static void test_mauvais_magic_rejete(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    buf[0] ^= 0xFF;
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
}

/* Une version antérieure a pu écrire une disposition différente à la même
 * adresse : elle doit être rejetée, pas relue de travers. */
static void test_mauvaise_version_rejetee(void)
{
    hb_config_t src = sample_config();
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_record_pack(buf, &src);
    buf[4] = 99;
    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
}

/* Chaque octet utile doit être couvert par le CRC : un octet ignoré serait
 * un champ qui peut se corrompre sans être détecté. */
static void test_chaque_octet_est_couvert_par_le_crc(void)
{
    hb_config_t src = sample_config();
    size_t      i;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        hb_config_t dst;
        uint8_t     buf[HB_RECORD_SIZE];

        hb_record_pack(buf, &src);
        buf[i] ^= 0x01; /* un seul bit retourné */
        CHECK_EQ_INT(hb_record_unpack(buf, &dst), 0);
    }
}

static void test_cfg_intact_si_rejet(void)
{
    hb_config_t cfg;
    uint8_t     buf[HB_RECORD_SIZE];
    size_t      i;

    hb_config_defaults(&cfg);
    cfg.raw_min = 4242;

    for (i = 0; i < HB_RECORD_SIZE; i++) {
        buf[i] = 0xFF;
    }
    CHECK_EQ_INT(hb_record_unpack(buf, &cfg), 0);
    CHECK_EQ_INT(cfg.raw_min, 4242); /* non écrasé */
}

/* --- Validation après relecture ------------------------------------------ */

/* Un CRC correct ne prouve que l'intégrité. Un enregistrement authentique
 * mais au contenu inexploitable doit quand même être ramené dans le domaine
 * valide, sinon un gamma NaN contaminerait tout l'axe. */
static void test_valeurs_hors_domaine_rattrapees(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.gamma = 999.0f;
    src.curve = 77;
    hb_record_pack(buf, &src);

    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_NEAR(dst.gamma, HB_GAMMA_MAX, 1e-6);
    CHECK_EQ_INT(dst.curve, HB_CURVE_LINEAR);
}

static void test_gamma_nan_rattrape(void)
{
    hb_config_t src;
    hb_config_t dst;
    uint8_t     buf[HB_RECORD_SIZE];

    hb_config_defaults(&src);
    src.gamma = (float)NAN;
    hb_record_pack(buf, &src);

    CHECK_EQ_INT(hb_record_unpack(buf, &dst), 1);
    CHECK_NEAR(dst.gamma, 1.0f, 1e-6);
}

/* --- CRC ------------------------------------------------------------------ */

/* Vecteur de référence du CRC-16/CCITT-FALSE : garantit que l'implémentation
 * est bien l'algorithme annoncé, et non une variante proche. */
static void test_crc16_vecteur_de_reference(void)
{
    const uint8_t check[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    CHECK_EQ_INT(hb_crc16(check, sizeof check), 0x29B1);
}

static void test_crc16_detecte_les_differences(void)
{
    const uint8_t a[] = {1, 2, 3, 4};
    const uint8_t b[] = {1, 2, 3, 5};
    const uint8_t c[] = {1, 2, 4, 3};

    CHECK(hb_crc16(a, sizeof a) != hb_crc16(b, sizeof b));
    CHECK(hb_crc16(a, sizeof a) != hb_crc16(c, sizeof c)); /* ordre compris */
    CHECK_EQ_INT(hb_crc16(a, 0), 0xFFFF);                  /* valeur initiale */
}

int main(void)
{
    RUN(test_aller_retour);
    RUN(test_aller_retour_valeurs_par_defaut);
    RUN(test_aller_retour_extremes);

    RUN(test_eeprom_vierge_rejetee);
    RUN(test_mauvais_magic_rejete);
    RUN(test_mauvaise_version_rejetee);
    RUN(test_chaque_octet_est_couvert_par_le_crc);
    RUN(test_cfg_intact_si_rejet);

    RUN(test_valeurs_hors_domaine_rattrapees);
    RUN(test_gamma_nan_rattrape);

    RUN(test_crc16_vecteur_de_reference);
    RUN(test_crc16_detecte_les_differences);

    TEST_SUMMARY("hb_record");
}
