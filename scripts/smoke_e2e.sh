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
run_live_openai_agents=0
run_live_claude=0
live_agents_install_mode="repo"
live_agents_install_target=""
live_agents_keep_sandbox=0
artifacts_root="${MODEIO_SMOKE_ARTIFACTS_DIR:-}"
ARTIFACTS_DIR=""
KEEP_ARTIFACTS=0

python_smoke_status="not_run"
setup_smoke_status="not_run"
openclaw_cli_status="not_run"
offline_gateway_status="not_run"
live_gateway_status="not_run"
live_openai_agent_matrix_status="not_run"
live_claude_agent_matrix_status="not_run"
live_agent_matrix_status="not_run"

usage() {
  cat <<'EOF' >&2
Usage: smoke_e2e.sh [--live] [--live-agents] [--live-openai-agents] [--live-claude] [--install-mode MODE] [--install-target VALUE] [--keep-sandbox] [--artifacts-dir PATH]

  --live                Run a generic live gateway smoke against a real upstream
  --live-agents         Run both live agent paths: OpenAI-compatible clients and Claude hooks
  --live-openai-agents  Run only Codex/OpenCode/OpenClaw live smoke through OpenAI-compatible middleware routes
  --live-claude         Run only Claude hook live smoke (no upstream model provider required)
  --install-mode MODE   Runtime install mode for the middleware under test: repo|wheel|path|git
  --install-target VAL  Optional wheel/path/git target used with --install-mode
  --keep-sandbox        Keep the live-agent temp HOME/XDG sandbox for debugging
  --artifacts-dir PATH  Persist logs and JSON outputs under PATH/<timestamp-pid>/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      run_live=1
      ;;
    --live-agents)
      run_live_openai_agents=1
      run_live_claude=1
      ;;
    --live-openai-agents)
      run_live_openai_agents=1
      ;;
    --live-claude)
      run_live_claude=1
      ;;
    --install-mode)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      live_agents_install_mode="$2"
      shift
      ;;
    --install-target)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      live_agents_install_target="$2"
      shift
      ;;
    --keep-sandbox)
      live_agents_keep_sandbox=1
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

resolve_live_upstream_fields() {
  "$PYTHON_BIN" - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root))

from modeio_middleware.cli.setup_lib.upstream import resolve_live_upstream_selection

selection = resolve_live_upstream_selection()
if not selection.get("ready"):
    raise SystemExit(
        "[smoke] missing reusable live upstream for openai-compatible smoke "
        f"(source={selection.get('source')} base={selection.get('baseUrl')} model={selection.get('model')}). "
        "Set MODEIO_GATEWAY_UPSTREAM_BASE_URL/MODEL with a key, reuse an existing remote OpenCode/OpenClaw config, or set OPENAI_API_KEY."
    )

for key in ("baseUrl", "model", "apiKey", "source", "provider"):
    print(selection.get(key) or "")
PY
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

seed_openclaw_family_state() {
  local config_path="$1"
  local models_cache_path="$2"
  local family="$3"

  local provider=""
  local model=""
  local api=""
  local base_url=""

  case "$family" in
    openai-completions)
      provider="openai"
      model="gpt-4.1"
      api="openai-completions"
      base_url="https://api.openai.com/v1"
      ;;
    anthropic-messages)
      provider="anthropic"
      model="claude-sonnet-4-6"
      api="anthropic-messages"
      base_url="https://api.anthropic.com"
      ;;
    *)
      echo "[smoke] unsupported OpenClaw family seed: $family" >&2
      exit 1
      ;;
  esac

  "$PYTHON_BIN" - "$config_path" "$models_cache_path" "$provider" "$model" "$api" "$base_url" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
models_cache_path = Path(sys.argv[2])
provider = sys.argv[3]
model = sys.argv[4]
api = sys.argv[5]
base_url = sys.argv[6]

provider_payload = {
    "api": api,
    "baseUrl": base_url,
    "models": [{"id": model, "name": f"Smoke {model}"}],
}
config_payload = {
    "agents": {"defaults": {"model": {"primary": f"{provider}/{model}"}}},
    "models": {"providers": {provider: provider_payload}},
}
cache_payload = {
    "models": {"providers": {provider: provider_payload}},
}

