# Contributing

Thanks for contributing to `modeio-middleware`.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . build
```

## Validation

Run the full Python test suite:

```bash
python -m unittest discover tests -p 'test_*.py'
```

Run offline smoke validation and keep artifacts:

```bash
./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke
```

Run packaged-artifact validation:

```bash
./scripts/release_check.sh
```

Run a live gateway check against a real upstream:

```bash
./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke
```

Check whether the current machine is ready for controller-based live acceptance smoke:

```bash
middleware inspect opencode --json
middleware inspect openclaw --json
middleware inspect claude --json
```

Live agent smoke assumes OpenCode/OpenClaw/Claude are already installed and authenticated on the host. Middleware reuses harness-owned auth only and does not provide a managed upstream fallback.
For OpenCode, live smoke covers only redirectable selected providers. Built-in `openai` with ChatGPT OAuth remains outside middleware preserve-provider routing and should show up as unsupported rather than silently passing.

Run the OpenCode/OpenClaw controller matrix only in environments where those CLIs are installed and authenticated:

```bash
./scripts/smoke_e2e.sh --live-openai-agents --artifacts-dir ./.artifacts/live-openai-agent-smoke
```

Run the Claude hook matrix when only Claude integration needs live validation:

```bash
./scripts/smoke_e2e.sh --live-claude --artifacts-dir ./.artifacts/live-claude-smoke
```

OpenClaw setup preserves the active supported provider in place. Unsupported provider families fail clearly instead of switching to middleware-owned auth.

Run the full supported controller matrix only in environments where all supported client CLIs are installed and authenticated:

```bash
./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke
```

Run the fresh-install acceptance variant to exercise packaged middleware entrypoints from a temp virtualenv. This assumes the host already has `opencode`, `openclaw`, and `claude` installed and authenticated:

```bash
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance
```

## Notes

- Public external plugins are scaffolded as `stdio-jsonrpc` plugins.
- Repo-local scripts under `scripts/` are source-checkout conveniences; installed users should prefer the packaged `middleware` controller command plus the plugin utility entrypoints.
- When you are working from a repo-local editable install, prefer `python scripts/middleware.py ...` and other `python scripts/*.py` wrappers instead of installed console entrypoints.
- When editing smoke tooling, keep artifact output machine-readable and avoid provider-specific assumptions in the default path.
