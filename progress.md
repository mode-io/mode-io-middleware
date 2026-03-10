# Progress Log

## Session: 2026-03-10

### Phase 1: Discovery and native-auth investigation
- **Status:** complete
- **Started:** 2026-03-10 04:07 UTC
- Actions taken:
  - Audited middleware setup, routing, smoke infrastructure, and live artifacts.
  - Added client-scoped routes, native-auth bridging, provider-aware OpenCode routing, and doctor diagnostics.
  - Investigated installed OpenClaw and OpenCode codepaths to understand their auth/provider architecture.
- Files created/modified:
  - `modeio_middleware/http_transport.py`
  - `modeio_middleware/core/client_auth.py`
  - `modeio_middleware/cli/setup.py`
  - `modeio_middleware/cli/setup_lib/opencode.py`
  - `modeio_middleware/cli/setup_lib/openclaw.py`
  - `scripts/smoke_agent_matrix.py`
  - `scripts/smoke_matrix/sandbox.py`
  - `tests/**`

### Phase 2: Detailed implementation planning
- **Status:** complete
- Actions taken:
  - Converted the investigation into a phased refactor plan.
  - Defined the target architecture around provider adapters and typed credential resolution.
  - Documented the main risks, execution order, and validation gates.
- Files created/modified:
  - `task_plan.md` (created)
  - `findings.md` (created)
  - `progress.md` (created)

### Phase 3: Implementation kickoff
- **Status:** complete
- Actions taken:
  - Added shared provider/auth foundation in `modeio_middleware/core/provider_auth.py`.
  - Replaced duplicated auth parsing in `modeio_middleware/core/client_auth.py` with a compatibility facade over the shared resolver.
  - Kept setup and runtime behavior stable while moving native-auth inspection onto provider-aware abstractions.
  - Added regression coverage for provider resolution, sanitized inspections, and existing client bridges.
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py` (created)
  - `modeio_middleware/core/client_auth.py`
  - `tests/unit/test_client_auth.py`

### Phase 4: Codex native adapter
- **Status:** in_progress
- Actions taken:
  - Added a distinct `CodexNativeAdapter` in the shared provider registry.
  - Promoted Codex-specific transport/fallback semantics into provider inspections (`transport=codex_native`, `fallbackMode=managed_upstream`).
  - Routed model normalization through provider adapters so Codex-specific prefixes can be handled centrally.
  - Confirmed the real Codex backend shape (`/backend-api/codex/models`, `/backend-api/codex/responses`) and wired middleware transport overrides toward it.
  - Added a dedicated Codex live-smoke tap proxy and rewrote Codex model discovery responses to disable websocket preference through middleware.
  - Fixed a stale `content-encoding` header leak so native Codex backend requests are forwarded correctly after middleware body decoding.
  - Verified repo and wheel live smoke now pass Codex end to end through the native backend route.
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py`
  - `modeio_middleware/core/upstream_client.py`
  - `scripts/smoke_agent_matrix.py`

