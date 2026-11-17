# PRD implementation contract

This file is the shared contract for implementing the RAGReader PRD
(`PRD.md`, kept outside the repo during implementation). Every phase builds on
the names, shapes and rules below. Code may add fields and endpoints, but must
not rename or remove anything defined here without updating this file in the
same change.

## Phase plan

| Phase | PRD sections | Scope |
| --- | --- | --- |
| 1 — Foundation (MVP) | §7–16, §33–43, §50–52 | Workspaces, persistent documents, async staged ingestion, URL ingestion with SSRF protection, persistent conversations, streaming chat, citations, reader, token auth |
| 2 — Observability | §20–21, §32, §44 | Persisted retrieval runs, per-stage telemetry, "Why this answer?" |
| 3 — Advanced retrieval | §17–19, §45 | BM25/hybrid/rerank in chat, pipeline configuration and versioning |
| 4 — Evaluation lab | §26–31, §42, §46 | Datasets, retrieval/generation metrics, experiment registry and comparison |
| 5 — Research platform | §22–25, §47 | Research Mode, multi-document comparison, evidence extraction, contradictions, reports |

Phases run in order. Each phase is committed on branch `prd-implementation`
after both test suites pass.

## Invariants (every phase)

- The deep-analysis product keeps working unchanged: routes
  `/ground-truth/:conversationId/:documentId` and `/deep-result/:conversationId`,
  `POST /api/v1/start-analysis/`, `GET /api/v1/analysis-status/<job_id>/`, the
  `ws/analysis/<job_id>/` WebSocket, candidate pooling, and every endpoint in
  `backend/evaluation/urls.py`.
- Legacy endpoints in `backend/router/urls.py` and `POST /api/v1/sign-up/` keep
  their request and success response shapes. Sign-up may only *add* fields.
  Since the security pass every one of them (except `analysis-config/`), the
  evaluation endpoints and the analysis WebSocket require the bearer token
  and serve only the caller's data (see "Identity and ownership").
- `_build_index` in the three pipelines stays one atomic transaction: a failed
  rebuild must leave the old chunks, ground truth and engines untouched
  (`router/tests_stability.py::IndexStabilityTests::test_failed_embedding_rolls_back_chunk_changes_and_keeps_both_hybrid_indexes`).
  Progress that other connections must see is written *outside* that block.
- The legacy model `router.Conversation` is **one question/answer turn** and is
  the anchor for `GroundTruthChunk`, `GroundTruthResponse` and `AnalysisBatch`.
  It is never renamed, and the PRD's "conversation" (a thread) is a different
  model, `workspace.ChatSession`.
- Tests are hermetic: no network, no Redis, no API keys. Mock Celery `.delay`,
  embedding clients and LLM clients.
- No `print()` in new code; use `logging`.

## Test commands

Backend (Docker image `ragreader-backend:testenv` must exist; see
`docker images | grep ragreader`):

```sh
docker run --rm --entrypoint "" --network none \
  -v /Users/imac/Documents/dev/RagReader/backend:/app -w /app \
  -e DEVELOPMENT_MODE=True -e RAG_DISABLE_ENGINE_INIT=1 -e DATABASE_URL= \
  ragreader-backend:testenv python manage.py test --noinput

docker run --rm --entrypoint "" --network none \
  -v /Users/imac/Documents/dev/RagReader/backend:/app -w /app \
  -e DEVELOPMENT_MODE=True -e RAG_DISABLE_ENGINE_INIT=1 -e DATABASE_URL= \
  ragreader-backend:testenv python manage.py makemigrations --check --dry-run
```

A single module: append e.g. `workspace.tests.test_chat` to the test command.

Frontend (from `frontend/`): `npm run lint` (0 errors), `npm run test:modules`,
`npm run build`.

Baseline before Phase 1: backend 583 tests OK; frontend lint 0 errors and 1
pre-existing warning (`src/components/ui/button.tsx`), 47 module tests pass,
build OK. After Phase 1: backend 699, 91 module tests. After Phase 2: backend
734, 102 module tests. After the security pass (passwords, token on every
endpoint): backend 776, 118 module tests. After Phase 3: backend 829, 129
module tests.

## Backend layout

New Django app **`workspace`** (`backend/workspace/`) owns the PRD domain:

```
workspace/
  apps.py admin.py models.py urls.py serializers.py tasks.py
  auth.py                 token issue + DRF authentication class
  errors.py               ApiError + exception handler for the new API
  views/                  base.py workspaces.py documents.py conversations.py
  services/
    uploads.py            validation, MIME sniffing, storage
    url_fetch.py          SSRF-safe fetcher
    extraction.py         per-source page extraction + cleaning
    ingestion.py          stage runner, start/retry ingestion
    positions.py          chunk → char offsets → pages
    embedding_cache.py    persistent per-document embedding checkpoint
    index_cache.py        in-memory LRU of loaded dense indexes for chat
    chat.py               run_chat_turn(): event generator
    citations.py          [n] marker parsing, evidence objects
    sse.py                SSE framing + WSGI/ASGI transports
    tracing.py            Phase 2: span tracer (bounded, never raises)
    runs.py               Phase 2: save_run(), percentile(), reliability_summary()
    retrieval.py          Phase 3: run_retrieval() — dense, BM25, hybrid, hybrid + rerank
    pipelines.py          Phase 3: pipeline configs, validation, versions, default pipeline
    rerankers.py          Phase 3: Ollama and LLM rerankers (strict parsing)
    llms.py               Phase 3: one shared OpenRouterLLM per pipeline model
  views/runs.py           Phase 2: retrieval runs list/detail/summary
  views/pipelines.py      Phase 3: pipelines, versions, options
  views/indexes.py        Phase 3: index versions (DocumentVector rows)
  tests/                  package; modules named test_*.py
```

`router.Document`, `router.DocumentVector`, `router.Job`, `router.GuestUser`,
`router.Conversation` (legacy turn) and `evaluation.Chunk` stay where they are.
Migrations: `workspace/0001_initial` depends on `router/0014`; the router
schema migration for the new `Document`/`Job` fields depends on
`workspace/0001`; a separate router data migration backfills existing rows.

## Domain model (Phase 1)

### `workspace.Workspace`
`user` FK `router.GuestUser` (CASCADE, related_name `workspaces`), `name`
(max 120), `is_default` bool, `created_at`, `updated_at`. Every user has
exactly one default workspace, created on first need
(`default_workspace_for(user)`); the last workspace cannot be deleted.

### `router.Document` (new fields)
- `workspace` FK `workspace.Workspace`, null, CASCADE, related_name `documents`
- `status` — `Document.Status` TextChoices, max_length 16, indexed, default `QUEUED`:
  `UPLOADING, QUEUED, EXTRACTING, CLEANING, CHUNKING, EMBEDDING, INDEXING, READY, FAILED`
- `status_detail` (max 255, blank) — human text, e.g. `Embedded 640 of 1,000 chunks`
- `progress` 0–100
- `error_stage`, `error_code`, `error_message`, `retryable`
- `mime_type` (max 100, blank), `file_size` (BigInteger, null)
- `metadata` JSON (default dict). Keys: `original_filename`, `page_count`
  (PDF only, else null), `pages` (`[{"number", "start", "end"}]`, PDF only),
  `char_count`, `word_count`, `chunk_count`, `embedding_model`,
  `chunk_config`, `final_url`, `content_type`
- `current_index` FK `router.DocumentVector`, null, SET_NULL — PRD
  `current_index_version_id`
- `ingested_at` (null)
- `source_type` choices gain `docx`.

`Document.name` remains the title column; the API calls it `title`.

Data migration: each user with documents gets a default workspace and their
documents are assigned to it. Documents with a ready dense `DocumentVector`
become `READY` with `current_index` = newest one; the rest become `FAILED`
with `error_code="not_indexed"`, `retryable=True`,
`error_message="This document was added before background ingestion. Re-index it to use it in chat."`.

### `router.Job` (new field)
`kind` (max 16, default `initialize`; the new task uses `ingest`). The new
ingestion task uses the same claim protocol (`PENDING → PROCESSING` by
conditional update), `mark_failed`, and `expire_if_stalled` as
`initialize_rag_task`. Updating the job at every stage/batch keeps the stall
detector from expiring long runs.

### `workspace.ApiToken`
`user` FK GuestUser (CASCADE, related_name `api_tokens`), `key_hash`
(sha256 hex, unique), `created_at`, `last_used_at` (null), `expires_at`
(default `workspace.models.default_token_expiry`: now + `RAG_TOKEN_TTL_DAYS`;
migration `workspace/0003_apitoken_expires_at` gave existing rows one such
value). Plaintext tokens are `rr_` + `secrets.token_urlsafe(32)`, returned
once, never stored.

### `router.GuestUser` (new field)
`password` (max 128, blank, default `""`): a Django `make_password` hash;
empty means the account predates passwords and can be claimed once
(migration `router/0017_guestuser_password`). `set_password`,
`check_password` (upgrades outdated hashes) and `has_password`.

### `workspace.ChatSession` (API name: conversation)
`user` FK GuestUser, `workspace` FK (CASCADE, related_name `conversations`),
`title` (max 200, default `New conversation`), `title_is_auto` bool (true until
renamed; the first question sets an auto title, ≤ 80 chars), `documents` M2M
`router.Document` (blank; empty means *all READY documents in the workspace*
at question time), `created_at`, `updated_at` (touched on every message).

### `workspace.ChatMessage`
`session` FK (CASCADE, related_name `messages`), `role` (`user`/`assistant`),
`content`, `status` (`streaming`/`complete`/`failed`), `citations` JSON list
(Evidence objects), `retrieval` JSON (null), `token_usage` JSON (null),
`latency_ms` (null), `error_code`, `error_message`, `retryable`,
`analysis_turn` FK `router.Conversation` (null, SET_NULL), `created_at`,
`updated_at`.

### `workspace.EmbeddingCacheEntry`
`document` FK (CASCADE), `model` (max 200), `text_hash` (sha256 hex of the
exact chunk text), `dimensions`, `vector` (BinaryField, float32
little-endian), `created_at`; unique (`document`, `model`, `text_hash`). This
is the embedding checkpoint (PRD §41): every embedded batch is committed, so a
retry only embeds what is missing. `DenseRAG.index_documents` and
`HybridRAG.index_documents` accept an optional `embedding_cache` and the
pipelines' `_build_index` pass one for the document being built, so the
atomic build reuses committed vectors instead of calling the provider.

## Identity and ownership

- Accounts have passwords. `POST /api/v1/sign-up/` (`USERNAME`, `EMAIL`,
  `PASSWORD`) creates an account (201 + `token` in `data`, legacy envelope),
  or sets the password of a passwordless legacy account whose username *and*
  email match exactly (one-time claim, 200 + `token`, `claimed: true`,
  earlier tokens revoked); otherwise 409 `account_exists`. Passwords go
  through `validate_password` (400 `invalid_request`, messages in
  `details.PASSWORD`). `PASSWORD` is required (400 without it) and new
  usernames cannot contain `@`.
- `POST /api/v1/sign-in/` (`USERNAME` or `EMAIL`, `PASSWORD`; an identifier
  containing `@` is looked up as an email only, otherwise as a username only)
  → 200 `{token, username, email, expires_at}`; unknown account, passwordless
  account and wrong password give the identical 401 `invalid_credentials` (a
  dummy hash is checked when there is no password to check).
  `POST /api/v1/sign-out/` revokes the presenting token (204).
