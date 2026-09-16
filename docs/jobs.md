# Job identity, retries and errors

Apply the backend migration before starting the API and workers:

```sh
python manage.py migrate
```

## Initialization

`POST /api/v1/open-chat/` reuses the latest job for the user's current document. Reloading the loading page follows that job. A failed job is retained until an explicit request with `retry: true` creates a new job for that document. A task uses the document stored on its job, even if the user uploads another document before the worker starts.

`GET /api/v1/job-status/<UUID>/` returns the canonical `job_id`, document, status, progress, `error`, `error_code`, and `retryable`. Malformed UUIDs return 400; unknown jobs return 404. Queue failures return 503 with the failed job ID. Initialization tasks have a 30-minute soft limit and a 31-minute hard limit. A pending or processing job with no progress for 35 minutes becomes a retryable `initialization_timeout` when checked.

The loading page polls sequentially, stops for terminal states, and stops after three consecutive connection/server failures. **Check again** follows the same job. **Retry initialization** creates a new job after a saved failure.

## Analysis

Clients may supply a UUID `request_id` to `POST /api/v1/start-analysis/`. Repeating the same request ID, conversation and configuration returns the same batch. Reusing an ID for different inputs returns 409. The app shares request IDs across effect remounts and page reloads; an explicit Run action gets a new ID.

The database is authoritative for the batch's user, conversation, document and configuration. Cached request data cannot override those bindings. An optional `conversation_id` on the status request detects a saved batch belonging to another conversation.

Only one worker owns a batch at a time. Its lease renews every 20 seconds and can be reclaimed after 120 seconds without renewal. Reconnecting clients receive `WAITING` while current work finishes, follow live updates when the channel layer is available, and recover saved results by polling. A disconnected worker may finish and save its current variant; subsequent variants can resume on the reconnect. Engine locks protect document selection and retrieval settings while a shared engine is in use.

Each variant has one durable success or failure. REST reports `completed`, `failed`, `finished`, `is_complete` (all succeeded) and `is_finished` (all have an outcome). A WebSocket `COMPLETE` frame also reports `outcome`: `completed`, `partial_failure`, or `failed`. Failures replay on reload without automatically repeating provider calls. Run Deep Analysis again to retry with a new batch.

Fatal WebSocket errors include `status: ERROR`, `terminal: true`, `error`, `error_code` and `retryable`. They close the stream and appear on the page. A failed variant includes its method and model and allows the remaining variants to continue.

## Embeddings

OpenRouter embedding requests use the OpenAI SDK, up to 64 inputs per request, a 45-second SDK timeout and one SDK retry. Responses must contain exactly one finite, nonzero vector per input. Input indices determine vector order; missing or duplicate indices and mismatched dimensions are errors. All vectors validate before replacing an index. Chunk changes roll back if indexing fails, and Hybrid swaps its two indexes together.

Saved dense/hybrid indexes require a matching embedding-model stamp. Old unstamped indexes rebuild on first use, as do incompatible or malformed indexes. This can incur new embedding calls after upgrading. Ollama reranking also uses a 45-second timeout and validates its vectors before scoring. No Torch dependency is added.

Common public error codes include `missing_provider_key`, `provider_authentication`, `provider_credits`, `provider_rate_limit`, `provider_timeout`, `provider_unreachable`, `provider_request_rejected`, `provider_unavailable`, `reranker_unavailable`, `invalid_embeddings`, and `empty_model_response`. Provider response bodies are retained in server diagnostics, rather than exposed to the browser. Ragas metric failures remain individual unavailable metric outcomes.

Migration 0014 adds durable errors, execution leases and a unique batch/method/model constraint. For existing duplicate variants, it retains the newest nonempty answer and archives the superseded rows' contents in that result's `evaluation_metrics` under `superseded_results` before removing duplicate rows.
