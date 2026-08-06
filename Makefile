# Raccourcis du projet.
#
# `make test` lance les deux suites : le cœur du firmware en natif (gcc) et
# l'app de calibration (pytest). Aucune des deux n'a besoin de la carte.

# Beaucoup de clones Pro Micro embarquent le bootloader Leonardo et
# s'annoncent comme tel (2341:8036). Vérifiez avec `arduino-cli board list` et
# surchargez si besoin : make build FQBN=arduino:avr:micro
FQBN ?= arduino:avr:leonardo
SKETCH = firmware/handbrake
VENV = app/.venv

# L'environnement Python place l'interpréteur dans Scripts/ sous Windows.
VENV_PY = $(if $(wildcard $(VENV)/Scripts/python.exe),$(VENV)/Scripts/python.exe,$(VENV)/bin/python)

.PHONY: help test test-firmware test-app setup-app build flash clean

help:
	@echo "make test           les deux suites de tests"
	@echo "make test-firmware  tests natifs du cœur du firmware (gcc)"
	@echo "make test-app       tests de l'app de calibration (pytest)"
	@echo "make setup-app      crée l'environnement Python de l'app"
	@echo "make detect         identifie la carte et son FQBN"
	@echo "make build          compile le firmware (arduino-cli requis)"
	@echo "make flash PORT=…   téléverse le firmware sur la carte"
	@echo "make clean          supprime les artefacts de compilation"

test: test-firmware test-app

test-firmware:
	@$(MAKE) -C tests test

test-app: $(VENV)
	@$(VENV_PY) -m pytest app/tests -q

setup-app: $(VENV)

# --system-site-packages : le backend GTK de pywebview a besoin de PyGObject,
# que pip ne fournit pas sans chaîne de compilation complète. Sous Linux, la
# bibliothèque système est déjà là et se prête au partage ; sous Windows le
# drapeau est sans effet, pywebview y passant par WebView2.
$(VENV):
	@echo "Création de l'environnement Python…"
	@cd app && uv venv --system-site-packages .venv \
		&& uv pip install --python .venv -e ".[dev,desktop]"

build:
	arduino-cli compile --fqbn $(FQBN) $(SKETCH)

flash:
	@test -n "$(PORT)" || { echo "Indiquez le port : make flash PORT=/dev/ttyACM0"; exit 1; }
	arduino-cli upload --fqbn $(FQBN) --port $(PORT) $(SKETCH)

# Détecte la carte et affiche le FQBN à utiliser.
detect:
	arduino-cli board list

clean:
	@$(MAKE) -C tests clean
	rm -rf $(SKETCH)/build
