# Findings & Decisions

## Requirements
- Users with an already authed supported harness should be able to start middleware naturally without extra provider setup.
- Native auth must be the primary/default path for `codex`, `opencode`, `openclaw`, and `claude`.
- Managed-upstream mode must remain available as an explicit fallback, not the default assumption.
- Setup, doctor, and live smoke must reflect true per-client readiness rather than generic environment guesses.
- Refactor must preserve current middleware functionality while improving architecture, maintainability, and operator clarity.

## Research Findings
- OpenClaw uses a layered auth-resolution pipeline instead of a single env/config lookup; see `/opt/homebrew/lib/node_modules/openclaw/dist/subagent-registry-CkqrXKq4.js:18185`.
- OpenClaw tracks provider/profile auth health and readiness, including expiring/expired/cooldown states; see `/opt/homebrew/lib/node_modules/openclaw/dist/subagent-registry-CkqrXKq4.js:23669`.
- OpenClaw resolves OAuth-like credentials separately from provider routing and supports refresh-oriented auth handling; see `/opt/homebrew/lib/node_modules/openclaw/dist/subagent-registry-CkqrXKq4.js:18235`.
- OpenCode uses a provider-auth plugin contract (`auth.provider`, `auth.methods`, `auth.loader`) rather than hard-coding one credential path; see `/Users/siruizhang/.config/opencode/node_modules/@opencode-ai/plugin/dist/index.d.ts:19`.
- OpenCode's Anthropic bridge owns runtime auth injection, refresh, header mutation, and protocol rewriting; see `/Users/siruizhang/.cache/opencode/node_modules/opencode-anthropic-auth/index.mjs:82`.
- Provider selection and auth material are separate in OpenCode: config/state select the provider/model, while provider auth is loaded later through provider-specific contracts.
- Our current middleware now supports client-scoped routes and basic native-auth bridging, but remaining OpenAI-compatible failures are client/account specific rather than shared routing bugs.
- OpenAI Codex OAuth is implemented in OpenClaw's `@mariozechner/pi-ai` package with client id `app_EMoamEEZ73f0CkXaXp7hrann`, token endpoint `https://auth.openai.com/oauth/token`, and refresh support; see `/opt/homebrew/lib/node_modules/openclaw/node_modules/@mariozechner/pi-ai/dist/utils/oauth/openai-codex.js:19`.
- Codex-native model discovery succeeds against `https://chatgpt.com/backend-api/codex/models?client_version=<version>` and returns explicit websocket preference fields.
- Codex-native response creation succeeds against `https://chatgpt.com/backend-api/codex/responses` when the payload sets `store=false` and `stream=true`; the middleware now routes Codex-native traffic toward those endpoints.
- OpenClaw's auth store resolution refreshes OAuth credentials under a file lock and reuses the latest shared profile; see `/opt/homebrew/lib/node_modules/openclaw/dist/model-selection-CjMYMtR0.js:12571`.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Introduce a shared `ProviderAdapterRegistry` | Mirrors the provider/plugin architecture seen in OpenCode and keeps provider-specific behavior out of generic transport code |
| Introduce a typed `CredentialResolver` | Mirrors OpenClaw's auth profile semantics and prevents stringly-typed auth handling |
| Keep client bridges thin and provider-aware | Clients choose the current provider; adapters decide how to inject or refresh auth |
| Add per-client `guaranteed` readiness in doctor | Native support should be proven, not implied |
| Keep secrets out of setup artifacts and doctor JSON | Required for safe diagnostics and predictable operator UX |
| `modeio_middleware/core/provider_auth.py` is the new shared foundation module | Centralizes provider normalization, credential inspection, runtime auth resolution, and health snapshots |
| Keep `modeio_middleware/core/client_auth.py` as a facade for now | Minimizes migration risk while we refactor remaining call sites onto the shared foundation |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Codex OAuth token reaches upstream but public OpenAI-compatible routes reject it | Treat Codex as a dedicated native-adapter problem, not a generic passthrough case |
| OpenCode current `openai` provider has no reusable auth on this machine | Plan provider-aware inspection and explicit `not guaranteed` reporting for missing auth |
| OpenClaw native live smoke mixed local cache/config bugs with external rate limiting | Fixed local route/cache sync first, then isolated remaining live failure as upstream `429` |
| Gateway contract subset regressed after OpenClaw family work | Independent rerun showed 4 failing tests: 3 are stale tests tied to old header casing/mock shapes, 1 is a real boundary mismatch where `/clients/openclaw/openai-codex/*` still reaches Codex-native transport even though OpenClaw support intentionally excludes `openai-codex-responses` for now |

