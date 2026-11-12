# Workspace API

The workspace API is RAGReader's resource-oriented API for persistent
documents, background ingestion, conversations and cited, streamed answers
(PRD Phase 1), and the retrieval runs that make every answer inspectable
(Phase 2). It lives in the `workspace` Django app, under `/api/v1/`, next
to the legacy endpoints, which keep their request and response shapes but,
like everything else, now require the bearer token.

The authoritative shapes are in [`prd-implementation.md`](prd-implementation.md);
this page explains how the API behaves.

## Authentication

Accounts are a username, an email and a password (Django's
`make_password` hash; the plaintext is never stored or logged).

1. **Create an account** — `POST /api/v1/sign-up/` with
   `{"USERNAME": "…", "EMAIL": "…", "PASSWORD": "…"}`. The password must pass
   Django's `AUTH_PASSWORD_VALIDATORS` (length ≥ 8, not common, not only
   digits, not similar to the username or email). Answers **201** in the
   legacy envelope, `{"status", "message", "timestamp", "data": {"response",
   "username", "email", "token"}}`.
2. **Sign in** — `POST /api/v1/sign-in/` with `{"USERNAME": "…", "PASSWORD": "…"}`
   (or `EMAIL`; either value is matched as a username first, then as an
   email) → **200** `{"token", "username", "email", "expires_at"}`. Every
   sign-in issues a new token, so a second browser does not log the first one
   out; only the newest 20 tokens per user are kept.
3. Send the token on every request: `Authorization: Bearer rr_…` (`rr_`
   followed by 43 URL-safe characters).
4. **Sign out** — `POST /api/v1/sign-out/` with the token → **204**. Revokes
   that token only; other sessions stay signed in.

Tokens expire `RAG_TOKEN_TTL_DAYS` (default 30) after they are issued. A
missing, malformed, unknown, revoked or expired token returns **401** with
`WWW-Authenticate: Bearer` and the error envelope (`authentication_required`).
Only a SHA-256 of each token is stored.

| Situation | Sign-up with `PASSWORD` | Sign-in |
| --- | --- | --- |
| New username and email | 201 + token | 401 `invalid_credentials` |
| Weak password | 400 `invalid_request`, validator messages in `details.PASSWORD` | — |
| Account with a password | 409 `account_exists` (no token) | 200 + token, or 401 `invalid_credentials` |
| Username or email taken by different accounts | 409 `account_exists` | — |
| Account from before passwords, same username **and** email | Sets the password: 200 + token, `"claimed": true` | 409 `password_not_set` |
| Account from before passwords, other email | 409 `account_exists` | 409 `password_not_set` |

An unknown account and a wrong password give byte-for-byte the same 401, and
the unknown case still checks the password against a dummy hash, so neither
the body nor the response time tells them apart. Claiming an account from
before passwords is a conditional update (only while the stored password is
empty), so two concurrent claims cannot both win; it also revokes every
token the account had, since those were issued to anyone who knew its
username and email.

Sign-up **without** `PASSWORD` keeps its old behaviour and response (201
"User created successfully!" / 200 "User already exists") but never contains
a token, so it cannot be used to sign in. Sign-up errors keep the legacy
envelope and add the `error` object below (`data` is `null`).

Sign-up and sign-in share a per-client throttle (DRF `ScopedRateThrottle`,
scope `auth`, `RAG_AUTH_THROTTLE_RATE`, default `10/min`): beyond it they
answer **429** `rate_limited` with `Retry-After`. Clients are told apart by
IP address; set `RAG_NUM_PROXIES` to the number of reverse proxies in front
of Daphne so the address is taken from the right `X-Forwarded-For` hop.

