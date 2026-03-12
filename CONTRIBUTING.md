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

Run packaged-artifact validation:

```bash
./scripts/release_check.sh
```

Live operator smoke now lives in the external `middleware-api-smoke` skill in the local workflow repo.

Check whether the current machine is ready for controller-based operator smoke:

```bash
middleware inspect opencode --json
middleware inspect openclaw --json
middleware inspect claude --json
```

Live operator smoke assumes OpenCode/OpenClaw/Claude are already installed and authenticated on the host. Middleware reuses harness-owned auth only and does not provide a managed upstream fallback.
For OpenCode, live smoke covers only redirectable selected providers. Built-in `openai` with ChatGPT OAuth remains outside middleware preserve-provider routing and should show up as unsupported rather than silently passing.

OpenClaw setup preserves the active supported provider in place. Unsupported provider families fail clearly instead of switching to middleware-owned auth.

## Notes

- Public external plugins are scaffolded as `stdio-jsonrpc` plugins.
- Repo-local scripts under `scripts/` are source-checkout conveniences; installed users should prefer the packaged `middleware` controller command plus the plugin utility entrypoints.
- When you are working from a repo-local editable install, prefer `python scripts/middleware.py ...` and other `python scripts/*.py` wrappers instead of installed console entrypoints.
- Operator smoke tooling is intentionally external to this repo and owned by the external `middleware-api-smoke` workflow skill.
