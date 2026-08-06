# Handbrake progressif pour simracing

Handbrake à cellule de charge, vu par le PC comme un **périphérique USB HID
natif** : aucun driver, aucun logiciel à laisser tourner pendant le jeu. Il
apparaît dans « Contrôleurs de jeu USB » de Windows comme un handbrake du
commerce, et se mappe comme n'importe quel axe.

```
Cellule 20 kg ──> HX711 ──> Pro Micro (ATmega32u4) ──USB-C──> PC
                                                      │
                                    joystick HID (jeu) + série (calibration)
```

## État

| Partie | État |
|---|---|
| Cœur du firmware (courbes, filtre, protocole, EEPROM) | ✅ écrit, 3425 assertions natives |
| Couche matérielle + sketch | ✅ écrit, compile pour l'ATmega32u4 |
| App de calibration | ✅ écrite, 113 tests |
| Essai sur matériel réel | ⏳ en attente de la carte |

Rien n'a encore tourné sur une vraie carte : tout ce qui touche au HX711, à
l'énumération HID et à l'EEPROM reste à valider avec le montage en main. Voir
`docs/design.md` §9 pour le détail de ce qui est vérifié et de ce qui ne l'est
pas.

## Matériel

| Élément | Précision |
|---|---|
| Cellule de charge 20 kg | 4 fils, avec module HX711 |
| Module HX711 | Amplificateur + convertisseur 24 bits |
| **Pro Micro ATmega32u4** | 5 V / 16 MHz, USB-C |

⚠️ **Une carte ESP8266 ou à puce CH340 ne convient pas.** Leur port USB est
relié à un pont USB↔série à fonction fixe, incapable de se présenter comme un
joystick. Il faut un micro-contrôleur dont le contrôleur USB est dans la puce
principale. Détails dans `docs/design.md` §1.

Câblage complet : `docs/wiring.md`.

## Structure

```
firmware/handbrake/   firmware ATmega32u4
  hb_core.c           courbes, normalisation, filtre        ← C99 pur, testé
  hb_protocol.c       protocole série                       ← C99 pur, testé
  hb_record.c         sérialisation EEPROM + CRC            ← C99 pur, testé
  hx711.cpp           driver capteur                        ← matériel
  hb_storage.cpp      accès EEPROM                          ← matériel
  handbrake.ino       boucle principale, HID                ← matériel
app/                  app de calibration (Python)
tests/                tests natifs du cœur du firmware (gcc)
docs/                 conception et câblage
```

Le firmware est séparé en **cœur pur** et **couche matérielle** : toute la
logique susceptible d'être fausse est en C99 sans dépendance Arduino, donc
compilée et testée sur PC en une seconde. Ce qui reste dans la couche
matérielle ne peut de toute façon être validé qu'avec la carte branchée.

## Tests

```bash
make test            # les deux suites
make test-firmware   # cœur du firmware, natif (gcc)
make test-app        # app de calibration (pytest)
```

Aucune des deux suites n'a besoin de la carte.

## Compiler et téléverser le firmware

### Dépendance : la bibliothèque Joystick

⚠️ **Elle n'est pas dans le gestionnaire de bibliothèques Arduino.** Une autre
bibliothèque nommée « Joystick » (Giuseppe Martini) y figure — elle sert à
*lire* un module joystick analogique, pas à en émuler un. L'installer conduit
à une erreur `'Joystick_' does not name a type`.

Il faut celle de **MHeironimus**, installée depuis GitHub :

```bash
# Avec arduino-cli
ARDUINO_LIBRARY_ENABLE_UNSAFE_INSTALL=true \
  arduino-cli lib install --git-url https://github.com/MHeironimus/ArduinoJoystickLibrary.git

# Avec l'IDE Arduino : télécharger le .zip du dépôt, puis
# Croquis > Inclure une bibliothèque > Ajouter la bibliothèque .ZIP
```

### Compilation

```bash
make detect                      # identifie la carte et son FQBN
make build                       # arduino:avr:leonardo par défaut
make flash PORT=/dev/ttyACM0     # téléversement
```

Occupation constatée : 17896 octets de flash (62 %), 687 octets de RAM (26 %).

**Le FQBN dépend du bootloader du clone.** Beaucoup de Pro Micro embarquent le
bootloader Leonardo et s'annoncent `2341:8036`. D'autres se présentent en
Arduino Micro (`2341:8037`) ou en SparkFun Pro Micro (`1B4F:…`). `make detect`
donne le bon ; pour en utiliser un autre :

