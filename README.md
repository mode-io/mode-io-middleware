# modeio-middleware

`modeio-middleware` is a local policy gateway and plugin host for model traffic.

It sits between agent clients and an upstream provider, applies request/response policy hooks, preserves provider-compatible routes, and exposes a stable external plugin contract.

## Why use it

- Put local policy enforcement in front of model traffic without rewriting clients
- Keep an OpenAI-shaped HTTP surface for chat and responses APIs
- Support Claude Code through a native hook connector
- Extend behavior through external `stdio-jsonrpc` plugins instead of patching the core gateway

## Supported clients

- Codex CLI
- Claude Code
- OpenCode
- OpenClaw

## Public surface

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /connectors/claude/hooks`
- `GET /healthz`

## Install

From GitHub:

```bash
python -m pip install git+https://github.com/mode-io/mode-io-middleware
```

From a local checkout:

```bash
python -m pip install .
```

## Quick start

Start the gateway:

```bash
export MODEIO_GATEWAY_UPSTREAM_API_KEY="<your-upstream-key>"

modeio-middleware-gateway \
  --host 127.0.0.1 \
  --port 8787 \
  --upstream-chat-url "https://api.openai.com/v1/chat/completions" \
  --upstream-responses-url "https://api.openai.com/v1/responses"
```

Route supported clients through it:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8787/v1"
modeio-middleware-setup --apply-opencode --create-opencode-config
modeio-middleware-setup --apply-openclaw --create-openclaw-config
modeio-middleware-setup --apply-claude --create-claude-settings
```

Verify health:

```bash
modeio-middleware-setup --health-check --json
curl -s http://127.0.0.1:8787/healthz
```

## Plugin workflow

Scaffold, validate, and conformance-check a public external plugin:

```bash
modeio-middleware-new-plugin my-policy
modeio-middleware-validate-plugin ./plugins_external/my_policy/manifest.json
modeio-middleware-plugin-conformance \
  ./plugins_external/my_policy/manifest.json \
  python3 ./plugins_external/my_policy/plugin.py
```

## Project docs

- Operator guide: `QUICKSTART.md`
- Architecture: `ARCHITECTURE.md`
- External plugin protocol: `MODEIO_PLUGIN_PROTOCOL.md`
- Contributor workflow: `CONTRIBUTING.md`

## Validation

Full repo validation:

```bash
python -m unittest discover tests -p 'test_*.py'
./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke
./scripts/release_check.sh
```

Live routing check against a real upstream:

```bash
./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke
```

Full agent-matrix smoke is available for local or self-hosted environments where Codex, Claude, OpenCode, and OpenClaw CLIs are installed:

```bash
./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke
```

Fresh-install acceptance smoke uses the packaged middleware entrypoints from a temp virtualenv while keeping agent configs in a temp sandbox:

- This fresh-install path assumes `codex`, `opencode`, `openclaw`, and `claude` are already installed and authenticated on the host.
- Only the middleware under test is freshly installed for the run.

```bash
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance
```
