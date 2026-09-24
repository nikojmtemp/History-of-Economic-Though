#!/bin/bash
# Double-click on a Mac to play Stock straight from this folder, without building an app.
# The first run makes a Python environment in .venv-mac; after that it starts at once.
# Close the game's browser tab and this window to stop.
set -e
cd "$(dirname "$0")/.."
if [ ! -x .venv-mac/bin/python ]; then
  python3 -m venv .venv-mac
  .venv-mac/bin/pip install --quiet --upgrade pip
  .venv-mac/bin/pip install --quiet -e .
fi
.venv-mac/bin/python -m stock.launch
