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
export MODEIO_GATEWAY_UPSTREAM_API_KEY="<your-upstream-key>"
./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke
```

Check whether the current machine is ready for live acceptance smoke:

```bash
modeio-middleware-setup --doctor --json \
  --require-commands codex,opencode,openclaw,claude \
  --require-upstream-api-key
```

Run the full agent matrix only in environments where all client CLIs are installed and authenticated:

```bash
./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke
```

Run the fresh-install acceptance variant to exercise packaged middleware entrypoints from a temp virtualenv. This assumes the host already has `codex`, `opencode`, `openclaw`, and `claude` installed and authenticated:

```bash
./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance
```

## Notes

- Public external plugins are scaffolded as `stdio-jsonrpc` plugins.
- Repo-local scripts under `scripts/` are source-checkout conveniences; installed users should prefer the packaged `modeio-middleware-*` console entrypoints.
- When editing smoke tooling, keep artifact output machine-readable and avoid provider-specific assumptions in the default path.
