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

### Phase 16 planning: strict harness-state contract
- **Status:** planning complete
- Actions taken:
  - Reconfirmed the product contract with the user:
    - middleware is not an auth provider
    - middleware is not a model/provider chooser
    - middleware should preserve exact harness-selected state or fail clearly
  - Audited the current branch for remaining drift against that contract.
  - Identified remaining runtime drift:
    - Codex still falls back to `OPENAI_API_KEY` if `~/.codex/auth.json` is missing
    - OpenCode still falls back to provider env vars
    - OpenClaw still falls back to provider env vars
    - OpenClaw still resolves `:default` or first available matching profile
    - OpenClaw still infers API family from provider id when state is incomplete
  - Identified remaining smoke drift:
    - Codex smoke was still forcing a fallback model and is being corrected toward exact selected-model resolution
    - OpenCode smoke still has generic `fallback_model`
    - OpenClaw smoke still picks first-matching providers/models and uses synthesized family defaults
  - Identified remaining setup/doctor drift:
    - OpenClaw managed-mode code paths are still present in setup libs
    - doctor/setup output still frames readiness with softer `guaranteed` / `best_effort` language instead of exact-state semantics
  - Converted the audit into a new Phase 16 strict-state enforcement plan in `task_plan.md`.
- Files created/modified:
  - `findings.md`
  - `task_plan.md`
  - `progress.md`

### Session: 2026-03-10 refactor readiness review
- Committed the OpenClaw boundary fix checkpoint as `1177ebb` (`Gate deferred OpenClaw Codex family`).
- Performed a structural review over the current branch with local inspection focused on:
  - `modeio_middleware/cli/setup_lib/openclaw.py`
  - `modeio_middleware/core/provider_auth.py`
  - `modeio_middleware/core/upstream_client.py`
  - `modeio_middleware/http_transport.py`
  - `modeio_middleware/core/engine.py`
  - `scripts/smoke_agent_matrix.py`
  - `scripts/upstream_tap_proxy.py`
  - key unit/integration/smoke-support test files
- Highest-confidence findings recorded in `findings.md`:
  - OpenClaw setup should be rewritten around one transaction model
  - auth/transport should move to a typed upstream plan instead of metadata dict hints
  - request-context parsing is duplicated across transport, engine, and connectors
  - smoke orchestration should be split into scenario, runner, and reporting layers
  - several dead-surface candidates are now clear enough to track for post-refactor removal
- The detailed staged refactor sequence is now captured in `task_plan.md` under:
  - `Phase 15: Structural refactor gate`
  - `Structural Refactor Plan`

### Phase 15: Structural refactor review and plan
- **Status:** in_progress
- Actions taken:
  - Committed the public OpenClaw boundary fix as `1177ebb` (`Gate deferred OpenClaw Codex family`) so the structural review starts from a clean, green checkpoint.
  - Re-ran the exact failing auth/transport/gateway subset after the fix and confirmed it stayed green.
  - Reviewed the main cleanup hotspots locally and via split subsystem review prompts:
    - OpenClaw setup
    - auth/transport
    - gateway boundary
    - smoke infrastructure
    - test architecture
    - repo-wide dead-surface scan
  - Converted the review into a concrete refactor gate in `task_plan.md`, with sequencing and target abstractions instead of a loose “clean it up later” note.
- Key conclusions:
  - The branch is now ready for refactor because the wrong public boundary has been corrected.
  - The biggest problem is duplicated logic and mixed responsibilities, not a large pile of safely deletable dead code.
  - Highest-priority refactor targets are:
    - `modeio_middleware/cli/setup_lib/openclaw.py`
    - `modeio_middleware/core/provider_auth.py`
    - `modeio_middleware/core/upstream_client.py`
    - `scripts/smoke_agent_matrix.py`
  - The right next move is a structural refactor gate before continuing more OpenClaw-family feature work.
- Planned execution order:
  1. OpenClaw setup transaction rewrite
  2. Auth/transport plan split
  3. Upstream strategy extraction
  4. Smoke scenario/execution/reporting split
  5. Test fixture/contract cleanup
  6. Compatibility/dead-surface deletion

