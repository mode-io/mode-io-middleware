# Task Plan: Native Auth Middleware Refactor

## Goal
Refactor `modeio-middleware` so a user with an already authed supported harness (`codex`, `opencode`, `openclaw`, or `claude`) can start middleware and use it naturally without extra provider setup, while keeping managed-upstream mode as an explicit fallback.

## Current Phase
Phase 9

## Phases

### Phase 1: Discovery and contract definition
- [x] Capture current native-auth behavior for Codex, OpenCode, OpenClaw, and Claude.
- [x] Confirm which failures are middleware bugs versus client/account/provider limitations.
- [x] Research OpenClaw and OpenCode auth/provider architecture patterns.
- **Status:** complete

### Phase 2: Architecture and execution planning
- [x] Define the target contract: native auth by default, managed upstream only by explicit choice.
- [x] Define the shared abstraction layers needed for the refactor.
- [x] Break implementation into safe slices with dedicated validation gates.
- **Status:** complete

### Phase 3: Shared auth/provider foundation
- [x] Introduce `ProviderAdapterRegistry` for provider-specific request/auth behavior.
- [x] Introduce `CredentialResolver` / `CredentialHealthStore` abstractions with typed outputs (`oauth`, `token`, `api_key`, `missing`).
- [x] Move client-specific auth inspection logic behind provider-aware interfaces.
- [x] Define provider normalization and auth-sharing rules (`openai`, `openai-codex`, `anthropic`, `openrouter`, etc.).
- [x] Keep secrets runtime-only; no token persistence in generated client config or doctor JSON.
- **Status:** complete

### Phase 4: Codex native adapter
- [x] Create `CodexNativeAdapter` with dedicated auth loading and adapter-owned request shaping/model normalization hooks.
- [x] Stop relying on generic public OpenAI-compatible `/v1/responses` assumptions for Codex native mode for model discovery and response routing.
- [x] Add Codex-specific readiness reporting (`guaranteed`, `best_effort`, `managed_required`).
- [x] Define explicit fallback behavior when Codex native auth cannot satisfy upstream requirements.
- **Status:** complete

### Phase 5: OpenCode provider-native adapters
- [x] Refactor OpenCode bridging to resolve the current provider first, then delegate to a provider adapter.
- [x] Support config-held API keys and provider env keys through the shared provider resolver.
- [x] Preserve provider-specific model routing and protocol quirks at request time.
- [x] Mark OpenCode native mode as guaranteed only when the active provider has a reusable auth source.
- **Status:** complete

### Phase 6: OpenClaw adapter migration
- [x] Replace ad hoc OpenClaw bridging with provider-adapter-backed auth resolution.
- [x] Add profile health, `lastGood`, and cooldown-aware selection where appropriate.
- [x] Preserve current native provider/profile by default; keep managed mode explicit.
- [x] Verify sidecar restore metadata and uninstall/idempotence remain stable.
- [ ] Translate Codex-native backend responses/events into the shape OpenClaw expects for the exact copied local path.
- **Status:** in_progress

### Phase 7: Setup, doctor, routes, and runtime cleanup
- [x] Refactor setup/doctor to report per-client `ready`, `guaranteed`, `strategy`, `reason`, and fallback mode.
- [ ] Audit client-scoped routes so routing, model discovery, and transport all use the same provider-aware contract.
- [x] Reduce duplicated auth/routing logic across `setup.py`, `client_auth.py`, smoke harness, and transport.
- [ ] Preserve backward compatibility for existing managed-mode users.
- **Status:** in_progress

### Phase 8: Smoke/test matrix and rollout
- [x] Add provider-adapter unit tests and per-client integration coverage.
- [x] Expand smoke matrix for native-auth guarantee checks in repo and wheel modes.
- [x] Add OpenClaw family-aware smoke infrastructure for the supported preserve-provider families (`openai-completions`, `anthropic-messages`) across `smoke_agent_matrix.py`, sandbox seeding, and `smoke_e2e.sh`.
- [ ] Validate repo + wheel on `claude`, `openclaw`, `opencode`, and `codex`, with per-client diagnostics.
- [ ] Update docs and migration notes; prepare PR slices or one large staged PR if the diff stays reviewable.
- **Status:** in_progress

