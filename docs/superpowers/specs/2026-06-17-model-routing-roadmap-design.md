# HappyImage Model Routing Roadmap Design

Date: 2026-06-17

## Summary

HappyImage will start its larger architecture cleanup with a backend-core-first roadmap. Phase 1 introduces a model routing service that centralizes model definitions, aliases, capabilities, provider routing, account selection hints, and upstream model slug mapping.

This phase does not rewrite image generation, image editing, chat execution, task queues, quota accounting, logging, or streaming. Existing execution paths remain in place and gradually consume structured model routing decisions from the new service.

## Goals

- Centralize model-related behavior currently spread across protocol handlers, `utils.helper`, `services.protocol.conversation`, `services.protocol.openai_v1_models`, and `services.openai_backend_api`.
- Preserve existing external API behavior for `/v1/models`, `/v1/images/generations`, `/v1/images/edits`, `/v1/chat/completions`, and `/v1/responses`.
- Create a stable foundation for later account-pool decoupling, provider adapter extraction, OAuth service work, token configuration, and frontend/backend separation.
- Keep Phase 1 small enough to implement and verify safely.

## Non-Goals

- Do not replace the current image generation or image editing execution pipeline.
- Do not rewrite `account_service` in Phase 1.
- Do not introduce database-backed model configuration in Phase 1.
- Do not build token configuration UI in Phase 1.
- Do not split Docker services or deploy frontend/backend separately in Phase 1.
- Do not change the public OpenAI-compatible response shape in a breaking way.

## Current Context

The current codebase already exposes OpenAI-compatible routes through FastAPI and serves a Next.js frontend from the same backend process. Model behavior is distributed across several locations:

- `services/protocol/openai_v1_models.py` builds `/v1/models`, mixing upstream anonymous model data with dynamic HappyImage image models from the account pool.
- `utils/helper.py` defines image model constants and helpers such as `split_image_model`, `is_supported_image_model`, and `is_codex_image_model`.
- `services/protocol/conversation.py` validates supported image models, chooses account filters, decides whether to use Web image generation or Codex image generation, and reports unsupported models.
- `services/openai_backend_api.py` maps public image model names to upstream ChatGPT model slugs.
- The frontend treats image models mostly as strings fetched from `/v1/models`.

This distribution makes it harder to add OAuth service behavior, token configuration, new providers, and frontend/backend separation without repeatedly touching the same model conditionals.

## Recommended Approach

Use the "model routing layer" approach for Phase 1.

The new layer will sit between API/protocol code and existing execution code. It interprets a user-provided model string into a structured route. Existing generation/edit/chat code can then consume that route without each module re-implementing model parsing or provider knowledge.

This is preferred over:

- A model catalog only, which would centralize display data but leave provider routing and account filtering scattered.
- A model execution layer, which would be architecturally cleaner but too large for the first phase because it would touch queues, quota, logs, streaming, and upstream adapters all at once.

## Phase 1 Architecture

Add `services/model_service.py` with three main concepts.

### ModelDefinition

Describes a model known to HappyImage.

Fields:

- `id`: canonical public model ID, such as `gpt-image-2` or `codex-gpt-image-2`.
- `aliases`: alternate public names accepted by the API.
- `provider`: the route family, initially `chatgpt_web`, `codex`, or `openai_web_text`.
- `capabilities`: supported capabilities such as `image_generation`, `image_edit`, `chat`, `responses`, or `models_list`.
- `required_source_type`: account source type needed by the model, such as `codex`.
- `allowed_plan_types`: optional plan types such as `plus`, `team`, and `pro`.
- `upstream_model_slug`: model slug sent to the upstream ChatGPT backend.
- `public`: whether the model should appear in `/v1/models`.

### ModelRoute

Describes one resolved request.

Fields:

- `requested_model`: original user input.
- `model_id`: canonical public model ID.
- `base_model_id`: base model after removing plan prefixes.
- `provider`: provider route family.
- `capabilities`: capabilities from the matched definition.
- `account_source_type`: source type to pass to account selection.
- `account_plan_type`: explicit plan type from a model prefix such as `plus-`.
- `account_plan_types`: fallback allowed plan types when no explicit plan prefix is present.
- `upstream_model_slug`: model slug for upstream calls.

### ModelService

Provides stable methods:

- `list_models()`: returns OpenAI-compatible model objects for public models, including dynamic availability where needed.
- `resolve(model)`: returns a `ModelRoute` or raises a typed model error.
- `is_image_model(model)`: replaces scattered image-model checks.
- `is_codex_model(model)`: replaces Codex-specific checks.
- `account_filters_for(model)`: returns account selection hints.
- `upstream_slug_for(model)`: returns the upstream model slug.

Existing helper functions can remain as compatibility wrappers during Phase 1:

- `utils.helper.split_image_model`
- `utils.helper.is_supported_image_model`
- `utils.helper.is_codex_image_model`

Those wrappers should delegate to `ModelService` after migration.

## Data Flow

### `/v1/models`

`services.protocol.openai_v1_models.list_models()` should call `ModelService.list_models()` for HappyImage-owned model definitions. It may continue to fetch upstream anonymous model data as supplemental data, but HappyImage image models should come from the local model catalog.

