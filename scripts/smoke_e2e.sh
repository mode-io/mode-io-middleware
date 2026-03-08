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

  echo "[smoke] missing required Python interpreter; bootstrap the repo or set PYTHON_BIN" >&2
  exit 1
}

PYTHON_BIN="$(resolve_python_bin)"
if [[ -d "${REPO_ROOT}/.venv/bin" ]]; then
  export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
fi

run_live=0
run_live_agents=0
artifacts_root="${MODEIO_SMOKE_ARTIFACTS_DIR:-}"
ARTIFACTS_DIR=""
KEEP_ARTIFACTS=0

python_smoke_status="not_run"
setup_smoke_status="not_run"
openclaw_cli_status="not_run"
offline_gateway_status="not_run"
live_gateway_status="not_run"
live_agent_matrix_status="not_run"

usage() {
  cat <<'EOF' >&2
Usage: smoke_e2e.sh [--live] [--live-agents] [--artifacts-dir PATH]

  --live                Run a generic live gateway smoke against a real upstream
  --live-agents         Run the full live agent matrix (local/self-hosted only)
  --artifacts-dir PATH  Persist logs and JSON outputs under PATH/<timestamp-pid>/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      run_live=1
      ;;
    --live-agents)
      run_live_agents=1
      ;;
    --artifacts-dir)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      artifacts_root="$2"
      shift
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

