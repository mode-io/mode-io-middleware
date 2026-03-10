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

## OpenClaw Family Smoke Findings
- The smoke harness now supports real OpenClaw preserve-provider family runs for the two currently supported families:
  - `openai-completions`
  - `anthropic-messages`
- `scripts/smoke_agent_matrix.py` now resolves family scenarios from copied OpenClaw config/models-cache/auth-profile state, writes per-family sandbox patches, and emits separate reports/artifacts per family.
- `scripts/smoke_e2e.sh` now seeds family-specific OpenClaw fixtures for setup/uninstall and CLI smoke instead of assuming a synthetic `modeio-middleware/middleware-default` provider.
- Current live result on this machine:
  - `anthropic-messages` reaches the intended upstream `/v1/messages` path through the family tap and returns `401`, so the path is real but externally blocked by current auth/account state.
  - `openai-completions` still returns `401` before the intended family tap sees traffic, even after preferring concrete copied providers over generic `auto` entries. That points to a remaining OpenClaw OpenAI-family auth/routing gap, not just a missing smoke scenario.
