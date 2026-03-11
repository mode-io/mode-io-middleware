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