## Independent Investigation: Contract Mismatch
- Re-ran `./.venv/bin/python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.unit.test_http_transport tests.integration.test_gateway_contract` on commit `bbb9b77`; result: `52` tests, `2` failures, `2` errors.
- Independently reproduced the four failing integration cases:
  - `test_gateway_preserves_safe_upstream_metadata_headers`: runtime behavior is correct; upstream stub stores request headers with lowercased names (`authorization`, `openai-organization`), so the test is stale rather than the middleware being wrong.
  - `test_client_scoped_route_normalizes_provider_prefixed_model`: adding `resolved_headers={}` to the mocked inspection makes the test pass. The current failure is a stale mock shape after `_build_upstream_headers()` started expecting `resolved_headers`.
  - `test_codex_native_transport_uses_backend_api_paths`: likewise passes once the mocked inspection includes `resolved_headers={}`; this is also a stale mock/test-double issue.
  - `test_client_scoped_openclaw_route_bridges_placeholder_auth`: this is the real mismatch. With host `~/.openclaw` seeded only with `openai-codex` auth, `/clients/openclaw/openai-codex/v1/chat/completions` now bypasses the configured stub upstream and returns `401` from the Codex-native backend instead.
- Interpretation:
  - The first three failures do not block refactor; they are test maintenance.
  - The last failure is a real contract ambiguity. OpenClaw v1 support is currently defined around `openai-completions` and `anthropic-messages`, while `openai-codex-responses` is explicitly deferred, but the generic client-scoped route still allows `openai-codex` to trigger Codex-native transport.
- Recommendation from the investigation:
  - Fix this one boundary mismatch first by making the deferred OpenClaw Codex family explicit, for example rejecting `/clients/openclaw/openai-codex/*` with an unsupported-family error until the dedicated `openai-codex-responses` surface exists, or otherwise gating native Codex transport behind an explicit OpenClaw family contract.
  - After that targeted fix, proceed with the larger refactor. Refactoring before clarifying this contract would bake the wrong boundary into the cleanup.

## Resources
- Middleware worktree context: `/Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass/.worktree-context.md`
- OpenClaw auth/health logic: `/opt/homebrew/lib/node_modules/openclaw/dist/subagent-registry-CkqrXKq4.js`
- OpenCode auth plugin example: `/Users/siruizhang/.cache/opencode/node_modules/opencode-anthropic-auth/index.mjs`
- OpenCode plugin contract: `/Users/siruizhang/.config/opencode/node_modules/@opencode-ai/plugin/dist/index.d.ts`
- Current middleware auth inspection: `/Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass/modeio_middleware/core/client_auth.py`
- Current smoke diagnostics: `/Users/siruizhang/Desktop/ModeIOSkill/.worktrees/middleware--new--backend-quality-pass/.artifacts/live-agent-native-auth/20260310T075237Z-17487/live-openai-agent-matrix/20260310t075241z-17560/summary.json`

## Visual/Browser Findings
- No browser-specific findings captured in this planning slice.

## Implementation Slices
- Slice A: provider/auth foundation (`ProviderAdapterRegistry`, `CredentialResolver`, health model)
- Slice B: `CodexNativeAdapter`
- Slice C: OpenCode provider-native adapter migration
- Slice D: OpenClaw adapter migration and health-aware profile handling
- Slice E: setup/doctor/runtime cleanup
- Slice F: smoke/docs/rollout hardening

## Foundation Progress
- Slice A is now implemented in `modeio_middleware/core/provider_auth.py`.
- The current foundation supports:
  - provider normalization (`codex` -> `openai-codex`, provider-scoped OpenCode/OpenClaw routing)
  - typed credential inspections with sanitized public output
  - a shared resolver for runtime authorization lookup
  - a lightweight health snapshot store for future failure/cooldown handling
- Existing doctor/setup/runtime code still calls `client_auth.py`, but those functions now delegate to the shared foundation instead of duplicating file/env parsing logic.