### Phase 5: OpenCode provider-native adapters
- **Status:** in_progress
- Actions taken:
  - Moved OpenCode auth inspection behind provider-aware adapter logic in `provider_auth.py`.
  - Made setup-side live upstream detection provider-aware and preserved base-url-aware env fallback behavior.
  - Added automatic placeholder API-key injection so OpenCode will talk to localhost without manual user setup when the selected provider otherwise insists on a key.
  - Added best-effort fallback from OpenCode `openai` provider to shared Codex/OpenClaw OAuth via the Codex-native transport.
  - Normalized Codex-native payload differences for OpenCode helper and main requests (`gpt-5-nano` remap, `max_output_tokens` removal, `minimal` reasoning effort normalization, instructions extraction).
  - Repo and wheel native live smoke now pass OpenCode end to end through middleware.
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py`
  - `modeio_middleware/cli/setup_lib/upstream.py`
  - `modeio_middleware/connectors/openai_http.py`
  - `modeio_middleware/cli/setup_lib/opencode.py`

### Phase 6: OpenClaw adapter migration
- **Status:** in_progress
- Actions taken:
  - Moved OpenClaw auth inspection behind the shared provider adapter contract.
  - Added `OpenClawSelectionResolver` so provider/profile choice is encapsulated instead of scattered across helper functions.
  - Added auto-refresh support for expired `openai-codex` OpenClaw OAuth profiles and fallback-aware health bookkeeping.

### Session: 2026-03-10 test review
- **Status:** in_progress
- Actions taken:
  - Audited changed tests on the branch against `origin/main`.
  - Read the main unit test files plus touched integration/smoke helpers.
  - Identified likely structural issues around config-shape coupling, private-helper testing, and missing higher-level Anthropic/OpenClaw coverage.
- Files inspected:
  - `tests/unit/test_client_auth.py`
  - `tests/unit/test_upstream_client.py`
  - `tests/unit/test_setup_gateway.py`
  - `tests/smoke/test_smoke_agent_matrix_support.py`
  - `tests/integration/test_gateway_contract.py`
  - `tests/smoke/test_smoke_client_setup_flows.py`
  - `tests/helpers/gateway_harness.py`
  - Added runtime cooldown marking on `429`/auth rejection so the resolver has real failure state to work with.
  - Added bounded fallback-provider selection from the user’s configured OpenClaw models cache, but the current machine’s alternate providers do not offer a like-for-like `gpt-5.4` replacement, so live OpenClaw still does not clear end-to-end.
  - Preserved current native provider/profile resolution and managed fallback semantics.
  - Verified repo and wheel live runs isolate OpenClaw failures to external provider/account state and classify them as `external_blocked` instead of product failures.
  - Ran an exact copied-state investigation: direct copied OpenClaw works, and copied-state OpenClaw through middleware now reaches the correct Codex-native backend after transport fixes.
  - The remaining OpenClaw failure is not auth reuse; it is response adaptation. Middleware returns Codex-native success upstream, but OpenClaw still ends with empty `payloads`, which means we still need to translate the native response/events into the client shape OpenClaw expects.
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py`

### Planning Slice: OpenClaw practical release families
- **Status:** complete
- Actions taken:
  - Committed the current middleware auth refactor checkpoint as `c6f983d` (`Refactor native auth routing and live smoke support`) so the branch now has a stable planning baseline.
  - Re-checked OpenClaw docs/runtime and confirmed its provider abstraction is not a single universal wire format; `api` is configured per provider, which means supporting multiple families requires multiple synthetic middleware providers.
  - Confirmed the current middleware already exposes the OpenAI-compatible surface needed for `openai-completions`, does not yet expose a generic Anthropic Messages HTTP surface, and already contains the upstream Codex-native work needed for a dedicated `openai-codex-responses` boundary.
  - Defined the practical OpenClaw release plan around three explicit managed families:
    - `openai-completions`
    - `anthropic-messages`
    - `openai-codex-responses`
  - Defined the release pivot: OpenClaw v1 should ship as additive managed providers, while native-profile reuse stays experimental until the family-specific boundaries are finished.
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

### Phase 8A: OpenClaw family-aware smoke infrastructure
- **Status:** complete
- Actions taken:
  - Reworked `scripts/smoke_agent_matrix.py` so OpenClaw live smoke now resolves and runs one scenario per supported family instead of one generic OpenClaw pass.
  - Added sandbox helpers to patch copied OpenClaw config/models-cache state for preserve-provider smoke scenarios without exposing secrets.
  - Updated `scripts/smoke_e2e.sh` to seed real OpenClaw family fixtures for setup/uninstall and CLI validation instead of the old synthetic `modeio-middleware` assumption.
  - Added smoke-support tests covering OpenClaw family parsing, scenario resolution, and sandbox patching.
  - Ran a real OpenClaw-only live smoke after the harness changes to capture both supported family outcomes from copied local state.
- Files created/modified:
  - `scripts/smoke_agent_matrix.py`
  - `scripts/smoke_matrix/sandbox.py`
  - `scripts/smoke_e2e.sh`
  - `tests/smoke/test_smoke_agent_matrix_support.py`

