#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Python 3.11 ou plus recent est necessaire." >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
# Les bibliothèques sont mises à jour quand requirements.txt change (correctifs de sécurité).
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  if .venv/bin/python -m pip install -r requirements.txt; then
    cp requirements.txt .venv/installed-requirements.txt
  else
    echo "Mise à jour des bibliothèques impossible pour l'instant, lancement avec les versions installées." >&2
  fi
fi
# Une installation interrompue est reprise au lancement suivant.
if ! .venv/bin/python -c "import PySide6, PIL" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi
.venv/bin/python main.py