log() {
  printf '[smoke] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[smoke] missing required command: $1" >&2
    exit 1
  fi
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

check_json_field() {
  local file="$1"
  local code="$2"
  "$PYTHON_BIN" - "$file" "$code" <<'PY'
import json
import sys

path = sys.argv[1]
expr = sys.argv[2]
payload = json.loads(open(path, encoding="utf-8").read())
if not eval(expr, {"payload": payload}):
    raise SystemExit(f"json assertion failed: {expr}")
PY
}

write_summary() {
  local exit_code="$1"
  local summary_path="${ARTIFACTS_DIR}/summary.json"

  SMOKE_EXIT_CODE="$exit_code" \
  PYTHON_SMOKE_STATUS="$python_smoke_status" \
  SETUP_SMOKE_STATUS="$setup_smoke_status" \
  OPENCLAW_CLI_STATUS="$openclaw_cli_status" \
  OFFLINE_GATEWAY_STATUS="$offline_gateway_status" \
  LIVE_GATEWAY_STATUS="$live_gateway_status" \
  LIVE_AGENT_MATRIX_STATUS="$live_agent_matrix_status" \
  "$PYTHON_BIN" - "$summary_path" <<'PY'
import json
import os
import sys

path = sys.argv[1]
payload = {
    "exitCode": int(os.environ["SMOKE_EXIT_CODE"]),
    "artifactsDir": str(path.rsplit("/summary.json", 1)[0]),
    "steps": {
        "pythonSmoke": os.environ["PYTHON_SMOKE_STATUS"],
        "setupSmoke": os.environ["SETUP_SMOKE_STATUS"],
        "openclawCliSmoke": os.environ["OPENCLAW_CLI_STATUS"],
        "offlineGatewaySmoke": os.environ["OFFLINE_GATEWAY_STATUS"],
        "liveGatewaySmoke": os.environ["LIVE_GATEWAY_STATUS"],
        "liveAgentMatrixSmoke": os.environ["LIVE_AGENT_MATRIX_STATUS"],
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")
PY
}

cleanup() {
  local exit_code=$?
  if [[ -n "$ARTIFACTS_DIR" && "$KEEP_ARTIFACTS" -eq 1 ]]; then
    write_summary "$exit_code" || true
    log "artifacts saved to ${ARTIFACTS_DIR}"
  elif [[ -n "$ARTIFACTS_DIR" ]]; then
    rm -rf "$ARTIFACTS_DIR"
  fi
}
trap cleanup EXIT

init_artifacts_dir() {
  local run_id
  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  if [[ -n "$artifacts_root" ]]; then
    KEEP_ARTIFACTS=1
    mkdir -p "$artifacts_root"
    ARTIFACTS_DIR="$(cd "$artifacts_root" && pwd)/${run_id}"
    mkdir -p "$ARTIFACTS_DIR"
  else
    ARTIFACTS_DIR="$(mktemp -d)"
  fi
}

run_python_smoke_suite() {
  local log_path="$1"
  log "running Python smoke suite"
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" -m unittest discover tests/smoke -p "test_*.py" 2>&1 | tee "$log_path"
  )
  python_smoke_status="passed"
}

run_setup_smoke() {
  local setup_json="$ARTIFACTS_DIR/setup-all.json"
  local uninstall_json="$ARTIFACTS_DIR/uninstall-all.json"

  log "running setup/uninstall smoke (temp config paths)"
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-opencode \
      --create-opencode-config \
      --opencode-config-path "$ARTIFACTS_DIR/opencode.json" \
      --apply-openclaw \
      --create-openclaw-config \
      --openclaw-config-path "$ARTIFACTS_DIR/openclaw.json" \
      --apply-claude \
      --create-claude-settings \
      --claude-settings-path "$ARTIFACTS_DIR/claude-settings.json" \
      >"$setup_json"

    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --uninstall \
      --apply-opencode \
      --opencode-config-path "$ARTIFACTS_DIR/opencode.json" \
      --apply-openclaw \
      --openclaw-config-path "$ARTIFACTS_DIR/openclaw.json" \
      --apply-claude \
      --claude-settings-path "$ARTIFACTS_DIR/claude-settings.json" \
      >"$uninstall_json"
  )

  check_json_field "$setup_json" "payload['success'] is True"
  check_json_field "$setup_json" "payload['opencode']['changed'] is True"
  check_json_field "$setup_json" "payload['openclaw']['changed'] is True"
  check_json_field "$setup_json" "payload['claude']['changed'] is True"

  check_json_field "$uninstall_json" "payload['success'] is True"
  check_json_field "$uninstall_json" "payload['opencode']['changed'] is True"
  check_json_field "$uninstall_json" "payload['openclaw']['changed'] is True"
  check_json_field "$uninstall_json" "payload['claude']['changed'] is True"
  setup_smoke_status="passed"
}

run_openclaw_cli_smoke() {
  local cfg="$ARTIFACTS_DIR/openclaw-cli.json"
  local models_json="$ARTIFACTS_DIR/openclaw-models.json"
  local validate_log="$ARTIFACTS_DIR/openclaw-validate.log"

  log "running OpenClaw config/list smoke using OPENCLAW_CONFIG_PATH=temp"

  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-openclaw \
      --create-openclaw-config \
      --openclaw-config-path "$cfg" \
      >/dev/null

    OPENCLAW_CONFIG_PATH="$cfg" openclaw config validate >"$validate_log"
    OPENCLAW_CONFIG_PATH="$cfg" openclaw models list --json >"$models_json"
  )

  check_json_field "$models_json" "payload['count'] >= 1"
  check_json_field "$models_json" "any(m.get('key') == 'modeio-middleware/middleware-default' for m in payload['models'])"
  openclaw_cli_status="passed"
}

run_offline_gateway_smoke() {
  local output_json="$ARTIFACTS_DIR/offline-gateway-smoke.json"
  log "running offline gateway e2e smoke with mock upstream"

  "$PYTHON_BIN" - "$REPO_ROOT" >"$output_json" <<'PY'
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root))

from modeio_middleware.cli.gateway import create_server
from modeio_middleware.core.engine import GatewayRuntimeConfig
from modeio_middleware.core.profiles import DEFAULT_PROFILE

upstream_calls = []


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        upstream_calls.append(
            {
                "path": self.path,
                "payload": payload,
                "auth": self.headers.get("Authorization"),
                "accept": self.headers.get("Accept"),
            }
        )

        if self.path == "/v1/chat/completions":
            body = json.dumps(
                {
                    "id": "chatcmpl_smoke",
                    "object": "chat.completion",
                    "model": payload.get("model", "gpt-4o-mini"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "pong-chat"},
                        }
                    ],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/v1/responses":
            if payload.get("stream"):
                chunks = [
                    b"event: response.created\\n",
                    b"data: {\"type\":\"response.created\"}\\n\\n",
                    b"event: response.output_text.delta\\n",
                    b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"pong-stream\"}\\n\\n",
                    b"data: [DONE]\\n\\n",
                ]
                total = sum(len(chunk) for chunk in chunks)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(total))
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
                return

            body = json.dumps(
                {
                    "id": "resp_smoke",
                    "object": "response",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "pong-responses"}],
                        }
                    ],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, _fmt, *_args):
        return


