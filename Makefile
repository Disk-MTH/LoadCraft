# Raccourcis du projet.
#
# `make test` lance les deux suites : le cœur du firmware en natif (gcc) et
# l'app de calibration (pytest). Aucune des deux n'a besoin de la carte.

FQBN ?= arduino:avr:micro
SKETCH = firmware/handbrake
VENV = app/.venv

.PHONY: help test test-firmware test-app setup-app build flash clean

help:
	@echo "make test           les deux suites de tests"
	@echo "make test-firmware  tests natifs du cœur du firmware (gcc)"
	@echo "make test-app       tests de l'app de calibration (pytest)"
	@echo "make setup-app      crée l'environnement Python de l'app"
	@echo "make build          compile le firmware (arduino-cli requis)"
	@echo "make flash PORT=…   téléverse le firmware sur la carte"
	@echo "make clean          supprime les artefacts de compilation"

test: test-firmware test-app

test-firmware:
	@$(MAKE) -C tests test

test-app: $(VENV)
	@$(VENV)/bin/python -m pytest app/tests -q

setup-app: $(VENV)

$(VENV):
	@echo "Création de l'environnement Python…"
	@cd app && uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

build:
	arduino-cli compile --fqbn $(FQBN) $(SKETCH)

flash:
	@test -n "$(PORT)" || { echo "Indiquez le port : make flash PORT=/dev/ttyACM0"; exit 1; }
	arduino-cli upload --fqbn $(FQBN) --port $(PORT) $(SKETCH)

clean:
	@$(MAKE) -C tests clean
	rm -rf $(SKETCH)/build
