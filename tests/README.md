# Middleware Test Suite

This suite is physically split by confidence layer:

- `tests/unit/`
- `tests/integration/`
- `tests/smoke/`

Additional validation layers live outside `unittest discover` entrypoints:

- `./scripts/release_check.sh` for built-artifact and packaged-resource validation
- `./scripts/smoke_e2e.sh --live`, `--live-openai-agents`, `--live-claude`, or `--live-agents` for manual or nightly live-routing validation (with native client auth preferred over middleware-owned upstream keys)
- `modeio-middleware-setup --doctor --json ...` for machine-readable local readiness checks before live acceptance

## Support Layer

- `helpers/gateway_harness.py`
  - shared upstream/gateway harness plus reusable HTTP request helpers
- `helpers/plugin_modules.py`
  - dynamic plugin-module registration for in-process test plugins
- `fixtures/`
  - reusable stdio protocol plugin fixtures

## Unit-Style Coverage

These tests should pin one module or one narrow contract at a time:

- `unit/test_config_resolver.py`
- `unit/test_http_transport.py`
- `unit/test_new_plugin_cli.py`
- `unit/test_packaging_resources.py`
- `unit/test_plugin_manager.py`
- `unit/test_plugin_overrides_validation.py`
- `unit/test_profile_policy.py`
- `unit/test_protocol_manifest.py`
- `unit/test_protocol_registry.py`
- `unit/test_redact_utils.py`
- `unit/test_runtime_manager.py`
- `unit/test_setup_gateway.py`
- `unit/test_sse.py`
- `unit/test_stdio_supervisor.py`
- `unit/test_upstream_client.py`

## Integration Coverage

These tests exercise multiple middleware layers together:

- `integration/test_gateway_contract.py`
- `integration/test_claude_hook_connector.py`
- `integration/test_protocol_stdio_runtime.py`

## Smoke Coverage

These tests validate operator flows and repo tooling:

- `smoke/test_protocol_example_plugin.py`
- `smoke/test_smoke_agent_matrix_support.py`
- `smoke/test_smoke_opencode_flow.py`

The shell smoke entrypoint can also persist logs and JSON outputs with `--artifacts-dir`.

## Release Coverage

These checks validate the built wheel/sdist instead of only the repo checkout:

- build artifacts from `pyproject.toml`
- install into a fresh virtualenv
- verify bundled config, schemas, and example plugin resources
- run installed console entrypoints and plugin conformance against the bundled example

## Live Coverage

These checks are not required on every PR because they depend on external CLIs, local auth state, and a real upstream:

- `./scripts/smoke_e2e.sh --live --artifacts-dir ./.artifacts/live-smoke`
- `./scripts/smoke_e2e.sh --live-openai-agents --artifacts-dir ./.artifacts/live-openai-agent-smoke`
- `./scripts/smoke_e2e.sh --live-claude --artifacts-dir ./.artifacts/live-claude-smoke`
- `./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-smoke`
- `./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-acceptance`

## Rules

- Prefer adding direct unit tests before expanding large gateway happy-path files.
- Reuse helpers from `tests/helpers/` instead of adding inline HTTP clients or plugin registration code.
- Add new black-box gateway tests only when the behavior truly crosses module boundaries.
