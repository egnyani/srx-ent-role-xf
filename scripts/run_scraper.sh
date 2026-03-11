#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"
LOG_DIR="${LOG_DIR:-$REPO_DIR/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/scraper.log}"
LOCK_FILE="${LOCK_FILE:-$REPO_DIR/.scraper.lock}"

mkdir -p "$LOG_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python not found at $PYTHON_BIN" >&2
  echo "Create a virtualenv first: python3 -m venv $VENV_DIR" >&2
  exit 1
fi

cd "$REPO_DIR"

{
  if ! flock -n 9; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Skipping scraper run: previous run still active"
    exit 0
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Starting scraper"
  "$PYTHON_BIN" main.py --notify-email --max-age-hours 0 --concurrency 10
  echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Scraper finished"
} 9>"$LOCK_FILE" >> "$LOG_FILE" 2>&1