### Phase 9: OpenClaw family-boundary redesign
- [ ] Pivot the OpenClaw v1 contract from provider-native zero-config reuse to explicit managed families.
- [ ] Replace the single synthetic OpenClaw provider assumption with three family-scoped providers, because OpenClaw's `api` is configured at the provider level rather than the model level.
- [ ] Freeze current native-profile reuse work behind an experimental path so it no longer blocks release-grade OpenClaw support.
- [ ] Define the v1 support matrix and setup UX for:
  - `modeio-openai` -> `api: "openai-completions"`
  - `modeio-anthropic` -> `api: "anthropic-messages"`
  - `modeio-codex` -> `api: "openai-codex-responses"`
- **Status:** planned

### Phase 10: OpenClaw `openai-completions` family
- [ ] Keep the existing OpenAI-compatible gateway surface as the base for OpenClaw's explicit managed provider path.
- [ ] Add family-specific OpenClaw setup/install metadata so this provider can be added or removed without touching other OpenClaw providers.
- [ ] Validate `models` plus `chat/completions` behavior for common API-key and proxy upstreams (ZenMux, OpenRouter, LiteLLM, vLLM, LM Studio, generic OpenAI-compatible gateways).
- [ ] Add focused OpenClaw integration tests for the managed provider path instead of native-profile reuse.
- **Status:** planned

### Phase 11: OpenClaw `anthropic-messages` family
- [ ] Add a generic Anthropic Messages HTTP connector surface to middleware; the current repo only exposes OpenAI-compatible routes plus Claude hooks.
- [ ] Build request/response canonicalization so plugins and observability work against Anthropic-style requests as a first-class public gateway surface.
- [ ] Add OpenClaw managed provider setup for Anthropic-compatible upstreams (Anthropic API key, MiniMax, Synthetic, Kimi Coding, other Anthropic-compatible providers).
- [ ] Add model discovery and integration coverage for Anthropic-compatible OpenClaw provider entries.
- **Status:** planned

### Phase 12: OpenClaw `openai-codex-responses` family
- [ ] Stop forcing the OpenClaw Codex path through `openai-completions`; instead expose a dedicated OpenClaw-facing Codex responses family that matches the client's own abstraction.
- [ ] Reuse the existing middleware Codex-native upstream work (`/backend-api/codex/models`, `/backend-api/codex/responses`) behind that family boundary.
- [ ] Implement only the response/event adaptation required for the OpenClaw `openai-codex-responses` contract, rather than mirroring the entire OpenClaw provider-runtime stack.
- [ ] Keep Codex-family OpenClaw setup explicit and additive; no automatic reuse of current OpenClaw provider/profile state in v1.
- **Status:** planned

### Phase 13: Setup, doctor, and release UX for OpenClaw
- [ ] Update `modeio-middleware-setup` so OpenClaw installs one or more family-specific providers instead of a single catch-all provider.
- [ ] Make setup additive by default: add middleware providers, but do not overwrite the user's primary OpenClaw model unless explicitly requested.
- [ ] Extend doctor output to report family readiness separately (`openai-completions`, `anthropic-messages`, `openai-codex-responses`) with explicit upstream/auth requirements.
- [ ] Document the minimal-user-flow for each family and the release-time unsupported cases.
- **Status:** planned

### Phase 14: OpenClaw release validation
- [ ] Validate repo + wheel packaging for all three OpenClaw practical families with explicit fixtures and smoke slices.
- [ ] Add regression tests for setup install/uninstall idempotence across all three synthetic providers.
- [ ] Confirm monitoring, plugin blocking/modification, and dashboard traces remain consistent across the three families.
- [ ] Prepare release notes that separate managed OpenClaw family support from deferred experimental native-profile reuse.
- **Status:** planned

