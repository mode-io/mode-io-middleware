# Findings

## Locked Product Decisions
- Normalized payload is the primary product contract for plugins and traces.
- Raw/native payload remains available only as a debug/escape hatch.
- Source instructions are read-only; middleware/plugin-added context must be additive.
- Semantic rewrites must fail closed when they cannot be denormalized back to the current native connector shape.
- Streaming should surface semantic units instead of raw RFC6902-style patch targets.

## Current Seam Audit
- `CanonicalInvocation`, `HookEnvelope`, `PluginManager`, and `RequestJournalService` are still raw-body-first.
- External protocol handling still assumes `request_body` / `response_body` / `event` plus RFC6902 patches.
- Built-in and example plugins still read raw request/response bodies directly.
- The best shared refactor seam is:
  - connector/request boundary for normalization
  - hook envelope / plugin manager for semantic mutations
  - connector/stream boundary for denormalization

## Immediate Risks
- OpenAI/Anthropic/Claude all encode prompts, actions, and observations differently, so unit metadata must preserve enough native mapping to support exact denormalization.
- Stream events are currently raw SSE events; semantic streaming support must be conservative and fail closed when the event does not contain enough information for safe reconstruction.

## Landed Outcome
- Normalized payload is now the primary hook, plugin, and observability surface.
- External stdio plugins receive `payload` plus `native`, and return semantic `operations` instead of raw body patches.
- Connectors normalize and denormalize supported OpenAI, Anthropic, and Claude request/response/event shapes.
- Denormalization failures degrade safely and preserve native harness compatibility instead of emitting partially rewritten native payloads.
- Supported live smoke passed for the current product matrix after the refactor:
  - Codex
  - OpenCode via the supported `opencode` provider
  - OpenClaw `openai-completions`
  - Claude

## Corpus Hardening Outcome
- The live smoke stack can now be reused for richer payload collection by overriding only the prompt and working directory; product behavior and harness support rules stay unchanged.
- The local payload corpus now includes:
  - richer real action-oriented captures for Codex, OpenCode, Claude, and additional OpenClaw prompt traffic
  - canonical local examples for tool calls, tool results, multimodal inputs, and incomplete responses
- Imported JSON captures from the new action runs validated cleanly through normalization + denormalization roundtrips.

## Remaining Corpus Gaps
- Real Anthropic Messages captures are still missing from the live corpus.
- OpenClaw support still only exercises the supported OpenAI-compatible family; there is still no live Anthropic OpenClaw capture on this machine.
- Streaming remains mostly text/SSE sidecar data rather than a dense set of JSON stream event objects.
- Error/degraded coverage is broader than before, but still thin compared with the happy-path and action-oriented samples.