def request(host, port, method, path, body=None, headers=None):
    url = f"http://{host}:{port}{path}"
    payload = None
    req_headers = headers or {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json", **req_headers}

    req = urllib.request.Request(url, data=payload, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as error:
        body_data = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"request failed: {method} {path} -> {error.code} {body_data}")


upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
upstream_host, upstream_port = upstream.server_address
upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
upstream_thread.start()

cfg = GatewayRuntimeConfig(
    upstream_chat_completions_url=f"http://{upstream_host}:{upstream_port}/v1/chat/completions",
    upstream_responses_url=f"http://{upstream_host}:{upstream_port}/v1/responses",
    upstream_timeout_seconds=10,
    upstream_api_key_env="MODEIO_GATEWAY_UPSTREAM_API_KEY",
    default_profile=DEFAULT_PROFILE,
    profiles={DEFAULT_PROFILE: {"plugins": []}},
    plugins={},
)

gateway = create_server("127.0.0.1", 0, cfg)
gateway_host, gateway_port = gateway.server_address
gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
gateway_thread.start()

try:
    health_status, _, health_body = request(gateway_host, gateway_port, "GET", "/healthz")

    chat_status, chat_headers, chat_body = request(
        gateway_host,
        gateway_port,
        "POST",
        "/v1/chat/completions",
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "modeio": {"profile": DEFAULT_PROFILE},
        },
        headers={"Authorization": "Bearer smoke-key"},
    )

    resp_status, _, resp_body = request(
        gateway_host,
        gateway_port,
        "POST",
        "/v1/responses",
        {
            "model": "gpt-4o-mini",
            "input": "ping",
            "stream": False,
            "modeio": {"profile": DEFAULT_PROFILE},
        },
        headers={"Authorization": "Bearer smoke-key"},
    )

    stream_status, stream_headers, stream_body = request(
        gateway_host,
        gateway_port,
        "POST",
        "/v1/responses",
        {
            "model": "gpt-4o-mini",
            "input": "ping",
            "stream": True,
            "modeio": {"profile": DEFAULT_PROFILE},
        },
        headers={"Authorization": "Bearer smoke-key"},
    )

    summary = {
        "health": {
            "status": health_status,
            "ok": json.loads(health_body.decode("utf-8")).get("ok"),
        },
        "chat": {
            "status": chat_status,
            "assistant": json.loads(chat_body.decode("utf-8"))["choices"][0]["message"]["content"],
            "contractHeadersPresent": all(
                key in {k.lower(): v for k, v in chat_headers.items()}
                for key in [
                    "x-modeio-contract-version",
                    "x-modeio-request-id",
                    "x-modeio-profile",
                    "x-modeio-upstream-called",
                ]
            ),
        },
        "responses": {
            "status": resp_status,
            "assistant": json.loads(resp_body.decode("utf-8"))["output"][0]["content"][0]["text"],
        },
        "responsesStream": {
            "status": stream_status,
            "streamHeader": stream_headers.get("x-modeio-streaming"),
            "containsDone": "[DONE]" in stream_body.decode("utf-8", errors="replace"),
        },
        "upstreamCalls": {
            "count": len(upstream_calls),
            "paths": [call["path"] for call in upstream_calls],
            "authForwardedAll": all(call["auth"] == "Bearer smoke-key" for call in upstream_calls),
            "acceptForStream": upstream_calls[-1]["accept"] if upstream_calls else None,
        },
    }
    print(json.dumps(summary))
finally:
    gateway.shutdown()
    gateway.server_close()
    upstream.shutdown()
    upstream.server_close()
    gateway_thread.join(timeout=2)
    upstream_thread.join(timeout=2)