- Sign-up and sign-in are throttled per client by
  `workspace.auth.AuthRateThrottle` (a `ScopedRateThrottle`, scope `auth`,
  rate read per request from `RAG_AUTH_THROTTLE_RATE`, default `10/min`;
  `RAG_NUM_PROXIES` sets DRF's `NUM_PROXIES`, default 1) and per submitted
  identifier by `workspace.auth.AuthIdentifierThrottle`
  (`RAG_AUTH_IDENTIFIER_THROTTLE_RATE`, default `20/hour`) → 429 `rate_limited`.
- `workspace.auth.GuestTokenAuthentication` reads `Authorization: Bearer <token>`
  through `resolve_token` (prefix, SHA-256 lookup, expiry; expired rows are
  deleted). `authenticate_header()` returns `Bearer`, so missing/invalid
  credentials give **401**. `GuestUser` has `is_authenticated = True` /
  `is_anonymous = False` properties.
- Every new view subclasses `workspace.views.base.OwnedAPIView`
  (`authentication_classes=[GuestTokenAuthentication]`,
  `permission_classes=[IsAuthenticated]`) and loads objects only through its
  helpers (`get_workspace`, `get_document`, `get_session`), which filter by
  `request.user` and raise **404** for objects the user does not own.
- Every legacy, deep-analysis and evaluation view mixes in
  `workspace.auth.TokenRequiredMixin` (same authentication, 401 in the error
  envelope, other error shapes unchanged), except the public
  `analysis-config/`. A body/path username must equal `request.user.username`
  and every id is looked up owner-filtered (`router.views.owned_conversations`
  for legacy turns, with a fallback to the document's owner for rows without
  a user); anything else is the endpoint's usual 404.
- The analysis WebSocket authenticates with its first frame
  `{"type": "auth", "token"}` (10 s timeout): 4401 for no/invalid auth, a
  `job_not_found` frame + 4404 for a batch the user does not own; nothing
  about the job is sent, and no group subscription is made, before that.
- Test helpers for all of this are in `backend/common/testing.py`
  (`sign_in(client, user)`, `bearer(user)`, `open_analysis_socket`).

## Errors (new API)

Every non-2xx JSON response from the new API:

```json
{"error": {"code": "unsupported_file_type", "message": "Upload a PDF, DOCX, TXT or Markdown file.", "retryable": false, "stage": null, "details": null}}
```

Codes used by Phase 1 include `authentication_required` (401),
`not_found` (404), `invalid_request` (400, `details` = field errors),
`file_too_large` (413), `unsupported_file_type` (415), `url_not_allowed` (400),
`ingestion_in_progress` (409), `no_ready_documents` (409),
`index_unavailable` (409), `last_workspace` (409),
`job_queue_unavailable` (503). Pipeline errors reuse `PipelineError.code`.
Phase 3 adds `embedding_model_mismatch` (409) and `default_pipeline` (409);
reranker fallbacks record `reranker_unavailable`, `reranker_invalid_response`,
`reranker_failed` or the provider's code on the `retrieve.rerank` span only.

## API (Phase 1, all under `/api/v1/`, token required)

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `workspaces/` | | `{"results": [Workspace]}` (creates the default if none) |
| POST | `workspaces/` | `{name}` | 201 Workspace |
| GET/PATCH/DELETE | `workspaces/{id}/` | PATCH `{name}` | Workspace / 204 |
| GET | `documents/?workspace_id=` | | `{"results": [Document]}` newest first; default workspace if omitted |
| POST | `documents/` | multipart `file`, `title?`, `workspace_id?` · JSON `{source_type:"url", url, title?, workspace_id?}` · JSON `{source_type:"text", text, title?, workspace_id?}` | **202** Document |
| GET/PATCH/DELETE | `documents/{id}/` | PATCH `{title}` | Document / 204 (also deletes stored files and index pickles) |
| GET | `documents/{id}/ingestion/` | | IngestionStatus |
| POST | `documents/{id}/ingestion/` | | 202 IngestionStatus (retry / re-index; 409 if a live job exists) |
| GET | `documents/{id}/file/` | | original upload, `inline`, `X-Content-Type-Options: nosniff`; 404 `no_original_file` for URL/text sources |
| GET | `documents/{id}/text/` | | `{"document_id", "text", "pages": [...], "char_count", "truncated"}` |
| GET | `conversations/?workspace_id=` | | `{"results": [Conversation]}` by `updated_at` desc |
| POST | `conversations/` | `{title?, workspace_id?, document_ids?}` | 201 Conversation |
| GET/PATCH/DELETE | `conversations/{id}/` | PATCH `{title?, document_ids?}` | Conversation / 204 |
| GET | `conversations/{id}/messages/` | | `{"results": [Message]}` oldest first |
| POST | `conversations/{id}/messages/` | `{content, document_ids?}` | `text/event-stream` (see below); `?stream=0` returns `{"user_message", "assistant_message"}` JSON |

`document_ids` must belong to the conversation's workspace. A message's
`document_ids` overrides the conversation scope for that question only.

### Workspace
```json
{"id": 3, "name": "My Workspace", "is_default": true, "document_count": 4, "conversation_count": 2, "created_at": "…", "updated_at": "…"}
```

### Document
```json
{
  "id": 12, "workspace_id": 3, "title": "Attention Is All You Need",
  "source_type": "pdf", "source": "attention.pdf",
  "mime_type": "application/pdf", "file_size": 2345678, "has_original_file": true,
  "status": "EMBEDDING", "status_detail": "Embedded 640 of 1,000 chunks", "progress": 64,
  "error": null,
  "page_count": 15, "chunk_count": 384, "char_count": 51234,
  "index": {"id": 7, "method": "dense", "embedding_model": "openai/text-embedding-3-small", "created_at": "…"},
  "created_at": "…", "updated_at": "…", "ingested_at": null
}
```
`source_type` ∈ `pdf, docx, txt, md, url, text` (legacy rows may say
`markdown`). `source` is the original filename, the URL, or null for pasted
text. `error` is `{"code", "message", "retryable", "stage"}` or null. `index`
is null until READY.

### IngestionStatus
```json
{
  "document_id": 12, "status": "EMBEDDING", "progress": 64, "status_detail": "…",
  "stages": [
    {"id": "UPLOADING", "label": "Uploaded", "state": "done"},
    {"id": "EXTRACTING", "label": "Text extracted", "state": "done"},
    {"id": "CLEANING", "label": "Content cleaned", "state": "done"},
    {"id": "CHUNKING", "label": "Chunks created", "state": "done"},
    {"id": "EMBEDDING", "label": "Embeddings generated", "state": "active"},
    {"id": "INDEXING", "label": "Index built", "state": "pending"}
  ],
  "job": {"id": "uuid", "status": "PROCESSING", "updated_at": "…"},
  "error": null, "can_retry": false
}
```
`state` ∈ `done, active, pending, failed`. `QUEUED` = Uploaded done, the rest
pending. `FAILED` marks `error.stage` failed, earlier stages done. Reading a
document whose latest job has failed or stalled (`Job.expire_if_stalled`)
while the document is non-terminal moves the document to `FAILED` with the
job's error.

### Conversation
```json
{"id": 9, "workspace_id": 3, "title": "Retrieval methods", "document_ids": [12, 14], "message_count": 6, "last_message_preview": "…", "created_at": "…", "updated_at": "…"}
```

### Message
```json
{
  "id": 55, "conversation_id": 9, "role": "assistant",
  "content": "RAG combines retrieval with generation [1].",
  "status": "complete",
  "citations": [Evidence],
  "retrieval": RetrievalMetadata,
  "token_usage": {"prompt_tokens": 812, "completion_tokens": 96, "total_tokens": 908},
  "latency_ms": 2600,
  "error": null,
  "analysis_turn": {"conversation_id": 123, "document_id": 12},
  "created_at": "…"
}
```
`analysis_turn` links the answer to a legacy `router.Conversation` turn so the
existing Deep analysis flow (`/ground-truth/{conversation_id}/{document_id}`)
works. It is set only when the question was scoped to exactly one document;
otherwise null.

### Evidence (citation) — PRD §14
```json
{
  "citation_id": 1, "document_id": 12, "document_title": "…",
  "index_version_id": 7, "chunk_id": 345,
  "page_number": 4, "page_end": 4, "char_start": 10234, "char_end": 10746,
  "text": "…", "retrieval_score": 0.82, "rerank_score": null, "cited": true
}
```
`citations` on an assistant message lists every source given to the model, in
the `[n]` order of the prompt; `cited` says whether the answer references
`[n]`. Page fields are null for non-PDF sources and for chunks indexed before
positions existed.

### RetrievalMetadata (Phase 1 shape; later phases extend it)
```json
{
  "pipeline": {"strategy": "dense", "embedding_model": "…", "generation_model": "…", "temperature": 0.0, "candidate_k": 20, "top_k": 5, "prompt_version": "chat-cited-v1"},
  "query": {"original": "…", "rewritten": "…", "rewrite_applied": true},
  "documents": [{"document_id": 12, "index_version_id": 7}],
  "candidates": [{"document_id": 12, "chunk_id": 345, "retrieval_score": 0.82, "rank": 1}],
  "candidate_count": 20, "context_count": 5, "cited_count": 3,
  "timings_ms": {"rewrite": 350, "embed_query": 120, "search": 8, "first_token": 900, "generation": 2100, "total": 2600}
}
```
`generation_model` is the model that actually answered (it differs from the
configured one when the OpenRouter free-model fallback was used). Phase 2 adds
`run_id`, the answer's retrieval run (see Phase 2 below).

## Chat turn

1. Persist the user message and an assistant message with `status=streaming`.
2. **Rewrite** — history-aware standalone search query from the last
   `CHAT_HISTORY_MESSAGES` (6) completed messages, via the chat engine's LLM
   (non-streaming). Must be one line ≤ 200 chars, otherwise fall back to the
   original question (`rewrite_applied=false`).
3. **Retrieve** — engine `rag_registry.get_engine(DEFAULT_CHAT_VARIANT["method"], DEFAULT_CHAT_VARIANT["model"])`.
   Embed the query once. For each READY document in scope load its dense index
   (`current_index`, else the newest ready dense `DocumentVector`) through
   `index_cache` (LRU keyed by `DocumentVector.id`, size
   `RAG_CHAT_INDEX_CACHE_SIZE`, default 8, float32 copies; loading happens
   under `engine_execution(engine)` via the pipeline's `_load_state`, then the
   arrays are snapshotted). Score every chunk by cosine similarity, merge across
   documents, de-duplicate identical text, keep `CHAT_CANDIDATE_K` (20)
   candidates and the top `CHAT_CONTEXT_K` (5) as context. A document whose
   index cannot be loaded fails the turn with `index_unavailable` naming it; the
   chat path never builds an index inline.
4. **Generate** — `common.prompt_builder.cited_chat_messages(question, sources, history)`
   (prompt version `chat-cited-v1`): answer only from the numbered sources,
   cite `[n]` after each supported claim, say so when the sources are
   insufficient, never invent a citation number. Stream with
   `OpenRouterLLM.stream_chat(messages)`, which yields text deltas and ends
   with usage and the model that answered, keeps no per-call state on the
   instance (engines are shared between threads), and applies the same
   credit-exhaustion free-model fallback as `_call_api` before the first token.
5. **Finish** — parse cited ids (`[1]`, `[1, 2]`, `[1][3]`; ignore
   out-of-range), set `cited` flags, store `retrieval`, `token_usage`,
   `latency_ms`, create the legacy analysis turn when single-document, set
   `status=complete`. On error set `status=failed` with the error fields.

Constants live in `common/constant.py`: `CHAT_CANDIDATE_K`, `CHAT_CONTEXT_K`,
`CHAT_HISTORY_MESSAGES`, `CHAT_PROMPT_VERSION`.

### SSE stream (`POST conversations/{id}/messages/`)

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`,
`X-Accel-Buffering: no`. Frames are `event: <name>\ndata: <json>\n\n`;
`: ping` comments may be sent while waiting.

| Event | Data |
| --- | --- |
| `message.created` | `{"user_message": Message, "assistant_message": Message}` |
| `stage` | `{"id": "rewrite" \| "retrieve" \| "generate", "status": "running" \| "completed" \| "skipped" \| "failed", "detail": "Retrieved 20 candidates", "duration_ms": 120}` |
| `retrieval` | `{"candidate_count": 20, "context_count": 5, "citations": [Evidence with cited=false]}` — sent before generation |
| `token` | `{"delta": "text"}` |
| `message.completed` | `{"message": Message}` — final assistant message |
| `error` | `{"error": Error, "message": Message \| null}` |

The stream ends after `message.completed` or `error`. Validation problems
found before streaming starts (empty content, unknown conversation, no READY
documents) are ordinary JSON errors, not streams.

Transport: one producer, `run_chat_turn(...)`, is a generator of events. Under
WSGI and the Django test client the view iterates it inline. Under ASGI
(Daphne) a sync iterator would be buffered whole, so the view returns an
**async** iterator: the producer runs in a worker thread, pushes events
through `loop.call_soon_threadsafe` into an `asyncio.Queue`, and closes its DB
connections when done. The producer keeps running if the client disconnects,
so the finished answer is still persisted.

## Ingestion

`POST documents/` validates, stores the upload, creates the `Document`
(`QUEUED`) and a `Job(kind="ingest")`, and enqueues
`workspace.tasks.ingest_document_task(job_id)` with `transaction.on_commit`.
If enqueueing fails, the job and document become `FAILED`
(`job_queue_unavailable`, retryable) and the response is 503 with the
document. Upload acknowledgement must not parse or embed anything.

Worker stages (status, progress):

1. `EXTRACTING` (5–15) — PDF page by page (PyPDF2), DOCX paragraphs
   (`zipfile` + `xml.etree`, zip-bomb limits), TXT/MD decode, URL fetch +
   readable HTML text (or PDF bytes when the URL serves a PDF). Re-indexing
   re-extracts from the stored original (the saved HTML for URLs), never
   refetches.
2. `CLEANING` (15–20) — `DataLoader._clean_text` per page, drop empty pages,
   join with `\n\n`, record `pages` offsets, save the extracted text, fill
   metadata counts.
3. `CHUNKING` (20–25) — `engine.chunker.chunk(text)` with the chat engine, so
   the texts match what `_build_index` will produce.
4. `EMBEDDING` (25–85) — embed missing unique chunk texts in batches of
   `EMBEDDING_BATCH_SIZE`, commit each batch to `EmbeddingCacheEntry`, update
   progress per batch.
5. `INDEXING` (85–99) — `engine._build_index(username, document)` under
   `engine_execution(engine)` (all embeddings come from the cache), set
   `current_index`, then write chunk positions into `Chunk.metadata`
   (`ordinal`, `char_start`, `char_end`, `page_start`, `page_end`; merged, not
   replaced).
6. `READY` (100), `ingested_at`.

A failure records `error_stage`, the `error_payload` fields, and fails the
job. A duplicate task delivery that cannot claim the job does nothing.

The legacy `initialize_rag_task` also keeps the document status in step
(`CHUNKING` when it starts, `READY` with `current_index` on success, `FAILED`
on failure). Legacy insert endpoints assign the user's default workspace.

## Upload and URL security (PRD §39)

- Size limit `MAX_UPLOAD_BYTES` (env `RAG_MAX_UPLOAD_BYTES`, default 25 MB);
  pasted text limit `RAG_MAX_TEXT_CHARS` (default 2,000,000).
- Type by content, not by the client's header: PDF needs `%PDF-`; DOCX must be
  a zip containing `word/document.xml`; TXT/MD must decode as text and contain
  no NUL bytes. Allowed extensions: `.pdf .docx .txt .text .md .markdown`.
- Stored under `documents/user_<user id>/<uuid>/<sanitized filename>`.
- URLs: `http`/`https` only, no userinfo, ports 80/443/8080/8443. Every
  connection — including each redirect, at most 5 — is made to an address that
  was resolved and checked at connect time (custom urllib3 connection
  `_new_conn`); anything that is not `ipaddress.ip_address(...).is_global`
  (loopback, private, link-local, CGNAT, multicast, reserved, IPv4-mapped
  private) is refused. `trust_env=False`. Timeouts 5 s connect / 15 s read,
  body cap `RAG_MAX_URL_BYTES` (default 10 MB), content types HTML, XHTML,
  plain text, Markdown, PDF. `POST documents/` rejects obviously bad URLs
  (scheme, `localhost`, literal non-global IPs) synchronously with
  `url_not_allowed`; the worker applies the full check.

## Frontend layout

New code follows PRD §34:

```
src/features/
  auth/        token storage, 401 handling
  workspaces/  api, hooks, components (switcher)
  documents/   api, hooks (polling), components (library, upload, status checklist)
  chat/        api, hooks (streaming), components (thread, message, sources, why-panel)
  reader/      components (text reader with highlight + search, PDF view)
src/services/streaming/sse.ts   fetch-based POST SSE client
```

- Token in `localStorage["token"]`; `apiClient` adds `Authorization: Bearer`.
  A 401 from any token-protected path (`isProtectedApiPath`: the workspace API
  and every legacy/deep-analysis endpoint; not sign-in/sign-up/sign-out or
  `analysis-config`) sends the user to `/login?next=<path>`; the login page
  follows `next` only when it starts with `/` and not `//`. The login page has
  "Sign in" and "Create account" modes; logout calls `sign-out/` and clears
  the session. The deep-analysis pages require a token (`useRequireToken`),
  and `services/websocket.ts` sends the auth frame on every (re)connect and
  does not retry 4401/4404.
- Routes: `/workspace`, `/workspace/:workspaceId`,
  `/workspace/:workspaceId/c/:conversationId` (lazy-loaded). `/chat` and
  `/loading` redirect to `/workspace`.
- Workspace page (PRD §37): documents | reader | chat on desktop, tabs on
  mobile, footer status `Retrieval: 20 → 5 → 3 cited · 2.6 s · first token 0.9 s`.
- Citations `[n]` are buttons; clicking opens the evidence in the reader,
  highlights `char_start..char_end` and scrolls to it. PDFs can switch to the
  original file (fetched as a blob with the token, `#page=n`).
- Pure logic (SSE parsing, citation markers, stage derivation, highlight
  segmentation) lives in plain `.ts` modules covered by `tests/*.test.mjs`.

## Phase 2 — RAG observability (PRD §20–21, §32, §44, §49)

Every chat turn is traced and stored as a **retrieval run**, completed or
failed. Phase 1 shapes are unchanged except for the additive `run_id` keys
below.

### Tracer (`workspace/services/tracing.py`)

`Tracer(name, label, origin=…)` records a tree of spans on the monotonic
clock: `name` (stable id), `label` (for people), `start_ms` (offset from the
run's start), `duration_ms`, `status` (`completed`, `skipped`, `failed`),
`detail`, `error_code`, `data`. `with tracer.span(name, label, **data) as span`
or `tracer.start()`/`tracer.finish()`; finishing a span closes any span still
open inside it. An exception leaving a span scope closes it (and its open
children) as `failed` with the error's code (`PipelineError.code`/`ApiError.code`,
`stream_interrupted` for `GeneratorExit`, else `internal_error`) and is
re-raised unchanged. `span.skip()` / `span.fail(code)` mark steps that did not
raise. Bounds: 100 spans per trace (the rest counted as root
`data.dropped_spans`), 2 KB of JSON data per span, strings ≤ 200 chars,
detail ≤ 255. Every tracer method swallows its own errors, logs the first and
goes inert (`export()` then returns `[]`): **tracing never fails a turn**.

The chat turn's tree (§32):

```
chat.turn
├── prepare                   history + save the question
├── rewrite                   completed | skipped (first question, unusable) | failed (rewrite_failed, recovered)
├── retrieve
│   ├── retrieve.load_indexes data: documents, cache_hits, cache_misses
│   │   └── index.load ×doc   data: document_id, index_version_id, cache hit|miss, chunks (first 25 documents)
│   ├── retrieve.embed_query  data: model, dimensions
│   ├── retrieve.search       data: similarity, chunks_scored, pooled
│   └── retrieve.select       data: candidates, duplicates_skipped, context
├── generate                  data: configured_model, model, fallback, finish_reason, characters
│   └── generate.first_token  request → first token
├── citations                 data: sources, cited
└── persist                   answer + legacy analysis turn saved
```

`persist` ends after `total` is measured, so the root span can outlast
`total_ms`; the waterfall scales to the later of the two.

### Models (`workspace` app, migration `workspace/0002_retrieval_runs`, depends on `workspace/0001` and `router/0016`)

`RetrievalRun`: `user` FK GuestUser (CASCADE, `retrieval_runs`), `workspace`
FK (CASCADE), `conversation` FK ChatSession (null, CASCADE — runs hold the
question text), `message` FK ChatMessage (null, CASCADE), `source`
(`chat`/`evaluation`/`research`, default `chat`), `status`
(`completed`/`failed`), `error_stage` (`rewrite`/`retrieve`/`generate`, the
SSE error stage), `error_code`, `error_message`, `query_original`,
`query_rewritten`, `rewrite_applied`, `rewrite_reason`
(`first_question`/`rewritten`/`unchanged`/`unusable`/`failed`), `provenance`
JSON, `total_ms`, `rewrite_ms`, `retrieval_ms`, `rerank_ms` (null until
Phase 3), `generation_ms`, `first_token_ms` (null when the step did not run or
complete; `total_ms` = the message's `latency_ms`, `first_token_ms` from the
turn's start), `prompt_tokens`, `completion_tokens`, `total_tokens` (generation
only; the rewrite call reports no usage), `candidate_count`, `context_count`,
`cited_count`, `started_at` (settable, the window field), `created_at`.
Indexes `(workspace, -started_at)`, `(user, -started_at)`.

`RetrievalSpan`: `run` FK (CASCADE, `spans`), `ordinal` (pre-order position,
unique per run), `parent_ordinal` (null for the root), `depth`, `name`,
`label`, `status`, `start_ms`/`duration_ms` (float ms), `detail`,
`error_code`, `data` JSON.

`RetrievalCandidate`: `run` FK (CASCADE, `candidates`), `rank`, `document` FK
(null, SET_NULL) + `document_title` snapshot, `index_version_id` and
`chunk_id` (plain bigints — a re-index may replace chunk rows),
`retrieval_score`, `rerank_score` (null until Phase 3),
`selected_for_context`, `cited`, `citation_id` (its `[n]`, null outside the
context), `page_start`, `page_end`, `char_start`, `char_end`, `snippet`
(≤ 300 chars). At most 50 candidates per run (`MAX_RUN_CANDIDATES`; chat
stores its 20).

Provenance (§20):

```json
{
  "schema_version": 1, "timestamp": "…",
  "strategy": "dense",
  "retrieval_parameters": {"candidate_k": 20, "context_k": 5, "similarity": "cosine", "deduplicate": true, "query_rewrite": true, "history_messages": 2, "history_limit": 6},
  "embedding_model": "openai/text-embedding-3-small",
  "reranker": null,
  "generation_model": "…", "configured_generation_model": "…", "fallback_used": false,
  "generation_parameters": {"temperature": 0.0, "stream": true},
  "prompt_version": "chat-cited-v1",
  "index_versions": [{"document_id": 12, "document_title": "…", "index_version_id": 7, "method": "dense", "created_at": "…", "embedding_model": "…", "loaded": true}],
  "index_version_count": 1
}
```

`generation_model` is what the provider reported (null if no model answered);
`fallback_used` comes from `StreamResult.fallback`, set only on the
free-model path (`StreamResult` also gained `requested_model`).
`index_versions` holds at most 200 entries; `index_version_count` is the
number of documents in scope.

### Recording

The run is written by the producer in its own savepoint, **before** the
closing events: on success after the answer is saved (then
`ChatMessage.retrieval.run_id` is set with one UPDATE), on failure before the
message is marked failed (including `stream_interrupted` on a WSGI
disconnect). Any error while recording is logged and the turn continues
without a run id.

### Payload additions

- `ChatMessage.retrieval.run_id` (int or null); every Phase 1 key unchanged.
- SSE `message.completed`: `{"message": Message, "run_id": int | null}`.
- SSE `error`: `{"error": Error, "message": Message | null, "run_id": int | null}`.
- No new SSE events or stage ids.
- Reader evidence: client-side `Evidence.candidate_rank` (optional) when a
  candidate that was not a cited source is opened.

### API (token required, owner-scoped, error envelope)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `retrieval/runs/?workspace_id=&conversation_id=&status=&source=&limit=` | `{"results": [Run], "has_more"}` newest first (`started_at`); `limit` 1–200, default 50. Filters combine; with neither id the default workspace. |
| GET | `retrieval/runs/{id}/` | RunDetail |
| GET | `retrieval/runs/summary/?workspace_id=&days=&source=` | ReliabilitySummary; `days` 1–365, default 30 |

Bad `status`/`source`/`limit`/`days` → 400 `invalid_request`; another user's
run, workspace or conversation → 404 `not_found`.

Run:

```json
{
  "id": 41, "workspace_id": 3, "conversation_id": 9, "message_id": 55, "source": "chat", "status": "completed",
  "query": {"original": "…", "rewritten": "…", "rewrite_applied": true, "rewrite_reason": "rewritten"},
  "error": null,
  "latency_ms": {"total": 2600, "rewrite": 350, "retrieval": 140, "rerank": null, "generation": 2100, "first_token": 900},
  "token_usage": {"prompt_tokens": 812, "completion_tokens": 96, "total_tokens": 908},
  "candidate_count": 20, "context_count": 5, "cited_count": 3,
  "strategy": "dense", "generation_model": "…", "started_at": "…", "created_at": "…"
}
```

`error` is `{"code", "message", "stage"}` for failed runs. RunDetail adds
`provenance`, `spans` (a list of root spans, each
`{"name", "label", "status", "start_ms", "duration_ms", "detail", "error_code", "data", "children"}`)
and `candidates`:

```json
{"rank": 1, "document_id": 12, "document_title": "…", "document_available": true, "index_version_id": 7, "chunk_id": 345,
 "page_number": 4, "page_end": 4, "char_start": 10234, "char_end": 10746, "text": "…",
 "retrieval_score": 0.82, "rerank_score": null, "selected_for_context": true, "cited": true, "citation_id": 1}
```

`text` is the whole chunk while it exists in the same document, else the
stored snippet; `document_title` is the current title, else the snapshot.

ReliabilitySummary (§49):

```json
{
  "workspace_id": 3, "days": 30, "source": null, "since": "…",
  "runs": {"total": 8, "completed": 5, "failed": 3},
  "failure_rate": 0.375,
  "failures_by_stage": {"retrieval": {"count": 1, "rate": 0.125}, "generation": {"count": 1, "rate": 0.125}, "other": {"count": 1, "rate": 0.125}},
  "latency_ms": {"sample_size": 5, "total": {"p50": 300.0, "p95": 880.0, "count": 5}, "retrieval": {…}, "generation": {…}, "first_token": {…}},
  "tokens": {"prompt": 960, "completion": 40, "total": 1000, "runs_with_usage": 4, "average_per_run": 250.0},
  "ingestion": {"documents": 5, "ready": 2, "failed": 1, "in_progress": 1, "not_indexed": 1, "success_rate": 0.6667, "failure_rate": 0.3333,
                "attempts": {"total": 4, "succeeded": 2, "failed": 1, "failure_rate": 0.3333}}
}
```

Runs are counted by `started_at` within the window. Rates are fractions
(4 decimals), null when the denominator is 0; `retrieval` counts
`error_stage=retrieve`, `generation` counts `generate`, `other` the rest
(e.g. a disconnect during the rewrite). Percentiles: completed runs only (the
newest 10,000), nulls skipped, linear interpolation between closest ranks
(numpy's default, PostgreSQL `percentile_cont`), null for no values, rounded
to 0.1 ms. Ingestion counts the workspace's documents by current status; the
Phase 1 backfill's `not_indexed` documents are reported apart and are not
failures; `attempts` are `ingest` jobs created in the window.

### Frontend

`src/features/runs/` — `api/runs.ts`, `types/`, `hooks/useRunDetail.ts`
(fetched only when needed, cached per run id, aborted on unmount),
`hooks/useRunsOverview.ts`, `lib/waterfall.ts` (layout),
`lib/runMetrics.ts` (formatting, funnel, rewrite text, summary cards,
candidate → evidence), components `RunTrace`, `LatencyWaterfall`,
`CandidateTable`, `ProvenanceBlock`, `RunsPanel`.

- "Why this answer?" loads `retrieval/runs/{run_id}/` when opened and shows
  the error (failed runs), question and rewrite (or why not), the funnel, the
  candidate table (clicking a row opens the passage in the reader), the
  latency waterfall with a text equivalent per row, timings, tokens and
  provenance. Without a `run_id` (older answers), or if the run cannot be
  loaded, it shows the Phase 1 metadata panel. Failed answers with a run get
  the same panel as "What went wrong?".
- Workspace page: the right column has **Chat | Runs** tabs on desktop;
  mobile has a fourth **Runs** tab. The chat stays mounted while Runs is
  shown. Runs shows the summary cards (7/30/90-day window), recent runs and,
  on selection, the run's trace; it refreshes after every chat turn.
- `retrieval/…` paths are treated as token-protected (401 → sign in).

## Phase 3 — Advanced retrieval (PRD §17–19, §45)

Chat retrieval is configurable per conversation through versioned
pipelines. Every Phase 1 and Phase 2 shape is unchanged; the additions below
are new keys only, and the default pipeline reproduces Phase 1 exactly.

### Retrieval service (`workspace/services/retrieval.py`)

`run_retrieval(query, documents, config, *, engine=None, tracer=None,
indexes=None, timings=None) -> RetrievalResult` — candidates (final order),
context (first `top_k`), loaded snapshots, `duplicates_skipped`, `rerank`
outcome. It generates nothing; chat calls it per question and Phase 4 can
call it directly. `chat_index`, `index_unavailable` and the index loading
moved here from `chat.py` (re-exported there).

Strategies (`config.strategy`):

| id | Ranking |
| --- | --- |
| `dense` | Phase 1 verbatim: cosine of the query embedding with every passage of each loaded snapshot; each document's top `candidate_k` pooled; sorted by score, ties by document order then position; identical passages (whitespace-normalised) kept once; first `candidate_k`. |
| `bm25` | `rank_bm25.BM25Okapi` over the **union** of the in-scope snapshots' passages (one IDF and average length, so scores compare across documents), tokenised by `sparse_rag.sparse_rag.tokenize` with NLTK English stop words; passages with score ≤ 0 are not candidates; same pooling and de-duplication. No query embedding is made. |
| `hybrid` | Both rankings, each de-duplicated and cut to `candidate_k`, fused. `weighted`: raw dense and BM25 scores min-max normalised over the passages being fused (all equal → 1), `hybrid_weight × dense + (1 − hybrid_weight) × bm25`; a retriever with weight 0 contributes no passages, so weight 1 / 0 equals the dense / BM25 ranking exactly. `rrf`: `Σ 1 / (rrf_k + rank)` over the rankings that returned the passage. Ties by document order then position; first `candidate_k`. |
| `hybrid_rerank` | `hybrid`, then the reranker scores every candidate and they are reordered by that score (stable: ties keep the fused order). Any reranker exception keeps the fused order (rerank scores null, rank = rank before), marks `retrieve.rerank` `fallback` with the error code and never fails the turn. |

The BM25 index is cached per process by the *set* of index versions it
covers (`index_cache.fetch_bm25`, LRU `RAG_CHAT_BM25_CACHE_SIZE`, default 4);
`index_cache.discard`/`clear` drop it with the snapshots.

Rerankers (`services/rerankers.py`, `reranker_for({"provider", "model"})`):
`ollama` wraps `hybrid_rag.get_cross_encoder(model).predict` (models from
`RERANKER_MODELS`; any Ollama error → `reranker_unavailable`); `llm` sends
one prompt to `llms.llm_for(model)` with every candidate numbered, each cut
to `LLM_RERANK_PASSAGE_CHARS` (700) and to `LLM_RERANK_PROMPT_CHARS`
(16,000) together, asking for `{"scores": [{"id", "score"}]}` with 0–10
scores; the reply must be exactly that JSON (a bare list or a ```` ```json ````
fence is accepted), every id once, finite scores in range, else
`reranker_invalid_response`. LLM scores are stored divided by 10.

Per candidate: `retrieval_score` (the score it was retrieved by: cosine,
BM25 or fused), `dense_score`, `bm25_score`, `fused_score` (each null when
the strategy did not compute it), `rerank_score`, `retrieval_rank` (before
reranking) and `rank` (final).

Spans, under `retrieve` (no new root spans, no new SSE stage ids):
`retrieve.load_indexes` (+ `index.load`), then `retrieve.embed_query` and
`retrieve.search` (dense strategies), `retrieve.bm25` (data `cache`
hit/miss, `corpus_chunks`, `query_terms`, `chunks_scored`, `matched`,
`pooled`), `retrieve.fusion` (`method`, `hybrid_weight` or `rrf_k`,
`dense_candidates`, `bm25_candidates`, `fused`), `retrieve.select`, and
`retrieve.rerank` (`provider`, `model`, `candidates`, `reordered`; status
`completed` or `fallback`). The dense strategy emits exactly Phase 2's spans
and data. Span status gains **`fallback`** (tracer `span.fallback(code,
detail)`, `RetrievalSpan.Status.FALLBACK`): the step failed and the request
went on with a fallback result; it does not fail its parent.

### Pipelines (`workspace/services/pipelines.py`)

A configuration has every one of these keys (`CONFIG_KEYS`):

```json
{"strategy": "dense", "fusion": "weighted", "hybrid_weight": 0.6, "rrf_k": 60,
 "candidate_k": 20, "top_k": 5, "reranker": null,
 "generation_model": "openai/gpt-4o-mini", "temperature": 0.0,
 "prompt_version": "chat-cited-v1", "embedding_model": "openai/text-embedding-3-small"}
```

That is `default_config()`: Phase 1 chat (`CHAT_CANDIDATE_K`,
`CHAT_CONTEXT_K`, `DEFAULT_CHAT_MODEL`, `DEFAULT_TEMPERATURE`,
`CHAT_PROMPT_VERSION`, `INGEST_CONFIG["embedding_model"]`). Validation
(`normalize_config(changes, base)`: `changes` merged onto `base`, the latest
version or the defaults) rejects, with 400 `invalid_request` and one message
per field in `details["config.<key>"]`: unknown keys; `strategy` ∉
`PIPELINE_STRATEGY_IDS`; `fusion` ∉ `weighted`/`rrf`; `candidate_k` outside
`CHILD_TOP_K_MIN..MAX` (1–50), `top_k` outside `TOP_K_MIN..MAX` (1–20) or
above `candidate_k`, `rrf_k` outside `RRF_K_*`, `hybrid_weight` outside
`HYBRID_WEIGHT_MIN..MAX` (0–1), `temperature` outside `TEMPERATURE_*`
(non-integers, booleans and non-finite numbers are rejected, never clamped);
`generation_model` that fails `is_valid_model_id`; `prompt_version` ≠
`CHAT_PROMPT_VERSION`; `embedding_model` ≠ `INGEST_CONFIG["embedding_model"]`
(indexes are built with the ingest-time model). `reranker` is `null` or
`{"provider": "ollama" | "llm", "model"}` and exists exactly for
`hybrid_rerank`: switching away drops the base's reranker, switching to it
without one picks `{"provider": "ollama", "model": DEFAULT_RERANKER_MODEL}`,
an explicit `null` for it or a reranker for another strategy is an error.
Ollama models must be in `RERANKER_MODEL_IDS` (an `ollama/` prefix is
stripped); LLM models must be well-formed OpenRouter ids.

Generation: when `generation_model` is the chat engine's model the engine's
own LLM answers (default pipeline = Phase 1); otherwise `llms.llm_for(model)`,
one shared `OpenRouterLLM` per model. The rewrite uses the same LLM; the
answer is streamed with `stream_chat(messages, temperature=config.temperature)`.

### Models (migration `workspace/0004_pipelines`, depends on `workspace/0003_apitoken_expires_at`)

- `Pipeline`: `workspace` FK (CASCADE, `pipelines`), `name` (max 120),
  `is_default`, `created_at`, `updated_at`; unique constraint
  `one_default_pipeline_per_workspace`. `default_pipeline_for(workspace)`
  creates the default (`"Default (dense)"`, v1 = `default_config()`) on
  first need, race-safe like `default_workspace_for`. No data migration:
  defaults are created lazily.
- `PipelineVersion`: `pipeline` FK (CASCADE, `versions`), `number`
  (unique per pipeline, assigned under the pipeline's row lock), `config`
  JSON (the full configuration), `config_hash` (sha256 of the canonical
  JSON: sorted keys, no whitespace), `created_at`. `save()` on an existing
  row raises `ImmutableVersionError`; the admin is read-only.
- `ChatSession.pipeline`: FK (null, SET_NULL). Null = the workspace default
  at question time, so existing conversations behave as before.
- `RetrievalRun.pipeline_version`: FK (null, SET_NULL).
- `RetrievalCandidate`: `dense_score`, `bm25_score`, `fused_score` (float,
  null), `retrieval_rank` (null).
- `RetrievalSpan.status` choices gain `fallback`.

Editing (`update_pipeline`): a merged configuration with the same hash as
the latest version adds nothing; a rename alone adds nothing; otherwise
version n + 1. Deleting the default is 409 `default_pipeline`; deleting
another moves its conversations to the default (SET_NULL) and its runs keep
`provenance.pipeline` (their `pipeline_version_id` becomes null).

### Chat turn changes

`ConversationMessagesView.post` resolves the conversation's pipeline and
its **latest version at question time** (`session_pipeline`), then, before
streaming, refuses with **409 `embedding_model_mismatch`** a dense-using
pipeline when a document in scope recorded another `metadata.embedding_model`
(documents without one — backfilled legacy rows — are let through; their
index's model stamp is still checked on load). `run_retrieval` repeats the
check against the engine's model inside the stream (same code). BM25-only
pipelines skip the check but still load each index through the engine, whose
model-stamp check fails a mismatched index with `index_unavailable`. The turn is
`run_chat_turn(session, user, question, documents, pipeline_version=None)`
(None → the session's latest version).

### Payload additions

- `ChatMessage.retrieval`: `pipeline_version_id`, `pipeline_version`
  (`{"id", "pipeline_id", "name", "number"}`), `rerank` (null, or
  `{"provider", "model", "applied", "fallback", "error_code", "duration_ms"}`);
  `retrieval.pipeline` keeps exactly its Phase 1 keys (values now come from
  the version: strategy, embedding model, generation model, temperature,
  `candidate_k`, `top_k`, prompt version); each `retrieval.candidates[]`
  entry adds `dense_score`, `bm25_score`, `fused_score`, `rerank_score`,
  `retrieval_rank`. `timings_ms` keeps its Phase 1 keys (rerank time is on
  the run).
- Evidence: `rerank_score` is filled for reranked context (key set unchanged).
- SSE: unchanged events and stage ids; the `retrieve` completed detail adds
  ", reranked to M" or "; the reranker failed, so the fused order was kept".
- Conversation: `pipeline_id` (the effective pipeline: the conversation's,
  else the workspace default). `POST`/`PATCH conversations/` accept
  `pipeline_id` (PATCH `null` = back to the default); a pipeline of another
  workspace or user, or an unknown id, is 400 `invalid_request` with
  `details.pipeline_id` (same message either way).
- Run: `pipeline_version_id`, `pipeline` (`{"id", "name", "version",
  "version_id"}` from provenance, null before Phase 3); `latency_ms.rerank`
  = `rerank_ms` (the `retrieve.rerank` span; `retrieval` still covers the
  whole retrieve stage, reranking included).
- Run candidate: `dense_score`, `bm25_score`, `fused_score`, `retrieval_rank`.
- Provenance: `retrieval_parameters.similarity` is `cosine`, `bm25` or
  `cosine+bm25`; hybrid adds `fusion` and `hybrid_weight` or `rrf_k` (the
  dense dict is exactly Phase 2's); `reranker` is null or `{"provider",
  "model", "applied", "fallback", "error_code"}`; new `pipeline`:
  `{"pipeline_id", "name", "version_id", "version", "config", "config_hash"}`.

### API (token required, owner-scoped, error envelope)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `pipelines/?workspace_id=` | `{"results": [Pipeline]}` default first (creates the default) |
| POST | `pipelines/` | `{name, workspace_id?, config?}` → 201 Pipeline (v1 = defaults + `config`) |
| GET | `pipelines/options/` | strategies, fusion methods, reranker providers (+ models, default model, `open`), generation models, embedding models, prompt versions, `ranges`, `defaults`, `default_reranker`, `keys` |
| GET/PATCH/DELETE | `pipelines/{id}/` | PATCH `{name?, config?}` (partial config merged onto the latest version) → Pipeline + `version_created`; DELETE → 204, default → 409 `default_pipeline` |
| GET | `pipelines/{id}/versions/` | `{"pipeline_id", "results": [Version]}` newest first |
| GET | `indexes/?document_id=` | `{"results": [IndexVersion]}` newest first; without `document_id`, every index of `workspace_id`'s (or the default workspace's) documents |
| GET | `indexes/{id}/` | IndexVersion |
| GET | `retrieval/runs/?pipeline_version_id=` | new filter; malformed → 400, another user's version → 404 |

Pipeline: `{"id", "workspace_id", "name", "is_default", "version": Version,
"version_count", "versions": [{"id", "number", "created_at"}], "created_at",
"updated_at"}`. Version: `{"id", "pipeline_id", "number", "config",
"config_hash", "created_at"}`. IndexVersion (a `router.DocumentVector`):
`{"id", "document_id", "document_title", "method", "status", "is_current",
"embedding_model", "chunk_config", "chunk_count", "created_at", "updated_at"}`
— the build settings come from the document's ingest metadata, so only the
current index has them (others: null). Another user's pipeline, version,
index or document is 404.

### Frontend

`src/features/pipelines/` — `api/pipelines.ts` (pipelines, options,
versions, index versions), `types/`, `hooks/usePipelines.ts`,
`lib/pipelineConfig.ts` (validation mirroring the server, `withStrategy`,
`inactiveKeys`, `configChanges` = PATCH body, `diffConfigs`,
`versionHistory`, `describeConfig`, `pipelineVersionLabel`), components
`PipelineBar` (chat header: the conversation's pipeline + version,
switchable), `PipelinePanel` (§17: choose, create, edit, delete),
`PipelineForm`, `PipelineHistory` (versions with diffs). The workspace's
right column (and mobile tabs) gain **Pipelines**; a new conversation
inherits the pipeline chosen while none is open.
`runs/lib/runMetrics.ts` adds `formatCandidateScore`, `rankMovement`,
`candidateScoreColumns`, `hasRankChanges`, `wasReranked`,
`runPipelineLabel`; the §21 funnel reads `Retrieved N → Reranked to M →
Used K` (`Selected M` when no reranker reordered). The candidate table shows
the score columns the run has and rank before → after; provenance shows the
pipeline version, its configuration and the reranker outcome; the Runs view
filters by pipeline version; the footer names the answering pipeline
version; document rows list index versions (`documents/lib/indexVersions.ts`).
`pipelines/` and `indexes/` are token-protected paths.

### Deferred

- Building extra index versions with other chunk settings or embedding
  models. `_sync_chunks` deletes every chunk of another configuration
  (cascading to ground truth) and indexes are keyed by method only, so a
  second chunking would destroy the first version's chunks and the deep
  analysis attached to them. Chunk settings and the embedding model stay
  Tier B (ingest time); index versions are the re-index history.
- Build settings of superseded index versions (only the current index's
  are recorded, on the document).
- Changing which pipeline is the workspace default.

## Phase 4 — Evaluation lab (PRD §26–31, §42, §46, §49)

Evaluation datasets with immutable versions, retrieval and generation
metrics, an experiment registry that runs one dataset version through one
pipeline version in the background, comparison with paired bootstrap
confidence intervals, and failure analysis. Every Phase 1–3 shape is
unchanged; the additions are new endpoints and new keys.

### App and layout

New Django app **`lab`** (`backend/lab/`), so nothing collides with the
legacy `evaluation` app (ground truth, chunk metrics, Ragas). `lab` reuses
`evaluation.eval.evaluate_response` (Ragas through OpenRouter) unchanged.

```
lab/
  apps.py admin.py models.py urls.py tasks.py serializers.py
  services/
    metrics.py       pure retrieval and citation metrics (§27, §28)
    matching.py      expected source → chunks of the evaluated index
    datasets.py      item validation, versions, content hash, import/export (JSON, CSV), chat-answer drafts
    judge.py         LLM judge: answer relevance, faithfulness, answer correctness
    runner.py        experiment lifecycle (create, start/resume, cancel, rerun) and the Celery body
    aggregate.py     per-experiment aggregates (means, latency percentiles, tokens, failure counts)
    comparison.py    §30: deltas, win/loss, paired bootstrap, hygiene warnings
    failures.py      §31: failure labels
    environment.py   git commit and package versions (§42)
  views/             datasets.py experiments.py
  tests/             test_*.py
```

Migration `lab/0001_initial` depends on `workspace/0004_pipelines` and
`router/0017_guestuser_password`. `lab.urls` is included under `/api/v1/`.

### Models

- `EvaluationDataset`: `workspace` FK (CASCADE, related_name
  `evaluation_datasets`), `name` (max 120), `description` (max 2000, blank),
  `created_at`, `updated_at`.
- `DatasetVersion` — immutable (`save()` on a saved row raises
  `lab.models.ImmutableRecordError`): `dataset` FK (CASCADE, `versions`),
  `number` (unique per dataset, assigned under the dataset's row lock),
  `document_ids` JSON (the corpus searched; empty = every READY document of
  the workspace when the experiment starts, recorded on the experiment),
  `content_hash` (sha256 of the canonical JSON — sorted keys, no whitespace —
  of `{"document_ids": sorted ids, "items": [canonical items in order]}`),
  `item_count`, `note` (max 200: what changed, e.g. `Added 1 item`),
  `created_at`.
- `DatasetItem` — one item of one version, never updated: `version` FK
  (CASCADE, `items`), `position` (1-based, unique per version), `item_id`
  (max 64, unique per version; the item's stable key across versions),
  `question`, `expected_answer` (blank), `expected_sources` JSON,
  `history` JSON, `tags` JSON, `metadata` JSON.
- `Experiment`: `workspace` FK (CASCADE, `experiments`), `name` (max 200),
  `hypothesis`, `conclusion` (blank, editable), `dataset_version` FK (null,
  SET_NULL) + `dataset_snapshot` JSON, `pipeline_version` FK
  `workspace.PipelineVersion` (null, SET_NULL), `config` JSON (the full
  snapshot below), `index_versions` JSON, `retrieval_only`, `seed`,
  `status` (`draft`, `queued`, `running`, `completed`, `failed`,
  `cancelled`), `error_code`, `error_message`, `retryable`, `run_token`
  (UUID, null: the claim), `heartbeat_at`, `item_count`, `completed_count`,
  `failed_count`, `metrics` JSON (aggregates, stored when the run ends),
  `warnings` JSON, `git_commit` (max 64, null), `environment` JSON,
  `rerun_of` FK self (null, SET_NULL), `runtime_ms` (null), `created_at`,
  `updated_at`, `started_at`, `finished_at`.
- `ExperimentItem`: `experiment` FK (CASCADE, `items`), `position` (unique
  per experiment), `item_id`, a snapshot of the dataset item (`question`,
  `expected_answer`, `expected_sources`, `history`, `tags`), `status`
  (`pending`, `completed`, `failed`), `error_code`, `error_message`,
  `error_stage` (`rewrite`, `retrieve`, `generate`, `judge`, or `score` for an internal scoring error), `run` FK
  `workspace.RetrievalRun` (null, SET_NULL, related_name
  `evaluation_items`), `answer`, `details` JSON (query, matching,
  retrieved list, alternative query), `metrics` JSON, `metric_reasons`
  JSON, `failure_labels` JSON, `latency_ms`, `retrieval_ms`,
  `generation_ms`, `judge_ms`, `prompt_tokens`, `completion_tokens`,
  `total_tokens`, `started_at`, `finished_at`.

Deleting a dataset keeps its experiments (their `dataset_version` becomes
null; the snapshot and the per-item snapshots remain). Deleting a pipeline
keeps experiments the same way (`config` holds the configuration).
Deleting an experiment deletes its evaluation runs.

### Dataset item

```json
{
  "item_id": "q1", "position": 1,
  "question": "What retrieval method was used?",
  "expected_answer": "Hybrid retrieval",
  "expected_sources": [ExpectedSource],
  "history": [{"role": "user", "content": "…"}, {"role": "assistant", "content": "…"}],
  "tags": ["methods"],
  "metadata": {}
}
```

ExpectedSource (stored with every key; `document_title` is not stored, it
is filled in on output from the current title, null once the document is
gone):

```json
{"document_id": 12, "document_title": "Paper A", "chunk_id": 345, "index_version_id": 7,
 "char_start": 10234, "char_end": 10746, "page": 6, "page_end": 6, "text": "…"}
```

Validation (400 `invalid_request`, one message per field in `details`,
keys `items[<0-based index>].<field>` for lists, `<field>` for single items):

| Field | Rule |
| --- | --- |
| `item_id` | Optional; `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$`, unique in the version. Missing → the first free `q<n>` (n from the item count + 1 upwards). |
| `question` | Required, stripped, 1–4000 chars. |
| `expected_answer` | Optional, stripped, ≤ 20,000 chars (`""` = none). |
| `expected_sources` | ≤ 20. Each needs a document of the dataset's workspace: `document_id` if it is one, else a `document_title` that names exactly one; otherwise "Document … is not in this workspace." (same text for unknown, other workspace and other user). `chunk_id`, `index_version_id` positive ints or null; `char_start`/`char_end` both or neither, `0 ≤ start < end`; `page ≥ 1`, `page_end ≥ page` (defaults to `page`); `text` ≤ 1000 chars. Unknown keys are refused. |
| `history` | ≤ 6 turns `{"role": "user" \| "assistant", "content": 1–4000 chars}` (the conversation before the question, oldest first). |
| `tags` | ≤ 20 strings, each stripped, 1–50 chars; duplicates dropped. |
| `metadata` | A JSON object, ≤ 8 KB serialised. |

A version holds at most 2,000 items; `document_ids` must be documents of
the dataset's workspace (same message as above).

### Versions

Every change that alters the content hash creates version n + 1 (copying
the items); a change that produces the latest version's hash adds nothing
(`version_created: false`), and renaming or describing the dataset never
adds one. Writes that create versions accept `base_version` (a version
number): if it is not the latest, 409 `version_conflict`. Version 1 is
created with the dataset (possibly empty).

### CSV format (import and export; frontend parser and backend share it)

RFC 4180: `,` separated, `"` quoted with `""` escapes, LF or CRLF, line
breaks allowed inside quoted cells, a UTF-8 BOM is ignored, rows whose
cells are all empty are skipped. The header row is required; column names
are case-insensitive, in any order: `item_id`, `question` (required),
`expected_answer`, `expected_sources`, `tags`, `metadata`, `history`.
Other columns are ignored and reported as `ignored_columns`.

- `expected_sources`: empty = none; a cell starting with `[` is a JSON
  array of ExpectedSource objects; otherwise compact references separated
  by `;`, each `DOC[#SEL[,SEL…]]` where DOC is a document id and SEL is
  `p<page>` or `p<page>-<page_end>` (pages), `c<chunk_id>` (chunk) or
  `<char_start>-<char_end>` (character range). Example:
  `12#p4; 14#c345,10234-10746`.
- `tags`: `;`-separated. `metadata`: empty or a JSON object. `history`:
  empty or a JSON array of turns.

Export writes every column, `expected_sources`/`metadata`/`history` as JSON
and `tags` joined with `; `. JSON export:

```json
{"format": "ragreader-dataset", "schema_version": 1,
 "dataset": {"id": 5, "name": "…", "description": "…"},
 "version": {"number": 2, "content_hash": "…", "document_ids": [12], "created_at": "…"},
 "items": [Item]}
```

JSON import accepts that object or a bare list of items; import resolves
sources by `document_id`, then by `document_title`, so an export can be
imported into another workspace with documents of the same titles.

### Expected source → evaluated chunks (`lab/services/matching.py`)

The evaluated index of a document is the one `run_retrieval` loads (its
`current_index`, else its newest ready index). For each expected source,
in order:

1. **`chunk_id`** — the chunk id is in that index's loaded snapshot
   (`IndexSnapshot.chunk_ids`). A `Chunk` row that merely exists does not
   count.
2. **`char_overlap`** — `char_start`/`char_end` given: every chunk of that
   index whose `Chunk.metadata` `char_start`/`char_end` overlaps
   `[char_start, char_end)`.
3. **`page`** — `page` given: every chunk of that index whose
   `page_start..page_end` (metadata) overlaps `page..page_end`.
4. **`document`** — only `document_id` given: every chunk of the document
   (document-level relevance).
5. **`unresolved`** — none of the above matched (document deleted or not in
   the corpus, chunk gone without a usable range or page, legacy chunks
   without positions), with `reason`.

Chunk positions are read once per document per experiment run
(`Chunk.objects.filter(pk__in=snapshot.chunk_ids)`). Each item records
`details.matching`: `[{"source": 0, "rule": "char_overlap", "chunk_ids": [...], "reason": null}]`.

### Metrics (`lab/services/metrics.py`; pure functions)

Relevance is binary and counted per **expected source**. Let
`S_1..S_m` be the chunk-id sets of the *resolved* expected sources
(unresolved ones are excluded from every denominator and reported as a
dataset problem), `R = ∪ S_j`, and `L` the ranked candidate chunk ids in
final order with repeated ids removed (a repeated id never counts twice).

| Key | Definition |
| --- | --- |
| `recall@K` | Expected sources with at least one chunk in the top K of `L`, ÷ m. |
| `precision@K` | Distinct relevant chunks (∈ R) in the top K, ÷ **K** (also when fewer than K passages were retrieved). Two different chunks of one source both count. |
| `hit_rate@K` | 1 if the top K holds any relevant chunk, else 0; its mean is the hit rate. |
| `mrr` | 1 / rank of the first relevant chunk in the whole candidate list (`candidate_k`), 0 if none. |
| `ndcg@K` | Binary gain: a passage gains 1 only if it covers an expected source no higher-ranked passage covered. DCG = Σ gain_i / log2(i + 1) over the top K; IDCG = Σ_{i ≤ min(m, K)} 1 / log2(i + 1). |
| `context_recall` | Expected sources covered by the final context (the `top_k` passages given — or, retrieval only, that would be given — to the model), ÷ m. |
| `context_precision` | Context passages that are relevant ÷ context size. PRD §28's "context relevance" is reported as this metric. |
| `faithfulness` | LLM judge (Ragas `faithfulness`): share of the answer's claims supported by the context passages. |
| `answer_relevance` | LLM judge (Ragas `answer_relevancy`): how directly the answer addresses the question. |
| `answer_correctness` | LLM judge (Ragas `factual_correctness`, F1 mode) against the expected answer. |
| `citation_correctness` | Cited context passages (`[n]` markers) that are relevant ÷ cited passages. |
| `citation_completeness` | Expected sources covered by a **cited** passage ÷ expected sources covered by the context (what the model was given and could cite), so retrieval misses do not count against generation. |

K values come from the experiment (`k_values`, default `[1, 3, 5, 10]`).
Retrieval metrics (the first seven) and generation metrics (the last
five) are separate groups everywhere. A metric that cannot be computed is
**null with a reason**, never 0:

| Reason | When |
| --- | --- |
| `no_expected_sources` | The item has no expected sources (every retrieval metric, citation metrics). |
| `expected_sources_unresolved` | None of its expected sources matched the evaluated index. |
| `empty_context` | `context_precision` with no context; judge metrics without passages. |
| `item_failed` | The item failed (every metric). |
| `retrieval_only` | Generation metrics of a retrieval-only experiment. |
| `no_citations` | `citation_correctness` when the answer cites nothing. |
| `no_expected_source_in_context` | `citation_completeness` when the context covered no expected source. |
| `no_expected_answer` | `answer_correctness` without an expected answer. |
| `no_answer` | Judge metrics for an empty answer. |
| `judge_unavailable` | No OpenRouter key configured for the judge. |
| `judge_failed` | The judge produced no valid score (timeout, invalid output). |

Expected sources that exist but are not retrieved give real zeros.
Aggregates are means over the items with a value:
`{"mean": 0.82, "count": 16, "null_count": 2, "reasons": {"no_expected_sources": 2}}`
(`mean` null when `count` is 0; values rounded to 6 decimals).

### Experiment configuration snapshot (`Experiment.config`)

```json
{
  "schema_version": 1,
  "pipeline": {"pipeline_id": 4, "name": "Hybrid", "version_id": 11, "version": 3, "config": {…all CONFIG_KEYS…}, "config_hash": "…"},
  "dataset": {"dataset_id": 5, "name": "Paper QA", "version_id": 9, "version": 2, "content_hash": "…", "item_count": 20},
  "document_ids": [12, 14],
  "retrieval_only": false,
  "query_rewrite": true,
  "k_values": [1, 3, 5, 10],
  "judge_model": "mistralai/mistral-nemo",
  "thresholds": {"faithfulness": 0.5, "answer_correctness": 0.5},
  "seed": 42
}
```

`judge_model` is null for retrieval-only experiments. `index_versions`:
`[{"document_id", "document_title", "index_version_id", "method", "created_at", "embedding_model"}]`,
resolved when the run is claimed. `environment`:
`{"python", "packages": {"django", "djangorestframework", "celery", "numpy", "rank-bm25", "ragas", "openai"}, "models": {"embedding", "generation", "reranker", "judge"}}`
(missing packages null). `git_commit`: env `GIT_COMMIT`, else read from the
nearest `.git` above `BASE_DIR` (HEAD → loose ref or `packed-refs`, no
`git` process), else null.

### Running an experiment (`lab/services/runner.py`, `lab.tasks.run_experiment_task`)

- Create (`POST experiments/`) validates, snapshots the configuration and
  the dataset items into `ExperimentItem` rows (`pending`), then either
  stays `draft` or starts: status `queued`, a new `run_token`, and
  `run_experiment_task.delay(experiment_id, run_token)` after commit. If
  enqueueing fails the experiment becomes `failed`
  (`job_queue_unavailable`, retryable) and the response is 503 with the
  error envelope plus `"experiment"`.
- The worker claims with a conditional update (`queued` + its token →
  `running`); a duplicate delivery or a superseded token does nothing.
  Every item starts with a heartbeat that is also the ownership check; a
  run that lost ownership (cancelled, superseded, deleted) stops without
  writing. Each item's run record and its `completed`/`failed` state are
  written in **one transaction** that re-checks ownership, so a crash never
  leaves an orphan run or a half-finished item.
- **Stalls**: reading a `queued`/`running` experiment whose `heartbeat_at`
  is older than 35 minutes fails it (`experiment_stalled`, retryable).
  The task's limits are 60 min soft / 61 min hard; the soft limit fails it
  with `experiment_timeout` (retryable).
- **Resume**: `POST experiments/{id}/start/` on a `failed` or `cancelled`
  experiment queues it again with a new token; items already `completed`
  are skipped (not recomputed), `pending` and `failed` items run. On a
  `draft` it is the first start.
- **Cancel**: `queued`/`running` → `cancelled` (token cleared); the worker
  notices at its next heartbeat.
- **Rerun** (`POST experiments/{id}/rerun/`, §42): a new experiment with
  the stored configuration, seed, documents and item snapshots (so it
  works after the dataset was deleted), `rerun_of` set. It runs with the
  stored pipeline configuration; warnings record what no longer matches.
- Per item, the same path as chat: if the item has `history` and
  `query_rewrite` is true, `chat.rewrite_question` with the pipeline's
  generation LLM (`llms.generation_llm`); retrieval through `chat.retrieve`
  → `run_retrieval`; unless `retrieval_only`, `cited_chat_messages` +
  `stream_chat(temperature=…)` + `mark_cited`; then, unless retrieval
  only, the judge (`lab.services.judge.judge_answer`, wrapping
  `evaluation.eval.evaluate_response` with `judge_model`). When the
  rewrite was applied, retrieval also runs with the original question
  (diagnostic, after generation, for `query_mismatch`). Retrieval-only
  experiments make no generation or judge call; only items with `history`
  make the (non-generating) rewrite call.
- Each item records a `RetrievalRun` with `source="evaluation"` (no
  conversation or message), linked from `ExperimentItem.run`. Its span tree
  is `evaluation.item` → `rewrite`, `retrieve` (chat's children),
  `generate` (`generate.first_token`), `citations`, `alternative_query`,
  `judge`, `score`; skipped steps are `skipped`. `total_ms` (and the item's
  `latency_ms`) is the pipeline time: rewrite + retrieval + generation,
  without the diagnostic retrieval and the judge (`judge_ms`). Provenance is
  chat's shape (`generation_parameters.stream` true) plus
  `"evaluation": {"experiment_id", "item_id", "position"}`.
- Errors: `index_unavailable`, `embedding_model_mismatch`,
  `missing_provider_key`, `provider_authentication`, `provider_credits`
  and `provider_request_rejected` fail the whole experiment at that item
  (resume continues there). Any other error fails only the item (its run is
  recorded as failed with the stage); three consecutive item failures with
  the same code fail the experiment with that code.
- When every item is processed the experiment is `completed` (also with
  failed items), aggregates are stored, `runtime_ms` is the summed active
  time of every worker run.

### Failure analysis (§31, `lab/services/failures.py`)

Item labels `{"category", "code", "detail", "sources": [indexes]}`; an item
can carry several. With `thresholds` from the configuration:

| Category | Code | Rule |
| --- | --- | --- |
| retrieval | `relevant_not_retrieved` | A resolved expected source has no chunk anywhere in the candidates. |
| retrieval | `insufficient_k` | A resolved source is among the candidates but only beyond the context (`rank > top_k`). |
| retrieval | `wrong_document` | A resolved source is missing from the context and more than half of the context passages come from documents no expected source names. |
| retrieval | `query_mismatch` | The query used missed a source in the context that the other formulation retrieved into the context: the rewritten query (used) vs the original question, or the original question (used when `query_rewrite` is false or the rewrite was not usable) vs a usable rewrite. |
| generation | `unsupported_claim` | `faithfulness` < `thresholds.faithfulness`. |
| generation | `citation_mismatch` | A cited passage is not relevant (`citation_correctness` < 1), or the context held expected evidence and none of it was cited (`citation_completeness` = 0). |
| generation | `incomplete_answer` | `answer_correctness` < `thresholds.answer_correctness`. |
| dataset | `ambiguous_question` | No expected source, so retrieval cannot be judged. |
| dataset | `missing_evidence` | An expected source could not be resolved in the documents. |
| dataset | `duplicate_question` | Another item of the version has the same question (case, whitespace and punctuation ignored). |

`query_mismatch` needs both formulations: when `query_rewrite` is false
an item with history still gets its rewrite computed (one non-generating
call) so the original-query direction can be checked.

Experiment-level warnings `{"code", "message", …}` (hygiene and §42
reproducibility): `repeated_dataset_runs` (≥ 5 experiments in the
workspace on this dataset version: test-set tuning), `pipeline_version_missing`,
`pipeline_version_differs`, `dataset_version_missing`, `document_missing`,
`index_version_missing`, `index_version_changed` (the recorded index is
no longer the document's current one), `index_changed_during_run`.

### API (token required, owner-scoped, error envelope)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `evaluations/datasets/?workspace_id=` | `{"results": [Dataset]}`, most recently updated first; default workspace if omitted |
| POST | `evaluations/datasets/` | `{name, description?, workspace_id?, document_ids?, items?}` → 201 Dataset (version 1) |
| POST | `evaluations/datasets/import/` | New dataset from a file: JSON `{format: "json" \| "csv", content, name?, workspace_id?}`, JSON `{items, name}`, or multipart `file` (+ `name`, `workspace_id`) → 201 `{"dataset", "imported", "ignored_columns"}` |
| GET/PATCH/DELETE | `evaluations/datasets/{id}/` | PATCH `{name?, description?, document_ids?, items?, base_version?}` (`items` replaces the list) → Dataset + `version_created`; DELETE → 204 |
| GET | `evaluations/datasets/{id}/versions/` | `{"dataset_id", "results": [Version]}` newest first |
| GET | `evaluations/datasets/{id}/items/?version=` | `{"dataset_id", "version": Version, "results": [Item]}` (default latest) |
| POST | `evaluations/datasets/{id}/items/` | `{items: [Item], base_version?}` or one Item → 201 `{"version", "items": [added]}` |
| PATCH/DELETE | `evaluations/datasets/{id}/items/{item_id}/` | PATCH: partial Item (+ `base_version?`) → `{"version", "item"}`; DELETE → `{"version"}` |
| POST | `evaluations/datasets/{id}/import/` | Same bodies as above + `mode: "append" \| "replace"` (default append), `base_version?` → 201 `{"version", "imported", "ignored_columns"}` |
| GET | `evaluations/datasets/{id}/export/?format=json\|csv&version=` | Attachment `dataset-<id>-v<n>.json\|csv` |
| GET | `evaluations/datasets/{id}/items/from-message/?message_id=` | Draft from a chat answer, nothing written: `{"draft": Item, "sources": [Evidence + "suggested"], "message_id", "conversation_id"}` |
| GET | `experiments/?workspace_id=&dataset_id=&status=` | `{"results": [Experiment]}` newest first |
| POST | `experiments/` | ExperimentInput → 202 Experiment (queued), or 201 with `draft: true` |
| GET | `experiments/compare/?ids=1,2&baseline=1&metric=&seed=` | Comparison |
| GET/PATCH/DELETE | `experiments/{id}/` | ExperimentDetail; PATCH `{name?, hypothesis?, conclusion?}`; DELETE → 204 (with its runs; a running one stops) |
| POST | `experiments/{id}/start/` | First start (draft) or resume (failed/cancelled) → 202 |
| POST | `experiments/{id}/cancel/` | → 200 Experiment |
| POST | `experiments/{id}/rerun/` | `{name?, draft?}` → 202 (or 201 draft) new Experiment |
| GET | `experiments/{id}/items/?status=&category=&label=&offset=&limit=` | `{"results": [ExperimentItem], "count", "offset", "limit"}`; limit 1–500, default 100 |

Another user's dataset, version, experiment or message is 404 (from-message:
400 `invalid_request` on `message_id`, the same for unknown, another
workspace's and another user's message, or one that is not a completed
answer). A `pipeline_version_id`/`pipeline_id` outside the dataset's
workspace is 400 with `details.pipeline_version_id`. New error codes:
`version_conflict` (409), `dataset_empty` (409, no items),
`documents_not_ready` (409, a corpus document is not READY),
`experiment_in_progress` (409, start while queued/running),
`experiment_finished` (409, start on a completed experiment — rerun it),
`experiment_not_running` (409, cancel when not queued/running);
`no_ready_documents`, `embedding_model_mismatch` and
`job_queue_unavailable` are reused. Experiments fail with
`experiment_stalled`, `experiment_timeout` or the pipeline's codes.

ExperimentInput:

```json
{"name": "Hybrid vs dense", "hypothesis": "Hybrid retrieval improves Recall@5.",
 "workspace_id": 3, "dataset_id": 5, "dataset_version": 2,
 "pipeline_version_id": 11, "retrieval_only": false, "seed": 42,
 "k_values": [1, 3, 5, 10], "judge_model": "mistralai/mistral-nemo", "query_rewrite": true, "draft": false}
```

`dataset_version` (a number) defaults to the latest; `dataset_version_id`
may be sent instead. `pipeline_version_id` may be replaced by `pipeline_id`
(its latest version); with neither, the workspace's default pipeline.
`seed` 0–2³¹−1 (default 42); `k_values` 1–6 values in 1–50 (sorted, unique);
`judge_model` an OpenRouter id (default `RAG_JUDGE_MODEL`); thresholds use
the defaults. The experiment's workspace is the dataset's
(`workspace_id`, when sent, must match it).

Dataset:

```json
{"id": 5, "workspace_id": 3, "name": "Paper QA", "description": "",
 "version": Version, "version_count": 3,
 "versions": [{"id": 9, "number": 3, "item_count": 20, "content_hash": "…", "note": "Added 1 item", "created_at": "…"}],
 "experiment_count": 4, "created_at": "…", "updated_at": "…"}
```

Version: `{"id", "dataset_id", "number", "content_hash", "item_count",
"document_ids", "note", "created_at", "checks"}` with `checks` =
`{"items_without_sources": [item_id…], "duplicate_questions": [[item_id…]…], "missing_documents": [item_id…]}`
(each list ≤ 50, computed on read against the current documents).

Experiment (list and detail):

```json
{
  "id": 42, "workspace_id": 3, "name": "…", "hypothesis": "…", "conclusion": "",
  "status": "running", "error": null,
  "dataset": {"id": 5, "name": "Paper QA", "version_id": 9, "version": 2, "content_hash": "…", "item_count": 20, "available": true},
  "pipeline": {"id": 4, "name": "Hybrid", "version_id": 11, "version": 3, "config_hash": "…", "strategy": "hybrid", "available": true},
  "retrieval_only": false, "seed": 42, "k_values": [1, 3, 5, 10],
  "progress": {"total": 20, "completed": 5, "failed": 1, "pending": 14},
  "metrics": Aggregates,
  "failures": {"retrieval": {"relevant_not_retrieved": 1, "wrong_document": 0, "insufficient_k": 2, "query_mismatch": 0},
               "generation": {"unsupported_claim": 0, "citation_mismatch": 1, "incomplete_answer": 0},
               "dataset": {"ambiguous_question": 0, "missing_evidence": 0, "duplicate_question": 0},
               "items_with_failures": 3},
  "warnings": [{"code": "repeated_dataset_runs", "message": "…"}],
  "git_commit": "abc123" , "rerun_of": null, "runtime_ms": 12345,
  "created_at": "…", "updated_at": "…", "started_at": "…", "finished_at": null
}
```

`error` is `{"code", "message", "retryable"}` or null. `metrics` and
`failures` cover the completed items so far (recomputed on read while the
run is unfinished, stored when it ends). ExperimentDetail adds `config`,
`index_versions`, `environment` and `reproducibility`
(`{"status": "reproducible" | "changed", "warnings": [...]}`, computed on
read against the current pipeline, dataset and index versions).

Aggregates:

```json
{
  "items": {"total": 20, "completed": 18, "failed": 2},
  "retrieval": {"recall@5": {"mean": 0.82, "count": 16, "null_count": 2, "reasons": {"no_expected_sources": 2}}, "…": {}},
  "generation": {"faithfulness": {"mean": 0.9, "count": 18, "null_count": 0, "reasons": {}}, "…": {}},
  "latency_ms": {"total": {"p50": 420.0, "p95": 910.0, "mean": 480.5, "count": 18}, "retrieval": {…}, "generation": {…}, "judge": {…}},
  "tokens": {"prompt": 9000, "completion": 1200, "total": 10200, "per_item": 566.7, "items_with_usage": 18},
  "cost": {"usd": null, "reason": "pricing_unavailable"}
}
```

Percentiles as Phase 2 (`runs.percentile`). Tokens are generation tokens
(the judge reports none).

ExperimentItem:

```json
{
  "position": 1, "item_id": "q1", "status": "completed", "error": null,
  "question": "…", "expected_answer": "…", "expected_sources": [ExpectedSource], "history": [], "tags": [],
  "run_id": 77, "answer": "…",
  "query": {"used": "…", "original": "…", "rewritten": "…", "rewrite_applied": true, "rewrite_reason": "rewritten"},
  "matching": [{"source": 0, "rule": "chunk_id", "chunk_ids": [345], "reason": null}],
  "retrieved": [{"rank": 1, "document_id": 12, "chunk_id": 345, "in_context": true, "cited": true, "relevant": true, "sources": [0]}],
  "alternative": null,
  "metrics": {"recall@5": 1.0, "mrr": 1.0, "faithfulness": 0.92, "…": null},
  "metric_reasons": {"answer_correctness": "no_expected_answer"},
  "failure_labels": [{"category": "retrieval", "code": "insufficient_k", "detail": "…", "sources": [1]}],
  "latency_ms": {"total": 820, "retrieval": 140, "generation": 650, "judge": 2100},
  "token_usage": {"prompt_tokens": 812, "completion_tokens": 96, "total_tokens": 908},
  "started_at": "…", "finished_at": "…"
}
```

`alternative` (when computed) is `{"query", "retrieved": [{"rank", "document_id", "chunk_id", "in_context", "relevant", "sources"}]}`.
`error` is `{"code", "message", "stage"}` or null.

Comparison (`GET experiments/compare/`): 2–6 distinct ids of the caller's
experiments (unknown or another user's → 404), all on the **same dataset**
(else 400 `invalid_request`, `details.ids`); `baseline` one of them
(default the first); `metric` the per-item table's metric (default
`recall@5` when every experiment has K = 5, else `mrr`); `seed` defaults
to the baseline's.

```json
{
  "baseline_id": 1,
  "experiments": [Experiment],
  "metrics": [{"key": "recall@5", "group": "retrieval", "higher_is_better": true,
    "cells": [{"experiment_id": 1, "mean": 0.8, "count": 18, "delta": null, "paired_delta": null, "ci_low": null, "ci_high": null, "pairs": null, "wins": null, "losses": null, "ties": null},
              {"experiment_id": 2, "mean": 0.9, "count": 18, "delta": 0.1, "paired_delta": 0.1, "ci_low": 0.02, "ci_high": 0.18, "pairs": 18, "wins": 3, "losses": 1, "ties": 14}]}],
  "operational": [{"key": "latency_p50_ms", "higher_is_better": false, "cells": [{"experiment_id": 1, "value": 420.0, "delta": null}, …]},
                  "latency_p95_ms", "tokens_per_item", "total_tokens", "cost_usd"],
  "items": {"metric": "recall@5", "rows": [{"item_id": "q1", "question": "…", "cells": [{"experiment_id": 1, "value": 1.0, "outcome": null}, {"experiment_id": 2, "value": 0.0, "outcome": "loss"}]}]},
  "bootstrap": {"seed": 42, "resamples": 2000, "confidence": 0.95},
  "config_differences": [{"key": "strategy", "values": ["dense", "hybrid"]}],
  "warnings": [{"code": "multiple_changes", "message": "…", "experiment_ids": [3]}]
}
```

- Cells and `values` follow the order of `experiments`. `delta` = mean −
  baseline mean. Pairs are items present in both (same `item_id` and the
  same question, expected answer and sources) where both values are
  non-null, sorted by `item_id`; `paired_delta` is their mean difference
  and `ci_low`/`ci_high` its paired bootstrap percentile interval: 2,000
  resamples of the pairs with `numpy.random.default_rng(seed)` (a fresh
  generator per cell, so results do not depend on order), 2.5th and 97.5th
  percentiles, 6 decimals; null with fewer than 2 pairs. `wins`/`losses`/
  `ties` compare each pair (higher is better for every quality metric).
- Operational rows: p50/p95 of item `latency_ms.total`, generation tokens
  per completed item and in total, and `cost_usd` (null: no pricing data).
- `config_differences`: every pipeline setting (`config.pipeline.config`)
  and evaluation setting (`retrieval_only`, `query_rewrite`, `k_values`,
  `judge_model`, `thresholds`, `document_ids`) that differs, values aligned
  with `experiments`.
- Warnings: `dataset_version_mismatch` (different versions of the dataset;
  only unchanged items are paired), `evaluation_settings_differ`,
  `multiple_changes` (more than one pipeline setting differs from the
  baseline, so a difference cannot be attributed to one change),
  `index_versions_differ`, `incomplete_experiment` (not completed, or
  failed items), `repeated_dataset_runs`.

### Retrieval runs

- Evaluation items are recorded with `source="evaluation"`.
- `GET retrieval/runs/summary/` **without** `source` now excludes
  evaluation runs (they are test traffic) and says so with the additive key
  `"excluded_sources": ["evaluation"]` (`[]` when `source` is given;
  `source` stays null when not filtered). `?source=evaluation` reports only
  them.
- `GET retrieval/runs/` is unchanged (every source unless `source` is
  given); the web client's Runs list asks for `source=chat`.

### Frontend

`src/features/evaluation/` — `api/evaluation.ts`, `types/`, `hooks/`
(`useDatasets`, `useDataset`, `useExperiments`, `useExperiment` — polls
every 2 s while `queued`/`running` —, `useComparison`), `lib/metrics.ts`
(definitions, groups, formatting, null reasons), `lib/comparison.ts`
(deltas, direction, CI text, trade-offs), `lib/failures.ts` (labels,
grouping), `lib/datasetCsv.ts` (CSV + compact sources, mirroring the
server), `lib/experiments.ts` (status, progress), components for the
dataset list and editor (item table, item form with a source picker,
import/export), the experiment launcher, the registry, the experiment
detail (aggregates with definitions, item table with failure labels,
drill-down into each item's run with `RunTrace`), the comparison view and
the "Add to dataset" dialog.

- The workspace's right column and the mobile tabs gain **Evaluation**; on
  wide screens the right column widens while Evaluation is shown.
- Every complete answer has **Add to dataset**: pick a dataset (or create
  one), confirm the question, optionally type an expected answer (never
  prefilled with the model's answer), and pick expected sources (the cited
  ones are pre-selected).
- The Runs list requests `source=chat`, with a Chat / Evaluation filter.
- `evaluations/` and `experiments/` are token-protected paths.

### Deferred

- Pinning an old index version for a rerun: `run_retrieval` always searches
  each document's current index; a rerun records `index_version_changed`
  instead.
- Dollar cost: no pricing data in the model catalogue (`cost.usd` null).
- Judge token usage: Ragas does not report it.
- LLM sampling is not seeded; the seed drives the bootstrap.

## Reserved for later phases

- Phase 2 (done) added persisted retrieval runs and per-stage telemetry;
  Phase 3 (done) fills `rerank_ms`, `rerank_score` and
  `provenance.reranker`; Phase 4/5 record runs with `source`
  `evaluation`/`research`.
- Phase 3 (done) made the chat strategy (`dense`, `bm25`, `hybrid`,
  `hybrid_rerank`) selectable through versioned pipelines.
- Phase 4 (done) added evaluation datasets, metrics and an experiment
  registry that reference pipeline and index versions, recording runs with
  `source="evaluation"`.
- Phase 5 adds Research Mode, comparison, extraction and reports on top of the
  chat and evidence model.
