# Câblage — montage de test sur breadboard

## Matériel

- Cellule de charge 20 kg (4 fils)
- Module HX711
- Pro Micro ATmega32u4, 5 V / 16 MHz, USB-C
- Breadboard + straps
- Câble USB-C

Tout est alimenté par le port USB-C du Pro Micro. Aucune alimentation externe.

## Schéma

```
         CELLULE DE CHARGE 20 kg
        ┌──────────────────────┐
        │  rouge   E+ ─────────┼───► E+  ┐
        │  noir    E- ─────────┼───► E-  │  bornier à vis
        │  vert    A+ ─────────┼───► A+  │  du module HX711
        │  blanc   A- ─────────┼───► A-  ┘
        └──────────────────────┘

              MODULE HX711                    PRO MICRO 32u4
        ┌──────────────────────┐          ┌──────────────────┐
        │  VCC  ───────────────┼──────────┤ VCC   (5 V)      │
        │  GND  ───────────────┼──────────┤ GND              │
        │  DT   ───────────────┼──────────┤ 4   (données)    │
        │  SCK  ───────────────┼──────────┤ 5   (horloge)    │
        │  RATE ───────────────┼──────────┤ VCC   (→ 80 SPS) │
        └──────────────────────┘          └────────┬─────────┘
                                                   │ USB-C
                                                   ▼  vers PC
```

## Table de correspondance

### Cellule → HX711

| Fil cellule | Borne HX711 |
| --- | --- |
| E+ | E+ |
| E− | E− |
| A+ | A+ |
| A− | A− |

⚠️ **Les couleurs varient selon le fabricant.** La convention la plus courante est
rouge = E+, noir = E−, vert = A+, blanc = A−, mais il faut vérifier sur la notice
fournie avec la cellule.

Se tromper entre A+ et A− n'a aucune conséquence ici : le signe s'inverse, et la
normalisation min/max l'absorbe automatiquement (voir `docs/design.md` §3.3).
Inverser E+ et E− est en revanche à éviter.

### HX711 → Pro Micro

| HX711 | Pro Micro | Défini dans |
| --- | --- | --- |
| VCC | `VCC` | — |
| GND | `GND` | — |
| DT | broche 4 | `config.h` → `HB_PIN_HX711_DT` |
| SCK | broche 5 | `config.h` → `HB_PIN_HX711_SCK` |
| RATE | `VCC` | — |

**`VCC` et non `RAW`** : sur un Pro Micro, `RAW` est une *entrée* d'alimentation
(avant régulateur). La sortie régulée 5 V utilisable est la broche `VCC`.

**`RATE` → `VCC`** fait passer le HX711 de 10 à 80 échantillons/seconde. Sur
certains modules cette broche n'est pas sortie sur le connecteur : il faut alors
un pont de soudure sur le pad `RATE` au dos de la carte. Si ce n'est pas fait, le
montage fonctionne quand même, mais avec une latence de ~100 ms au lieu de
~12,5 ms — nettement perceptible en jeu.

Les broches 4 et 5 sont des GPIO libres, sans conflit avec l'USB ni avec quoi que
ce soit d'autre. Elles sont modifiables dans `firmware/handbrake/config.h`.

## Vérification avant la première mise sous tension

1. Aucun court-circuit entre `VCC` et `GND`.
2. Les 4 fils de la cellule sont bien serrés dans le bornier (les fils fins
   ressortent facilement).
3. `RATE` est bien sur `VCC`, pas sur `GND`.
4. La cellule est montée **dans le bon sens** mécaniquement : la flèche gravée
   sur son flanc indique le sens de la force. Une cellule montée à l'envers
   fonctionne mais travaille en compression au lieu de traction — le signe est
   inversé (sans conséquence logicielle) mais la tenue mécanique est moins bonne.

## Première mise en route

```bash
# 1. Vérifier que la lecture brute réagit
#    (téléverser le firmware, puis :)
python -m handbrake_tuner

# 2. Sans toucher le levier          → cliquer « Définir le minimum »
# 3. En tirant à la force maximale   → cliquer « Définir le maximum »
# 4. Ajuster la courbe au ressenti   → cliquer « Sauvegarder »
```

Si la valeur brute ne bouge pas du tout quand on appuie sur la cellule :
vérifier DT/SCK, puis les 4 fils de la cellule. Si elle saute entre des valeurs
extrêmes de façon erratique : mauvaise masse ou alimentation instable.

## Passage au montage définitif

Les « grilles vertes avec plein de trous » évoquées pour la version définitive
s'appellent des **plaques d'essai à pastilles** (perfboard / veroboard). Le
câblage ci-dessus s'y transpose à l'identique, en soudant les liaisons au lieu
d'utiliser des straps.
