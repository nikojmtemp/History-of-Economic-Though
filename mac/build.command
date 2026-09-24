#!/bin/bash
# Double-click on a Mac to build Stock.app and Stock.dmg (in the project's dist/ folder).
# The first run makes a Python environment in .venv-mac and installs what the build needs.
set -e
cd "$(dirname "$0")/.."
if [ ! -x .venv-mac/bin/python ]; then
  python3 -m venv .venv-mac
  .venv-mac/bin/pip install --quiet --upgrade pip
  .venv-mac/bin/pip install --quiet -e ".[exe]"
fi
.venv-mac/bin/python mac/build_mac.py
open dist
