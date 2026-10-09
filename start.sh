#!/usr/bin/env bash
# Install dependencies (first run only) and serve the API.
#   ./start.sh            -> listens on 0.0.0.0:8000
#   PORT=5000 ./start.sh  -> listens on 0.0.0.0:5000
# Tries, in order: a local .venv, a --user pip install, and finally Flask's built-in server.
set -uo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-4}"
export PORT

PY=python3
if [ ! -x .venv/bin/python ]; then
  rm -rf .venv
  if python3 -m venv .venv >/dev/null 2>&1 && [ -x .venv/bin/pip ]; then
    .venv/bin/pip install -q --upgrade pip
  else
    rm -rf .venv
    echo "[start] python3-venv not available, falling back to pip --user"
  fi
fi

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
  .venv/bin/pip install -q -r requirements.txt
elif ! $PY -c "import flask, gunicorn" 2>/dev/null; then
  $PY -m pip install -q --user -r requirements.txt 2>/dev/null \
    || $PY -m pip install -q --user --break-system-packages -r requirements.txt 2>/dev/null \
    || echo "[start] pip install failed"
fi

if $PY -c "import gunicorn" 2>/dev/null; then
  echo "[start] gunicorn on 0.0.0.0:${PORT} (${WORKERS} workers)"
  exec $PY -m gunicorn app:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
fi

if $PY -c "import flask" 2>/dev/null; then
  echo "[start] gunicorn missing, using Flask server on 0.0.0.0:${PORT}"
  exec $PY app.py
fi

echo "[start] Flask is not installed and could not be installed. Try:"
echo "        sudo apt install -y python3-pip python3-venv   (then re-run ./start.sh)"
exit 1
