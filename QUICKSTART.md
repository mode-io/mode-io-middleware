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

## 2) Inspect current harness state

Middleware assumes your harness is already working. It does not log you in, pick a provider, or pick a model for you.

```bash
middleware inspect opencode --json
middleware inspect openclaw --json
middleware inspect claude --json
```

### Source-checkout maintainer flow

If you are working from the repo and want a deterministic local runtime, use the repo wrapper instead:

```bash
python scripts/middleware.py inspect opencode --json
```

## 3) Enable supported harnesses

### OpenCode

```bash
middleware enable opencode
```

This works for redirectable OpenCode providers. If the active provider is unsupported, `middleware enable opencode` fails clearly and leaves the harness unchanged.

### OpenClaw

```bash
middleware enable openclaw
```

### Claude Code

```bash
middleware enable claude
```

This writes the Claude hook entries to the current middleware server.

## 4) Verify the gateway

```bash
middleware status --json
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
middleware status --config /path/to/middleware.json --json
```

The controller stores `controller.json`, `controller.pid`, and `controller.log` beside the selected middleware config.

Path resolution rules for plugin manifests and relative command paths still follow the config location:

- `manifest` paths are resolved relative to the config file.
- `command` arguments that point at existing local files are also resolved relative to the config file.

## 8) Uninstall or roll back local routing

```bash
middleware disable openclaw
middleware disable --all
```

## 9) Contributor validation

```bash
# Optional readiness check before live smoke
middleware inspect opencode --json
middleware inspect openclaw --json
middleware inspect claude --json

# Full Python test suite
python -m unittest discover tests -p 'test_*.py'

# Offline smoke + saved artifacts
./scripts/smoke_e2e.sh

# Offline smoke with a fixed artifact directory
./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke

# Live upstream traversal check
./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke

# Supported controller matrix for OpenCode/OpenClaw
./scripts/smoke_e2e.sh --live-openai-agents --artifacts-dir ./.artifacts/live-openai-agent-smoke

# Claude-only hook matrix (no separate OpenAI-compatible upstream required)
./scripts/smoke_e2e.sh --live-claude --artifacts-dir ./.artifacts/live-claude-smoke

# Full supported controller matrix
./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke

# Fresh-install acceptance path for the middleware only (client CLIs stay host-installed)
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance

# Build artifact validation
./scripts/release_check.sh
```

OpenClaw setup preserves the active supported provider in place. Unsupported provider families fail clearly instead of switching to middleware-owned auth.

If you are working from a source checkout and want the repo-local helper equivalents, use:

```bash
python scripts/middleware.py status --json
```

For live frontend editing against the same middleware state:

```bash
cd dashboard
npm run dev
```

The Vite server stays on `127.0.0.1:4173` and proxies middleware APIs to `127.0.0.1:8787` by default. Set `MODEIO_DASHBOARD_PROXY_TARGET` if you need a different gateway target.
