# modeio-middleware Quickstart

This guide covers the normal operator workflow first, then source-checkout contributor notes at the end.

## 1) Install

From GitHub:

```bash
python -m pip install git+https://github.com/mode-io/mode-io-middleware
```

From a local checkout:

```bash
python -m pip install .
```

Optional source-checkout environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . build
```

## 2) Start the gateway

The bundled default config starts with no active plugins enabled.

```bash
export MODEIO_GATEWAY_UPSTREAM_API_KEY="<your-upstream-key>"

modeio-middleware-gateway \
  --host 127.0.0.1 \
  --port 8787 \
  --upstream-chat-url "https://api.openai.com/v1/chat/completions" \
  --upstream-responses-url "https://api.openai.com/v1/responses"
```

### Source-checkout maintainer flow

If you are working from the repo and want a deterministic local runtime, use the maintainer wrapper instead:

```bash
python scripts/dev_gateway.py --fresh
```

What it does:

- stores config and discovered plugins under `./.modeio-dev/`
- keeps traces ephemeral because the request journal is still in-memory
- avoids accidental reuse of `~/.config/modeio`
- serves the canonical review URL at `http://127.0.0.1:8787/modeio/dashboard`

Useful maintainer commands:

```bash
python scripts/dev_gateway.py status
python scripts/dev_gateway.py reset
python scripts/dev_gateway.py --build-dashboard
```

## 3) Configure local client routing

### Codex CLI

```bash
modeio-middleware-setup --health-check --json
export OPENAI_BASE_URL="http://127.0.0.1:8787/v1"
```

### OpenCode

```bash
modeio-middleware-setup \
  --apply-opencode \
  --create-opencode-config
```

### OpenClaw

```bash
modeio-middleware-setup \
  --apply-openclaw \
  --create-openclaw-config
```

### Claude Code

```bash
modeio-middleware-setup \
  --apply-claude \
  --create-claude-settings
```

This writes `~/.claude/settings.json` hook entries for `UserPromptSubmit` and `Stop`
to `POST http://127.0.0.1:8787/connectors/claude/hooks`.

## 4) Verify the gateway

```bash
curl -s http://127.0.0.1:8787/healthz
```

Expected shape:

```json
{
  "ok": true,
  "service": "modeio-middleware",
  "version": "0.1.0"
}
```

## 5) Send one request through middleware

```bash
curl -i http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "hello"}
    ],
    "modeio": {
      "profile": "dev"
    }
  }'
```

Check these middleware headers in the response:

- `x-modeio-request-id`
- `x-modeio-profile`
- `x-modeio-pre-actions`
- `x-modeio-post-actions`
- `x-modeio-degraded`

## 6) Author or validate an external plugin

Public external plugins use `stdio-jsonrpc`.

```bash
mkdir my-plugin-work
cd my-plugin-work
modeio-middleware-new-plugin my-policy
```

Generated files:

- `./plugins_external/my_policy/plugin.py`
- `./plugins_external/my_policy/manifest.json`
- `./tests/test_protocol_plugin_my_policy.py`

Validate and run conformance:

```bash
modeio-middleware-validate-plugin ./plugins_external/my_policy/manifest.json
modeio-middleware-plugin-conformance \
  ./plugins_external/my_policy/manifest.json \
  python3 ./plugins_external/my_policy/plugin.py
```

The bundled default config also ships with a disabled external example plugin. If you copy the config file elsewhere, update any relative `manifest` and local-file `command` paths.

## 7) Use a custom config

```bash
modeio-middleware-gateway --config /path/to/middleware.json
```

Path resolution rules:

- `manifest` paths are resolved relative to the config file.
- `command` arguments that point at existing local files are also resolved relative to the config file.

## 8) Uninstall or roll back local routing

```bash
modeio-middleware-setup \
  --uninstall \
  --apply-opencode \
  --apply-openclaw \
  --apply-claude
```

## 9) Contributor validation

```bash
# Optional readiness check before live smoke
modeio-middleware-setup --doctor --json \
  --require-commands codex,opencode,openclaw,claude \
  --require-upstream-api-key

# Full Python test suite
python -m unittest discover tests -p 'test_*.py'

# Offline smoke + saved artifacts
./scripts/smoke_e2e.sh

# Offline smoke with a fixed artifact directory
./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke

# Live upstream traversal check
./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke

# Full Codex/OpenCode/OpenClaw/Claude matrix (local or self-hosted only)
./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke

# Fresh-install acceptance path for the middleware only (client CLIs stay host-installed)
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance

# Build artifact validation
./scripts/release_check.sh
```

If you are working from a source checkout and want the repo-local helper equivalents, use:

```bash
python scripts/dev_gateway.py
python scripts/setup_middleware_gateway.py --health-check
```

For live frontend editing against the same middleware state:

```bash
cd dashboard
npm run dev
```

The Vite server stays on `127.0.0.1:4173` and proxies middleware APIs to `127.0.0.1:8787` by default. Set `MODEIO_DASHBOARD_PROXY_TARGET` if you need a different gateway target.