config_path.parent.mkdir(parents=True, exist_ok=True)
models_cache_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(config_payload, indent=2) + "\n", encoding="utf-8")
models_cache_path.write_text(json.dumps(cache_payload, indent=2) + "\n", encoding="utf-8")
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
  LIVE_OPENAI_AGENT_MATRIX_STATUS="$live_openai_agent_matrix_status" \
  LIVE_CLAUDE_AGENT_MATRIX_STATUS="$live_claude_agent_matrix_status" \
  LIVE_AGENT_MATRIX_STATUS="$live_agent_matrix_status" \
  LIVE_AGENT_MATRIX_MODE="$live_agents_install_mode" \
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
        "liveOpenAIAgentSmoke": os.environ["LIVE_OPENAI_AGENT_MATRIX_STATUS"],
        "liveClaudeSmoke": os.environ["LIVE_CLAUDE_AGENT_MATRIX_STATUS"],
        "liveAgentMatrixSmoke": os.environ["LIVE_AGENT_MATRIX_STATUS"],
    },
    "liveAgentMatrixMode": os.environ["LIVE_AGENT_MATRIX_MODE"],
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
  local openai_dir="$ARTIFACTS_DIR/openclaw-openai"
  local anthropic_dir="$ARTIFACTS_DIR/openclaw-anthropic"
  local openai_cfg="$openai_dir/openclaw.json"
  local openai_models="$openai_dir/agents/main/agent/models.json"
  local anthropic_cfg="$anthropic_dir/openclaw.json"
  local anthropic_models="$anthropic_dir/agents/main/agent/models.json"
  local openai_setup_json="$ARTIFACTS_DIR/setup-openclaw-openai.json"
  local openai_uninstall_json="$ARTIFACTS_DIR/uninstall-openclaw-openai.json"
  local anthropic_setup_json="$ARTIFACTS_DIR/setup-openclaw-anthropic.json"
  local anthropic_uninstall_json="$ARTIFACTS_DIR/uninstall-openclaw-anthropic.json"
  local opencode_json="$ARTIFACTS_DIR/opencode.json"
  local claude_settings_json="$ARTIFACTS_DIR/claude-settings.json"

  seed_openclaw_family_state "$openai_cfg" "$openai_models" "openai-completions"
  seed_openclaw_family_state "$anthropic_cfg" "$anthropic_models" "anthropic-messages"

  log "running setup/uninstall smoke (temp config paths)"
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-opencode \
      --create-opencode-config \
      --opencode-config-path "$opencode_json" \
      --apply-openclaw \
      --openclaw-config-path "$openai_cfg" \
      --openclaw-models-cache-path "$openai_models" \
      --apply-claude \
      --create-claude-settings \
      --claude-settings-path "$claude_settings_json" \
      >"$openai_setup_json"

    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --uninstall \
      --apply-opencode \
      --opencode-config-path "$opencode_json" \
      --apply-openclaw \
      --openclaw-config-path "$openai_cfg" \
      --openclaw-models-cache-path "$openai_models" \
      --apply-claude \
      --claude-settings-path "$claude_settings_json" \
      >"$openai_uninstall_json"

    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-openclaw \
      --openclaw-config-path "$anthropic_cfg" \
      --openclaw-models-cache-path "$anthropic_models" \
      >"$anthropic_setup_json"

    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --uninstall \
      --apply-openclaw \
      --openclaw-config-path "$anthropic_cfg" \
      --openclaw-models-cache-path "$anthropic_models" \
      >"$anthropic_uninstall_json"
  )

  check_json_field "$openai_setup_json" "payload['success'] is True"
  check_json_field "$openai_setup_json" "payload['opencode']['changed'] is True"
  check_json_field "$openai_setup_json" "payload['openclaw']['changed'] is True"
  check_json_field "$openai_setup_json" "payload['openclaw']['apiFamily'] == 'openai-completions'"
  check_json_field "$openai_setup_json" "payload['claude']['changed'] is True"

  check_json_field "$openai_uninstall_json" "payload['success'] is True"
  check_json_field "$openai_uninstall_json" "payload['opencode']['changed'] is True"
  check_json_field "$openai_uninstall_json" "payload['openclaw']['changed'] is True"
  check_json_field "$openai_uninstall_json" "payload['claude']['changed'] is True"

  check_json_field "$anthropic_setup_json" "payload['success'] is True"
  check_json_field "$anthropic_setup_json" "payload['openclaw']['changed'] is True"
  check_json_field "$anthropic_setup_json" "payload['openclaw']['apiFamily'] == 'anthropic-messages'"

  check_json_field "$anthropic_uninstall_json" "payload['success'] is True"
  check_json_field "$anthropic_uninstall_json" "payload['openclaw']['changed'] is True"
  setup_smoke_status="passed"
}