```bash
make build FQBN=arduino:avr:micro
```

Sous l'IDE Arduino, choisir la carte correspondante (**Arduino Leonardo** ou
**Arduino Micro** — même ATmega32u4) et ouvrir
`firmware/handbrake/handbrake.ino`.

### Si le téléversement échoue

Le 32u4 doit passer en bootloader pour être flashé. Normalement l'outil s'en
charge en ouvrant le port à 1200 bauds, mais un sketch qui plante la pile USB
empêche ce mécanisme. Solution manuelle : **double appui rapide sur RESET**,
puis lancer le téléversement dans les ~8 secondes où le bootloader est actif.

## Prérequis par système

### Linux

L'accès au port série passe par le groupe `dialout` :

```bash
sudo usermod -aG dialout $USER   # puis déconnexion/reconnexion de session
```

Sans ça, `/dev/ttyACM0` reste en `root:dialout` et l'app comme le
téléversement échouent sur un refus de permission.

### Windows

Rien à installer : Windows 10/11 fournit le pilote CDC pour l'ATmega32u4 à
identifiants Arduino, et le périphérique HID est reconnu nativement.

Le port est un `COM…` au lieu de `/dev/ttyACM0` — l'app le détecte de la même
façon. Le `Makefile` suppose un environnement Unix ; sous Windows, lancer les
commandes directement :

```
cd app
uv venv .venv
uv pip install --python .venv -e ".[dev]"
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m handbrake_tuner
```

Le firmware est strictement identique sur les deux systèmes : la calibration
sauvegardée sous Linux reste valable une fois la carte branchée sur le PC de
jeu, puisqu'elle vit dans l'EEPROM de la carte et non sur le PC.

## Vérifier que l'axe est bien vu par le système

### Linux

```bash
sudo dnf install evtest joystick   # Fedora
jstest /dev/input/js0              # l'axe doit bouger quand on tire
```

### Windows

`Win+R` → `joy.cpl` → sélectionner le périphérique → **Propriétés**. L'axe X
doit se déplacer quand on tire sur le levier.

Une fois visible ici, n'importe quel jeu peut le mapper comme handbrake.

## App de calibration

```bash
make setup-app
app/.venv/bin/python -m handbrake_tuner
```

Options : `--browser` (ouvrir dans le navigateur), `--no-window` (serveur
seul), `--port N` (port HTTP fixe). Le serveur n'écoute que sur `127.0.0.1`.

Pour une fenêtre native plutôt que le navigateur :

```bash
cd app && .venv/bin/python -m pip install pywebview
```

### Procédure de calibration

1. Brancher la carte, sélectionner le port, **Connecter**.
2. Levier au repos → **Définir ici** sur la ligne *Minimum*.
3. Tirer à la force qui doit correspondre au frein à fond → **Définir ici**
   sur la ligne *Maximum*.
4. Essayer les courbes et le curseur gamma jusqu'à trouver le bon ressenti.
5. **Sauvegarder dans la carte**.

Sans l'étape 5, les réglages sont perdus au débranchement : l'EEPROM n'est
écrite que sur demande, pour ne pas l'user à chaque mouvement du curseur.

### Courbes disponibles

| Courbe | Effet |
|---|---|
| Linéaire | Sortie proportionnelle à la force |
| Puissance | `gamma < 1` : mordant dès le début. `gamma > 1` : progressif, précision en début de course |
| Courbe en S | `gamma > 1` : doux aux extrémités, franc au milieu. `gamma < 1` : l'inverse |

`gamma = 1` rend les trois identiques : c'est le repère neutre pour comparer.

Le bon réglage dépend du ressenti et du montage mécanique — d'où le réglage en
direct plutôt qu'une valeur figée dans le code.

## Protocole série

Utile pour déboguer sans l'app, depuis n'importe quel moniteur série :

```
PING                     → OK PING
GET                      → CFG min=… max=… curve=… gamma=… calibrated=…
SET MIN | SET MAX        capture la valeur filtrée courante
SET MIN <v> | SET MAX <v>
SET CURVE LINEAR|POWER|SCURVE [gamma]
SET GAMMA <f>
SAVE | LOAD | RESET
STREAM 0|1               télémétrie : T raw=… out=… axis=…
```

La télémétrie est coupée par défaut. Détails dans `docs/design.md` §6.

## Documentation

- `docs/design.md` — conception, choix techniques et leurs raisons
- `docs/wiring.md` — câblage, vérifications, première mise en route
