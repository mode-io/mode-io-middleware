#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASHBOARD_DIR="$REPO_ROOT/dashboard"

if [ ! -d "$DASHBOARD_DIR" ]; then
  echo "dashboard source directory is missing" >&2
  exit 1
fi

if [ -f "$DASHBOARD_DIR/package-lock.json" ]; then
  npm --prefix "$DASHBOARD_DIR" ci
else
  npm --prefix "$DASHBOARD_DIR" install
fi

npm --prefix "$DASHBOARD_DIR" run build
