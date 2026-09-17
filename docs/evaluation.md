# Ragas evaluation and the analysis flow

The analysis page shows a five-stage flow: **Question → Search → Refine
evidence → Write answer → Evaluate**. Select a method/model result and click a
stage to see its explanation and recorded module outcomes. Result cards have a
**View analysis flow** shortcut. The sidebar configures the next run; it does
not change the diagram for an existing result.

During analysis, the diagram follows the active method/model and highlights its
current stage. Module activity, follow-up searches, route choices, and each Ragas
metric update as they execute. Select any stage or another variant to inspect
it; **Follow live progress** returns to the active work. Future stages remain
planned. Direct routes show skipped retrieval and module failures show fallbacks.
Result counts increase only after the backend saves a result.
On small screens, **Analysis settings** opens the configuration panel; starting
a run returns to the full-width flow, with **Stop analysis** available above it.

Stopping or losing the connection pauses live indicators and preserves the last
observed steps. An in-flight variant may still finish and save, but that socket
will not start additional variants after disconnecting. Reload to check saved
results. Reconnection can retry unfinished work; events from an earlier attempt
never fill in a new attempt's stages. Live updates are temporary; completed
results retain their full module trace and evaluation details for replay and
REST reloads. Results without recorded Ragas evaluation show unavailable answer
metrics with guidance to run deep analysis again.

The existing analysis WebSocket sends `STAGE_PROGRESS` frames before each result.
Each carries `batch_id`, `method`, `aiModel`, `attempt_id`, an increasing
`sequence`, and an `event` with `kind`, `id`, `status`, `detail`, and its active
`stage`. Event kinds are `stage`, `module`, `metric`, `route`, and `activity`;
metric events may include a `score`, and search activity may include `queries`.
These frames are distinct from result frames and batch completion percentages.
Progress listeners are scoped to each run using context variables, including
worker threads and concurrent Ragas calls; shared engines hold no listeners.

## Answer metrics

| Metric | Inputs | Meaning |
| --- | --- | --- |
| Ragas Faithfulness | Original question, generated answer, final source passages | Fraction of answer claims supported by those passages. |
| Ragas Response relevance (`answer_relevancy`) | Original question, generated answer | Similarity of questions generated from the answer to the original question, using remote embeddings. |
| Ragas Factual correctness (`factual_correctness`, F1 mode) | Generated answer, reference answer | Balance of correct and complete claims compared with the reference. |

Retrieval Precision@K, Recall@K, and F1@K continue to compare retrieved chunk
IDs with the configured reference chunk set. Their calculation needs no model.
Result labels substitute the saved run's Top-K value, such as Precision@8,
Recall@8, and F1@8. Each REST/WebSocket result carries `top_k` from its batch
configuration, so editing the next run's settings does not relabel saved results.

Only answer scores with recorded Ragas provenance are exposed. Older answer
metrics are omitted rather than relabeled as Ragas scores. The three supported
answer metrics remain unavailable until the question is evaluated with Ragas.

Ragas scores are displayed as percentages. Missing inputs skip only affected
metrics: no reference answer skips factual correctness; no retrieved evidence
skips faithfulness. Authentication, timeout, malformed output, and non-finite
scores produce JSON `null` with an explanation, never a fabricated zero.
Successful metrics and the generated answer survive another metric's failure.

## Provider configuration

Use the existing `OPENROUTER_API_KEY`. Ragas creates an `openai.AsyncOpenAI`
client with `base_url="https://openrouter.ai/api/v1"` for both generation and
embeddings. No separate OpenAI account key is needed. The analysis sidebar's
**Evaluation judge** selects the OpenRouter model; it must support JSON output.
Response relevance uses the app's configured `RAG_EMBEDDING_MODEL` (default
`openai/text-embedding-3-small`), including for Sparse runs.

Each metric has a 120-second limit. HTTP requests have a 45-second timeout and
one transport retry; structured responses allow two attempts. Ragas may make
multiple judge/embedding calls per metric, so evaluation contributes to run
latency and OpenRouter usage. Clients close after each evaluation. Ragas usage
telemetry is disabled by default.

Scores are stored under `evaluation.response_evaluation`; provenance and
per-metric statuses are in `evaluation.response_evaluation_details`. Both survive
WebSocket delivery, database persistence, replay, and REST reloads.

## Dependencies and verification

Install `backend/requirements.txt` or rebuild the backend image. Ragas 0.4.3's
base package uses remote model clients; do not install its optional `[all]`
extras. OpenAI 2.54.0 and Instructor 1.17.0 share a compatible `jiter` dependency.
`langchain-community` stays at 0.3.31 because Ragas imports a module removed in
newer versions. The rest of the app also uses the pinned OpenAI SDK.

The dependency test rejects local neural and overlap evaluator packages.
Answer evaluation runs through Ragas with remote clients. Reranking stays in
the separate Ollama service.

Backend tests exercise real Ragas, Instructor, and OpenAI client code using an
HTTP mock for OpenRouter, covering scoring, routing, incomplete inputs, and
partial failures. A gated WebSocket test proves live events arrive before a
blocked pipeline returns its answer. Tests also cover all three baseline flows,
scope isolation, direct-route skips, module fallbacks, FLARE follow-up searches,
event ordering, retries, interruption, and unavailable scores. These tests do
not measure live-provider answer quality.

Sources: [Ragas LLM clients](https://docs.ragas.io/en/stable/references/llms/),
[Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/),
[Response relevance](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/),
[Factual correctness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/),
[OpenRouter with the OpenAI SDK](https://openrouter.ai/docs/guides/community/openai-sdk).
