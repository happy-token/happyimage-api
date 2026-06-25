# Image Conversation Persistence Design

## Problem

The current image workspace stores the user-facing conversation model in browser-local storage and stores only image task records on the server. A new browser can load server tasks, but tasks are not a reliable source of truth for conversations, turns, result ordering, deletion state, or retries. Inferring conversations from task IDs has already produced incorrect session splitting.

## Goals

- Make server-side image conversations the authoritative source of history.
- Preserve the existing async image task execution flow.
- Ensure new browser sessions load the same conversations, turns, and gallery items for the same user.
- Stop guessing conversation structure from old `image_tasks`.
- Keep the implementation incremental and compatible with JSON, SQLite, and Postgres storage modes.

## Non-Goals

- Do not migrate old task-only history into server conversations.
- Do not redesign image generation, model routing, or image storage.
- Do not change official gallery behavior.
- Do not attempt semantic grouping by prompt, time, or task ID for legacy records.

## Data Model

Add a server-side image conversation store with three logical record types.

`ImageConversation`

- `id`: client-generated stable ID.
- `owner_id`: authenticated user ID.
- `title`: user-editable title.
- `created_at`, `updated_at`.
- `deleted_at` optional soft-delete marker.

`ImageTurn`

- `id`: client-generated stable ID.
- `conversation_id`.
- `owner_id`.
- `prompt`.
- `model`.
- `mode`: `generate` or `edit`.
- `reference_images`: metadata only by default. Avoid persisting large base64 blobs unless a later reference-image storage feature needs it.
- `count`, `size`, `ratio`, `tier`, `quality`.
- `status`: `queued`, `generating`, `success`, or `error`.
- `error`.
- `prompt_deleted`, `results_deleted`.
- `created_at`, `updated_at`.

`ImageResult`

- `id`: stable image/result ID.
- `conversation_id`.
- `turn_id`.
- `task_id`.
- `status`: `loading`, `success`, or `error`.
- `task_status`: `queued` or `running`.
- `progress`.
- `url`, `revised_prompt`, `error`.
- `duration_ms`.
- `feedback`.
- `created_at`, `updated_at`.

The public API can return conversations as the nested shape already used by the frontend:

```json
{
  "items": [
    {
      "id": "conversation-id",
      "ownerId": "user-id",
      "title": "Title",
      "createdAt": "...",
      "updatedAt": "...",
      "turns": [
        {
          "id": "turn-id",
          "prompt": "...",
          "images": [
            { "id": "image-id", "taskId": "task-id", "status": "success", "url": "..." }
          ]
        }
      ]
    }
  ]
}
```

## Storage

Introduce `services/image_conversation_store.py` and `services/image_conversation_service.py`.

The first implementation should support:

- JSON storage in `data/image_conversations.json`.
- Database storage when `STORAGE_BACKEND` is sqlite/postgres/database.

Database mode can use a single `image_conversations` table containing serialized conversation JSON, similar to the current `image_tasks` table pattern. This keeps the first version small and avoids multi-table migration complexity. The service boundary should still expose conversations, turns, and results as separate logical concepts so the table layout can be normalized later without frontend changes.

## API

Add `api/image_conversations.py`.

Endpoints:

- `GET /api/image-conversations`
  - Returns current user conversations sorted by `updated_at desc`.

- `PUT /api/image-conversations/{conversation_id}`
  - Creates or updates conversation metadata.
  - Used for initial conversation creation and rename.

- `POST /api/image-conversations/{conversation_id}/turns`
  - Creates a turn and its placeholder image results before image tasks are submitted.
  - Request includes prompt, model, mode, size, quality, count, and result IDs.

- `PATCH /api/image-conversations/{conversation_id}/turns/{turn_id}`
  - Updates prompt/result deletion flags, status, and error.

- `PATCH /api/image-conversations/{conversation_id}/results/{image_id}`
  - Updates a result entry for task progress, success, error, duration, revised prompt, and feedback.

- `DELETE /api/image-conversations/{conversation_id}`
  - Soft-deletes the conversation.

All endpoints require identity through existing `require_identity`. Users can only access their own conversations.

## Task Integration

Keep `image_tasks` as the async task execution layer.

When the frontend submits a generation/edit task, include:

- `client_conversation_id`
- `client_turn_id`
- `client_image_id`

The image task service should persist these fields in each task. On task updates:

- When task starts: update corresponding `ImageResult` to `loading`, `task_status=running`, and update turn status to `generating`.
- When task succeeds: update result to `success`, copy `url`, `revised_prompt`, `duration_ms`, feedback, and recompute turn status.
- When task fails: update result to `error`, copy error and duration, and recompute turn status.

If the conversation record is missing, task execution should still complete and persist the task. It should log the missing conversation link rather than failing image generation.

Feedback updates should update both the task feedback and the corresponding conversation result feedback when the client IDs are present.

## Frontend Flow

The `/image` page should treat the server as authoritative.

On load:

1. Load cached local conversations for quick paint if desired.
2. Fetch `GET /api/image-conversations`.
3. Replace local state with server conversations.
4. Write server conversations into local cache.

On create:

1. Generate `conversationId`, `turnId`, and image IDs on the client.
2. Optimistically add the conversation/turn/results to UI.
3. Call backend conversation/turn create APIs.
4. Submit image tasks with the client IDs.
5. Poll tasks as today, but update server conversation results as task status changes.

On rename/delete/prompt delete/results delete:

- Call the conversation API first or optimistically update then reconcile on failure.
- Update local cache after server success.

The user gallery should continue to derive items from `ImageConversation[]`, but the source list should come from the server-backed conversation API.

## Legacy Data Policy

Old `image_tasks` without `client_conversation_id` are not migrated.

Rationale:

- There is no reliable historical mapping from task-only records to frontend conversations.
- Time/prompt heuristics can merge unrelated work.
- Leaving old data alone is less harmful than creating false conversation history.

Existing browser-local conversations may still appear on that same browser until naturally replaced by server-backed history. New browser history correctness starts from the new implementation.

## Error Handling

- Conversation API failures should show a user-visible toast and keep local optimistic state marked recoverable.
- Task execution must not fail solely because a conversation update failed.
- Polling should continue to recover task status from `image_tasks`.
- If task success cannot update a result, log it and allow the next page load/poll to reconcile.

## Testing

Backend tests:

- Create/list conversation for one owner.
- Owner isolation: another user cannot read or mutate the conversation.
- Create turn with placeholder results.
- Task success updates linked result and turn status.
- Task error updates linked result and turn status.
- Rename/delete/prompt-delete/results-delete mutations persist.
- JSON and database store persistence round trips.

Frontend tests:

- API type mapping for server conversations.
- User gallery derivation from server-backed conversations.
- Local cache is overwritten by server data after load.

Manual verification:

- Generate multiple turns in one conversation.
- Open a fresh Chrome profile and log in as the same user.
- Confirm the conversation remains one session with multiple turns.
- Confirm gallery shows all successful results.
- Retry one failed image and confirm it stays inside the same turn/conversation.

## Rollout

1. Add backend store, service, router, and tests.
2. Add frontend API client helpers.
3. Change `/image` load path to fetch server conversations.
4. Change create/rename/delete/update flows to persist server conversations.
5. Keep local cache as fallback only.
6. Remove task-ID-based conversation reconstruction once server conversations are in use.

## Design Decisions

- The first database implementation stores serialized conversation JSON in one table. This is intentionally simple for the first version.
- Reference image persistence remains metadata-only in this design. If cross-browser edit-continuation from reference images is required later, add stored reference images as a separate feature.