run_openclaw_cli_smoke() {
  local openai_dir="$ARTIFACTS_DIR/openclaw-cli-openai"
  local anthropic_dir="$ARTIFACTS_DIR/openclaw-cli-anthropic"
  local openai_cfg="$openai_dir/openclaw.json"
  local openai_models_cache="$openai_dir/agents/main/agent/models.json"
  local anthropic_cfg="$anthropic_dir/openclaw.json"
  local anthropic_models_cache="$anthropic_dir/agents/main/agent/models.json"
  local openai_models_json="$ARTIFACTS_DIR/openclaw-openai-models.json"
  local anthropic_models_json="$ARTIFACTS_DIR/openclaw-anthropic-models.json"
  local openai_validate_log="$ARTIFACTS_DIR/openclaw-openai-validate.log"
  local anthropic_validate_log="$ARTIFACTS_DIR/openclaw-anthropic-validate.log"

  seed_openclaw_family_state "$openai_cfg" "$openai_models_cache" "openai-completions"
  seed_openclaw_family_state "$anthropic_cfg" "$anthropic_models_cache" "anthropic-messages"

  log "running OpenClaw config/list smoke using OPENCLAW_CONFIG_PATH=temp"

  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-openclaw \
      --openclaw-config-path "$openai_cfg" \
      --openclaw-models-cache-path "$openai_models_cache" \
      >/dev/null

    OPENCLAW_CONFIG_PATH="$openai_cfg" \
    OPENCLAW_STATE_DIR="$openai_dir" \
    OPENCLAW_AGENT_DIR="$(dirname "$openai_models_cache")" \
    openclaw config validate >"$openai_validate_log"

    OPENCLAW_CONFIG_PATH="$openai_cfg" \
    OPENCLAW_STATE_DIR="$openai_dir" \
    OPENCLAW_AGENT_DIR="$(dirname "$openai_models_cache")" \
    openclaw models list --json >"$openai_models_json"

    "$PYTHON_BIN" scripts/setup_middleware_gateway.py \
      --json \
      --apply-openclaw \
      --openclaw-config-path "$anthropic_cfg" \
      --openclaw-models-cache-path "$anthropic_models_cache" \
      >/dev/null

    OPENCLAW_CONFIG_PATH="$anthropic_cfg" \
    OPENCLAW_STATE_DIR="$anthropic_dir" \
    OPENCLAW_AGENT_DIR="$(dirname "$anthropic_models_cache")" \
    openclaw config validate >"$anthropic_validate_log"

    OPENCLAW_CONFIG_PATH="$anthropic_cfg" \
    OPENCLAW_STATE_DIR="$anthropic_dir" \
    OPENCLAW_AGENT_DIR="$(dirname "$anthropic_models_cache")" \
    openclaw models list --json >"$anthropic_models_json"
  )

  check_json_field "$openai_models_json" "payload['count'] >= 1"
  check_json_field "$openai_models_json" "any(m.get('key') == 'openai/gpt-4.1' for m in payload['models'])"
  check_json_field "$anthropic_models_json" "payload['count'] >= 1"
  check_json_field "$anthropic_models_json" "any(m.get('key') == 'anthropic/claude-sonnet-4-6' for m in payload['models'])"
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
  local resolved_output=""
  local resolved=()
  if ! resolved_output="$(resolve_live_upstream_fields)"; then
    live_gateway_status="failed"
    return 1
  fi
  mapfile -t resolved <<< "$resolved_output"
  local upstream_base_url="${resolved[0]}"
  local upstream_model="${resolved[1]}"
  local upstream_api_key="${resolved[2]}"
  local upstream_source="${resolved[3]}"
  local upstream_provider="${resolved[4]}"
  local stdout_log="$ARTIFACTS_DIR/live-gateway.stdout.log"
  local stderr_log="$ARTIFACTS_DIR/live-gateway.stderr.log"
  local response_headers="$ARTIFACTS_DIR/live-gateway.headers.txt"
  local response_body="$ARTIFACTS_DIR/live-gateway-response.json"
  local http_code=""

  log "running live gateway smoke against real upstream (source=${upstream_source} provider=${upstream_provider})"
  live_gateway_status="failed"

  local rc=0
  (
    cd "$REPO_ROOT"

    MODEIO_GATEWAY_UPSTREAM_API_KEY="$upstream_api_key" \
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

    http_code="$(curl -sS -D "$response_headers" -o "$response_body" -w '%{http_code}' "http://127.0.0.1:${gateway_port}/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${upstream_model}\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with LIVE_CHAT_SMOKE_OK only\"}]}" )"

    if [[ ! "$http_code" =~ ^2 ]]; then
      echo "[smoke] live gateway returned HTTP ${http_code}" >&2
      if [[ -f "$response_body" ]]; then
        echo "[smoke] response body:" >&2
        cat "$response_body" >&2
      fi
      exit 1
    fi

    cleanup_live
    trap - EXIT
  ) || rc=$?

  if [[ "$rc" -ne 0 ]]; then
    return "$rc"
  fi

  live_gateway_status="passed"
}

