#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return
  fi

  if [[ -x "${REPO_VENV_PYTHON}" ]]; then
    printf '%s\n' "${REPO_VENV_PYTHON}"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  echo "[release-check] missing required Python interpreter; bootstrap the repo or set PYTHON_BIN" >&2
  exit 1
}

PYTHON_BIN="$(resolve_python_bin)"
TMPDIR_RELEASE="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_RELEASE}"' EXIT

log() {
  printf '[release-check] %s\n' "$*"
}

assert_file_exists() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[release-check] expected file missing: $path" >&2
    exit 1
  fi
}

cd "$REPO_ROOT"

log "building sdist and wheel"
rm -rf dist build *.egg-info
"$PYTHON_BIN" -m build

WHEEL_PATH="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path
dist = Path('dist')
wheels = sorted(dist.glob('*.whl'))
if not wheels:
    raise SystemExit('missing built wheel in dist/')
print(wheels[-1])
PY
)"

VENV_DIR="${TMPDIR_RELEASE}/venv"
"$PYTHON_BIN" -m venv "$VENV_DIR"
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_BIN="${VENV_DIR}/bin"

log "installing built wheel into clean virtualenv"
"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
"$VENV_PYTHON" -m pip install "$WHEEL_PATH" >/dev/null

readarray -t RESOURCE_PATHS < <("$VENV_PYTHON" - <<'PY'
from modeio_middleware.resources import (
    bundled_default_config_path,
    bundled_example_plugin_dir,
    bundled_protocol_schema_dir,
)

print(bundled_default_config_path())
print(bundled_example_plugin_dir() / 'manifest.json')
print(bundled_example_plugin_dir() / 'plugin.py')
print(bundled_protocol_schema_dir() / 'MODEIO_PLUGIN_MANIFEST.schema.json')
print(bundled_protocol_schema_dir() / 'MODEIO_PLUGIN_MESSAGE.schema.json')
PY
)

for path in "${RESOURCE_PATHS[@]}"; do
  assert_file_exists "$path"
done

MANIFEST_PATH="${RESOURCE_PATHS[1]}"
PLUGIN_PATH="${RESOURCE_PATHS[2]}"

log "checking installed console entrypoints"
PATH="${VENV_BIN}:${PATH}" middleware --help >/dev/null
PATH="${VENV_BIN}:${PATH}" middleware inspect --json >/dev/null
PATH="${VENV_BIN}:${PATH}" middleware status --json >/dev/null
PATH="${VENV_BIN}:${PATH}" modeio-middleware-new-plugin --help >/dev/null
if PATH="${VENV_BIN}:${PATH}" command -v modeio-middleware-gateway >/dev/null 2>&1; then
  echo "[release-check] unexpected legacy gateway entrypoint is still installed" >&2
  exit 1
fi
if PATH="${VENV_BIN}:${PATH}" command -v modeio-middleware-setup >/dev/null 2>&1; then
  echo "[release-check] unexpected legacy setup entrypoint is still installed" >&2
  exit 1
fi

log "validating bundled example plugin"
PATH="${VENV_BIN}:${PATH}" modeio-middleware-validate-plugin "$MANIFEST_PATH" >/dev/null
PATH="${VENV_BIN}:${PATH}" modeio-middleware-plugin-conformance "$MANIFEST_PATH" "$VENV_PYTHON" "$PLUGIN_PATH" >/dev/null

log "release checks passed"