PY

  check_json_field "$output_json" "payload['health']['status'] == 200 and payload['health']['ok'] is True"
  check_json_field "$output_json" "payload['chat']['status'] == 200 and payload['chat']['assistant'] == 'pong-chat'"
  check_json_field "$output_json" "payload['chat']['contractHeadersPresent'] is True"
  check_json_field "$output_json" "payload['responses']['status'] == 200 and payload['responses']['assistant'] == 'pong-responses'"
  check_json_field "$output_json" "payload['responsesStream']['status'] == 200"
  check_json_field "$output_json" "payload['responsesStream']['streamHeader'] == 'true'"
  check_json_field "$output_json" "payload['responsesStream']['containsDone'] is True"
  check_json_field "$output_json" "payload['upstreamCalls']['count'] == 3"
  check_json_field "$output_json" "payload['upstreamCalls']['paths'] == ['/v1/chat/completions', '/v1/responses', '/v1/responses']"
  check_json_field "$output_json" "payload['upstreamCalls']['authForwardedAll'] is True"
  offline_gateway_status="passed"
}

run_live_gateway_smoke() {
  local gateway_port=18787
  local upstream_base_url="${MODEIO_GATEWAY_UPSTREAM_BASE_URL:-https://api.openai.com/v1}"
  local upstream_model="${MODEIO_GATEWAY_UPSTREAM_MODEL:-gpt-4o-mini}"
  local stdout_log="$ARTIFACTS_DIR/live-gateway.stdout.log"
  local stderr_log="$ARTIFACTS_DIR/live-gateway.stderr.log"

  if [[ -z "${MODEIO_GATEWAY_UPSTREAM_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "[smoke] --live requires MODEIO_GATEWAY_UPSTREAM_API_KEY or OPENAI_API_KEY" >&2
    exit 1
  fi

  log "running live gateway smoke against real upstream"

  (
    cd "$REPO_ROOT"

    "$PYTHON_BIN" scripts/middleware_gateway.py \
      --host 127.0.0.1 \
      --port "$gateway_port" \
      --upstream-chat-url "${upstream_base_url%/}/chat/completions" \
      --upstream-responses-url "${upstream_base_url%/}/responses" \
      >"$stdout_log" \
      2>"$stderr_log" &
    local gateway_pid=$!

    cleanup_live() {
      kill "$gateway_pid" >/dev/null 2>&1 || true
      wait "$gateway_pid" >/dev/null 2>&1 || true
    }
    trap cleanup_live EXIT

    for _ in {1..30}; do
      if curl -s "http://127.0.0.1:${gateway_port}/healthz" >/dev/null 2>&1; then
        break
      fi
      sleep 0.3
    done

    curl -sSf "http://127.0.0.1:${gateway_port}/healthz" >/dev/null

    curl -sSf "http://127.0.0.1:${gateway_port}/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${upstream_model}\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with LIVE_CHAT_SMOKE_OK only\"}]}" \
      >"$ARTIFACTS_DIR/live-gateway-response.json"

    cleanup_live
    trap - EXIT
  )

  live_gateway_status="passed"
}

run_live_agent_matrix_smoke() {
  if [[ -z "${MODEIO_GATEWAY_UPSTREAM_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "[smoke] --live-agents requires MODEIO_GATEWAY_UPSTREAM_API_KEY or OPENAI_API_KEY" >&2
    exit 1
  fi

  log "running live agent matrix smoke (codex/opencode/openclaw/claude via middleware)"
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/smoke_agent_matrix.py --artifacts-dir "$ARTIFACTS_DIR/live-agent-matrix"
  )
  live_agent_matrix_status="passed"
}

main() {
  require_cmd mktemp
  require_cmd curl
  require_cmd tee

  init_artifacts_dir

  run_python_smoke_suite "$ARTIFACTS_DIR/python-smoke.log"
  run_setup_smoke
  if have_cmd openclaw; then
    run_openclaw_cli_smoke
  else
    openclaw_cli_status="skipped"
    log "skipping OpenClaw CLI smoke because 'openclaw' is not installed"
  fi
  run_offline_gateway_smoke

  if [[ "$run_live" -eq 1 ]]; then
    run_live_gateway_smoke
  else
    live_gateway_status="skipped"
  fi

  if [[ "$run_live_agents" -eq 1 ]]; then
    run_live_agent_matrix_smoke
  else
    live_agent_matrix_status="skipped"
  fi

  log "all smoke checks passed"
}

main