## Adapter Migration Progress
- `CodexNativeAdapter` now exists as a distinct provider adapter for `openai-codex`, with explicit `transport=codex_native`, `fallbackMode=managed_upstream`, and adapter-owned model normalization.
- OpenCode now resolves the active provider first, both in setup routing (`modeio_middleware/cli/setup_lib/opencode.py`) and in credential inspection (`modeio_middleware/core/provider_auth.py`), instead of assuming `provider.openai` everywhere.
- OpenClaw now resolves through the same shared provider adapter contract; remaining work is health/cooldown richness rather than basic adapter structure.
- `modeio_middleware/connectors/openai_http.py` now delegates model normalization to the shared provider resolver instead of keeping local prefix rules.
- `modeio_middleware/cli/setup_lib/upstream.py` now combines provider-aware auth inspection with base-url-aware env fallback, so managed/live-upstream detection still works for cases like ZenMux configs.
- `modeio_middleware/core/upstream_client.py` now routes Codex-native `/models` and `/responses` traffic to the ChatGPT Codex backend when a native base URL is available, rewrites websocket model flags to `false`, and adds Codex-specific response payload normalization.
- `scripts/smoke_agent_matrix.py` now starts a dedicated Codex tap proxy targeting `https://chatgpt.com/backend-api/codex`, so native Codex backend traffic is observable during live smoke.
- `OpenCode` now rides the same Codex-native backend path automatically when its selected `openai` provider lacks a reusable API key, with middleware injecting a localhost placeholder key only to get the CLI talking to the gateway.
- The smoke harness now distinguishes product failures from external provider/account issues (`outcome`, `productOk`), so OpenClaw `429` conditions no longer fail the whole native-auth smoke slice.

## Current Product Support State
- `Claude`: supported end to end and live-smoke validated.
- `Codex`: supported end to end and live-smoke validated in repo and wheel modes through the ChatGPT Codex backend.
- `OpenCode`: supported end to end and live-smoke validated in repo and wheel modes, including automatic provider-aware fallback onto the Codex-native transport when needed.
- `OpenClaw`: auth/config reuse is proven, but full end-to-end middleware support is not finished yet. The remaining blocker is response-shape compatibility when routing OpenClaw's `openai-codex` path through the Codex-native backend.

## OpenClaw Investigation Result
- Direct `OpenClaw` with a copied untouched local state succeeds: copied `~/.openclaw` returns the expected token using provider `openai-codex` and model `gpt-5.3-codex`.
- The earlier `429` was not the real root cause; it came from a smoke/middleware mismatch where OpenClaw traffic was being sent to `https://api.openai.com/v1/chat/completions` instead of the Codex-native backend.
- After fixing transport selection, the exact copied local OpenClaw state now reaches `https://chatgpt.com/backend-api/codex/responses` through middleware, so auth reuse and upstream routing are correct.
- However, the OpenClaw client still emits empty `payloads` through middleware even though upstream returns success. This shows the remaining bug is on the response adaptation layer: middleware is forwarding Codex-native response events, but OpenClaw expects the shape its own native transport wrapper would produce.
- Conclusion: the previous rate-limit symptom was setup/middleware-induced, not caused by the user's local OpenClaw config. The remaining support gap is a middleware protocol-translation issue, not auth reuse.

## OpenClaw Practical Release Family Findings
- OpenClaw already normalizes many providers, but it does not collapse them all into one universal wire contract. Its config and runtime still distinguish multiple provider API families, including `openai-completions`, `openai-responses`, `openai-codex-responses`, and `anthropic-messages`.
- In OpenClaw config, `api` is configured at the provider level, not the model level. That means one synthetic middleware provider cannot simultaneously represent multiple practical families cleanly.
- For a release-grade middleware integration, OpenClaw should be treated as an explicit managed-provider client with one synthetic provider per practical family rather than a transparent mirror of the user's current OpenClaw provider/runtime state.
- The three practical release families are:
  - `openai-completions` for most API-key and proxy providers (ZenMux, OpenRouter, LiteLLM, vLLM, LM Studio, generic OpenAI-compatible gateways)
  - `anthropic-messages` for Anthropic-compatible providers (Anthropic API key, MiniMax, Synthetic, Kimi Coding, similar gateways)
  - `openai-codex-responses` for the Codex-native backend path already supported through the middleware's Codex work
- Official OpenClaw docs reinforce that provider-family choice matters:
  - MiniMax prefers `anthropic-messages`, with `openai-completions` only as an optional alternative.
  - Ollama warns that its OpenAI-compatible path can break tool calling and recommends its native API instead.
  - Custom providers are configured explicitly via provider entries rather than a hidden universal adapter.