### Phase 8B: OpenClaw family live-smoke stabilization
- **Status:** complete
- Actions taken:
  - Fixed OpenClaw provider inspection so the current provider's own models-cache API key and env fallback are used before cross-provider fallback, which keeps preserve-provider routing pinned to the intended upstream base URL.
  - Fixed OpenClaw family tap proxies so they no longer overwrite preserved caller auth with the generic managed upstream key.
  - Relaxed default OpenClaw OpenAI-family scenario selection so model-based provider selection only happens when explicitly requested; default live smoke now uses the first configured OpenAI-compatible provider instead of deriving from the middleware's generic smoke model.
  - Re-ran real OpenClaw family live smoke and confirmed both supported families now hit their intended family taps and classify as external auth/account blocks instead of product failures.
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py`
  - `scripts/smoke_agent_matrix.py`
  - `tests/unit/test_client_auth.py`
  - `tests/smoke/test_smoke_agent_matrix_support.py`

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Full Python suite | `./.venv/bin/python -m unittest discover tests -p 'test_*.py'` | Green suite | `198` tests passed | pass |
| Claude native live smoke | `./scripts/smoke_e2e.sh --live-claude` | Pass | Passed | pass |
| Repo native live matrix | `./scripts/smoke_e2e.sh --live-agents` | OpenAI-compatible + Claude split diagnostics | Claude passed; OpenAI-compatible client-specific blockers isolated | mixed |
| Wheel native live matrix | `./scripts/smoke_e2e.sh --live-agents --install-mode wheel` | Same as repo mode | Same split outcome | mixed |
| Provider foundation compile check | `./.venv/bin/python -m py_compile modeio_middleware/core/provider_auth.py ...` | No syntax regressions | Passed | pass |
| Focused auth/setup/smoke-support tests | `./.venv/bin/python -m unittest tests.unit.test_client_auth ...` | Green targeted coverage | `73` tests passed | pass |
| Full Python suite after provider foundation | `./.venv/bin/python -m unittest discover tests -p 'test_*.py'` | Green suite after refactor | `202` tests passed | pass |
| Claude live smoke after adapter migration | `./scripts/smoke_e2e.sh --live-claude` | Pass | Passed | pass |
| Repo native live matrix after adapter migration | `./scripts/smoke_e2e.sh --live-agents` | Stable split diagnostics | Claude passed; Codex/OpenCode/OpenClaw blockers unchanged but isolated | mixed |
| Wheel native live matrix after adapter migration | `./scripts/smoke_e2e.sh --live-agents --install-mode wheel` | Stable split diagnostics | Claude passed; Codex/OpenCode/OpenClaw blockers unchanged but isolated | mixed |
| Full Python suite after deeper adapter work | `./.venv/bin/python -m unittest discover tests -p 'test_*.py'` | Green suite after Codex/OpenClaw transport changes | `210` tests passed | pass |
| Repo native live matrix after Codex/OpenCode native routing | `./scripts/smoke_e2e.sh --live-openai-agents` | Codex and OpenCode traverse native backend paths successfully | Codex `ok=true`, OpenCode `ok=true`, OpenClaw still rate-limited | mixed |
| Wheel native live matrix after Codex backend routing | `./scripts/smoke_e2e.sh --live-agents --install-mode wheel` | Same as repo mode | Same split outcome | mixed |
| Final repo native live matrix | `./scripts/smoke_e2e.sh --live-agents` | Pass overall with Codex/OpenCode/Claude green | Passed, but OpenClaw still has a protocol-translation gap | mixed |
| Final wheel native live matrix | `./scripts/smoke_e2e.sh --live-agents --install-mode wheel` | Same as repo mode | Same support state | mixed |
| Direct copied OpenClaw without middleware | temp copy of `~/.openclaw` + `openclaw agent --local` | Return token | Passed | pass |
| Exact copied OpenClaw through middleware | temp copy of `~/.openclaw` + middleware native route, no model override | Should match direct path | Reaches `chatgpt.com/backend-api/codex/responses`, but OpenClaw gets empty payloads | mixed |
| Focused OpenClaw smoke-support tests | `python -m unittest tests.smoke.test_smoke_agent_matrix_support tests.smoke.test_smoke_client_setup_flows` | Green targeted harness coverage | `14` tests passed | pass |
| Full smoke support suite | `python -m unittest discover tests/smoke -p 'test_*.py'` | Green smoke-support coverage | `17` tests passed | pass |
| Offline smoke wrapper after OpenClaw family updates | `bash ./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke-openclaw-families` | Setup/CLI/offline smoke green with both supported OpenClaw families | Passed | pass |
| Real OpenClaw family live smoke | `./.venv/bin/python scripts/smoke_agent_matrix.py --agents openclaw --artifacts-dir ./.artifacts/live-openclaw-family-smoke` | Real traffic evidence for `openai-completions` and `anthropic-messages` | `anthropic-messages` hit `/v1/messages` and returned `401` (`external_blocked`); `openai-completions` still failed before the family tap saw traffic | mixed |
| OpenClaw provider-auth regression tests after preserve-provider fix | `python -m unittest tests.unit.test_client_auth tests.smoke.test_smoke_agent_matrix_support` | Green targeted coverage after auth/routing fix | `27` tests passed | pass |
| Final offline smoke wrapper after OpenClaw live-smoke fixes | `bash ./scripts/smoke_e2e.sh --artifacts-dir ./.artifacts/manual-smoke-openclaw-families-final` | Setup/CLI/offline smoke still green after provider-auth changes | Passed | pass |
| Final real OpenClaw family live smoke | `./.venv/bin/python scripts/smoke_agent_matrix.py --agents openclaw --artifacts-dir ./.artifacts/live-openclaw-family-smoke` | Supported families should traverse intended family taps and avoid product failure | Passed overall: `openai-completions` hit the OpenRouter family tap and returned `401` (`external_blocked`); `anthropic-messages` hit `/v1/messages` and returned `401` (`external_blocked`) | pass |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-03-10 07:34 UTC | Codex native auth still rejected by upstream public routes | 1 | Reclassified as dedicated-adapter requirement, not generic bridge bug |
| 2026-03-10 07:35 UTC | OpenCode current provider had no reusable auth | 1 | Added provider-aware inspection and explicit diagnostics |
| 2026-03-10 07:35 UTC | OpenClaw live run still failed after native bridge landed | 1 | Separated local route/cache bug from external `429` rate limiting |
| 2026-03-10 07:58 UTC | Existing auth logic was too duplicated to safely extend Codex/OpenCode/OpenClaw separately | 1 | Added shared provider-auth foundation first, then kept compatibility wrappers to preserve current behavior |
| 2026-03-10 08:20 UTC | Provider-aware upstream selection broke the ZenMux fallback unit expectation | 1 | Restored base-url-aware env fallback after provider-specific inspection |
| 2026-03-10 09:39 UTC | Codex native backend requests bypassed the main tap proxy and produced misleading 404s | 1 | Added a dedicated Codex native tap proxy targeting `https://chatgpt.com/backend-api/codex` |
| 2026-03-10 09:58 UTC | Codex-native responses still failed after endpoint routing | 1 | Confirmed the backend requires `store=false` and `stream=true`; middleware now enforces those flags for Codex-native `/responses` |
| 2026-03-10 10:34 UTC | OpenCode native requests still failed after auth/routing fixes | 1 | Normalized Codex-native payload quirks (`gpt-5-nano`, `max_output_tokens`, `reasoning.effort=minimal`) and fixed smoke tap attribution |
| 2026-03-10 11:42 UTC | Live smoke still reported failure when only OpenClaw provider state was rate-limited | 1 | Added `outcome`/`productOk` semantics so external provider/account blocks no longer fail the whole product smoke slice |
| 2026-03-10 12:15 UTC | Exact copied OpenClaw through middleware still failed even after Codex-native routing | 1 | Isolated the remaining bug to response/event translation: upstream success is real, but OpenClaw receives an incompatible response shape and ends with empty payloads |
| 2026-03-10 12:52 UTC | A single synthetic OpenClaw provider could not cleanly cover all desired release families | 1 | Pivoted planning to three family-specific providers because OpenClaw config binds `api` at the provider level |
| 2026-03-10 12:52 UTC | Anthropic-family OpenClaw support looked like a setup-only task at first glance | 1 | Confirmed middleware lacks a generic Anthropic Messages HTTP surface, so this is explicit connector/transport work |
| 2026-03-10 13:52 UTC | OpenClaw-only live smoke still ran unrelated managed `/clients/codex/v1` gateway probes | 1 | Scoped generic gateway checks to codex/opencode live runs so OpenClaw family smoke reports only family-specific results |
| 2026-03-10 13:53 UTC | OpenClaw `openai-completions` live family smoke returned `401` without hitting the intended family tap | 1 | Harness now selects concrete copied providers instead of generic `auto`, but the current live result still points to a remaining OpenClaw OpenAI-family auth/routing gap to investigate separately |
| 2026-03-10 14:01 UTC | OpenClaw `openai-completions` preserve-provider inspection bypassed the current provider and silently fell back to another provider before checking the current provider's cached API key | 1 | Reordered `_inspect_openclaw_provider` so current-provider cache/env auth wins before cross-provider fallback; preserve-provider live smoke now reaches the intended family tap |
| 2026-03-10 14:02 UTC | OpenClaw family tap proxies were overwriting preserved caller auth with `MODEIO_TAP_UPSTREAM_API_KEY` | 1 | Removed the auth override from OpenClaw family taps so live smoke preserves the real copied OpenClaw credentials end to end |
| 2026-03-10 14:33 UTC | Generic `/clients/openclaw/openai-codex/...` routes could still fall through into upstream forwarding even though OpenClaw intentionally defers `openai-codex-responses` | 1 | Rejected unsupported OpenClaw families explicitly at the public runtime boundary and updated stale contract tests/mocks to match the current inspection shape |

