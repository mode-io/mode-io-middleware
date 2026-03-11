# Task Plan: Payload Normalization Contract

## Goal
Replace raw provider request/response bodies as the main middleware/plugin/trace surface with one normalized semantic payload contract, while preserving exact denormalization back to supported native connector shapes.

## Current Phase
Phase 8

## Phases

### Phase 1: Contract and seam audit
- [x] Read the payload design doc and lock the normalized-first contract.
- [x] Trace the raw payload path across connectors, hook envelopes, plugin runtimes, and observability.
- [x] Identify the minimal seam for normalization and denormalization.
- **Status:** complete

### Phase 2: Normalized payload core
- [x] Add normalized semantic unit models and public payload shape.
- [x] Add semantic mutation operations and fail-closed validation.
- [x] Add native escape-hatch payload storage for debug/migration only.
- **Status:** complete

### Phase 3: Hook/runtime migration
- [x] Refactor `HookEnvelope` and `PluginManager` to use normalized payload as the primary hook contract.
- [x] Replace raw RFC6902 patch handling in the stdio JSON-RPC runtime with semantic operations.
- [x] Update in-process plugin hooks, example plugin, and built-in redact plugin to the new contract.
- **Status:** complete

### Phase 4: Connector normalization and denormalization
- [x] Normalize supported request/response/event payloads for:
  - OpenAI chat completions
  - OpenAI responses
  - Anthropic messages
  - Claude hooks
- [x] Denormalize modified normalized payloads back to exact native shapes.
- [x] Fail closed on unmappable semantic edits.
- **Status:** complete

### Phase 5: Observability and docs
- [x] Refactor request journal and serializers to show normalized-first traces.
- [x] Keep raw/native payloads as secondary debug data.
- [x] Update `MODEIO_PLUGIN_PROTOCOL.md` and bundled protocol schema/resources.
- **Status:** complete

### Phase 6: Validation
- [x] Update unit/integration/smoke tests to the normalized contract.
- [x] Run the full Python suite.
- [x] Run offline smoke and the supported live smoke matrix.
- **Status:** complete

### Phase 7: Raw payload capture hardening
- [x] Persist full raw request/response sidecars from live smoke instead of preview-only bodies.
- [x] Import richer raw captures into the local-only payload corpus.
- [x] Re-run the supported live smoke matrix with full-body capture enabled.
- **Status:** complete

### Phase 8: Corpus expansion and action-heavy capture
- [x] Add a custom-prompt smoke seam so action-heavy captures can reuse the existing live sandbox/tap flow.
- [x] Capture richer Codex/OpenCode/OpenClaw/Claude payloads with action-oriented prompts in temp workspaces.
- [x] Add local canonical tool-use, tool-result, multimodal, and incomplete-response examples.
- [x] Validate imported JSON captures and new public examples through normalize + denormalize roundtrips.
- **Status:** complete