- Comparable products like Crust scope OpenClaw support to explicit local-provider configuration instead of zero-config native OAuth/profile reuse. That supports the decision to keep the OpenClaw v1 boundary explicit and additive.

## Current Middleware vs OpenClaw Family Gap
- Current middleware public HTTP surface:
  - OpenAI-compatible `models`, `chat/completions`, and `responses`
  - Claude hook connector
- Current middleware does not yet expose a generic Anthropic Messages HTTP connector, so `anthropic-messages` support is new boundary work rather than a setup-only change.
- Current middleware already has the hard upstream work for Codex-native traffic, but it is currently presented to OpenClaw through the wrong family boundary (`openai-completions`), which is why response-shape mismatch remains.

## OpenClaw V1 Planning Decision
- Release-grade OpenClaw support should pivot to family-explicit managed providers:
  - `modeio-openai`
  - `modeio-anthropic`
  - `modeio-codex`
- OpenClaw native-profile reuse should be retained only as an experimental path until the three managed families are implemented and validated.

## Test Review Notes
- Branch-vs-`origin/main` changed test surface is concentrated in `tests/unit/test_client_auth.py`, `tests/unit/test_upstream_client.py`, `tests/unit/test_setup_gateway.py`, `tests/smoke/test_smoke_agent_matrix_support.py`, plus `tests/integration/test_gateway_contract.py`, `tests/smoke/test_smoke_client_setup_flows.py`, and `tests/helpers/gateway_harness.py`.
- Early structural pattern: unit coverage is broad but heavily coupled to nested config dict shapes, on-disk OpenClaw state file layouts, and private helper functions. Higher-level integration coverage is stronger for generic gateway routes and Codex/OpenClaw OpenAI-compatible paths than for the newer Anthropic/OpenClaw family path.
- The most important likely gap is higher-level coverage for OpenClaw `anthropic-messages`: unit tests cover transport/header selection and setup rewrites, but no integration/smoke test currently drives `/clients/openclaw/<provider>/v1/messages` through the gateway.

## OpenClaw Family Smoke Findings
- The smoke harness now supports real OpenClaw preserve-provider family runs for the two currently supported families:
  - `openai-completions`
  - `anthropic-messages`
- `scripts/smoke_agent_matrix.py` now resolves family scenarios from copied OpenClaw config/models-cache/auth-profile state, writes per-family sandbox patches, and emits separate reports/artifacts per family.
- `scripts/smoke_e2e.sh` now seeds family-specific OpenClaw fixtures for setup/uninstall and CLI smoke instead of assuming a synthetic `modeio-middleware/middleware-default` provider.
- Current live result on this machine:
  - `anthropic-messages` reaches the intended upstream `/v1/messages` path through the family tap and returns `401`, so the path is real but externally blocked by current auth/account state.
  - `openai-completions` still returns `401` before the intended family tap sees traffic, even after preferring concrete copied providers over generic `auto` entries. That points to a remaining OpenClaw OpenAI-family auth/routing gap, not just a missing smoke scenario.

## Independent Investigation: Contract Mismatch
- Re-ran the exact contract-focused subset that previously surfaced the mismatch:
  - `python -m unittest tests.unit.test_client_auth tests.unit.test_upstream_client tests.unit.test_http_transport tests.integration.test_gateway_contract`
- Result before the fix: four failing cases split into three stale-test issues and one real contract bug.
- The stale cases were:
  - one upstream-header casing assertion in `tests/integration/test_gateway_contract.py`
  - two mocked `SimpleNamespace` inspection objects that no longer matched the runtime inspection shape because they omitted `resolved_headers`
- The real bug was narrower:
  - OpenClaw setup and product intent defer `openai-codex-responses`, but the generic `/clients/openclaw/openai-codex/...` runtime route could still fall through into transport selection and forward placeholder auth toward a generic upstream path.
- Fixed contract decision:
  - public OpenClaw runtime now rejects unsupported/deferred provider families explicitly
  - `openai-codex-responses` remains reusable internally for Codex/OpenCode auth sharing, but it is no longer silently exposed through the OpenClaw route boundary
- Post-fix validation:
  - the same four-module subset now passes cleanly (`55` tests)
  - targeted auth/upstream/integration coverage and adjacent setup/transport tests also pass
