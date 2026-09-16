import type { Lesson } from "./types.ts";

export const retrievalLessons: Lesson[] = [
  {
    id: "rrf-hybrid", moduleId: "rrf_hybrid",
    title: "RRF Hybrid: fuse ranks, not raw scores",
    summary: "Calculate reciprocal rank fusion and understand how this module changes each base method.",
    minutes: 16,
    objectives: ["Calculate an RRF score by hand.", "Distinguish the fusion constant from Top-K.", "Interpret dense, sparse, and hybrid labels when RRF Hybrid is enabled."],
    content: `## A common scale for different rankings

Dense cosine similarity and BM25 scores have different scales. **Reciprocal rank fusion** uses positions in ranked lists instead of adding those raw scores. A source receives a contribution from each ranking in which it appears:

~~~text
RRF(source) = sum over rankings containing source of
              1 / (rrf_k + one_based_rank)
~~~

The fusion constant rrf_k controls how strongly early positions differ. It is not Top-K, the requested number of returned results. A source absent from a ranking gets no contribution from that ranking.

## Worked example

Use rrf_k = 60. Dense returns [A, B, C] and BM25 returns [B, D, A].

~~~text
A = 1/61 + 1/63 = 0.03227
B = 1/62 + 1/61 = 0.03252
C = 1/63        = 0.01587
D = 1/62        = 0.01613
Fused order: B, A, D, C
~~~

B wins narrowly because it appears near the top of both lists. Its score is not a correctness probability. Agreement can promote an irrelevant passage if both methods make the same mistake.

Each source should contribute once per ranking. Counting duplicate occurrences would reward repeated output instead of support across searches. RAGReader identifies sources by chunk ID and deduplicates them during fusion.

## In RAGReader

RRF Hybrid retrieves dense and BM25 candidates for each search and fuses their rankings. It is available with every base method. While enabled, Dense, Sparse, and Hybrid variants all use this dense-plus-keyword fusion behavior. The usual Hybrid reranker is bypassed; changing its setting has no effect on those searches.

With RAG Fusion, this within-query fusion happens before rankings across alternative questions are combined. HyDE retains its dense hypothetical-passage search, whose real source hits join the other rankings.

## Interpret the experiment

Three differently labeled base variants may now share the same retrieval mechanism. Differences may still come from model-generated queries and later stages, so do not attribute a score change solely to the base label.

Use a clear baseline and compare the evidence introduced or removed by rank fusion. The module needs dense embeddings even when Sparse is selected. It can improve complementary candidate coverage, but it removes normal Hybrid rescoring and can amplify correlated errors.`,
    exercise: { title: "Recompute a fusion ranking", steps: ["Using the example, move A from rank 3 to rank 1 in the BM25 list: [A, B, D].", "Recompute A and B with rrf_k = 60.", "Explain whether the winner proves which source is relevant."], solution: "A becomes 2/61 = 0.03279. B becomes 2/62 = 0.03226. A now ranks first. The winner reflects rank agreement; only the question and source content determine relevance." },
    quiz: { question: "What is the contribution of a source missing from one ranking?", options: ["1/60", "A negative penalty", "Zero"], answer: 2, explanation: "A ranking contributes only for sources it contains. Missing sources get no term in the RRF sum." },
  },
  {
    id: "raptor", moduleId: "raptor",
    title: "RAPTOR: retrieve through a summary tree",
    summary: "Build multiple levels of abstraction, then map retrieved summaries back to source evidence.",
    minutes: 17,
    objectives: ["Explain embedding, clustering, and recursive summarization.", "Trace summary nodes back to original passages.", "Identify coverage and compression risks."],
    content: `## Search at more than one level

Flat chunks are good for local facts but can hide a document's larger themes. RAPTOR recursively embeds, clusters, and summarizes passages to build a tree. Leaves represent detailed text; higher nodes summarize groups. Searching across these levels can connect a broad question with several relevant sections.

The research proposes tree-organized retrieval over recursive summaries. RAGReader implements a bounded adaptation for the current document and variant.

## Build a small tree by hand

Imagine four passages: standard cache policy, Atlas's exception, an incident caused by stale results, and the resulting invalidation change. Group the first two as “cache policy” and the second two as “incident response.” Summarize those groups, then summarize their shared theme as “balancing freshness and cache behavior.”

A question about the relationship between policy and the incident may match that broad summary better than any one leaf. A question asking for the exact 5-minute value still needs the original exception passage.

## In RAGReader

The module embeds and clusters up to **32 relevant source chunks** and recursively summarizes up to **three levels** using agglomerative clustering. It creates a temporary tree for that variant. Leaves and summary nodes are searched together, and hits are mapped back to their original source passages.

The reader receives those original passages. Summaries guide retrieval; they do not become new ground-truth chunks. The stored index, source IDs, and existing reference selections stay intact.

This is not an unlimited tree over every uploaded document. On a large source, its starting subset can omit useful material. A tree can connect the leaves it contains; it cannot establish a fact from an omitted leaf.

## Compression has consequences

Summaries may lose a number, merge distinct entities, or erase an exception. Clusters can group superficially similar passages that should be distinguished. Mapping back to source text helps preserve provenance, but the reader still needs to interpret that text correctly.

Tree construction also adds embedding and generation work. Compare a broad synthesis question with a simple lookup. If the latter already retrieves its answer, a tree may add overhead with little benefit.

## Combining with LongRAG

RAPTOR and LongRAG build different temporary indexes. The former connects content through thematic summaries; the latter searches adjacent passage groups. Both can run, with earlier hits prioritized within the shared context budget. Inspect which original sources survive packing rather than assuming all tree and group hits reach the reader.`,
    exercise: { title: "Draw a two-level evidence tree", steps: ["Group the handbook's cache policy, exception, incident, and recovery passages into themes.", "Write one summary per group and a parent summary.", "For a broad incident question, identify the leaves needed to verify every statement in the parent summary."], solution: "The broad summary should point back to policy and incident passages. Exact durations and incident actions need leaf evidence. If the summary introduces a cause absent from every leaf, remove that claim rather than citing the summary." },
    quiz: { question: "What does the RAPTOR reader receive in RAGReader?", options: ["Only generated tree summaries", "Original source passages mapped from tree hits", "New permanent summary chunks used as ground truth"], answer: 1, explanation: "The temporary summary tree guides retrieval; original passages remain the reader's evidence and keep their source identity." },
    sources: [{ title: "Sarthi et al. — RAPTOR", url: "https://arxiv.org/abs/2401.18059" }],
  },
  {
    id: "longrag", moduleId: "long_rag",
    title: "LongRAG: retrieve larger evidence units",
    summary: "Keep neighboring facts together and understand the price of a longer reader context.",
    minutes: 15,
    objectives: ["Explain long retrieval units and passage expansion.", "Distinguish adjacent groups from thematic clusters.", "Measure actual evidence size as well as Top-K."],
    content: `## Give the reader a connected passage

Short chunks can separate a rule, its rationale, and an exception. LongRAG explores larger retrieval units together with a reader able to handle longer context. The approach shifts some work from finding a tiny isolated passage toward reading a larger connected unit.

The research studies long retrieval units, including grouped documents and whole-document units. RAGReader uses a smaller **passage-group adaptation** within the uploaded document.

## Worked example

The standard cache rule appears in one chunk, the rationale in the next, and the Atlas exception in a third. A short-chunk lookup might return only the rule. A group containing the neighboring passages gives the reader the relationship between them.

Now imagine the exception sits in a distant appendix. Grouping adjacent chunks will not automatically connect those distant sections. This is one difference from RAPTOR's thematic summaries, which can connect nonadjacent content within its selected leaves.

## In RAGReader

LongRAG creates temporary groups of **four adjacent chunks**, searches the groups using dense embeddings, and expands selected groups into original source passages for the reader. On large documents, it searches at most **64 groups**, prioritizing groups around current hits and sampling the rest across the document.

The original stored chunks and their reference IDs remain unchanged. The longer context cap is **48,000 characters**. A selected group can expand into several source chunks, so final evidence can exceed the configured Top-K.

This is neither a permanent re-chunking operation nor a guarantee that the whole document reaches the model. Group coverage, selected hits, and packing limits still matter.

## More text creates a tradeoff

Expansion may recover an omitted rationale, but also introduces irrelevant neighbors. The reader spends more input tokens and can be distracted by a conflicting rule for another service. A higher recall with lower precision can be a reasonable tradeoff if the final answer becomes more complete, but record both outcomes.

Compare actual final source count, context size, answer support, latency, and provider usage. Holding Top-K constant does not hold context size constant when expansion is enabled.

## Shared budgets

LongRAG, Self Route, and FLARE can all add source text. They share the longer budget rather than each receiving a separate 48,000-character allowance. FLARE can prioritize new evidence and displace earlier passages when the context is full. Inspect the final packed evidence in combined runs.`,
    exercise: { title: "Predict expansion effects", steps: ["Sketch eight adjacent source chunks and mark two neighboring relevant chunks.", "Group them into units of four and retrieve the matching group.", "Count relevant and irrelevant passages after expansion and explain the recall/precision tradeoff."], solution: "A selected group can supply both relevant chunks plus two irrelevant neighbors. Coverage improves if the short baseline missed one relevant chunk, but the irrelevant fraction grows. Evaluate final-answer support and actual context size." },
    quiz: { question: "Why can LongRAG return more source chunks than Top-K?", options: ["Each selected group expands into multiple original passages", "It silently changes stored ground truth", "Top-K counts generated answer sentences"], answer: 0, explanation: "Top-K group hits can expand into several source chunks. Inspect the final evidence set when interpreting retrieval metrics." },
    sources: [{ title: "Jiang et al. — LongRAG", url: "https://arxiv.org/abs/2406.15319" }],
  },
];
