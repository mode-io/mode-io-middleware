# modeio-middleware Architecture

## Goal

Provide a local middleware layer around an already-working harness/provider path:

- keep the harness in charge of auth, provider choice, model choice, and user workflow
- normalize request and response payloads into a semantic plugin surface
- allow plugins to observe, warn, modify, or block at the semantic layer
- denormalize accepted rewrites back into the provider-native or harness-native contract
- record observability around both directions of the flow

Core runtime remains generic and plugin-based.

## Layout

```text
repo-root/
  .github/workflows/
    ci.yml
  config/default.json
  CONTRIBUTING.md
  MODEIO_PLUGIN_PROTOCOL.md
  MODEIO_PLUGIN_MANIFEST.schema.json
  MODEIO_PLUGIN_MESSAGE.schema.json
  QUICKSTART.md
  README.md
  scripts/
    middleware.py
    new_plugin.py
    release_check.sh
    run_plugin_conformance.py
    validate_plugin_manifest.py
  modeio_middleware/
    resources.py
    resources/
      config/
        default.json
      plugins_external/
        example/
      protocol/
        MODEIO_PLUGIN_MANIFEST.schema.json
        MODEIO_PLUGIN_MESSAGE.schema.json
    cli/
      controller_process.py
      controller_service.py
      controller_state.py
      gateway.py
      harness_adapters/
        base.py
        claude.py
        codex.py
        opencode.py
        openclaw.py
        registry.py
      middleware.py
      new_plugin.py
      plugin_conformance.py
      validate_plugin_manifest.py
      setup_lib/
        common.py
        opencode.py
        claude.py
    http_transport.py
    connectors/
      base.py
      anthropic_http.py
      claude_hooks.py
      openai_http.py
    core/
      config_resolver.py
      contracts.py
      decision.py
      engine.py
      errors.py
      http_contract.py
      pipeline_session.py
      plugin_manager.py
      profiles.py
      services/
        telemetry.py
    protocol/
      versions.py
      messages.py
      manifest.py
      validator.py
      jsonpatch.py
    registry/
      resolver.py
      loader.py
    runtime/
      base.py
      legacy_inprocess.py
      manager.py
      stdio_jsonrpc.py
      supervisor.py
    plugins/
      base.py
      redact.py
  tests/
    fixtures/
      stdio_echo_manifest.json
      stdio_echo_plugin.py
    helpers/
      gateway_harness.py
      plugin_modules.py
    unit/
      test_config_resolver.py
      test_http_transport.py
      test_plugin_manager.py
      test_setup_gateway.py
      test_stdio_supervisor.py
      test_upstream_client.py
    integration/
      test_claude_hook_connector.py
      test_controller_attachment_flows.py
      test_gateway_contract.py
      test_opencode_gateway_flow.py
      test_protocol_example_plugin.py
      test_protocol_stdio_runtime.py
```

## Runtime data flow

HTTP request/response flow:

1. Gateway receives a supported provider-shaped route such as `POST /v1/chat/completions`, `POST /v1/responses`, `POST /v1/messages`, or a client-scoped `/clients/{client}/{provider}/v1/...` route.
2. `http_transport.py` normalizes client-scoped routes into canonical `/v1/...` paths and injects the detected harness/provider context into request headers.
3. A connector parses the native request, normalizes the model against the current harness-selected provider state, and builds a `CanonicalInvocation` with both:
   - a normalized semantic payload for plugins
   - a native payload snapshot for denormalization and debugging
4. Core resolves profile/plugin runtime config and starts the plugin pipeline session.
5. Plugin manager runs `pre.request` hooks against the normalized payload.
6. If plugins emit semantic rewrite operations, plugin manager denormalizes the updated semantic payload back into provider-native request JSON before the upstream call.
7. Upstream transport reuses explicit incoming auth when present; otherwise it reuses harness-native auth and the preserved provider route resolved from the active harness state.
8. Core forwards the request upstream with `httpx`.
9. Middleware normalizes the upstream response into the same semantic payload model and runs `post.response` hooks.
10. If plugins emit semantic rewrite operations on the response, plugin manager denormalizes them back into provider-native or harness-facing response JSON.
11. Gateway returns provider-compatible JSON plus middleware headers through the ASGI transport.

Claude hook connector flow:

1. Gateway receives `POST /connectors/claude/hooks`
2. Connector normalizes supported Claude hook events into canonical pre-request or post-response middleware invocations.
3. Core resolves profile/plugin runtime and executes the same plugin pipeline against normalized prompt/response payloads.
4. Connector maps policy output back to Claude's hook output contract instead of a provider HTTP response body.
5. Gateway returns JSON decision + middleware headers

## Integration boundaries

- `plugins/base.py` defines plugin contract
- Plugins can return dict payloads or typed `HookDecision`
- Plugins can `allow`, `modify`, `warn`, or `block`
- Connectors normalize provider-native or harness-native payloads into a semantic timeline; `plugin_manager.py` denormalizes accepted rewrites back into native request/response/event shapes.
- `runtime/legacy_inprocess.py` is internal-only for bundled plugins and tests
- Public external plugins run via `runtime/stdio_jsonrpc.py` using MPP v1
- Core does not hardcode plugin-specific policy decisions
- Presets are registry-driven when provided (`config/presets/*.json`)
- Runtime shared services are injected via `hook_input["services"]`
- Packaged defaults start with no active policy plugins; the shipped example lives under `plugins_external/example/` and stays disabled until explicitly enabled.
- Mode controls (`observe`, `assist`, `enforce`) keep external plugins non-intrusive by default
- Packaged defaults live under `modeio_middleware/resources/` so the installed gateway works without repo layout assumptions
- Relative `manifest` paths and local-file `command` arguments are resolved relative to the config file
- Gateway transport is ASGI-based and upstream traffic flows through `core/upstream_client.py`
- Streaming policy operates on full SSE events instead of single `data:` lines

## Compatibility and safety

- v1 supports non-streaming and streaming passthrough
- setup script supports safe OpenCode patch/unpatch with backup
- Codex integration is environment-based (`OPENAI_BASE_URL`) and is not part of the controller-managed attach/detach lifecycle yet
- Claude integration uses native hooks transport (`/connectors/claude/hooks`) while preserving the same plugin protocol and policy runtime
- Live/operator smoke orchestration is intentionally external to this repo and owned by the external `middleware-api-smoke` workflow skill