- Conclusion:
  - this was not evidence that the whole branch needs emergency rewrites before correctness work
  - the right order is the one we suspected: fix the one wrong boundary first, then do the larger structural refactor on top of the corrected contract

## Refactor Readiness Review
- The branch is now in the right state to start a structural refactor. The public boundary bug is fixed, the contract-focused test slice is green again, and the remaining problems are primarily maintainability and layering problems rather than unresolved correctness bugs.
- Highest-value structural hotspots:
  - `modeio_middleware/cli/setup_lib/openclaw.py`
    - too much duplicated apply/restore logic across config, models cache, managed mode, and preserve-provider mode
    - sidecar/restore correctness still depends on orchestration order rather than one transaction model
  - `modeio_middleware/core/provider_auth.py`
    - credential lookup, provider selection, fallback selection, refresh behavior, and transport hints are still too interleaved
    - runtime behavior still depends on free-form metadata keys like `upstreamBaseUrl`, `overrideBaseUrl`, and `nativeBaseUrl`
  - `modeio_middleware/core/upstream_client.py`
    - endpoint selection, auth precedence, request shaping, error mapping, and transport-specific behavior are still centralized in one large conditional module
  - `scripts/smoke_agent_matrix.py`
    - scenario discovery, patch generation, process orchestration, gateway probes, and report shaping are all in one file
- Clear request-context duplication exists today:
  - `x-modeio-client-provider` parsing is repeated in `http_transport.py`, `engine.py`, `openai_http.py`, and `anthropic_http.py`
  - `_client_provider_name()` is duplicated verbatim in both HTTP connector modules
- Dead / likely-removable surface identified locally:
  - `modeio_middleware/core/sse.py`
    - `parse_sse_data_line()` and `serialize_sse_data_line()` have no internal references
  - `modeio_middleware/core/upstream_transport.py`
    - currently a pure pass-through wrapper with no real policy or behavior of its own
  - `modeio_middleware/connectors/__init__.py`
    - compatibility aliases `ConnectorEvent` and `ClaudeHookInvocation` appear unused internally; external compatibility risk should be checked before removal
  - duplicated `OPENCLAW_SUPPORTED_API_FAMILIES` constants in setup and provider layers should be centralized once the new plan/transaction modules exist
  - `GatewayController.default_profile()` and runtime `runtime_name` fields still look like dead surface candidates and should be rechecked after the refactor
- Recommendation:
  - do not continue with more OpenClaw family feature work first
  - start the staged structural refactor now, with typed runtime plans and OpenClaw transaction rewrite as the first two slices

## Structural Review: Refactor Readiness
- The branch is now ready for refactor.
  - The public OpenClaw Codex boundary mismatch is fixed.
  - The focused contract/auth/transport subset is green again.
  - That means the next work can safely optimize for structure instead of continuing to chase correctness ambiguity.
- The main problem is not hidden dead runtime code. It is concentrated duplication and mixed responsibilities.
- High-confidence deletions in the touched path are limited.
  - The larger maintenance cost comes from multiple overlapping implementations of the same ideas.

## Strict Harness-State Contract Audit
- Product contract clarified:
  - middleware runs on top of an already-working harness
  - middleware does not choose provider, model, profile, or auth for the user
  - middleware does not rescue missing state with fallback, heuristics, or borrowed config
  - preserve the exact harness-selected state or fail clearly

### Remaining drift: runtime auth
- Codex still falls back to `OPENAI_API_KEY` when `~/.codex/auth.json` is missing.
  - File: `modeio_middleware/core/provider_auth.py`
  - Evidence: `_inspect_codex_store()` returns `strategy="provider-env"` when the Codex auth store is absent.
- OpenCode still falls back to provider env vars after config/auth-store lookup.
  - File: `modeio_middleware/core/provider_auth.py`
  - Evidence: `_inspect_opencode_provider()` iterates `_opencode_provider_envs()` and returns `strategy="provider-env"`.
- OpenClaw still falls back to provider env vars for supported families.
  - File: `modeio_middleware/core/provider_auth.py`
  - Evidence: `_openclaw_provider_env_inspection()` returns `strategy="provider-env"`.
- OpenClaw still uses heuristic profile resolution instead of one exact selected profile.
  - File: `modeio_middleware/core/provider_auth.py`
  - Evidence: `OpenClawSelectionResolver.resolve()` chooses `:default` or the first matching profile.