run_live_agent_matrix_smoke() {
  local agent_subset="$1"
  local artifact_leaf="$2"
  local label="$3"
  local status_var="$4"
  local smoke_args=(
    scripts/smoke_agent_matrix.py
    --agents "$agent_subset"
    --artifacts-dir "$ARTIFACTS_DIR/$artifact_leaf"
    --repo-root "$REPO_ROOT"
    --install-mode "$live_agents_install_mode"
  )

  if [[ -n "${MODEIO_GATEWAY_UPSTREAM_BASE_URL:-}" ]]; then
    smoke_args+=(--upstream-base-url "$MODEIO_GATEWAY_UPSTREAM_BASE_URL")
  fi

  if [[ -n "${MODEIO_GATEWAY_UPSTREAM_MODEL:-}" ]]; then
    smoke_args+=(--model "$MODEIO_GATEWAY_UPSTREAM_MODEL")
  fi

  if [[ -n "$live_agents_install_target" ]]; then
    smoke_args+=(--install-target "$live_agents_install_target")
  fi

  if [[ "$live_agents_keep_sandbox" -eq 1 ]]; then
    smoke_args+=(--keep-sandbox)
  fi

  log "running ${label} (install-mode=${live_agents_install_mode})"
  printf -v "$status_var" '%s' "failed"
  local rc=0
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" "${smoke_args[@]}"
  ) || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    return "$rc"
  fi
  printf -v "$status_var" '%s' "passed"
}

finalize_live_agent_matrix_status() {
  local requested=0
  local all_passed=1

  if [[ "$run_live_openai_agents" -eq 1 ]]; then
    requested=1
    [[ "$live_openai_agent_matrix_status" == "passed" ]] || all_passed=0
  else
    live_openai_agent_matrix_status="skipped"
  fi

  if [[ "$run_live_claude" -eq 1 ]]; then
    requested=1
    [[ "$live_claude_agent_matrix_status" == "passed" ]] || all_passed=0
  else
    live_claude_agent_matrix_status="skipped"
  fi

  if [[ "$requested" -eq 0 ]]; then
    live_agent_matrix_status="skipped"
  elif [[ "$all_passed" -eq 1 ]]; then
    live_agent_matrix_status="passed"
  else
    live_agent_matrix_status="failed"
  fi
}

main() {
  local smoke_failures=0

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
    if ! run_live_gateway_smoke; then
      smoke_failures=1
    fi
  else
    live_gateway_status="skipped"
  fi

  if [[ "$run_live_openai_agents" -eq 1 || "$run_live_claude" -eq 1 ]]; then
    live_agent_matrix_status="failed"
  fi

  if [[ "$run_live_openai_agents" -eq 1 ]]; then
    if ! run_live_agent_matrix_smoke \
      "codex,opencode,openclaw" \
      "live-openai-agent-matrix" \
      "live OpenAI-compatible agent smoke (codex/opencode/openclaw via middleware)" \
      "live_openai_agent_matrix_status"; then
      smoke_failures=1
    fi
  fi

  if [[ "$run_live_claude" -eq 1 ]]; then
    if ! run_live_agent_matrix_smoke \
      "claude" \
      "live-claude-matrix" \
      "live Claude hook smoke" \
      "live_claude_agent_matrix_status"; then
      smoke_failures=1
    fi
  fi

  finalize_live_agent_matrix_status

  if [[ "$smoke_failures" -ne 0 ]]; then
    log "one or more smoke checks failed"
    return 1
  fi

  log "all smoke checks passed"
}

main
