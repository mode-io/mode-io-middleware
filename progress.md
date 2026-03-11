# Progress Log

## Session: 2026-03-11

### Phase 1: Contract and seam audit
- **Status:** complete
- Actions taken:
  - Read `DESIGN_payload-summary.md` and the current plugin protocol/schema.
  - Audited the raw payload path through connectors, hook envelopes, plugin manager, runtime JSON-RPC adapter, stream relay, and observability serializers.
  - Replaced stale inherited planning files from the previous middleware refactor with payload-normalization-specific working docs.
- Files inspected:
  - `MODEIO_PLUGIN_PROTOCOL.md`
  - `MODEIO_PLUGIN_MESSAGE.schema.json`
  - `modeio_middleware/connectors/*`
  - `modeio_middleware/core/{decision,engine,hook_envelope,plugin_manager,stream_orchestrator}.py`
  - `modeio_middleware/core/observability/*`
  - `plugins_external/example/plugin.py`

### Phase 2-5: Contract implementation
- **Status:** complete
- Actions taken:
  - Added normalized payload core types, semantic mutation handling, and connector-specific normalization/denormalization helpers.
  - Rewired `CanonicalInvocation`, `HookEnvelope`, `PluginManager`, engine flow, stream flow, and observability around normalized-first payload handling.
  - Replaced external plugin raw body patching with semantic operations in the stdio JSON-RPC runtime and protocol schema/docs.
  - Migrated the example plugin, redact plugin, protocol conformance helper, and bundled resources to the normalized contract.
- Key files changed:
  - `modeio_middleware/core/payload_types.py`
  - `modeio_middleware/core/payload_mutations.py`
  - `modeio_middleware/core/payload_codec.py`
  - `modeio_middleware/core/plugin_manager.py`
  - `modeio_middleware/core/hook_envelope.py`
  - `modeio_middleware/runtime/stdio_jsonrpc.py`
  - `modeio_middleware/core/observability/*`
  - `MODEIO_PLUGIN_PROTOCOL.md`
  - `MODEIO_PLUGIN_MESSAGE.schema.json`

### Phase 6: Validation
- **Status:** complete
- Validation:
  - `python3 -m compileall modeio_middleware plugins_external/example`
  - `./.venv/bin/python -m unittest tests.unit.test_hook_envelope tests.unit.test_plugin_manager tests.unit.test_request_journal_service tests.smoke.test_protocol_example_plugin`
  - `./.venv/bin/python -m unittest tests.integration.test_monitoring_api tests.integration.test_plugin_management_api tests.unit.test_packaging_resources`
  - `./.venv/bin/python -m unittest discover tests -p 'test_*.py'`
  - `bash ./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/payload-normalization-live --opencode-provider opencode --opencode-model opencode/gpt-5.4 --opencode-base-url https://opencode.ai/zen/v1 --openclaw-families openai-completions --openclaw-openai-provider zenmux --openclaw-openai-model zenmux/gpt-5.3-codex`
- Result:
  - full Python suite passed (`258` tests)
  - supported live smoke passed for Codex, OpenCode, OpenClaw `openai-completions`, and Claude

### Phase 7: Raw payload capture hardening
- **Status:** complete
- Actions taken:
  - upgraded the smoke tap proxy to persist full raw request/response bodies as sidecar files
  - added best-effort decoded JSON/text sidecars for gzip, zstd, JSON, and SSE/text-friendly bodies
  - passed tap body directories through the live smoke runners for Codex, OpenCode, OpenClaw family scenarios, and Claude
  - added a unit test for tap-sidecar capture and gzip decoding
  - imported the richer live artifact into the local-only payload corpus under `.local/payloads/captured`
- Validation:
  - `./.venv/bin/python -m unittest tests.unit.test_upstream_tap_proxy`
  - `./.venv/bin/python -m unittest tests.smoke.test_smoke_agent_matrix_support`
  - `./.venv/bin/python -m unittest discover tests -p 'test_*.py'`
  - `bash ./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/payload-raw-capture-live --opencode-provider opencode --opencode-model opencode/gpt-5.4 --opencode-base-url https://opencode.ai/zen/v1 --openclaw-families openai-completions --openclaw-openai-provider zenmux --openclaw-openai-model zenmux/gpt-5.3-codex`
- Result:
  - full suite passed (`259` tests)
  - supported live smoke passed again
  - the local corpus now contains richer raw captures for Codex, OpenCode, OpenClaw, and Claude

### Phase 8: Corpus expansion and action-heavy capture
- **Status:** complete
- Actions taken:
  - added `--prompt-file` and `--agent-work-dir` to `scripts/smoke_agent_matrix.py` and threaded them through the smoke command builder/runner so live captures can reuse the existing sandbox/tap stack with richer prompts
  - added local-only helpers under `.local/payloads/`:
    - `capture_action_payloads.py`
    - `validate_captured_payloads.py`
  - captured richer action-oriented live payloads:
    - Codex: repeated `/responses` turns with tool definitions and long SSE response bodies
    - OpenCode: real `/responses` action flow that created `tmp/action-smoke/*` files in the temp workspace
    - Claude: real hook-side action flow that created `tmp/action-smoke/*` files in the temp workspace
    - OpenClaw: richer supported-family chat-completions traffic with an action-oriented prompt
  - expanded the local canonical `public/` corpus with tool-use, tool-result, multimodal, and incomplete-response examples for OpenAI and Anthropic families
  - refreshed the sampled corpus after importing the new captures
- Validation:
  - `./.venv/bin/python -m unittest discover tests -p 'test_*.py'`
  - local replay/roundtrip validation for the new public examples:
    - OpenAI chat-completions tool-call request/response
    - OpenAI responses tool-call request/response
    - OpenAI responses multimodal request
    - OpenAI responses incomplete response
    - Anthropic messages tool-use request/response
    - Anthropic messages tool-result request
    - Anthropic messages image request
  - local helper validation summaries:
    - OpenCode action capture: `validated=7`, `failureCount=0`
    - Claude action capture: `validated=4`, `failureCount=0`
    - OpenClaw action capture: `validated=3`, `failureCount=0`
    - Codex action capture: `validated=3`, `failureCount=0`
- Result:
  - full suite passed (`261` tests)
  - the local corpus now includes richer action-heavy captures and broader canonical family coverage without changing middleware product behavior