- OpenClaw still infers API family from provider id when config/cache state is missing.
  - File: `modeio_middleware/core/provider_auth.py`
  - Evidence: `_openclaw_current_api_family()` defaults to `anthropic-messages`, `openai-codex-responses`, or `openai-completions` by provider id.

### Remaining drift: smoke harness
- Codex selected-model fallback was the first obvious violation and is now being corrected to require the seeded Codex config unless an explicit `--model` override is provided.
- OpenCode smoke still falls back to a generic model when it cannot resolve the selected one from config/state.
  - File: `scripts/smoke_matrix/sandbox.py`
  - Evidence: `resolve_opencode_smoke_model(..., fallback_model=...)`.
- OpenClaw openai-family smoke still uses first-match heuristics for provider and model selection.
  - File: `scripts/smoke_matrix/openclaw_family.py`
  - Evidence:
    - chooses the first matching OpenAI-compatible provider candidate
    - chooses the first listed model if the current selection is unavailable
    - finally falls back to `args.model`
- OpenClaw anthropic-family smoke still synthesizes provider/model/base-url defaults rather than requiring the exact current harness selection.
  - File: `scripts/smoke_matrix/openclaw_family.py`
  - Evidence:
    - `DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER`
    - `DEFAULT_OPENCLAW_ANTHROPIC_MODEL`
    - `DEFAULT_OPENCLAW_ANTHROPIC_BASE_URL`

### Remaining drift: setup / doctor / UX
- OpenClaw managed-mode scaffolding is still present in setup code even though the clarified product contract is strict preserve-provider or fail.
  - Files:
    - `modeio_middleware/cli/setup_lib/openclaw_common.py`
    - `modeio_middleware/cli/setup_lib/openclaw_routes.py`
    - `modeio_middleware/cli/setup_lib/openclaw_transaction.py`
  - Evidence:
    - `OPENCLAW_AUTH_MODE_MANAGED`
    - `_resolve_managed_route_target()`
    - `_apply_managed_provider_route()`
    - `_apply_managed_models_cache_provider()`
- Doctor/setup language still emphasizes `guaranteed`, `best_effort`, and generalized readiness rather than exact harness-state preservation.
  - File: `modeio_middleware/cli/setup.py`
  - Impact:
    - this is less severe than runtime drift, but it still frames middleware as if it can compensate for missing native state

## Refactor Direction Decision
- The right product contract is now explicit:
  - exact selected harness provider/model/auth only
  - no cross-harness borrowing
  - no same-harness heuristic fallback
  - no managed-mode rescue path in the normal product flow
- That means the next cleanup should not be another feature pass.
- It should be a strict-state enforcement pass that removes remaining fallback/heuristic paths across:
  - runtime auth
  - smoke scenario resolution
  - setup/doctor semantics

### Highest-priority refactor targets
- `modeio_middleware/cli/setup_lib/openclaw.py` (`1456` lines)
  - carries parallel apply/remove/restore logic for:
    - managed provider mode
    - preserve-provider mode
    - config file
    - models-cache file
    - sidecar restore metadata
  - repeated concerns:
    - provider container discovery
    - base-url/api-family mutation
    - created-vs-existing provider handling
    - restore mismatch handling
    - primary-model preservation
  - precise rewrite seam:
    - replace mutation helpers with one route transaction plan that computes desired state once and then applies/restores it symmetrically
- `modeio_middleware/core/provider_auth.py` (`1570` lines)
  - currently mixes:
    - credential discovery
    - token refresh
    - family inference
    - provider fallback selection
    - request-header materialization
    - transport hints for upstream routing
  - repeated patterns:
    - auth materialization (`authorization` vs `resolved_headers`)
    - metadata assembly (`apiFamily`, `upstreamBaseUrl`, `nativeBaseUrl`, fallback fields)
    - near-duplicate OpenClaw profile/models-cache/env/fallback branches
  - precise rewrite seam:
    - separate credential lookup from outgoing auth materialization and from upstream transport planning
- `modeio_middleware/core/upstream_client.py` (`736` lines)
  - orchestration and policy are entangled:
    - explicit incoming auth precedence
    - unsupported-family policy
    - transport URL derivation
    - codex-native request shaping
    - retry/error mapping
  - precise rewrite seam:
    - keep this file as orchestration only and move family-specific behavior into transport strategies
- `scripts/smoke_agent_matrix.py` (`1779` lines)
  - combines:
    - scenario discovery
    - OpenClaw family inference
    - sandbox patch writing
    - process orchestration
    - gateway probes
    - report shaping
  - precise rewrite seam:
    - split into scenario resolution, runner execution, and report assembly modules

