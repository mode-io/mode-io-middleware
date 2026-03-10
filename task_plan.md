# Task Plan: Native Auth Middleware Refactor

## Goal
Refactor `modeio-middleware` so a user with an already authed supported harness (`codex`, `opencode`, `openclaw`, or `claude`) can start middleware and use it naturally without extra provider setup, while keeping managed-upstream mode as an explicit fallback.

## Current Phase
Phase 8

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
- [ ] Validate repo + wheel on `claude`, `openclaw`, `opencode`, and `codex`, with per-client diagnostics.
- [ ] Update docs and migration notes; prepare PR slices or one large staged PR if the diff stays reviewable.
- **Status:** in_progress

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

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Codex native bridge reaches upstream but public routes reject current token/scope | 1 | Treat as dedicated adapter problem, not a generic passthrough bug |
| OpenCode current provider lacks reusable auth on this machine | 1 | Plan provider-aware auth inspection and explicit `not guaranteed` reporting |
| OpenClaw live failures mixed local config bugs with upstream rate limiting | 1 | Fixed local route/cache sync first, then isolated remaining `429` as external state |
| Directly editing auth logic across setup, transport, and smoke paths would create another entangled pass | 1 | Added a shared provider-auth foundation first, then kept existing APIs as thin wrappers |
| Provider-aware upstream selection initially regressed the ZenMux fallback expectation in setup tests | 1 | Reintroduced base-url-aware env fallback after provider-auth inspection |
| Codex native traffic originally bypassed live smoke tap evidence and targeted the wrong upstream path | 1 | Added a dedicated Codex native tap proxy and routed Codex-native transport to `/backend-api/codex` |

## Execution Notes
- Preferred implementation order: shared provider/auth foundation -> Codex adapter -> OpenCode adapters -> OpenClaw migration -> setup/doctor cleanup -> smoke/rollout.
- Keep the refactor additive first, then reductive: introduce adapters beside current logic, migrate call sites, remove old paths only after tests and smoke are green.
- Use dedicated validation gates after each phase; do not wait until the end to discover compatibility drift.