## Key Questions
1. What exact backend/transport contract should `CodexNativeAdapter` target so native auth is actually valid end to end?
2. How should provider adapters expose refresh, request injection, and protocol rewrite hooks without duplicating transport code?
3. Which provider aliases should share auth domains (`openai` vs `openai-codex`, `anthropic` variants, etc.)?
4. Should credential health/cooldown live only in smoke/runtime memory first, or persist in a repo-local runtime store?
5. What minimum compatibility promise should doctor enforce before calling a client path `guaranteed`?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Native auth is the default product contract | Matches user expectation that an already authed harness should just work through middleware |
| Managed upstream remains explicit fallback | Needed for unsupported clients/providers and operational overrides |
| Provider adapters are the main seam, not client heuristics | OpenCode and OpenClaw both separate provider selection from auth injection/refresh |
| Per-client readiness must report `guaranteed` vs `best_effort` | Prevents over-claiming support when a bridge exists but upstream/account constraints still block success |
| Codex needs a dedicated native adapter | Current generic OpenAI-compatible bridge is not sufficient or reliable |
| `client_auth.py` stays as a compatibility facade over the new foundation | Lets the refactor land additively without breaking existing call sites while the deeper adapter migration continues |
| OpenClaw v1 should be family-explicit, not provider-native zero-config | OpenClaw's `api` abstraction is provider-level, so a release-grade integration needs one synthetic provider per practical family rather than one universal provider |
| OpenClaw support should ship around three practical families | `openai-completions` covers most API-key/proxy gateways, `anthropic-messages` covers Anthropic-compatible providers like MiniMax, and `openai-codex-responses` covers the Codex-native path we already support for Codex CLI |
| The current OpenClaw native-profile reuse path should not block release | It is valuable investigation, but managed family support is the simpler release boundary and matches how comparable tools scope OpenClaw support |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Codex native bridge reaches upstream but public routes reject current token/scope | 1 | Treat as dedicated adapter problem, not a generic passthrough bug |
| OpenCode current provider lacks reusable auth on this machine | 1 | Plan provider-aware auth inspection and explicit `not guaranteed` reporting |
| OpenClaw live failures mixed local config bugs with upstream rate limiting | 1 | Fixed local route/cache sync first, then isolated remaining `429` as external state |
| Directly editing auth logic across setup, transport, and smoke paths would create another entangled pass | 1 | Added a shared provider-auth foundation first, then kept existing APIs as thin wrappers |
| Provider-aware upstream selection initially regressed the ZenMux fallback expectation in setup tests | 1 | Reintroduced base-url-aware env fallback after provider-auth inspection |
| Codex native traffic originally bypassed live smoke tap evidence and targeted the wrong upstream path | 1 | Added a dedicated Codex native tap proxy and routed Codex-native transport to `/backend-api/codex` |
| OpenClaw `api` is provider-level, so one synthetic middleware provider cannot cleanly represent multiple practical families | 1 | Plan family-specific OpenClaw providers (`modeio-openai`, `modeio-anthropic`, `modeio-codex`) instead of one catch-all provider |
| Middleware currently lacks a generic Anthropic Messages HTTP surface | 1 | Treat Anthropic-family OpenClaw support as explicit new boundary work rather than a small config tweak |

## Execution Notes
- Preferred implementation order: shared provider/auth foundation -> Codex adapter -> OpenCode adapters -> OpenClaw migration -> setup/doctor cleanup -> smoke/rollout.
- Keep the refactor additive first, then reductive: introduce adapters beside current logic, migrate call sites, remove old paths only after tests and smoke are green.
- Use dedicated validation gates after each phase; do not wait until the end to discover compatibility drift.

## OpenClaw Practical Release Plan

### Family matrix

| Family | OpenClaw `api` | Example upstreams to cover | Current middleware state | Main work |
|--------|-----------------|----------------------------|--------------------------|-----------|
| OpenAI-compatible | `openai-completions` | ZenMux, OpenRouter, LiteLLM, vLLM, LM Studio, generic OpenAI-compatible APIs | Mostly present via `/v1/chat/completions` + `/v1/models` | Stabilize OpenClaw managed setup and family-specific tests |
| Anthropic-compatible | `anthropic-messages` | Anthropic API key, MiniMax, Synthetic, Kimi Coding, other Anthropic-compatible gateways | Missing as a generic HTTP gateway surface | Add public Anthropic Messages connector + transport + tests |
| Codex-native | `openai-codex-responses` | Codex CLI / ChatGPT OAuth via existing middleware Codex support | Upstream support exists, OpenClaw-facing contract is missing | Expose a dedicated OpenClaw Codex family boundary and adapt only that response shape |

### Release constraints

- OpenClaw setup must be additive. Installing middleware providers must not erase or silently replace the user's existing providers by default.
- OpenClaw provider entries must be family-specific because the `api` selector is configured per provider, not per model.
- The v1 path should be managed and explicit. Experimental native-profile reuse can remain in the branch, but it should not define the release contract.
- Family readiness should be independent: a bug in `openai-codex-responses` must not block release of `openai-completions` or `anthropic-messages`.

### Proposed implementation order

1. Reset the OpenClaw contract around three managed families and stop extending the catch-all provider path.
2. Ship `openai-completions` first because the gateway surface already exists and covers the broadest upstream set.
3. Ship `anthropic-messages` second because it unlocks Anthropic-compatible providers and requires the largest new boundary surface.
4. Ship `openai-codex-responses` third by reusing the existing Codex-native upstream work behind a dedicated OpenClaw-facing contract.
5. Update setup, doctor, docs, and smoke only after the family boundaries are explicit and testable.
