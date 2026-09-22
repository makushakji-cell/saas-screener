#!/bin/bash
# Double-click this to start the screener and open it in your browser.
# Closing this window, or pressing Ctrl-C in it, stops the server.

PROJECT="$HOME/saas-screener"
PORT=8899
URL="http://127.0.0.1:$PORT"

cd "$PROJECT" 2>/dev/null || {
  echo "Could not find the project at $PROJECT"
  echo "If you moved it, edit PROJECT at the top of this file."
  echo; read -n 1 -s -r -p "Press any key to close."; exit 1
}

# Already serving? Then there is nothing to start -- just show it. This is the
# case behind the "Address already in use" error if you start it twice.
if curl -s -o /dev/null -m 3 "$URL"; then
  echo "Already running. Opening it now."
  open "$URL"
  echo; read -n 1 -s -r -p "Press any key to close this window (the screener keeps running)."
  exit 0
fi

# First run on a new machine, or after the virtual environment was deleted.
if [ ! -x .venv/bin/python ]; then
  echo "Setting up for the first time. This takes a minute..."
  python3 -m venv .venv \
    && ./.venv/bin/pip install --quiet --upgrade pip \
    && ./.venv/bin/pip install --quiet -r requirements.txt \
    || { echo "Setup failed."; read -n 1 -s -r -p "Press any key to close."; exit 1; }
fi

# The database is a rebuildable artefact, so it may simply be absent.
if [ ! -f data/screener.db ]; then
  echo "No data yet. Fetching it -- about 40 seconds..."
  ./.venv/bin/python -m saasscreener.build 2>&1 | grep -vi "urllib3\|warnings.warn"
fi

echo "Starting the screener..."
./.venv/bin/python -m saasscreener.server 2>&1 | grep -vi "urllib3\|warnings.warn" &
SERVER_PID=$!

# Wait for it to actually answer before opening the browser, otherwise the tab
# loads an error page and needs a manual reload.
for _ in $(seq 1 40); do
  sleep 0.5
  curl -s -o /dev/null -m 2 "$URL" && break
done

if curl -s -o /dev/null -m 3 "$URL"; then
  open "$URL"
  echo
  echo "  Screener is open at $URL"
  echo "  Leave this window open. Ctrl-C or closing it stops the server."
  echo
else
  echo
  echo "  The server did not start. Scroll up for the reason."
  echo
fi

wait $SERVER_PID
