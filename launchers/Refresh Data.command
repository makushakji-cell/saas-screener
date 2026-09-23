#!/bin/bash
# Double-click to pull fresh prices, filings and analyst ratings.
# Also records a dated snapshot of today's ratings, which is what makes
# `query track` able to tell you later whether the ratings were any good.
# Worth running about once a week.

# Resolve the project: if this script sits inside it (launchers/), use that.
# Otherwise fall back to the usual location -- the Desktop copies land here.
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -d "$HERE/../saasscreener" ]; then
  PROJECT="$(cd "$HERE/.." && pwd)"
elif [ -d "$HERE/saasscreener" ]; then
  PROJECT="$HERE"
else
  PROJECT="$HOME/saas-screener"
fi
cd "$PROJECT" 2>/dev/null || {
  echo "Could not find the project at $PROJECT"
  echo; read -n 1 -s -r -p "Press any key to close."; exit 1
}

if [ ! -x .venv/bin/python ]; then
  echo "Run 'Open Screener' first -- it sets things up."
  echo; read -n 1 -s -r -p "Press any key to close."; exit 1
fi

echo "Refreshing from SEC EDGAR and Yahoo Finance. About 40 seconds."
echo
./.venv/bin/python -m saasscreener.build 2>&1 | grep -vi "urllib3\|warnings.warn"
echo
./.venv/bin/python -m saasscreener.query check 2>&1 | grep -vi "urllib3\|warnings.warn"
echo
echo "Done. If the screener is open in your browser, reload the page."
echo
read -n 1 -s -r -p "Press any key to close."