Every object is filtered by the token's user. Another user's workspace,
document or conversation returns **404**, exactly like an id that does not
exist, so ids cannot be probed. The same holds for the legacy and
deep-analysis endpoints (see [Legacy and deep-analysis
endpoints](#legacy-and-deep-analysis-endpoints)).

## Errors

Every non-2xx JSON response has one shape:

```json
{"error": {"code": "unsupported_file_type", "message": "Upload a PDF, DOCX, TXT or Markdown file.", "retryable": false, "stage": null, "details": null}}
```

`message` is written for people; `code` is stable for programs. `details`
holds field errors for `invalid_request`. `stage` names the failed ingestion
stage or chat step where that applies.

| Code | Status | When |
| --- | --- | --- |
| `authentication_required` | 401 | No, invalid, revoked or expired token |
| `invalid_credentials` | 401 | Sign-in: unknown account or wrong password |
| `password_not_set` | 409 | Sign-in to an account created before passwords; claim it through sign-up |
| `account_exists` | 409 | Sign-up for a username or email that is taken |
| `rate_limited` | 429 | Too many sign-up/sign-in attempts from this client |
| `not_found` | 404 | Unknown id, or another user's object |
| `invalid_request` | 400 | Validation failed; see `details` |
| `file_too_large` | 413 | Upload over `RAG_MAX_UPLOAD_BYTES` |
| `unsupported_file_type` | 415 | Extension not allowed, or content does not match it |
| `url_not_allowed` | 400 | URL refused by the SSRF rules below |
| `ingestion_in_progress` | 409 | Re-index while a run is live; reader text not extracted yet |
| `no_ready_documents` | 409 | Question with no READY document in scope |
| `last_workspace` | 409 | Deleting the only workspace |
| `no_original_file` | 404 | `file/` of a web page or pasted text |
| `text_unavailable` | 404 | `text/` of a finished document without extracted text |
| `job_queue_unavailable` | 503 | The Celery broker could not be reached |
| `internal_error` | 500 | Unexpected server error (details only in server logs) |

Ingestion and chat failures stored on a document or message use the same
codes as the rest of the backend (`provider_timeout`, `provider_credits`,
`invalid_embeddings`, …; see [jobs.md](jobs.md)) plus `no_extractable_text`,
`invalid_pdf`, `pdf_encrypted`, `invalid_docx`, `missing_source`,
`url_fetch_failed`, `url_fetch_timeout`, `ingestion_failed`,
`ingestion_timeout`, `index_unavailable` and `stream_interrupted`.

## Endpoints

All paths are under `/api/v1/` and require the token, except `sign-up/` and
`sign-in/`.

| Method | Path | Notes |
| --- | --- | --- |
| POST | `sign-up/` | No token. Create an account or claim a legacy one; see [Authentication](#authentication). |
| POST | `sign-in/` | No token. `{USERNAME or EMAIL, PASSWORD}` → `{token, username, email, expires_at}`. |
| POST | `sign-out/` | Revokes the presenting token → 204. |
| GET | `workspaces/` | `{"results": [Workspace]}`, default first. Creates "My Workspace" on first use. |
| POST | `workspaces/` | `{name}` → 201. A user's first workspace becomes the default. |
| GET, PATCH, DELETE | `workspaces/{id}/` | PATCH `{name}`. DELETE removes its documents (with files and indexes) and conversations → 204; deleting the default promotes the oldest remaining workspace; deleting the last one is 409 `last_workspace`. |
| GET | `documents/?workspace_id=` | Newest first. Default workspace when omitted. |
| POST | `documents/` | See [Adding documents](#adding-documents) → **202** Document. |
| GET, PATCH, DELETE | `documents/{id}/` | PATCH `{title}`. DELETE also removes the stored original, saved page, extracted text and every index pickle → 204. |
| GET | `documents/{id}/ingestion/` | IngestionStatus (stage checklist, live job, error, `can_retry`). |
| POST | `documents/{id}/ingestion/` | Retry or re-index → **202** IngestionStatus; 409 `ingestion_in_progress` while a job is live. |
| GET | `documents/{id}/file/` | The original upload, `Content-Disposition: inline`, `X-Content-Type-Options: nosniff`. |
| GET | `documents/{id}/text/` | `{"document_id", "text", "pages", "char_count", "truncated"}` for the reader. `pages` is `[{"number", "start", "end"}]` (PDF content only). |
| GET | `conversations/?workspace_id=` | Most recently active first. |
| POST | `conversations/` | `{title?, workspace_id?, document_ids?}` → 201. |
| GET, PATCH, DELETE | `conversations/{id}/` | PATCH `{title?, document_ids?}`. Renaming stops automatic titles. |
| GET | `conversations/{id}/messages/` | Oldest first. |
| POST | `conversations/{id}/messages/` | `{content, document_ids?}` → `text/event-stream`; `?stream=0` → 201 `{"user_message", "assistant_message"}`. |
| GET | `retrieval/runs/` | Recent runs, newest first. `?workspace_id=&conversation_id=&status=completed\|failed&source=chat&limit=1–200` (default 50) → `{"results", "has_more"}`. See [Retrieval runs](#retrieval-runs). |
| GET | `retrieval/runs/{id}/` | One run's trace: provenance, span tree, candidates. |
| GET | `retrieval/runs/summary/` | Reliability for `?workspace_id=&days=1–365` (default 30): failure rates, latency percentiles, tokens, ingestion. |

`document_ids` must belong to the conversation's workspace (otherwise 400
`invalid_request`). Interactive OpenAPI docs are at `/api/docs/`.

## Legacy and deep-analysis endpoints

The endpoints in `router/urls.py` and `evaluation/urls.py` keep their request
and success response shapes, and require the same bearer token. Without a
valid one they answer 401 with the error envelope above. Anything they are
given that names another user — a `USER` body field, a `<username>` in the
path, or the id of someone else's document, chunk, legacy turn, ground
truth, job or analysis batch — is treated exactly like something that does
not exist: 404 in the endpoint's usual error shape, nothing read or written.
Legacy turns from before `Conversation.user` existed belong to their
document's owner.

| Endpoint | Checked against the caller |
| --- | --- |
| `POST insert-data/`, `insert-text/`, `insert-url/` | `USER` must be the caller (checked before any upload is parsed or URL fetched); the document goes to the caller's default workspace |
| `POST open-chat/`, `POST query/` | `USER` must be the caller |
| `GET job-status/<job_id>/` | the job's owner |
| `GET document/<username>/`, `GET conversation-history/<username>/` | `<username>` must be the caller |
| `GET conversation/<id>/` | the legacy turn's owner |
| `POST start-analysis/` | `conversation_id`'s owner; a `request_id` that belongs to another batch (anyone's) is 409 `request_id_conflict` |
| `GET analysis-status/<job_id>/` | the batch's owner, checked before `?conversation_id=` (so another user's batch is 404, never 409) |
| `POST chunk/`, `GET chunk/<document_id>/` | `USER` / the document's owner (a missing document is now 404 too) |
| `POST ground-truth-chunk/` | the turn's owner; `chunk_id`s outside the caller's documents are ignored |
| `POST ground-truth-chunk/pool/` | the turn's owner; pooled chunks that are not the caller's are dropped before they are stored or returned |
| `GET ground-truth-chunk/<id>/`, `POST`/`GET ground-truth-response/…` | the turn's owner (a missing turn is now 404 on the GETs too, instead of an empty list) |
| `POST evaluate/ground-truth-chunk/` | the turn's owner and `batch_id`'s owner |
| `POST evaluate/ground-truth-response/` | the turn's owner |
| `GET analysis-config/` | **Public**: static options and the model catalogue, no user data |

### Analysis WebSocket

`ws/analysis/<job_id>/` authenticates with its first message, so the token
never appears in a URL or an access log. After the socket opens the client
sends:

```json
{"type": "auth", "token": "rr_…"}
```

Until that token is valid and unexpired and the batch belongs to its user,
the server sends nothing about the job and does not subscribe the socket to
the batch's live updates. A first message that is not this, an invalid or
expired token, or no message within 10 seconds closes the socket with code
**4401**. A batch that does not exist or belongs to someone else gets the
usual terminal `job_not_found` error frame and close code **4404**. A
malformed `job_id` is reported (`invalid_job_id`, 4400) only after the
token is accepted. After that the protocol is unchanged (`CONFIG` or
`REPLAYING`, results, `STAGE_PROGRESS`, `WAITING`, `COMPLETE`). The web client
sends the auth frame on every (re)connect and treats 4401 and 4404 as final:
it stops reconnecting and asks the user to sign in.

## Adding documents

`POST /api/v1/documents/` accepts three bodies:

* **File** — `multipart/form-data` with `file`, optional `title` and
  `workspace_id`. PDF, DOCX, TXT and Markdown (`.pdf .docx .txt .text .md
  .markdown`).
* **URL** — JSON `{"source_type": "url", "url": "https://…", "title"?, "workspace_id"?}`.
  Without a title the page's `<title>` is used once it has been fetched.
* **Pasted text** — JSON `{"source_type": "text", "text": "…", "title"?, "workspace_id"?}`,
  at most `RAG_MAX_TEXT_CHARS` characters. Without a title the first line is used.

The request only validates and stores the input, creates the document
(`QUEUED`) and an ingest job, and enqueues `workspace.tasks.ingest_document_task`
after the transaction commits — nothing is parsed or embedded, so it answers
quickly. If the broker is down, the job and document are marked `FAILED`
(`job_queue_unavailable`, retryable) and the response is **503** with the
error envelope plus `"document": Document`. A failed re-index enqueue likewise
returns 503 with `"ingestion": IngestionStatus`.

### Upload rules

* The type is decided by the content, not by the browser's Content-Type: a
  PDF must start with `%PDF-`; a DOCX must be a ZIP containing
  `word/document.xml` within zip-bomb limits; TXT/Markdown must decode as
  UTF-8 or Windows-1252 and contain no NUL bytes. Anything else is 415.
* Size: `RAG_MAX_UPLOAD_BYTES` (default 25 MB) → 413. An oversized
  `Content-Length` is refused before the body is parsed.
* Files are stored as `documents/user_<user id>/<uuid>/<sanitised name>`, one
  directory per document.
* DOCX XML is parsed with DTDs and entity declarations refused, which blocks
  entity-expansion and external-entity attacks in any encoding.

## Ingestion lifecycle

```
QUEUED → EXTRACTING → CLEANING → CHUNKING → EMBEDDING → INDEXING → READY
                                                         (any stage) → FAILED
```

| Stage | Progress | What happens |
| --- | --- | --- |
| EXTRACTING | 5–15 | PDF page by page (PyPDF2); DOCX paragraphs; TXT/Markdown decoded; URLs fetched (see below) and read as an article, or as a PDF when the URL serves one. |
| CLEANING | 15–20 | Each page normalised with the legacy `_clean_text`, empty pages dropped, pages joined by a blank line and their character offsets recorded; counts saved. |
| CHUNKING | 20–25 | The chat engine's own chunker, so the texts match what the index will contain. |
| EMBEDDING | 25–85 | Missing chunk texts are embedded in batches of 64; every batch is committed to the embedding checkpoint before the next call. `status_detail` reads e.g. `Embedded 640 of 1,000 chunks`. |
| INDEXING | 85–99 | The engine's `_build_index` (one atomic transaction) reads every vector from the checkpoint; then `current_index` is set and each chunk's `ordinal`, `char_start`, `char_end`, `page_start`, `page_end` are merged into its metadata. |
| READY | 100 | `ingested_at` is set; the document can be used in chat. |

**Resuming.** A retry (`POST documents/{id}/ingestion/`) creates a new job.
Extraction and chunking are repeated (they are cheap and deterministic), but
only the chunk texts without a committed embedding are sent to the provider:
a failure at chunk 700 of 1,000 costs at most one batch. Re-indexing a READY
document reuses every vector unless the text or embedding model changed, and
creates a new index version (`index.id` changes). Re-indexing re-reads the
stored original — for web pages the saved copy — and never refetches.

**Failures** record `error.stage`, `error.code`, `error.message` and
`error.retryable` on the document, and fail the job. Worker crashes are
detected when the document is read: a job that has made no progress for 35
minutes is expired (`ingestion_timeout`) and the document becomes `FAILED`.
Duplicate task deliveries cannot claim the job and do nothing. A worker that
lost its job (expired, superseded) stops without writing. The task's limits
are 30 minutes (soft) and 31 minutes (hard).

**Legacy documents.** The migration gives every existing user with
documents a default workspace. Documents that already have a dense index
become `READY`; the others become `FAILED` with `not_indexed` and a "Re-index
it" message. Documents indexed through the legacy `open-chat` flow keep
their status in step (`CHUNKING` → `READY`/`FAILED`), and the legacy insert
endpoints file new documents into the default workspace. When a legacy
document that already has deep-analysis ground truth is re-indexed, its
original extracted text is indexed verbatim so its chunks — and the ground
truth attached to them — survive (its citations then carry no page numbers).

## URL ingestion security

URL documents are fetched by the worker, never by the API request, through a
fetcher built to prevent SSRF (PRD §39):

* `http` and `https` only, no `user:password@`, ports 80, 443, 8080, 8443.
* Every connection — the first and each redirect, at most 5 — is opened by a
  custom urllib3 connection that resolves the host itself, refuses it if any
  address is not globally routable (loopback, private, link-local incl.
  `169.254.169.254`, CGNAT, multicast, reserved, unspecified, IPv4-mapped,
  6to4/Teredo/NAT64-embedded private addresses), and connects to exactly the
  address it checked. DNS rebinding between check and connect is therefore not
  possible.
* Redirect targets are re-validated before their connection is opened.
* Proxy environment variables are ignored (`trust_env=False`); proxies are
  refused.
* 5 s connect / 15 s read timeouts and a 45 s total download budget;
  `RAG_MAX_URL_BYTES` body cap (default 10 MB, counted after decompression);
  content types HTML, XHTML, plain text, Markdown and PDF only.

`POST documents/` already refuses obviously bad URLs (scheme, `localhost`,
literal private addresses including short forms such as `127.1`) with 400
`url_not_allowed`; the worker applies the full check. The legacy
`POST /api/v1/insert-url/` uses the same fetcher.

## Chat

A question is answered from every READY document in scope: the message's
`document_ids` if given, otherwise the conversation's `document_ids`,
otherwise every document in the workspace. Documents still ingesting are
skipped; with none READY the request is 409 `no_ready_documents`.

One turn:

1. The question and an empty assistant message (`status: "streaming"`) are
   saved. The first question names an untitled conversation (≤ 80 chars).
2. **Rewrite.** With earlier messages, the chat model rewrites the question
   into a standalone search query from the last 6 completed messages. A
   rewrite that is not one line of at most 200 characters, or that fails, is
   ignored. The first question is searched as asked.
3. **Retrieve.** The query is embedded once and scored by cosine similarity
   against each document's current dense index; candidates from all
   documents are merged by score, identical passages are kept once, 20
   candidates are kept and the top 5 become numbered sources. Loaded indexes
   are cached per process (`RAG_CHAT_INDEX_CACHE_SIZE`, default 8). A document
   whose index cannot be loaded fails the turn with `index_unavailable` naming
   it; chat never builds an index itself.
4. **Generate.** The model is told to answer only from the numbered sources,
   to cite `[n]` after each supported claim, to say when the sources are
   insufficient and never to invent a citation (prompt version
   `chat-cited-v1`). The answer is streamed. If OpenRouter reports exhausted
   credits before the first token, the same free-model fallback as the rest of
   the backend applies; `retrieval.pipeline.generation_model` records the
   model that actually answered.
5. **Finish.** `[1]`, `[1, 2]` and `[1][3]` markers set each source's `cited`
   flag (out-of-range numbers are ignored). Citations, retrieval metadata,
   token usage and latency are saved. When exactly one document was in scope,
   the answer is also recorded as a legacy turn and linked as
   `analysis_turn`, so **Deep analysis** (`/ground-truth/{conversation_id}/{document_id}`)
   works on it.

### Server-sent events

`POST conversations/{id}/messages/` answers `200` with
`Content-Type: text/event-stream`, `Cache-Control: no-cache` and
`X-Accel-Buffering: no`. Frames are `event: <name>\ndata: <json>\n\n`;
`: ping` comment lines may appear while waiting.

| Event | Data |
| --- | --- |
| `message.created` | `{"user_message": Message, "assistant_message": Message}` |
| `stage` | `{"id": "rewrite" \| "retrieve" \| "generate", "status": "running" \| "completed" \| "skipped" \| "failed", "detail", "duration_ms"}` |
| `retrieval` | `{"candidate_count", "context_count", "citations": [Evidence with cited=false]}` (before generation) |
| `token` | `{"delta": "text"}` |
| `message.completed` | `{"message": Message, "run_id": int \| null}` |
| `error` | `{"error": {"code", "message", "retryable", "stage", "details"}, "message": Message \| null, "run_id": int \| null}` |

A successful turn reads `message.created`, `stage` (rewrite completed or
skipped), `stage` (retrieve running/completed), `retrieval`, `stage`
(generate running), `token`…, `stage` (generate completed),
`message.completed`. The stream ends after `message.completed` or `error`.
Problems found before streaming starts (empty question, unknown conversation,
no READY document) are ordinary JSON errors.

Use a `fetch` POST reader, not `EventSource` (which cannot POST or send the
Authorization header). `?stream=0` runs the same turn and returns both
messages as JSON (201).

**Transports.** Under WSGI and Django's test client the turn runs inline as
the response is read. Under ASGI (Daphne, as deployed) Django would buffer a
synchronous stream until it ended, so the view returns an asynchronous
iterator instead: the turn runs on a worker thread and hands each event to the
event loop as it is produced. The thread is independent of the connection: if
the browser disconnects, the answer is still completed and saved, and appears
on reload. (Under WSGI a disconnect stops the turn and marks the answer
`failed` with `stream_interrupted`.) An answer left `streaming` for more than
10 minutes (server restart) is shown as failed. Behind nginx,
`X-Accel-Buffering: no` turns proxy buffering off for this response.

## Retrieval runs

Every question is traced (PRD §32) and stored as a **retrieval run** —
whether it completed or failed — before the stream's closing events, so a
client that leaves early loses neither the answer nor its trace. The answer's
`retrieval.run_id` (and `run_id` in `message.completed`/`error`) points at it.
Recording is best-effort: if it fails, the error is logged and the answer is
delivered and saved without a run id. Tracing never fails a turn.

A run records:

* **What was asked and searched** — the question, the rewritten query, and
  why it was not rewritten when it was not (`first_question`, `unchanged`,
  `unusable`, `failed`).
* **Provenance** (§20) — strategy, retrieval parameters (`candidate_k`,
  `context_k`, cosine similarity, de-duplication, history), embedding model,
  reranker (none until Phase 3), the generation model that answered and the
  configured one (they differ when the free-model fallback was used;
  `fallback_used` says so), generation parameters, prompt version, and every
  index version searched (DocumentVector id, method, build time, embedding
  model, whether it loaded).
* **Latency** — total (= the message's `latency_ms`), rewrite, retrieval,
  rerank (null), generation and first token (from the question), each null
  when that step did not run or complete.
* **Tokens** — prompt, completion and total for the answer (the rewrite call
  reports none).
* **The span tree** — `chat.turn` → `prepare`, `rewrite`, `retrieve`
  (`retrieve.load_indexes` with one `index.load` per document and its cache
  hit or miss, `retrieve.embed_query`, `retrieve.search`, `retrieve.select`),
  `generate` (`generate.first_token`), `citations`, `persist`. Offsets are
  milliseconds from the start of the turn. A failure closes the failing span
  and its parents as `failed` with the error code.
* **Candidates** — every retrieved passage in rank order (at most 50 are
  stored; chat retrieves 20): document, page and character range, retrieval
  score, rerank score (null), whether it was in the context and under which
  `[n]`, and whether the answer cited it.

`GET retrieval/runs/{id}/` returns all of it. A candidate's `text` is the
whole passage while its chunk still exists, otherwise the stored 300-character
snippet; after the document is deleted, `document_id` is null,
`document_available` false and the title is kept. Deleting a conversation
deletes its runs (they contain the question).

`GET retrieval/runs/summary/` reports a workspace's reliability (§49) over the
last `days`:

* run counts and the failure rate, overall and by stage — `retrieval`
  (`error_stage=retrieve`), `generation` (`generate`), `other`;
* p50 and p95 of total, retrieval and generation latency and of first-token
  time over **completed** runs (linear interpolation between closest ranks, as
  numpy and PostgreSQL's `percentile_cont`; null without data);
* token totals and the average per answer;
* ingestion: the workspace's documents by current status with the success
  rate (READY of READY + FAILED), and ingestion attempts (jobs) started in the
  window. Documents from before background ingestion that were never indexed
  (`not_indexed`) are listed apart and not counted as failures.

Rates are fractions with four decimals, null when nothing was counted.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `RAG_MAX_UPLOAD_BYTES` | 26214400 (25 MB) | Largest accepted upload |
| `RAG_MAX_TEXT_CHARS` | 2000000 | Longest pasted text |
| `RAG_MAX_URL_BYTES` | 10485760 (10 MB) | Largest fetched web page or PDF |
| `RAG_CHAT_INDEX_CACHE_SIZE` | 8 | Loaded document indexes kept in memory per process |
| `RAG_TOKEN_TTL_DAYS` | 30 | Days a token stays valid after sign-up/sign-in |
| `RAG_AUTH_THROTTLE_RATE` | `10/min` | Sign-up + sign-in attempts per client (DRF rate; empty disables) |
| `RAG_NUM_PROXIES` | unset | Reverse proxies in front of Daphne; picks the client IP from `X-Forwarded-For` for the throttle |

The embedding model and chunking settings are the ingest-time settings in
`common/constant.py` (`RAG_EMBEDDING_MODEL`, `RAG_CHUNK_*`); chat retrieval
depth and the prompt version are constants there too (`CHAT_CANDIDATE_K`,
`CHAT_CONTEXT_K`, `CHAT_HISTORY_MESSAGES`, `CHAT_PROMPT_VERSION`).

## Known debt

* **One-time claim of passwordless accounts.** An account from before
  passwords — or one created since by a sign-up without `PASSWORD` (legacy
  clients) — gets its password from the first sign-up that names its exact
  username and email. Whoever knows both can therefore claim it before its
  owner does (and sign-in's `password_not_set` tells anyone which usernames
  are still unclaimed). The claim revokes every earlier token, and afterwards
  the account needs its password like any other.
* **Deploying this signs everyone out once.** Tokens issued before
  passwords were minted from a username and email alone, so migration
  `workspace/0003_apitoken_expires_at` deletes them; every user signs in
  (or claims their passwordless account) again.
* **No email verification or password reset.** The email is not checked
  for ownership, so an account is only as strong as its password, and a
  forgotten password cannot be recovered yet. Sign-up reveals whether a
  username or email is taken (409), as any sign-up form does; the throttle
  limits how fast that can be probed.
* **The throttle is per IP address.** Without `RAG_NUM_PROXIES` matching
  the deployment, either every client behind the proxy shares one budget or
  a client can rotate a forged `X-Forwarded-For` to get a new one. There is
  no per-account lockout.
* **`analysis-config/` is public.** It exposes no user data, but
  `?refresh=1` bypasses the catalogue cache, so anyone can make the server
  refetch the model list from OpenRouter on every such request.
* Every re-index writes a new index file; older versions stay on disk until
  the document is deleted.
* With `RAG_CHUNK_STRATEGY=semantic` the chunker embeds sentences itself;
  those calls are not checkpointed and repeat in `_build_index`.
* The chat index cache is per process; a document deleted through another
  process stays cached there (unreachable, never served) until evicted.
* Phase 1 chat is dense-only; BM25, hybrid and reranking arrive in Phase 3.
* Runs are kept until their conversation or workspace is deleted; there is
  no age-based clean-up yet. Each run is bounded (≤ 100 spans of ≤ 2 KB data,
  ≤ 50 candidates with 300-character snippets).
* A producer killed mid-turn (worker restart) leaves no run; its message is
  shown as failed after 10 minutes.
