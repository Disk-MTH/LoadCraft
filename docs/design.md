# Handbrake progressif USB — conception

Handbrake de simracing à cellule de charge, vu par le PC comme un périphérique
USB HID natif (aucun driver, aucun logiciel à laisser tourner pendant le jeu).

## 1. Matériel

| Élément | Référence | Rôle |
|---|---|---|
| Cellule de charge | 20 kg, jauge de contrainte 4 fils | Mesure la force appliquée sur le levier |
| Amplificateur / ADC | Module HX711 (24 bits) | Amplifie le pont de jauges et numérise |
| Micro-contrôleur | Pro Micro ATmega32u4, 5 V / 16 MHz, USB-C | Traitement + énumération USB HID |

### Pourquoi l'ATmega32u4 et pas un ESP8266

L'ESP8266 (ESP-01, ESP-12F, NodeMCU…) n'a **aucun contrôleur USB device**. Le port
micro-USB de ces cartes est relié à une puce pont USB↔série (CH340 / CP2102) à
fonction fixe : elle ne peut s'annoncer que comme port COM, jamais comme joystick.
L'ATmega32u4 embarque le contrôleur USB dans le silicium principal : c'est le
firmware qui décide du type de périphérique présenté à l'hôte.

Même raison pour écarter les clones « Nano USB-C » à puce CH340, malgré leur
description « compatible Pro Micro ».

## 2. Architecture logicielle

```
Cellule 20kg ──4 fils──> HX711 ──DT/SCK──> Pro Micro (ATmega32u4)
                                                  │
                                    ┌─────────────┴─────────────┐
                                    │      firmware C/C++       │
                                    │  1. lecture brute 24 bits │
                                    │  2. filtre EMA            │
                                    │  3. normalisation min/max │
                                    │  4. courbe de réponse     │
                                    │  5. axe 0..1023           │
                                    └─────────────┬─────────────┘
                                                  │
                              ┌───────────────────┴───────────────────┐
                              │        USB composite (natif)          │
                              │  ├─ HID joystick : 1 axe X            │
                              │  └─ CDC série    : protocole de config│
                              └───────────────────┬───────────────────┘
                                    ┌─────────────┴─────────────┐
                                    │                           │
                              Jeux (DirectInput)        App de calibration
                                                        (Python, optionnelle)
```

Le firmware est **autonome** : la configuration vit en EEPROM du 32u4, donc le
handbrake fonctionne correctement branché sur n'importe quel PC, app fermée.
L'app de calibration ne sert qu'à régler, pas à jouer.

## 3. Chaîne de traitement du signal

### 3.1 Acquisition

