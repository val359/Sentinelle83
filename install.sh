#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
mkdir -p data logs
echo "Installation terminée."
echo "Test : source .venv/bin/activate && python main.py --test-alert"
echo "Lancement : source .venv/bin/activate && python main.py"
