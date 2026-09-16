# Optional RAG modules

Complete the first deep analysis for a conversation, choose modules in the
**RAG modules** section, and click **Run deep analysis** again. Every module is
off by default. Switch individual modules off, or use **Turn all modules off**,
to return to the baseline on the next run.

Selections apply together to every selected retrieval method × model. They do
not add matrix variants. Each batch stores its configuration, and results show
the stages that completed, were skipped by routing, or fell back after an
error. Reloading restores the latest batch and its module selection.

## Implementations

These stages run with the existing OpenRouter models and uploaded document.
Several research architectures require specialized training or external
services; their adaptations here are described below.

| Module | Behavior in RagReader |
| --- | --- |
| RRF Hybrid | Retrieve dense and BM25 candidates and score each source chunk with `sum(1 / (rrf_k + rank))`. Bypass the normal hybrid reranker. Available with every base method. |
| [HyDE](https://arxiv.org/abs/2212.10496) | Generate a hypothetical passage, use its embedding for dense search, and fuse its source hits with the other rankings. Hypothetical text is never answer evidence. Sparse variants create a temporary dense index for this step. |
| [RAG Fusion](https://arxiv.org/abs/2402.03367) | Generate up to three distinct alternative questions. Retrieve each plus the original question and combine rankings with RRF. |
| [Step Back Prompting](https://arxiv.org/abs/2310.06117) | Generate a broader conceptual question, retrieve background evidence, and fuse it with the original question's evidence. |
| [MemoRAG](https://arxiv.org/abs/2409.05591) | Summarize document context into memory, then use it to produce retrieval clues. This is a summary-memory adaptation, without the paper's trained memory model. Cache the summary for one hour, keyed by document ID, content, model, and temperature. |
| [Self Route](https://arxiv.org/abs/2407.16833) | Ask whether retrieved evidence is sufficient. If it is not, send longer document context to the reader, subject to the context limit. |
| [Rewrite Retrieve Read](https://arxiv.org/abs/2305.14283) | Add a self-contained rewritten search question, then answer the original question. Uses prompting rather than a trained rewrite policy. The unmodified baseline retains its existing keyword optimization. |
| [RAPTOR](https://arxiv.org/abs/2401.18059) | Embed, cluster, and recursively summarize up to 32 relevant source chunks into a temporary tree. Search leaves and summary nodes together, then map hits to source passages. Uses agglomerative clustering; summaries guide retrieval and the reader receives original passages. |
| Contextual Learning | Include up to three saved reference Q&A pairs from other questions on the same document as demonstrations. Exclude the current conversation and matching question text. If no examples exist, generate up to two different examples from retrieved evidence. Examples are separate from answer evidence. |
| [LongRAG](https://arxiv.org/abs/2406.15319) | Search temporary groups of four adjacent chunks and expand matching groups for the reader. This is a passage-group adaptation; large uploads search up to 64 groups, prioritizing current hits and sampling the rest across the document. |
| [FLARE](https://arxiv.org/abs/2305.06983) | Predict upcoming sentences, retrieve for unsupported claims, and rewrite them against source evidence. Uses model-reported uncertainty instead of token probabilities, with at most three predictions. The final reader answers from the resulting source context. |
| [CRAG](https://arxiv.org/abs/2401.15884) | Grade relevance, discard rejected chunks, and make up to two corrective document searches when evidence is weak. Regrade the new evidence. This document-only adaptation does not perform external web search. |
| [Adaptive RAG](https://arxiv.org/abs/2403.14403) | Use a prompted complexity classifier to choose direct, single-pass, or multi-step retrieval. Direct is restricted by the prompt to requests requiring no document facts. Multi-step performs two follow-up retrievals informed by earlier evidence. No trained routing classifier is required. |

## Composition and limits

**All 13 modules can be enabled together in this implementation.** They form
an ordered pipeline. There are no mutually exclusive module pairs, but a
routing decision can skip work and context limits can change which passages
reach the reader. Enabling everything does not guarantee a better answer.

The sidebar's **Module compatibility** panel shows the selected execution
order and updates its interaction notes whenever a module or retrieval method
changes. Open **Combination guide** with no modules selected to read all notes.

| Combination | Behavior |
| --- | --- |
| Adaptive RAG + any others | A direct-answer route skips the others. Single-pass and multi-step routes continue through the selected stages. |
| RAG Fusion + RRF Hybrid | Dense and keyword results are fused for each question, then the different questions' rankings are fused. |
| HyDE + RRF Hybrid | The hypothetical passage retains dense retrieval; its source hits join the hybrid query results. |
| RRF Hybrid + any base method | Dense, Sparse, and Hybrid variants all use dense + BM25 RRF while enabled. The usual Hybrid reranker setting has no effect. |
| RAPTOR + LongRAG | Both temporary indexes run. Earlier hits are retained ahead of the additional grouped passages within the context limit. |
| CRAG + Self Route | Expanded context is graded too. Rejected chunks cannot return through expansion or a later stage's fallback. |
| CRAG + FLARE | Newly retrieved evidence is graded, and rejected chunks remain excluded from the final context. |
| LongRAG + Self Route + FLARE | They share the longer context budget. FLARE prioritizes new hits, which can replace earlier passages if the budget is full. |
| Contextual Learning + retrieval/refinement | Demonstrations are added after the final evidence is chosen. No evidence means no demonstrations; a direct Adaptive route skips them too. |
| Several query modules | Their searches are combined and duplicate questions are removed. Additional LLM and retrieval calls still increase work. |
| Sparse + HyDE/RRF Hybrid/RAPTOR/LongRAG | These stages also require the configured embedding provider. Selecting Sparse does not remove that dependency. |

Routing runs first. Query transformations add searches; RRF Hybrid controls
how each search combines dense and sparse hits. RAPTOR and LongRAG augment
evidence, followed by CRAG and Self Route. FLARE can retrieve more evidence;
when CRAG is also enabled, its additional hits are graded. Contextual Learning
adds demonstrations to the final reader prompt. A direct Adaptive RAG decision
skips the other selected stages and records that decision.

Ordinary module runs pack up to 24,000 characters of source context. LongRAG
and Self Route allow up to 48,000. These are character limits, not model token
limits; models with smaller context windows may require smaller deployment
limits. The result contains exactly the source text passed to the reader,
including any clipped passage. Long-context runs can exceed the configured
Top-K number of source chunks because matching groups expand into passages.

MemoRAG memory covers the first 24,000 characters. RAPTOR uses at most three
tree levels. Derived indexes remain in memory for the current variant and do
not replace the stored index or change chunk IDs or ground truth. Additional
generation and embedding calls increase latency and provider usage. They do
not guarantee higher evaluation scores.

## API and verification

`GET /api/v1/analysis-config/` returns the module catalogue.
`POST /api/v1/start-analysis/` accepts `config.modules` as a list of IDs:

```json
{"conversation_id": "1", "config": {"modules": ["hyde", "rag_fusion", "contextual_learning"]}}
```

Unknown IDs are dropped. Missing, malformed, or empty selections disable all
modules. A nonempty selection before a completed analysis for the same
conversation returns HTTP 400 without creating a batch. Failed or partial
variants do not unlock modules.

Batch status reports `config` and `modules_available`. Both WebSocket results
and REST results carry `evaluation.module_trace`, including enabled IDs,
route, step statuses, and retrieval queries. The queued analysis task reads
the stored batch configuration too.

`router.tests_modules` checks retrieval behavior, work limits, example
isolation, context provenance, configuration caching, and rerun eligibility.
`router.tests_module_combinations` runs all 13 modules individually and all 78
pairs over Dense, Sparse, and Hybrid retrieval, plus all modules together on
single-pass, multi-step, and direct routes: 282 execution cases. These use real
similarity search, BM25, reranking, fusion, clustering, and stage composition
with deterministic provider responses. They verify execution and evidence
handling; live provider availability and answer quality are separate concerns.

Frontend compatibility tests cover pair matching, removing stale notes,
Sparse-specific embedding requirements, duplicate selections, and all-enabled
selections (`cd frontend && npm run test:modules`).

The complete backend suite runs without network access:

```sh
cd backend
DEVELOPMENT_MODE=True RAG_DISABLE_ENGINE_INIT=1 python manage.py test --noinput
```