The route must keep returning an OpenAI-compatible list response:

```json
{
  "object": "list",
  "data": [
    {
      "id": "gpt-image-2",
      "object": "model",
      "owned_by": "happyimage"
    }
  ]
}
```

If HappyImage-specific capability metadata is added later, it should be additive and non-breaking.

### Image Generation and Image Edit

API-level validation, quota reservation, logging, and content filtering remain unchanged.

Before creating or executing a `ConversationRequest`, protocol code resolves the model:

```python
route = model_service.resolve(model)
```

`services.protocol.conversation` uses the route for:

- supported image model validation,
- Codex versus Web image generation selection,
- account selection filters,
- upstream model slug mapping.

### Chat and Responses

Phase 1 only introduces basic model resolution and capability checks for chat and responses. Text execution continues through the existing Web conversation path.

The model catalog should reserve room for text models such as `auto` and `gpt-5-*`, but Phase 1 does not need to fully normalize all text provider behavior.

### Frontend

The frontend continues to fetch `/v1/models` and render model IDs as strings. Phase 1 does not require a UI rewrite.

Future frontend enhancements may use additive fields such as capabilities, grouping, labels, or provider tags. Those fields are out of scope for Phase 1.

## Error Handling

Model errors should be explicit enough for API callers and stable enough for tests.

- Unknown model: return a `400 invalid_request_error` with a message that names the unsupported model.
- Unsupported capability: return `400 invalid_request_error` when a known model is used on an incompatible endpoint.
- No available account: preserve the existing account-pool failure path so users see behavior consistent with current image generation failures.
- Upstream failures: remain handled by existing `OpenAIBackendAPI`, `conversation.py`, and protocol error handling.

Unsupported image model messages should be generated from `ModelService` so the supported model list is not duplicated.

## Compatibility

Phase 1 should preserve existing public models:

- `gpt-image-2`
- `codex-gpt-image-2`
- `plus-codex-gpt-image-2`
- `team-codex-gpt-image-2`
- `pro-codex-gpt-image-2`
- existing text models returned from upstream where applicable

Existing API callers should not need to change request payloads.

Compatibility wrappers in `utils.helper` allow migration to be incremental. This avoids rewriting every call site in the same implementation step.

## Testing

Add focused tests for `ModelService`.

Required cases:

- `gpt-image-2` resolves to Web image provider with upstream slug `gpt-5-3`.
- `codex-gpt-image-2` resolves to Codex provider with allowed plan types `plus`, `team`, and `pro`.
- `plus-codex-gpt-image-2`, `team-codex-gpt-image-2`, and `pro-codex-gpt-image-2` resolve to Codex provider with explicit account plan filters.
- Unknown model raises the typed unknown-model error.
- Known model used with unsupported capability raises the typed unsupported-capability error.
- `/v1/models` can still return OpenAI-compatible model items.
- Legacy helper functions return results consistent with `ModelService`.

Also run Python compile checks for touched backend modules.

## Roadmap

### Phase 1: Model Routing Layer

Centralize model definitions, aliases, capabilities, provider route decisions, account selection hints, and upstream slug mapping.

### Phase 2: Account Pool Decoupling

Refactor account pool code so it owns token storage, refresh, quota state, account status, and generic account filtering. It should not need to know the business details of ChatGPT Web versus Codex reverse-engineered paths.

### Phase 3: Provider Adapter Extraction

Extract provider adapters for ChatGPT Web image generation, Codex image generation, and future providers. `ModelService` returns the provider route; adapters execute provider-specific behavior behind a shared interface.

### Phase 4: OAuth Service and Token Configuration

Add an OAuth service boundary that owns authorization flows, token lifecycle behavior, import/refresh strategy, and token configuration. This phase depends on clearer account-pool and provider boundaries.

### Phase 5: Frontend/Backend Separation

Stabilize API boundaries for the OpenAI-compatible API, Admin API, and frontend-facing API. Support independent frontend/backend deployment and later Docker service separation.

## Acceptance Criteria

- Model-related constants and parsing logic have one primary source in `ModelService`.
- Existing OpenAI-compatible image APIs keep their request and response behavior.
- `/v1/models` remains OpenAI-compatible and includes HappyImage-supported image models.
- Image model validation, Codex detection, account filter selection, and upstream slug mapping can be tested without invoking upstream ChatGPT.
- Phase 2 can start by changing account-pool consumers to accept `ModelRoute` account hints instead of hand-built model conditionals.

## Risks and Mitigations

- Risk: Moving model checks could subtly change model availability.
  Mitigation: Keep compatibility wrappers and add targeted tests for all current image model IDs.

- Risk: `/v1/models` currently mixes upstream model data with local dynamic image models.
  Mitigation: Preserve upstream fetch behavior as supplemental and make local image model output deterministic.

- Risk: Text model behavior is broader than image model behavior.
  Mitigation: Only reserve catalog space for text models in Phase 1; avoid a full text provider rewrite.

- Risk: Account availability is dynamic.
  Mitigation: Keep dynamic account checks in `list_models()` and account selection, while moving only the interpretation of model requirements into `ModelService`.