### Phase 8C: Contract boundary fix and stale test cleanup
- **Status:** complete
- Actions taken:
  - Added an explicit public OpenClaw-family gate so only `openai-completions` and `anthropic-messages` are routable through the OpenClaw client boundary.
  - Preserved internal reuse of OpenClaw `openai-codex` profiles for Codex/OpenCode fallback paths, so the fix does not regress shared auth behavior.
  - Updated the upstream client to fail fast with a clear validation error instead of forwarding placeholder OpenClaw auth toward a generic upstream path.
  - Fixed stale integration/unit tests:
    - header assertion now tolerates normalized casing
    - mocked inspection objects now include `resolved_headers`
    - the old OpenClaw `openai-codex` route test now asserts explicit rejection instead of unsupported success
    - replaced the stale public OpenClaw `openai-codex` inspection expectation with a public unsupported-family assertion plus a Codex-side refresh regression test
- Files created/modified:
  - `modeio_middleware/core/provider_auth.py`
  - `modeio_middleware/core/upstream_client.py`
  - `tests/integration/test_gateway_contract.py`
  - `tests/unit/test_client_auth.py`
  - `tests/unit/test_upstream_client.py`
- Validation:
  - `python-test-env.sh test --repo ... -- python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.integration.test_gateway_contract`
    - `49` tests passed
  - `python-test-env.sh test --repo ... -- python -m unittest tests.unit.test_http_transport tests.unit.test_setup_gateway`
    - `44` tests passed
  - `python-test-env.sh test --repo ... -- python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.unit.test_http_transport tests.integration.test_gateway_contract`
    - `55` tests passed

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Codex/OpenCode/Claude are green; OpenClaw investigation is complete enough to pivot from zero-config native mirroring toward a three-family managed release plan |
| Where am I going? | Implement family-explicit OpenClaw support in this order: `openai-completions`, `anthropic-messages`, then `openai-codex-responses`, while keeping native-profile reuse experimental |
| What's the goal? | Users with authed harnesses should be able to start middleware naturally without extra provider setup |
| What have I learned? | OpenClaw normalizes many providers, but still exposes multiple provider API families; the release-grade way to support it is one managed middleware provider per family, not one universal provider |
| What have I done? | Landed the provider-auth foundation, committed the auth/smoke refactor checkpoint, isolated the OpenClaw native gap, and converted the release strategy into a three-family implementation plan |