### Specific design problems to fix
- Stringly metadata is carrying transport policy.
  - `provider_auth.py` currently emits fields like `apiFamily`, `upstreamBaseUrl`, `nativeBaseUrl`, `overrideBaseUrl`, and fallback model hints inside `inspection.metadata`.
  - `upstream_client.py` then treats those as transport instructions.
  - This is the clearest sign that a typed `ResolvedUpstreamPlan` is needed.
- Explicit incoming auth precedence still lives too late in the flow.
  - `upstream_client.py` calls native inspection before it knows whether a real caller-provided auth header should just win.
  - That risks unnecessary file reads or refresh side effects on requests that should have been pass-through.
- OpenClaw setup/install symmetry is fragile.
  - Apply/uninstall correctness depends on matching current mutated base URLs plus sidecar state, rather than one transaction object that owns both directions.
- Smoke setup knowledge is duplicated between Python and shell.
  - `smoke_e2e.sh` and `smoke_agent_matrix.py` both encode scenario assumptions.
- The tap proxy is not transport-faithful for streaming.
  - It buffers the full upstream body before replaying and then logs previews.
  - That is fine for evidence capture, but not clean if we want it to validate streaming correctness.

### Test architecture findings
- The most common maintenance smell is fixture duplication, not missing assertions.
  - OpenClaw state fixtures are rebuilt by hand across setup, auth, integration, and smoke-support tests.
  - inspection mocks are hand-built in several places and drift easily when the contract grows.
- The next test cleanup should add builders for:
  - OpenClaw config/models-cache/auth-profiles
  - credential inspection objects
  - smoke family scenarios
- Contract tests should assert on public gateway behavior first, not private metadata shape unless that metadata is itself the public contract.

### Refactor decision
- Recommendation: proceed with structural refactor now.
- Scope recommendation:
  - not a full rewrite of the repo
  - yes to a deliberate rewrite of the OpenClaw setup slice
  - yes to a structural refactor of auth/transport planning
  - yes to a smoke infrastructure split, with likely rewrite of the tap proxy

## Structural Review Findings
- The current branch is functionally much healthier than the code shape suggests, but the implementation is now too patch-accumulative to extend safely without a structural pass.
- The three highest-value refactor seams are:
  1. `modeio_middleware/cli/setup_lib/openclaw.py`
     - It now contains four partially parallel workflows:
       - managed config apply/remove
       - managed models-cache apply/remove
       - preserve-provider config apply/restore
       - preserve-provider models-cache apply/restore
     - The file repeats the same concerns in slightly different forms:
       - provider lookup/container creation
       - `baseUrl` and `api` patching
       - backup/write bookkeeping
       - uninstall mismatch handling
       - sidecar metadata interpretation
     - This should be rewritten around one typed route transaction/plan model rather than further helper accretion.
  2. `modeio_middleware/core/provider_auth.py` + `modeio_middleware/core/upstream_client.py`
     - The resolver is doing too many jobs at once:
       - file/env state loading
       - OpenClaw provider selection policy
       - credential shaping
       - cross-client auth sharing
       - transport-target hints via free-form metadata
       - model normalization
     - `upstream_client.py` then interprets that stringly metadata (`upstreamBaseUrl`, `overrideBaseUrl`, `nativeBaseUrl`, `fallbackModelId`) as routing truth.
     - This is the core layering problem: credential inspection and transport planning are still entangled.
  3. `scripts/smoke_agent_matrix.py` + `scripts/smoke_e2e.sh` + `scripts/upstream_tap_proxy.py`
     - `smoke_agent_matrix.py` is simultaneously a scenario resolver, setup/doctor runner, process supervisor, gateway probe runner, report assembler, and CLI.
     - `smoke_e2e.sh` duplicates scenario knowledge and summary semantics that already exist in Python.
     - `upstream_tap_proxy.py` is adequate for request evidence, but it is not a transport-faithful streaming tee because it buffers full upstream responses before forwarding.
- Test burden is also too coupled to implementation details:
  - `tests/unit/test_setup_gateway.py` hand-builds many near-duplicate OpenClaw config/cache fixtures.
  - `tests/integration/test_gateway_contract.py` still patches low-level inspection objects directly rather than leaning on stable builders.
  - `tests/smoke/test_smoke_agent_matrix_support.py` asserts script heuristics rather than a formal scenario object contract.
