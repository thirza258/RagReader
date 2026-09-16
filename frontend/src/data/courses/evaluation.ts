import type { Lesson } from "./types.ts";

export const evaluationLessons: Lesson[] = [
  {
    id: "contextual-learning", moduleId: "contextual_learning",
    title: "Contextual Learning: examples without answer leakage",
    summary: "Teach the reader an answer pattern with demonstrations while keeping evidence and evaluation independent.",
    minutes: 14,
    objectives: ["Distinguish in-context examples from training.", "Separate demonstrations from evidence.", "Prevent target-answer leakage."],
    content: `## Learn a pattern inside the prompt

In-context learning supplies examples in the model's input so it can follow a format or task pattern. The model's weights do not change. For document QA, a demonstration might show how to compare two policies, name supporting passages, and state what the source leaves unknown.

Examples and evidence have different roles. An example illustrates how to answer; the current source passages establish what the answer can claim.

## Worked example

A demonstration asks “How long are request logs kept?” and answers “30 days, according to the retention policy.” The target asks about Atlas's cache. The demonstration can encourage a concise, source-based answer, but its 30-day value must not migrate into the cache response.

A reference Q&A containing the exact Atlas comparison would be a poor evaluation example: it hands the model the answer being scored. A higher correctness score would then reflect leakage rather than an improved ability to retrieve and read.

## In RAGReader

Contextual Learning is applied after final evidence selection. It uses up to **three saved reference Q&A pairs** from other questions on the same document, excluding the current conversation and matching question text.

If no saved examples exist, it can generate up to **two different examples** from retrieved evidence. Those examples remain separate from answer evidence. With no evidence, no demonstrations are added. A direct Adaptive route skips the module.

These safeguards reduce obvious leakage but do not replace careful experiment design. A differently worded example could still reveal the same answer. Review demonstration overlap when evaluating your own data.

## What this module can change

Demonstrations can improve answer structure, precision of wording, or handling of uncertainty. They do not fix a missing source fact by themselves. Generated examples can also contain mistakes; a reader might imitate those mistakes or copy a number from the wrong task.

Each example consumes prompt space and may add generation work when examples must be created. Keep examples concise and relevant to the desired behavior.

## Evaluate honestly

Hold the current question and reference answer out of demonstrations. Record example provenance and compare answer format, support, and completeness. Include an unanswerable question to check whether the reader can still abstain.

If the answer becomes better organized but its factual support is unchanged, report that narrower improvement. Do not describe in-context examples as fine-tuning or as learning a permanent memory of the document.`,
    exercise: { title: "Choose a safe demonstration", steps: ["Use the Atlas comparison as the target question.", "Choose between a log-retention Q&A and a paraphrased Atlas-comparison Q&A as the demonstration.", "Explain what the example should teach without revealing the target answer."], solution: "The retention Q&A can demonstrate concise citation and uncertainty handling. The paraphrased Atlas example may reveal the target answer even if exact text differs. Review semantic overlap as well as the app's exclusion checks." },
    quiz: { question: "Why exclude the current reference answer from demonstrations?", options: ["To prevent the answer being scored from leaking into the prompt", "Because demonstrations change model weights", "Because reference answers are never useful for evaluation"], answer: 0, explanation: "Evaluation should measure performance on a held-out target. Supplying its reference answer would confound the result." },
  },
  {
    id: "ground-truth",
    title: "Ground truth, candidate pooling, and labels",
    summary: "Create independent references and understand what pooled agreement actually measures.",
    minutes: 16,
    objectives: ["Distinguish reference chunks from a reference answer.", "Explain candidate pooling and its bias.", "Label relevant evidence consistently."],
    content: `## Two different references

**Reference chunks** identify source units relevant to a question. Retrieval metrics compare retrieved IDs against this set. A **reference answer** expresses the expected response and supports answer-level correctness evaluation. Selecting the right chunks does not automatically write a complete expected answer.

Create both by reading the source before inspecting the evaluated model's answer. Otherwise an attractive answer can influence which evidence you label, making the comparison circular.

## Worked labeling example

For the Atlas comparison, label the standard duration, the Atlas duration, and its documented rationale. If a chunk contains two of those facts, one source ID can cover both. A log-retention passage is related to data lifetimes but does not answer the cache comparison.

Write a reference answer containing all required claims and no unsupported additions. Agree in advance whether a passage must directly establish a fact or whether useful background also counts as relevant. Document ambiguous cases.

## Candidate pooling in RAGReader

Candidate pooling retrieves with Dense, Sparse, and Hybrid, then fuses ranked source IDs with RRF. It uses one optimized query across the retrieval methods. The resulting pool can be inspected and selected as the reference set.

The implementation can use top-ranked pooled candidates as references without human adjudication. That measures **agreement with a retriever consensus**, not independently verified relevance. The contributing systems can share blind spots, and Hybrid is structurally closer to the fusion process.

Human evaluation often uses a pooled shortlist as a starting point for relevance judgments. Automatically accepting its top entries skips that judgment step. Keep the distinction clear when reporting scores.

## Labels are versioned data

Chunk boundaries and IDs belong to a specific ingestion. Re-chunking invalidates old selections. Document updates can change the expected answer, and a changed question can change which chunks are relevant even when the source is unchanged.

Record document version, question, label policy, selection mode, source IDs, and reference answer. The same labels should be used across the variants you want to compare.

## Missing and incomplete references

An incomplete relevant set can penalize a retriever for finding genuinely useful unlabeled evidence. Review apparent false positives before concluding the retriever is wrong. A question with no answer in the document needs a separate abstention check; an empty reference set does not by itself describe every aspect of good behavior.

Use pooling for exploration and human labels for a more independent quality estimate when practical. Neither removes the need to inspect answer support.`,
    exercise: { title: "Write an independent reference", steps: ["Before running the model, label all source passages needed for the Atlas comparison.", "Write an expected answer and list its individual claims.", "Compare a pooled candidate set with your labels and explain every disagreement."], solution: "The expected answer includes 15 minutes, 5 minutes, and catalog freshness as the reason. Pooling may miss a fact or include distractors. Record those disagreements instead of replacing independent labels merely to improve a score." },
    quiz: { question: "What do scores against automatically accepted pooled chunks primarily measure?", options: ["A guarantee of human-verified truth", "Agreement with the retriever consensus", "Whether the model has memorized the course"], answer: 1, explanation: "Automatic pooling is a system-derived reference. It may be useful, but it is not the same as independently adjudicated relevance." },
  },
  {
    id: "retrieval-metrics",
    title: "Precision, recall, and F1 for retrieval",
    summary: "Calculate source-set overlap and interpret the tradeoff between coverage and noise.",
    minutes: 16,
    objectives: ["Calculate Precision@K, Recall@K, and F1@K.", "Interpret changing K and expanded source sets.", "Recognize what set-based metrics cannot tell you."],
    content: `## Count source identities

Let R be the unique source IDs retrieved and G the relevant reference IDs. True positives are the IDs in both sets. Precision measures how much returned evidence is relevant; recall measures how much of the reference set was recovered.

~~~text
TP = size(intersection(R, G))
Precision = TP / size(R)
Recall = TP / size(G)
F1 = 2 × Precision × Recall / (Precision + Recall)
~~~

F1 is zero when both precision and recall are zero. RAGReader's implementation returns zero for empty retrieval/reference edge cases; that arithmetic convention is not a complete evaluation of an unanswerable question.

## Worked example

Retrieved R = {A, B, C, D, E}. Reference G = {B, D, F, G}. Two IDs overlap.

~~~text
Precision = 2/5 = 40%
Recall    = 2/4 = 50%
F1        = 2 × 0.4 × 0.5 / 0.9 = 44.4%
~~~

Now add relevant F as a sixth retrieved source. Precision becomes 3/6 = 50%; recall becomes 3/4 = 75%; F1 becomes 60%. Adding another irrelevant passage would lower precision while leaving recall unchanged.

## In RAGReader

The app compares **sets of chunk IDs**. Precision divides by the number of distinct returned IDs, not blindly by the configured K if fewer or more chunks actually reach the result. This matters with LongRAG and other expansion stages, where final source count can exceed Top-K.

Rank order is not rewarded by these three metrics. The same relevant IDs at positions 1 and 2 or at positions 4 and 5 produce identical set-based scores. Rank-sensitive measures such as MRR and nDCG address different questions and are not current retrieval outputs here.

## Interpret the tradeoff

Increasing K can recover missing evidence but also add distractors. With nested candidate sets, recall cannot decrease merely from adding a source, but a complete pipeline can change ranking, filtering, and context packing between runs. Do not assume changing K produces nested final contexts.

High precision with low recall can mean a narrow answer missing an exception. High recall with low precision can mean a reader overloaded with irrelevant passages. An F1 average hides those distinct failures.

## Limits

Set overlap does not measure whether the reader used a passage, whether the source itself is correct, or whether a clipped passage still contains the needed sentence. Inspect final text and answer metrics alongside IDs. A perfect retrieval score can coexist with an incorrect answer.`,
    exercise: { title: "Calculate metrics without a model", steps: ["Use retrieved IDs {A, B, C} and relevant IDs {B, C, D, E}.", "Calculate precision, recall, and F1.", "Add irrelevant F and recalculate. Explain which metric stays constant."], solution: "Initially precision is 2/3 = 66.7%, recall is 2/4 = 50%, and F1 is 4/7 = 57.1%. After adding F, precision and recall are both 50%, and F1 is 50%. Recall stays constant because no new relevant ID was found." },
    quiz: { question: "Five distinct chunks are returned; two of four relevant chunks are found. What are precision and recall?", options: ["50% precision, 40% recall", "40% precision, 50% recall", "40% precision, 40% recall"], answer: 1, explanation: "Precision uses returned count: 2/5. Recall uses relevant count: 2/4. These are different denominators." },
  },
  {
    id: "answer-evaluation",
    title: "Faithfulness, relevance, and factual correctness",
    summary: "Read Ragas answer metrics separately, including missing inputs and judge failures.",
    minutes: 16,
    objectives: ["Explain the inputs and meaning of each answer metric.", "Distinguish source support from reference correctness.", "Treat unavailable scores separately from zero scores."],
    content: `## Three questions about an answer

**Faithfulness** asks whether claims in the answer are supported by the retrieved source passages. **Response relevance** asks whether the response addresses the question, using similarity between the original question and questions generated from the answer. **Factual correctness** in F1 mode compares the answer's claims with a reference answer, balancing correctness and completeness.

These are the three Ragas answer metrics used by new deep-analysis runs. They answer different questions and should not be collapsed into a single unexplained quality number.

## Worked example

The question asks for both cache durations and the reason Atlas differs. An answer saying only “The standard cache lasts 15 minutes” can be faithful to its source while missing most of the requested comparison.

An answer giving the correct 5-minute Atlas value from model memory might match the reference but lack support if the final context contains only the standard rule. Conversely, a faithful answer can repeat an outdated document value and disagree with a newer reference.

These are diagnostic patterns, not promised numeric scores. The actual judge may decompose claims differently or make an error.

## In RAGReader

Ragas uses the selected OpenRouter evaluation judge and remote embeddings. Faithfulness needs source context. Factual correctness needs a reference answer. Response relevance uses the original question and generated answer, plus embedding calls for the generated questions.

Missing inputs or failed evaluations are shown as **unavailable with a reason**. They are not fabricated zero scores. A failure in one metric does not discard successful metrics or the generated answer. Results retain evaluator details and module traces.

Historical runs may contain older metrics; do not mix them into a new Ragas comparison as though the measurement method were unchanged.

## Judge limitations

An LLM judge is an instrument with its own failure modes: inconsistent claim decomposition, sensitivity to phrasing, unsupported judgments, malformed output, and timeouts. Hold the judge configuration steady when comparing answer methods and manually audit disagreements.

Changing the judge can change scores without changing any answer. Report judge identity, reference availability, successful evaluation count, and question sample size.

## Read metrics together

Poor retrieval recall plus poor correctness suggests missing evidence. Good retrieval with poor faithfulness suggests reader or prompt problems. High faithfulness with low correctness may indicate incomplete answers or mismatched references. These are hypotheses to test against the actual source text.

Provider availability and answer quality are separate. A timeout is an operational failure, not evidence that an answer deserves 0% faithfulness.`,
    exercise: { title: "Diagnose a result card", steps: ["Imagine correct retrieved chunks but an answer omitting Atlas's exception.", "Explain which metrics can reveal the omission and which may remain high.", "Remove the reference answer and identify the metric that becomes unavailable."], solution: "Faithfulness can remain high for the supported partial answer; relevance and factual correctness may reveal missing requested content. Without a reference answer, factual correctness is unavailable. Never replace that missing value with zero." },
    quiz: { question: "Factual correctness is unavailable because no reference answer was supplied. How should you report it?", options: ["As 0% correctness", "As 100% because no contradiction was found", "As unavailable, with the missing-reference reason"], answer: 2, explanation: "A missing measurement is different from a measured zero. Preserve that distinction in comparisons and averages." },
    sources: [
      { title: "Ragas — Faithfulness", url: "https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/" },
      { title: "Ragas — Response relevance", url: "https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/" },
      { title: "Ragas — Factual correctness", url: "https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/" },
    ],
  },
];
