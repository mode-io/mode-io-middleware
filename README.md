# modeio-middleware

`modeio-middleware` is a local AI gateway for policy, plugins, and live observability.

Put it between agent clients and your upstream model provider to inspect traffic, enforce local policy, run external plugins, and open a built-in monitoring dashboard without rewriting the clients your team already uses.

![ModeIO Monitor dashboard](.github/assets/monitor-dashboard.png)

Built-in monitor with live traces, filters, before/after payload inspection, hook activity, and operator-friendly detail views.

## Why teams use it

- Drop in a local control layer in front of model traffic without changing client workflows
- Keep provider-compatible routes for chat and responses APIs
- See what the middleware actually did through a built-in browser dashboard
- Support Claude Code with a native hook connector
- Extend behavior with external `stdio-jsonrpc` plugins instead of patching core code
- Run locally for demos, operator workflows, safety experiments, and team rollouts

## What you get

- `OpenAI-compatible gateway`: route supported clients through a familiar `/v1` surface
- `Built-in observability`: inspect live traces, before/after payloads, block events, errors, and hook activity in the browser
- `Plugin platform`: author, validate, and conformance-test external plugins with a stable contract
- `Local-first operations`: keep policy logic and monitoring close to where the agents run

## Supported clients

- Codex CLI
- Claude Code
- OpenCode
- OpenClaw

## Public surface

Traffic routes:

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /connectors/claude/hooks`

Monitoring and ops routes:

- `GET /healthz`
- `GET /modeio/dashboard`
- `GET /modeio/api/events`
- `GET /modeio/api/events/{request_id}`
- `GET /modeio/api/stats`
- `GET /modeio/api/events/live`

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

1. Start the gateway:

```bash
export MODEIO_GATEWAY_UPSTREAM_API_KEY="<your-upstream-key>"

modeio-middleware-gateway \
  --host 127.0.0.1 \
  --port 8787 \
  --upstream-chat-url "https://api.openai.com/v1/chat/completions" \
  --upstream-responses-url "https://api.openai.com/v1/responses"
```

2. Route supported clients through it:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8787/v1"
modeio-middleware-setup --apply-opencode --create-opencode-config
modeio-middleware-setup --apply-openclaw --create-openclaw-config
modeio-middleware-setup --apply-claude --create-claude-settings
```

3. Verify health and open the dashboard:

```bash
modeio-middleware-setup --health-check --json
curl -s http://127.0.0.1:8787/healthz
open http://127.0.0.1:8787/modeio/dashboard
```

4. Send one request through the middleware:

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

The dashboard will update as traces arrive. If there is no live traffic yet, it shows example traces so the UI is still explorable for demos and onboarding.

## Monitoring dashboard

The dashboard is served directly by the gateway at `http://127.0.0.1:8787/modeio/dashboard`.

It is designed for both day-to-day operators and product demos. Out of the box you can:

- watch the live request stream in a browser
- inspect request and response bodies before and after middleware processing
- see block, error, and latency stats at a glance
- review hook and plugin activity per request
- filter traces by status, source, and endpoint
- switch between English and Chinese, plus day and night themes

If you want raw data or to wire your own tooling around it, use the monitoring APIs under `/modeio/api/*`.

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

- This path assumes `codex`, `opencode`, `openclaw`, and `claude` are already installed and authenticated on the host.
- Only the middleware under test is freshly installed for the run.

```bash
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance
```
