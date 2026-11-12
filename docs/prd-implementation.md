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
  their request and response shapes. Sign-up may only *add* fields.
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
734, 102 module tests.

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
  views/runs.py           Phase 2: retrieval runs list/detail/summary
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
(sha256 hex, unique), `created_at`, `last_used_at` (null). Plaintext tokens are
`rr_` + `secrets.token_urlsafe(32)`, returned once, never stored.

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

- Sign-up/sign-in (`POST /api/v1/sign-up/`) adds `"token"` to its `data`
  object; every call issues a new token.
- `workspace.auth.GuestTokenAuthentication` reads `Authorization: Bearer <token>`.
  `authenticate_header()` returns `Bearer`, so missing/invalid credentials give
  **401**. `GuestUser` gains `is_authenticated = True` / `is_anonymous = False`
  properties (no migration).
- Every new view subclasses `workspace.views.base.OwnedAPIView`
  (`authentication_classes=[GuestTokenAuthentication]`,
  `permission_classes=[IsAuthenticated]`) and loads objects only through its
  helpers (`get_workspace`, `get_document`, `get_session`), which filter by
  `request.user` and raise **404** for objects the user does not own.
- Legacy endpoints stay unauthenticated (known debt, documented in
  `docs/workspace-api.md`).

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
  A 401 from the new API sends the user to `/login?next=<path>`; the login page
  follows `next` only when it starts with `/` and not `//`.
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

## Reserved for later phases

- Phase 2 (done, see above) added persisted retrieval runs and per-stage
  telemetry; Phase 3 fills `rerank_ms`, `rerank_score` and
  `provenance.reranker`, and Phase 4/5 record runs with `source`
  `evaluation`/`research`.
- Phase 3 adds pipeline configuration/versioning and makes the chat strategy
  (`dense`, `bm25`, `hybrid`, `hybrid+rerank`) selectable; Phase 1 hardcodes
  `dense`.
- Phase 4 adds evaluation datasets, metrics and an experiment registry that
  reference pipeline and index versions.
- Phase 5 adds Research Mode, comparison, extraction and reports on top of the
  chat and evidence model.