### Phase 8D: Structural review and refactor planning
- **Status:** complete
- Actions taken:
  - Committed the OpenClaw contract-boundary fix as `1177ebb` (`Gate deferred OpenClaw Codex family`).
  - Re-ran a structural review focused on the new hotspots rather than the original product bug.
  - Consolidated the cleanup target list around three code seams:
    - OpenClaw setup transaction flow
    - auth/inspection/transport planning
    - smoke scenario/process/report orchestration
  - Converted the review into a staged refactor plan instead of a single large rewrite proposal.
- Files inspected:
  - `modeio_middleware/cli/setup_lib/openclaw.py`
  - `modeio_middleware/core/provider_auth.py`
  - `modeio_middleware/core/upstream_client.py`
  - `modeio_middleware/http_transport.py`
  - `scripts/smoke_agent_matrix.py`
  - `scripts/smoke_matrix/sandbox.py`
  - `scripts/smoke_e2e.sh`
  - `scripts/upstream_tap_proxy.py`
  - `tests/unit/test_setup_gateway.py`
  - `tests/unit/test_client_auth.py`
  - `tests/unit/test_upstream_client.py`
  - `tests/integration/test_gateway_contract.py`
  - `tests/smoke/test_smoke_agent_matrix_support.py`
- Main conclusion:
  - the branch is ready for refactor, but not for a repo-wide rewrite
  - the clean path is a staged structural pass built around typed plans/transactions and narrower modules, with behavior locked by the current contract and live-smoke coverage

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Codex/OpenCode/Claude are green; OpenClaw investigation is complete enough to pivot from zero-config native mirroring toward a three-family managed release plan |
| Where am I going? | Implement family-explicit OpenClaw support in this order: `openai-completions`, `anthropic-messages`, then `openai-codex-responses`, while keeping native-profile reuse experimental |
| What's the goal? | Users with authed harnesses should be able to start middleware naturally without extra provider setup |
| What have I learned? | OpenClaw normalizes many providers, but still exposes multiple provider API families; the release-grade way to support it is one managed middleware provider per family, not one universal provider |
| What have I done? | Landed the provider-auth foundation, committed the auth/smoke refactor checkpoint, isolated the OpenClaw native gap, and converted the release strategy into a three-family implementation plan |

### Session: 2026-03-10 15:32 UTC structural refactor implementation
- Implemented the structural refactor plan in one pass on top of `f91785c`.
- Runtime/auth work:
  - added `modeio_middleware/core/request_context.py`
  - added `modeio_middleware/core/upstream_plan.py`
  - added `modeio_middleware/core/upstream_strategy.py`
  - refactored `provider_auth.py`, `client_auth.py`, `upstream_client.py`, `upstream_transport.py`, `engine.py`, and `stream_orchestrator.py` so route context and typed upstream plans flow through the runtime instead of ad hoc metadata-only branching at the call sites
  - updated OpenAI/Anthropic connectors to use the shared client route context
- OpenClaw setup work:
  - split `modeio_middleware/cli/setup_lib/openclaw.py` into:
    - `openclaw_common.py`
    - `openclaw_routes.py`
    - `openclaw_transaction.py`
  - kept `openclaw.py` as a thin public facade to avoid a broad call-site break
- Smoke infrastructure work:
  - split `scripts/smoke_agent_matrix.py` into a thinner CLI entrypoint
  - moved OpenClaw family selection into `scripts/smoke_matrix/openclaw_family.py`
  - moved execution helpers into `scripts/smoke_matrix/runner.py`
- Test cleanup work:
  - added `tests/helpers/inspection_builder.py`
  - migrated the most brittle upstream/gateway tests to the builder instead of hand-built inspection objects
