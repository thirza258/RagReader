import type { Lesson } from "./types.ts";

export const queryLessons: Lesson[] = [
  {
    id: "rewrite-retrieve-read", moduleId: "rewrite_retrieve_read",
    title: "Rewrite Retrieve Read",
    summary: "Turn conversational or ambiguous wording into a searchable question while preserving intent.",
    minutes: 14,
    objectives: ["Identify vocabulary and reference problems in a question.", "Separate the retrieval query from the answer question.", "Evaluate whether a rewrite preserved entities and constraints."],
    content: `## Why rewrite?

Users ask questions in the language of a conversation. A retriever sees text to match against a corpus. “And how long for Atlas?” may be understandable after a cache discussion but weak as an isolated search. Rewriting produces a self-contained search question, such as “What is the search-cache duration for Atlas?”

The research framework studies a rewriter, retriever, and reader, including learning a rewrite policy from downstream feedback. RAGReader uses a **prompted adaptation**. It does not train a rewrite policy during your run.

## Follow the information

1. Keep the original question as the task to answer.
2. Generate a more explicit search question.
3. Retrieve using the additional query and combine source hits.
4. Give actual source passages to the reader, which answers the original question.

The rewrite must preserve product names, versions, dates, negation, and scope. A shorter query is not automatically better. “Which operations do not require approval?” changes meaning if “not” disappears.

## Worked example

Start with “Why is its cache shorter?” In a conversation where Atlas is clearly the subject, a useful rewrite names Atlas and asks for the rationale behind its 5-minute duration. An unsafe rewrite assumes the cause: “Why does Atlas's newer hardware require a shorter cache?” The handbook does not establish that hardware claim.

The second rewrite can bias retrieval toward an invented explanation. Inspect both the rewritten query and its retrieved passages. Retrieval improvements should mean more relevant source evidence, not simply more shared words.

## In RAGReader

The optional module adds a rewritten query alongside the original question. The module pipeline deduplicates repeated search questions. The baseline already has keyword optimization, so “modules off” does not mean “no query processing.” Compare saved traces to understand which transformations actually differ.

A prompt cannot recover missing conversation facts unless they are supplied. Use a self-contained question for a controlled experiment rather than assuming the module has an unlimited conversation history.

## Cost and failure modes

The module adds generation and retrieval work. It is useful when the original wording hides the relevant vocabulary, but can erase a constraint or invent a premise. Test exact identifiers, negative questions, and already clear questions. A successful rewrite preserves intent and improves evidence coverage without degrading these cases.`,
    exercise: { title: "Audit a rewrite", steps: ["Rewrite 'Does Atlas keep results as long as the normal service?' as a self-contained query.", "Underline the entity, comparison, and quantity in both versions.", "Compare an off/on run with the same method, model, Top-K, and labels."], solution: "'Compare the Atlas search-cache duration with the standard search-cache duration' preserves all three. Inspect whether both source rules reach the final context. An improvement on one ambiguous question should be checked against already explicit questions." },
    quiz: { question: "Which question should the final reader answer?", options: ["Only the generated rewrite, even if its meaning changed", "The original user question", "A new question inferred from the reference answer"], answer: 1, explanation: "The rewrite is a search aid. The original question remains the user task and the reference answer must not guide the search." },
    sources: [{ title: "Ma et al. — Query Rewriting for Retrieval-Augmented LLMs", url: "https://arxiv.org/abs/2305.14283" }],
  },
  {
    id: "step-back-prompting", moduleId: "step_back",
    title: "Step Back Prompting",
    summary: "Retrieve the broader principle behind a specific question, then reconnect it to the evidence.",
    minutes: 13,
    objectives: ["Distinguish abstraction from paraphrasing.", "Combine background evidence with question-specific facts.", "Recognize when a broader query becomes too broad."],
    content: `## Ask for the principle

Some questions need both a local fact and the principle explaining it. Step Back Prompting creates a broader conceptual question before solving the specific one. The research explores abstraction as a way to bring relevant concepts into reasoning. In a retrieval pipeline, that broader question becomes an additional way to find background evidence.

A paraphrase keeps the same level of detail: “What is Atlas's cache duration?” becomes “How long are Atlas results cached?” A step-back question changes the level: “What determines an appropriate cache duration?” These transformations serve different purposes.

## Worked example

The question “Why does Atlas use 5 minutes while the standard is 15?” needs both durations and the reason for the exception. A specific search may find only the Atlas rule. A broader search about “data freshness and cache duration” may find the handbook's explanation that frequently changing catalogs need shorter caching.

The reader should connect the concept to the named service only when the source does. General knowledge that stale caches can be a problem does not establish why a particular team chose a particular duration.

## In RAGReader

The module prompts the selected model for a broader conceptual question, retrieves it, and fuses that evidence with evidence for the original question. It runs in the query stage. The final reader answers the original question using source passages, not the generated abstraction as a factual reference.

When combined with other query modules, duplicate searches are removed, but distinct broad queries still add retrieval and generation work. A broad question can pull irrelevant background into a limited final context, pushing out an exact exception.

## Pick an appropriate scope

“What is caching?” is probably too broad for a question about Atlas's documented exception. “How does catalog freshness affect cache policy?” is closer to the needed relationship. A useful abstraction keeps the conceptual bridge while dropping incidental detail.

Try this module for explanation, causal, and principle-based questions. An exact lookup such as “How many days are logs retained?” may gain little from it. Compare the source coverage for the explanation and check that the final answer still names the right entity and value.

## What to inspect

Look at the broader query, the new source IDs, and the final context. Ask whether the added passage supplies a missing principle, merely repeats an existing fact, or introduces a distractor. Only the first is a clear success for this intervention.`,
    exercise: { title: "Choose an abstraction", steps: ["For the Atlas comparison, write a paraphrase and a step-back question.", "Identify the source passage each query should find.", "Write a two-sentence answer combining the specific rule with the documented rationale."], solution: "A paraphrase asks for the two durations. A step-back asks how freshness requirements shape cache policy. The answer needs the 15-minute standard, the 5-minute Atlas exception, and the source's statement about frequent catalog changes." },
    quiz: { question: "Which query best illustrates stepping back?", options: ["What broader freshness requirement explains the cache policy?", "Exactly how many minutes is the Atlas cache?", "Atlas cache minutes duration"], answer: 0, explanation: "Stepping back changes the abstraction level to seek a relevant principle, rather than merely rephrasing the same lookup." },
    sources: [{ title: "Zheng et al. — Take a Step Back", url: "https://arxiv.org/abs/2310.06117" }],
  },
  {
    id: "hyde", moduleId: "hyde",
    title: "HyDE: hypothetical document embeddings",
    summary: "Use a generated passage as a search probe, while keeping it out of the answer evidence.",
    minutes: 15,
    objectives: ["Explain why a passage can be a better dense-search probe than a short query.", "Keep hypothetical text separate from factual evidence.", "Recognize drift and embedding dependencies."],
    content: `## Search with an answer-shaped passage

HyDE stands for Hypothetical Document Embeddings. A language model generates a plausible passage answering the question. An encoder embeds that passage, and dense retrieval finds real source text nearby. The hypothetical passage acts as a bridge between a short question and the language used in documents.

The research uses a generated document and a contrastive encoder for zero-shot dense retrieval. RAGReader adapts the idea to its configured generation and embedding providers. It does not require relevance labels to create the search probe.

## The critical boundary

~~~text
question → hypothetical passage → embedding → real source hits
                                              ↓
                                  evidence for the reader
~~~

The generated passage may contain invented names, numbers, or explanations. Those details must not become source evidence. HyDE is using the passage's representation to search, not verifying the passage's truth.

## Worked example

Ask “When are request records removed?” A hypothetical passage might say “The service rotates request logs after a retention period.” This can bring the query closer to the handbook's vocabulary. It might also invent “90 days.” The actual handbook states 30 days.

A successful result retrieves the real 30-day passage and answers from it. An answer of 90 days would show a serious boundary failure if that number came only from the hypothetical passage. Even if the generated probe happens to be correct, it is still not independent source evidence.

## In RAGReader

The module generates a hypothetical passage, performs dense search with it, and fuses real source hits with other rankings. Sparse variants create a temporary dense index for this step. Selecting Sparse therefore does not eliminate the configured embedding provider when HyDE is enabled.

With RRF Hybrid, ordinary questions use the hybrid fusion path, while the hypothetical passage keeps its dense retrieval path. Their source hits join the evidence pool. The hypothetical text is not added as a stored chunk or as ground truth.

## When it helps or hurts

HyDE can help underspecified questions whose wording differs from the source. It can hurt when the generated passage assumes the wrong entity or answer family, steering search away from the right evidence. Narrow identifiers and unusual facts are useful stress tests.

Compare source recall, final support, and extra latency. Read the retrieval trace and verify that every final passage has an original source identity. A plausible hypothetical answer is an intermediate artifact, not a successful outcome.`,
    exercise: { title: "Spot hypothetical contamination", steps: ["Write a hypothetical answer saying request logs last 90 days.", "Find the handbook passage establishing the actual retention period.", "Explain which text can support the final answer and which text only guided search."], solution: "Only the handbook's 30-day statement is evidence. The 90-day hypothetical is a search probe and must never justify the final value. Check real source IDs and final context, not the fluency of the probe." },
    quiz: { question: "A HyDE passage invents a 90-day retention period. What should the reader use?", options: ["90 days, because the search model suggested it", "The average of the hypothetical and source values", "The retention period established by retrieved source text"], answer: 2, explanation: "Generated hypotheses are not evidence. The actual source must establish the answer, or the reader should report missing support." },
    sources: [{ title: "Gao et al. — Precise Zero-Shot Dense Retrieval without Relevance Labels", url: "https://arxiv.org/abs/2212.10496" }],
  },
  {
    id: "rag-fusion", moduleId: "rag_fusion",
    title: "RAG Fusion: several views of one question",
    summary: "Search alternative questions and merge their rankings without counting duplicate sources twice.",
    minutes: 15,
    objectives: ["Generate complementary search questions.", "Distinguish query fusion from dense/sparse fusion.", "Inspect query drift and correlated rankings."],
    content: `## One wording rarely covers everything

A complex question can express several information needs. RAG Fusion creates multiple related queries, retrieves for each, and combines the ranked lists using reciprocal rank fusion (RRF). The alternatives should explore useful perspectives while keeping the user's intent.

The original RAG-Fusion work combines multi-query generation with rank fusion. In RAGReader, the module produces up to three distinct alternative questions and searches them alongside the original.

## Worked example

For “Why does Atlas differ from the standard cache?”, useful alternatives include:

1. What is the standard search-cache duration?
2. What is the Atlas search-cache duration?
3. Why does Atlas need more frequent refreshes?

These queries cover a rule, an exception, and a rationale. Three cosmetic paraphrases of the same lookup are less useful. “Which hardware does Atlas use?” drifts away from the documented task.

Suppose the rule appears in one ranking and the exception appears in two. Fusion accumulates rank-based support per source chunk. Repeated chunks occupy one final evidence entry; they are not three independent sources simply because three queries found them.

## Two different fusion boundaries

**RAG Fusion** combines rankings from different questions. **RRF Hybrid** combines dense and BM25 rankings for a single search. Both can be enabled: first merge retrieval methods within each query, then merge results across queries.

These rankings are correlated. Several paraphrases generated by the same model are not independent votes establishing truth. RRF rewards repeated retrieval support, not factual correctness.

## In RAGReader

Query modules feed an ordered search process. Repeated search questions are deduplicated, and fused results retain original chunk IDs. The number of alternative queries is bounded to control work. Adding this module does not add new matrix variants: its searches run inside each selected method/model variant.

Compare the recorded query list with the actual evidence. Ask whether a genuinely missing facet was recovered and whether it survives the final context budget.

## Useful experiments

Try a multi-part comparison and an exact single-fact lookup. The comparison may benefit from decomposition; the lookup may show only extra latency. Watch for drift, diluted precision, and overrepresented passages. Use a fixed label set to measure the tradeoff instead of declaring success from an answer that merely became longer.`,
    exercise: { title: "Design three complementary queries", steps: ["Split the Atlas comparison into rule, exception, and rationale questions.", "Map each query to expected handbook evidence.", "Compare the new query list with an enabled RAG Fusion trace."], solution: "A useful set covers different required facts while preserving Atlas and the comparison. If all queries retrieve only the standard rule, the expansion did not recover the missing facet even if total calls increased." },
    quiz: { question: "What does RAG Fusion combine?", options: ["Rankings from alternative questions", "The language model's weights", "Reference answers from the current test question"], answer: 0, explanation: "It combines retrieval rankings across queries. RRF Hybrid instead combines dense and sparse rankings within a search." },
    sources: [{ title: "Rackauckas — RAG-Fusion: a New Take on RAG", url: "https://arxiv.org/abs/2402.03367" }],
  },
  {
    id: "memorag", moduleId: "memo_rag",
    title: "MemoRAG: document memory and retrieval clues",
    summary: "Use a document-level summary to guide search without treating the summary as a source.",
    minutes: 14,
    objectives: ["Explain global memory as a retrieval aid.", "Identify summary coverage and caching limits.", "Distinguish this adaptation from a trained memory model."],
    content: `## Find clues from the larger picture

A local query may miss terminology introduced elsewhere in a document. A document-level memory can connect topics, entities, and relationships before retrieval. MemoRAG's research architecture uses a memory-oriented model to help discover useful retrieval clues. The goal is to support questions whose information needs are difficult to express as a short direct query.

RAGReader uses a **summary-memory adaptation** with the existing generation model. It does not install or train the paper's specialized memory model.

## Worked example

The handbook's opening sections connect Atlas to catalog freshness, while the cache exception appears later. A summary might remember that Atlas handles frequent catalog updates. For “Why is its policy different?”, that memory can suggest searches for Atlas, refresh frequency, and the cache exception.

The reader must still receive the original passages establishing those claims. A summary can compress away exceptions or introduce an incorrect relationship. Its job is to propose clues that retrieval can verify.

## In RAGReader

The module summarizes document context into memory and uses it to generate up to three retrieval clues. The memory covers the first **24,000 characters** of document context. It is cached for one hour using a key tied to document identity, content, generation model, and temperature.

That boundary matters. A critical late appendix may not be represented in memory even though it remains in the source corpus. A warm-cache run can also be faster than a first run without indicating a better algorithm.

The summary is a temporary aid; it does not replace stored source chunks or change their IDs and reference labels. Search results still refer to the uploaded document.

## Separate two kinds of memory

Document summary memory is different from conversational memory. One summarizes the source; the other tracks earlier turns. Neither is automatically an authoritative answer to the current question. Do not assume an ambiguous pronoun can be resolved just because a summary cache exists.

## How to evaluate it

Choose a question requiring connections across sections, then compare memory-guided clues with the baseline query. Inspect whether the new source passages contain those connections. Also test a question whose answer appears late in a long document.

Record cache reuse when comparing latency. For quality, keep the question, document, labels, and answer model fixed. A better summary alone is insufficient: the final answer must improve with verifiable source support.`,
    exercise: { title: "Audit memory coverage", steps: ["Write a short summary of the handbook's major entities and relationships.", "Use it to generate two search clues for the Atlas rationale.", "Imagine the only relevant exception is beyond character 24,000. Explain the resulting limitation."], solution: "The summary can suggest Atlas and catalog freshness, but original passages must verify the relationship. A late exception may be absent from summary memory. Compare baseline source retrieval as well as memory-guided searches." },
    quiz: { question: "Which description matches MemoRAG in this project?", options: ["A trained model that remembers every uploaded document forever", "A cached document-summary adaptation used to generate retrieval clues", "A replacement for source chunks and reference labels"], answer: 1, explanation: "The app uses a bounded, cached summary with existing models. Original source passages remain the evidence." },
    sources: [{ title: "Qian et al. — MemoRAG", url: "https://arxiv.org/abs/2409.05591" }],
  },
];