Driver HX711 maison, non bloquant (~40 lignes). Le protocole HX711 est trivial
(24 bits en série synchrone + impulsions d'horloge pour choisir le gain), et une
implémentation maison évite une dépendance externe tout en garantissant que la
boucle principale ne se bloque jamais en attente de conversion — indispensable
pour continuer à servir l'USB et les commandes série.

Canal A, gain 128 (25 impulsions d'horloge) : c'est l'entrée à faible bruit,
adaptée à une cellule de charge.

Broche `RATE` du module reliée à VCC → **80 échantillons/seconde** au lieu des
10 par défaut. Sur un handbrake la latence compte : 12,5 ms au lieu de 100 ms.

### 3.2 Filtrage

Moyenne exponentielle (EMA) : `y[n] = y[n-1] + α·(x[n] − y[n-1])`.

Choisie plutôt qu'une moyenne glissante classique parce qu'elle ne coûte qu'une
valeur en RAM et une multiplication, sans tampon circulaire. α ≈ 0,25 à 80 SPS
donne un compromis correct bruit/réactivité (constante de temps ≈ 44 ms).

### 3.3 Normalisation

```
t = (raw − raw_min) / (raw_max − raw_min)   puis borné à [0, 1]
```

`raw_min` = levier au repos, `raw_max` = force maximale voulue à fond. Les deux
sont capturées par l'utilisateur depuis l'app, au ressenti.

Cette formule gère **aussi le cas `raw_max < raw_min`** : si la cellule est
câblée en polarité inverse (A+ et A− permutés), il suffit de calibrer
normalement, le signe s'annule de lui-même. Aucune option « inverser l'axe »
n'est donc nécessaire. Seul cas dégénéré : `raw_min == raw_max`, qui renvoie 0.

### 3.4 Courbe de réponse

`raw_min`/`raw_max` fixent la *plage*, la courbe fixe le *ressenti* à
l'intérieur. Trois formes, un seul paramètre `gamma` :

| Courbe | Formule | Effet |
|---|---|---|
| `LINEAR` | `t` | Sortie proportionnelle à la force |
| `POWER` | `t^gamma` | `gamma < 1` : mordant dès le début. `gamma > 1` : progressif, précision en début de course |
| `SCURVE` | `t<0,5 : ½(2t)^g`<br>`t≥0,5 : 1−½(2(1−t))^g` | `g > 1` : doux aux extrémités, franc au milieu. `g < 1` : l'inverse |

`gamma = 1` rend les trois courbes identiques (linéaire), ce qui donne un point
de repère neutre pour comparer.

Le choix de la bonne courbe dépend du ressenti et du montage mécanique — d'où
le réglage en direct dans l'app plutôt qu'une valeur figée dans le code.

### 3.5 Sortie HID

Un seul axe X, plage `0..1023`, type joystick, 0 bouton, 0 hat. Tout ce qui est
inutile est retiré du descripteur HID : rapport plus court et meilleure
compatibilité hôte.

1024 pas sur la course du levier dépassent largement la finesse de modulation
d'un pied ou d'une main, et restent en deçà du bruit résiduel du HX711 : monter
en résolution n'apporterait que du bruit supplémentaire.

`begin(false)` + `sendState()` explicite : l'état est envoyé en un rapport
atomique, jamais partiellement mis à jour. Le rapport n'est émis qu'au
changement de valeur, avec un renvoi périodique pour garder l'hôte en phase
même levier immobile.

La pile HID est celle de **MHeironimus/ArduinoJoystickLibrary**, qui permet de
déclarer exactement les axes voulus et de fixer leur plage. Elle **n'est pas
dans le gestionnaire de bibliothèques Arduino** : une autre bibliothèque nommée
« Joystick » y figure, destinée à *lire* un module joystick analogique.
L'installer produit une erreur `'Joystick_' does not name a type`. Voir le
README pour l'installation depuis GitHub.

## 4. Zéro et dérive

Pas de tare automatique au démarrage. `raw_min` issu de la calibration *est* le
zéro, et il est persistant.

Conséquence assumée : la dérive lente du zéro d'une cellule de charge (thermique,
tassement mécanique) finira par décaler légèrement le point de repos. La
correction est un clic sur « Définir le minimum » dans l'app, deux secondes.

L'alternative — retare au boot — a été écartée : elle produit un zéro faux si
l'USB est branché alors que le levier est tiré, et ce mode de panne est plus
pénible que la dérive qu'il corrige.

## 5. Persistance

EEPROM interne du 32u4 (1 Ko), adresse 0, enregistrement de 22 octets :

| Offset | Champ | Type |
|---|---|---|
| 0–3 | magic `"HBK1"` | u32 |
| 4 | version | u8 |
| 5 | curve | u8 |
| 6–9 | raw_min | i32 |
| 10–13 | raw_max | i32 |
| 14–17 | gamma | float |
| 18 | calibrated | u8 |
| 19 | réservé | u8 |
| 20–21 | CRC-16/CCITT | u16 |

Disposition petit-boutiste écrite octet par octet, et non une `struct`
sérialisée telle quelle : pas de dépendance au bourrage ni à l'alignement
choisis par le compilateur, donc le même enregistrement est relu à l'identique
par la cible AVR et par les tests natifs.

Magic + version + CRC16 : une EEPROM vierge, corrompue, ou écrite par une
version antérieure incompatible est détectée et remplacée par les valeurs par
défaut, plutôt que d'être interprétée comme une calibration valide.

Un CRC correct ne prouve cependant que l'intégrité. Un enregistrement
authentique peut contenir des valeurs inexploitables — un `gamma` NaN
contaminerait tout le calcul de l'axe. `hb_config_sanitize` est donc appliqué
systématiquement après relecture.

Écriture **uniquement sur commande `SAVE` explicite**. Les réglages en direct
(slider gamma) restent en RAM : l'EEPROM AVR est donnée pour ~100 000 cycles
d'écriture, un slider qui écrirait à chaque mouvement l'userait en quelques
séances.

Valeurs par défaut, EEPROM vierge : `calibrated = 0`, plage volontairement très
large. L'axe bouge donc à peine, ce qui rend l'absence de calibration évidente
au lieu de produire un comportement erratique difficile à diagnostiquer.

## 6. Protocole de configuration (CDC série)

Lignes ASCII terminées par `\n`, dans les deux sens. Choix du texte plutôt que
du binaire : lisible dans n'importe quel moniteur série, débogable sans outil.

### Hôte → périphérique

| Commande | Effet |
|---|---|
| `PING` | Test de présence |
| `GET` | Renvoie la configuration courante |
| `SET MIN` / `SET MAX` | Capture la valeur filtrée courante |
| `SET MIN <v>` / `SET MAX <v>` | Fixe une valeur explicite |
| `SET CURVE LINEAR\|POWER\|SCURVE` | Change la forme de courbe |
| `SET GAMMA <f>` | Change le paramètre de courbe |
| `SAVE` | Écrit en EEPROM |
| `LOAD` | Recharge l'EEPROM (annule les réglages non sauvés) |
| `RESET` | Valeurs par défaut en RAM |
| `STREAM 0\|1` | Coupe / active la télémétrie |

### Périphérique → hôte

- Réponses : `OK <commande> [valeur]` ou `ERR <raison>`
- Configuration : `CFG min=<i32> max=<i32> curve=<nom> gamma=<f> calibrated=<0|1>`
- Télémétrie (si `STREAM 1`) : `T raw=<i32> out=<f> axis=<0..1023>`

**Télémétrie coupée par défaut**, activée par l'app à la connexion. Un firmware
qui émettrait en continu risquerait de saturer le tampon CDC quand personne
n'écoute, au détriment de la boucle HID.

### Contrainte AVR : pas de `%f`

L'implémentation `printf` d'avr-libc **n'inclut pas le support des flottants**
sauf option d'édition de liens spécifique. Un `snprintf("%f")` produit du texte
vide ou faux sur cette cible, sans erreur de compilation — panne silencieuse
classique.

Le formatage des flottants passe donc par un helper maison en arithmétique
entière (`hb_fmt_fixed`), testé nativement. La lecture utilise `strtod`, que
avr-libc fournit bien.

## 7. Découpage du code

Le firmware est séparé en **cœur pur** et **couche matérielle**, pour que la
logique soit testable sur PC sans carte :

```
firmware/handbrake/
  hb_core.h/.c       C99 pur : config, normalisation, courbes, filtre EMA
  hb_protocol.h/.c   C99 pur : analyse des commandes, formatage, tampon de ligne
  hb_record.h/.c     C99 pur : sérialisation de l'enregistrement EEPROM + CRC16
  hx711.h/.cpp       driver matériel non bloquant
  hb_storage.h/.cpp  lecture/écriture EEPROM
  config.h           brochage et constantes
  handbrake.ino      assemblage : boucle, HID, série
```

`hb_core`, `hb_protocol` et `hb_record` ne dépendent que de la libc et de
`math.h` : ils sont compilés tels quels par les tests natifs (`tests/`, gcc) et
par le compilateur AVR. Toute la logique susceptible d'être fausse est ainsi
couverte par des tests qui tournent en une seconde, sans matériel.

La sérialisation est séparée de l'accès EEPROM précisément pour cette raison :
la détection de corruption casse sans bruit et ne se remarque qu'une fois la
calibration perdue. `hb_storage` se réduit alors à une boucle de lecture et une
boucle d'écriture.

`hb_storage`, `hx711` et le `.ino` sont volontairement minces : ce qu'ils
contiennent ne peut être validé qu'avec la carte en main.

## 8. App de calibration

Python. Serveur local Flask + interface web, présentée dans une fenêtre native
via `pywebview` — donc une vraie application de bureau Linux/Windows, sans
embarquer de navigateur (pywebview réutilise le moteur web du système, là où
Electron ajouterait ~100 Mo).

- `protocol.py` — miroir du protocole firmware, pur, testé
- `link.py` — port série, thread de lecture, file de télémétrie
- `server.py` — API HTTP locale + SSE pour la télémétrie temps réel
- `web/index.html` — graphe live, valeurs brutes/mappées, boutons de calibration,
  sélecteur de courbe, slider gamma, bouton de sauvegarde

SSE plutôt que WebSocket : flux unidirectionnel serveur→page uniquement, donc
SSE suffit et tient dans la bibliothèque standard côté navigateur, sans
dépendance supplémentaire côté serveur.

Le transport série est **injecté** dans `SerialLink` plutôt que créé par lui :
les tests fournissent une carte simulée et couvrent tout le dialogue — ordre
des réponses, effet des commandes, résistance aux octets parasites — sans
matériel ni pyserial.

Les courbes sont réimplémentées côté hôte plutôt que demandées à la carte, pour
que l'aperçu tracé montre exactement ce que le firmware calcule. Les tests
Python reprennent les propriétés vérifiées côté C (points fixes, monotonie,
symétrie, neutralité de `gamma = 1`).

L'énumération des ports ne retient que les périphériques USB : sous Linux,
pyserial remonte aussi la trentaine de ports 8250 hérités (`/dev/ttyS*`), où la
carte serait introuvable. Repli sur la liste complète si aucun port USB n'est
détecté — mieux vaut un choix encombré qu'aucun choix.

## 9. Plan de validation

| Étape | Vérifie | État |
|---|---|---|
| Tests natifs C | Courbes, normalisation, filtre, protocole, formatage, EEPROM | ✅ 3425 assertions |
| Tests pytest | Protocole hôte, dialogue série, API serveur, ports | ✅ 113 tests |
| Compilation AVR | Le firmware compile pour l'ATmega32u4 | ✅ 62 % flash, 26 % RAM |
| Lecture HX711 brute | Câblage, bruit, plage, signe | ⏳ carte requise |
| Énumération HID | Windows voit un joystick, l'axe bouge | ⏳ carte requise |
| Calibration bout en bout | App ↔ firmware, persistance EEPROM | ⏳ carte requise |
| Essai en jeu | Ressenti, choix final de la courbe | ⏳ carte requise |

Les tests avec carte simulée valident le *dialogue*, pas le matériel : ils ne
disent rien du bruit réel du HX711, de la stabilité mécanique du montage, ni de
la façon dont un jeu donné interprète l'axe.

## 10. Hors périmètre (v1)

- **Bluetooth / sans fil** — l'ATmega32u4 n'a pas de radio. Un handbrake sans fil
  complet imposerait un autre MCU (ESP32 et BLE HID) et une autre architecture.
- **Boutons / LED** — écartés volontairement : l'app couvre le besoin de
  calibration, une LED n'apporterait rien de plus.
- **Éditeur de courbe libre (splines, points)** — trois formes paramétriques
  couvrent l'espace de ressenti utile. À reconsidérer seulement si l'essai en
  jeu montre qu'aucune ne convient.