- Validation:
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.unit.test_http_transport tests.integration.test_gateway_contract`
    - `55` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.unit.test_setup_gateway tests.smoke.test_smoke_client_setup_flows`
    - `40` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest discover tests/smoke -p 'test_*.py'`
    - `18` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.unit.test_http_transport tests.unit.test_setup_gateway tests.integration.test_gateway_contract tests.smoke.test_smoke_agent_matrix_support tests.smoke.test_smoke_client_setup_flows`
    - `108` tests passed
- Result:
  - the structural refactor gate is complete
  - remaining cleanup is no longer a blocker for continuing product work or opening the next review

### Session: 2026-03-10 16:25 UTC release-smoke follow-up after refactor
- Re-ran the release smoke path from the refactor branch and found two real smoke-split regressions:
  - `scripts/smoke_agent_matrix.py` lost `tempfile`, `subprocess`, and `shutil` imports during the split
  - `scripts/smoke_matrix/runner.py` lost `sys` and `_zstd_codec` imports during the split
- Fixed those regressions and validated the smoke-support layer again:
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.smoke.test_smoke_agent_matrix_support`
    - `13` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest discover tests/smoke -p 'test_*.py'`
    - `18` tests passed
- Release-smoke discovery:
  - the wrapper path in `scripts/smoke_e2e.sh` was not forwarding `MODEIO_GATEWAY_UPSTREAM_BASE_URL` / `MODEIO_GATEWAY_UPSTREAM_MODEL` into `scripts/smoke_agent_matrix.py`
  - without that pass-through, the live matrix silently defaulted back to `https://api.openai.com/v1` + `gpt-4o-mini`, which caused false-negative repo smoke in this environment
  - patched `scripts/smoke_e2e.sh` to forward those explicit upstream overrides
- Auth-path confirmation from live debugging:
  - `opencode` does not need an OpenClaw-style public family split
  - but the internal auth layer still has to choose between:
    - direct selected-provider auth reuse
    - placeholder-localhost passthrough
    - shared Codex/OpenClaw native fallback
  - removing direct OpenAI-style env vars from the smoke sandbox proved the shared Codex-native fallback still works for `opencode`
  - preserving a missing OpenCode provider API key in setup, instead of force-injecting the local placeholder, kept the localhost path compatible with the now-cleaner auth precedence and the passing live smoke runs
- Final live smoke evidence after the wrapper/import fixes:
  - repo mode:
    - `bash ./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-agent-refactor-postgate-nativeenv2`
    - passed
    - artifact root: `.artifacts/live-agent-refactor-postgate-nativeenv2/20260310T162202Z-99837`
  - wheel mode:
    - `bash ./scripts/smoke_e2e.sh --live-agents --install-mode wheel --artifacts-dir ./.artifacts/live-agent-refactor-postgate-nativeenv2-wheel`
    - passed
    - artifact root: `.artifacts/live-agent-refactor-postgate-nativeenv2-wheel/20260310T162342Z-1414`

### Session: 2026-03-10 17:35 UTC strict harness-owned auth implementation
- Investigated the remaining OpenCode live-routing gap with a kept sandbox and confirmed:
  - the seeded sandbox config was patched correctly
  - `provider.openai.options.baseURL` and `OPENAI_BASE_URL` were both ignored by the real OpenCode `openai` OAuth path
  - upstream OpenCode source explains why: the built-in `openai` OAuth plugin rewrites requests internally to ChatGPT Codex
- Implemented the contract correction:
  - `modeio_middleware/cli/setup_lib/opencode.py`
    - added OpenCode route-support classification
    - refuse to patch selected provider `openai` when OpenCode auth store has `type: oauth`
  - `modeio_middleware/core/provider_auth.py`
    - OpenCode inspection now reports `unsupported_transport` for that same case
  - `scripts/smoke_agent_matrix.py` and `scripts/smoke_matrix/runner.py`
    - live smoke now skips unsupported OpenCode scenarios instead of claiming a false routed success
  - `scripts/smoke_e2e.sh`
    - setup smoke now uses an isolated temp HOME/XDG root so host OpenCode OAuth state does not contaminate temp-config setup checks
  - docs updated in `README.md`, `QUICKSTART.md`, and `CONTRIBUTING.md`