- A few dead-surface candidates exist, but they should be deleted only after the structural seams are stabilized:
  - compatibility/barrel alias surfaces
  - legacy managed-provider-only OpenClaw branches that no longer represent the release contract
  - smoke wrapper logic that becomes redundant once Python is the single source of truth

## Structural Refactor Implementation Findings
- The typed upstream-plan split is viable without a contract break.
  - `CredentialInspection` can stay as the compatibility facade while `ResolvedCredential`, `ResolvedAuthMaterial`, and `ResolvedUpstreamPlan` carry the real runtime boundary.
  - This lets existing callers migrate incrementally instead of forcing a repo-wide cutover in one patch.
- Request-context parsing was a real duplication seam.
  - Moving client/provider route parsing into `modeio_middleware/core/request_context.py` removed repeated header parsing from connectors and made the transport path easier to reason about.
- The OpenClaw setup rewrite was worth doing as a file split before any deeper semantics change.
  - `openclaw.py` dropped from a monolith into a thin facade backed by common helpers, route planning, and transaction-oriented apply/restore helpers.
  - That immediately removed the worst repeated config/models-cache patch scaffolding.
- The smoke split also paid off immediately.
  - `scripts/smoke_agent_matrix.py` is now mostly CLI composition, while family selection and execution logic moved into focused modules.
  - This is enough to make future smoke work additive instead of forcing more edits into a single 1700-line script.
- Test maintenance risk was concentrated in inspection-shaped mocks.
  - A small `build_inspection(...)` helper removed the most brittle `SimpleNamespace` duplication in the upstream/gateway tests.
  - More fixture consolidation is still useful, but the highest-drift surface is already addressed.
- The remaining cleanup category is now mostly deletion and consolidation, not architecture discovery.
  - The main gate is done.
  - Future cleanup can be targeted by zero-usage proof and normal review, rather than another exploratory design pass.

## Post-Refactor Smoke Findings
- The refactor did not break the middleware runtime contract, but it did break the smoke CLI entrypoints in small, real ways.
  - `smoke_agent_matrix.py` and `smoke_matrix/runner.py` both lost standard-library imports during the split.
  - The smoke-support tests were not exercising those exact entrypoint paths strongly enough to catch the missing imports before the live run.
- `smoke_e2e.sh` still held one hidden policy decision after the Python split.
  - The wrapper was not forwarding explicit upstream base/model overrides into `smoke_agent_matrix.py`.
  - In this environment that meant live smoke silently fell back to `https://api.openai.com/v1` + `gpt-4o-mini`, which is not the intended release validation path.
- The `opencode` investigation confirmed the architectural distinction:
  - transport is normalized enough that we do not need an OpenClaw-style provider-family matrix
  - auth reuse is still a separate concern because middleware must choose between direct selected-provider auth and shared native fallback
  - the OpenAI-specific native bridge for `opencode` remains the main special case, not a sign that `opencode` needs the same integration model as OpenClaw
  - the passing release smoke also showed that force-injecting a placeholder OpenCode API key is no longer required for the localhost setup path in this branch; preserving a missing key avoids one more auth-precedence edge case

## Session: 2026-03-10 17:35 UTC strict harness-owned auth correction
- OpenCode built-in `openai` with ChatGPT OAuth is not redirectable through middleware preserve-provider mode.
  - Upstream OpenCode source (`packages/opencode/src/plugin/codex.ts`) rewrites the OAuth `openai` path with a custom `fetch` directly to `https://chatgpt.com/backend-api/codex/responses`.
  - Because that happens inside OpenCode after provider setup, mutating `provider.openai.options.baseURL` or `OPENAI_BASE_URL` cannot force that path through middleware.
- Middleware contract correction:
  - OpenCode stays supported only when the selected provider is redirectable through its configured base URL.
  - Built-in `openai` with OAuth is now explicitly unsupported instead of being treated as a routing bug or being rescued by fallback behavior.
- Implementation result:
  - OpenCode setup now returns `supported: false` with reason `provider_uses_internal_oauth_transport` for that case and leaves the config unpatched.
  - Runtime auth inspection returns `strategy=unsupported_transport` for the same case so doctor/runtime no longer claim the path is reusable.
  - Live smoke skips the unsupported OpenCode OAuth scenario and keeps the matrix green for the intended routed scenarios.