- Validation:
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- ./.venv/bin/python -m unittest tests.unit.test_setup_gateway tests.unit.test_client_auth tests.smoke.test_smoke_agent_matrix_support tests.smoke.test_smoke_opencode_flow tests.unit.test_upstream_client tests.integration.test_gateway_contract`
    - `104` tests passed
  - `./scripts/smoke_e2e.sh --live-openai-agents --keep-sandbox --artifacts-dir ./.artifacts/live-openai-strict-harness-final`
    - passed
    - artifact root: `.artifacts/live-openai-strict-harness-final/20260310T173238Z-71819`
    - live outcomes:
      - `codex`: `warning` / `productOk=true` (`auth store needs a fresh login`)
      - `opencode`: `skipped` / `productOk=true` (`openai` OAuth transport unsupported for middleware routing)
      - `openclaw:openai-completions`: passed
      - `openclaw:anthropic-messages`: passed

### Session: 2026-03-11 02:54 UTC provider-family registry and pause note
- Added a future-facing provider-family registry in `modeio_middleware/core/provider_policy.py`.
  - centralized family specs, transport-kind mapping, and per-client support flags
  - routed existing OpenCode/OpenClaw policy resolution through that shared registry without changing the current support matrix
- Added the explicit pause/deferred-compatibility note:
  - user-facing note in `README.md`
  - internal restart note in `.worktree-context.md`
  - planning files updated so compatibility work can resume from the same seam later
- Validation:
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.unit.test_provider_policy tests.unit.test_client_auth tests.integration.test_gateway_contract`
    - `52` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest discover tests -p 'test_*.py'`
    - `254` tests passed
  - `bash ./scripts/smoke_e2e.sh --live-agents --artifacts-dir ./.artifacts/live-provider-family-registry --opencode-provider opencode --opencode-model opencode/gpt-5.4 --opencode-base-url https://opencode.ai/zen/v1 --openclaw-families openai-completions --openclaw-openai-provider zenmux --openclaw-openai-model zenmux/gpt-5.3-codex`
    - passed
    - artifact root: `.artifacts/live-provider-family-registry/20260311T025420Z-64341`
    - live outcomes:
      - `codex`: passed
      - `opencode`: passed
      - `openclaw:openai-completions`: passed
      - `claude`: passed

### Session: 2026-03-11 04:00 UTC harness adapter refactor
- Implemented `modeio_middleware/cli/harness_adapters/` as the real harness-attachment boundary.
  - added typed inspection/attach/detach models
  - added concrete adapters for `codex`, `opencode`, `openclaw`, and `claude`
  - codex is now represented explicitly as `env_session`
- Refactored `modeio_middleware/cli/setup.py` to consume the adapter registry.
  - doctor/setup JSON shape stayed stable
  - harness-specific patch/hook/env logic is no longer embedded directly in `setup.py`
- Added focused adapter tests in `tests/unit/test_harness_adapters.py`.
- Validation:
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest tests.unit.test_harness_adapters tests.unit.test_setup_gateway tests.smoke.test_smoke_client_setup_flows tests.smoke.test_smoke_agent_matrix_support tests.unit.test_client_auth tests.integration.test_gateway_contract`
    - `112` tests passed
  - `python-test-env.sh test --repo /Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass -- python -m unittest discover tests -p 'test_*.py'`
    - `258` tests passed
  - `bash ./scripts/smoke_e2e.sh --live-agents --live-claude --artifacts-dir ./.artifacts/live-harness-adapter-refactor --opencode-provider opencode --opencode-model opencode/gpt-5.4 --opencode-base-url https://opencode.ai/zen/v1 --openclaw-families openai-completions --openclaw-openai-provider zenmux --openclaw-openai-model zenmux/gpt-5.3-codex`
    - passed
    - artifact root: `.artifacts/live-harness-adapter-refactor/20260311T041217Z-95407`
    - live outcomes:
      - `codex`: passed
      - `opencode`: passed
      - `openclaw:openai-completions`: passed
      - `claude`: passed
