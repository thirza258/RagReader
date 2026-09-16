import type { Lesson } from "./types.ts";

export const routingLessons: Lesson[] = [
  {
    id: "adaptive-rag", moduleId: "adaptive_rag",
    title: "Adaptive RAG: choose the amount of retrieval",
    summary: "Route simple and complex questions differently, while inspecting skipped work.",
    minutes: 15,
    objectives: ["Distinguish direct, single-pass, and multi-step routes.", "Recognize when a document fact requires retrieval.", "Evaluate routing decisions as part of the pipeline."],
    content: `## Match work to the question

Not every request requires the same evidence-gathering process. A greeting can be answered directly. A log-retention lookup needs a source passage. A question connecting an incident to a later policy change may require an initial search followed by more focused retrieval.

Adaptive-RAG research learns to select different retrieval strategies based on question complexity. RAGReader uses a **prompted complexity classifier**, rather than a trained routing classifier.

## Three routes

The **direct** route skips retrieval. The **single-pass** route searches once through the configured stages. The **multi-step** route performs follow-up searches informed by earlier evidence.

Routing is itself a fallible prediction. A classifier can mistake a short factual question for a request requiring no source knowledge. “How long are logs kept?” is short but still document-dependent.

## Worked example

“Say hello” is a reasonable direct request. “How long does Atlas cache results?” needs the handbook. “Which change addressed the stale-results incident, and how does it relate to the cache policy?” may need multiple connected passages.

For the third question, the first pass might identify the incident and the next search its remediation. The intermediate evidence should determine the follow-up, rather than inventing a cause and looking only for confirmation.

## In RAGReader

Adaptive routing runs first. The prompt restricts direct answers to requests needing no document facts. A direct decision skips other selected modules and records that choice. Single-pass and multi-step routes continue through the selected stages; multi-step adds **two follow-up retrievals**.

All selected modules can be configured together, but a selected module is not proof it executed. Read the route and skipped stage statuses in the trace. A direct route has no retrieved evidence for a faithfulness calculation.

## Evaluate the router

Build a small labeled set containing nonfactual requests, simple document lookups, multi-part questions, and unanswerable questions. Inspect route choice, answer support, total work, and failure rate.

An unanswerable document question does not automatically justify a direct answer from model memory. The required behavior may be to search, recognize missing evidence, and abstain. A faster direct response that invents a fact is a routing failure, even if it reduces latency.

Only keep adaptive routing if the quality and work tradeoff fits the intended question distribution. A complex route for every greeting wastes work; a direct route for every short question loses grounding.`,
    exercise: { title: "Create a routing rubric", steps: ["Label 'Hello', 'How long are logs retained?', and 'How did the incident change cache invalidation?' with intended routes.", "Add 'Who designed Atlas?' as an unanswerable source question.", "Compare intended behavior with saved routing traces."], solution: "Hello can be direct; retention needs retrieval; the incident question may need multiple searches. The designer question should not receive an invented answer from memory. Inspect evidence and abstention even when the route label seems reasonable." },
    quiz: { question: "All modules are selected, but Adaptive RAG chooses direct. What happens?", options: ["All modules execute before the direct answer", "Later modules are skipped and the route is recorded", "The reference answer becomes the context"], answer: 1, explanation: "Direct routing short-circuits later stages. Selection and actual execution are separate facts." },
    sources: [{ title: "Jeong et al. — Adaptive-RAG", url: "https://arxiv.org/abs/2403.14403" }],
  },
  {
    id: "crag", moduleId: "crag",
    title: "CRAG: corrective retrieval",
    summary: "Grade source relevance, reject weak evidence, and search again within the document.",
    minutes: 16,
    objectives: ["Distinguish relevance grading from factual verification.", "Trace corrective searches and rejected chunks.", "Understand document-only correction limits."],
    content: `## Retrieval needs a quality check

A retriever always has a highest-ranked passage even when none answers the question. Corrective RAG introduces an assessment of retrieved evidence and uses that assessment to improve the context. The research includes corrective actions and external search; RAGReader implements a **document-only adaptation**.

The grader asks whether a passage is relevant to the question. This is not proof that the passage is accurate in the real world. A relevant but outdated rule can still mislead the final reader.

## Worked example

Ask about request-log retention. The first pass returns a 15-minute cache rule and a login procedure. They are related to the service but do not establish how long logs are kept. A correction searches for “request logs retention duration” and finds the 30-day rule.

The grader should keep the actual retention passage and reject the distractors. If it rejects the correct passage because the wording is unfamiliar, recall may fall. Adding a grader trades some retrieval noise for the grader's own errors and latency.

## In RAGReader

CRAG grades relevance, removes rejected chunks, and makes up to **two corrective document searches** when evidence is weak. It regrades newly retrieved evidence. It does not search the web or a second collection.

Rejected source IDs stay excluded throughout later expansion and fallback paths. With Self Route, expanded context is graded too. With FLARE, new hits pass through CRAG before reaching the reader. A later stage failure must not quietly restore a previously rejected passage.

## Absence and abstention

If the handbook never names Atlas's designer, another search in the same handbook cannot establish that name. A useful correction can conclude that evidence remains insufficient. Repeated retrieval is a bounded attempt to improve coverage, not a guarantee that an answer exists.

Distinguish “no relevant evidence” from “the grading service failed.” The trace records fallbacks when a stage is unavailable. A fallback answer should not be interpreted as a successfully corrected run.

## What to measure

Compare the accepted and rejected source IDs, new query text, final support, and latency. Inspect false positives and false negatives in grading. Try a lexical distractor, a paraphrased relevant passage, and an unanswerable question.

When comparing modules, keep reference labels fixed. If CRAG looks better only because the label set was changed after reading its output, the experiment does not isolate correction quality.`,
    exercise: { title: "Grade three candidates", steps: ["For the retention question, grade the standard cache rule, log-retention rule, and access-approval rule.", "Write one corrective search after rejecting the distractors.", "Explain what should happen if Self Route later rediscovers a rejected source."], solution: "The 30-day log rule is relevant; cache duration and approval are distractors. Search for the explicit retention topic. A rejected source should stay excluded when later context is expanded; CRAG must grade new evidence too." },
    quiz: { question: "Where does this project's CRAG search for corrective evidence?", options: ["The open web by default", "The current uploaded document", "The course quiz answers"], answer: 1, explanation: "RAGReader implements document-only corrective retrieval. It cannot supply missing external facts." },
    sources: [{ title: "Yan et al. — Corrective Retrieval Augmented Generation", url: "https://arxiv.org/abs/2401.15884" }],
  },
  {
    id: "self-route", moduleId: "self_route",
    title: "Self Route: retrieval or longer context",
    summary: "Check whether current evidence is enough before expanding the reader's view.",
    minutes: 14,
    objectives: ["Separate question-complexity routing from evidence-sufficiency routing.", "Explain bounded long-context expansion.", "Interpret interactions with CRAG and LongRAG."],
    content: `## Decide after seeing evidence

Adaptive RAG asks how much retrieval a question appears to need. Self Route asks whether the **evidence already retrieved is sufficient**. The research studies routing between RAG and long-context reading using model self-assessment. RAGReader adapts this by broadening source context when the evidence appears insufficient.

The distinction is timing and input: a complexity guess happens before retrieval, while a sufficiency judgment can examine actual passages.

## Worked example

For “How does Atlas differ from the standard cache?”, the current evidence contains only the 15-minute standard rule. The question asks for a comparison, so one side is missing. A sufficiency check should request more context, which may bring in the 5-minute Atlas exception and its rationale.

If the source already contains all required facts, expansion may only add unrelated text. If the source never contains the answer, more context does not make an invented answer valid.

## In RAGReader

Self Route asks the model whether current evidence is sufficient. When it is not, the reader receives longer document context, prioritizing earlier hits within a **48,000-character** cap. That cap is not a promise to include the entire document or to fit every model's token window.

The route is recorded for inspection. A decision to keep the existing context is still a meaningful outcome; enabling the module does not mean expansion must happen.

## Interactions

With CRAG, expanded passages are graded and previously rejected chunks remain excluded. This protects the relevance boundary when broadening context. With LongRAG, both stages share the longer budget. FLARE can later introduce new hits that displace earlier text when space is exhausted.

More selected stages do not create separate context allowances. Inspect the final source set and any clipped text.

## Evaluate the sufficiency judgment

Construct one question whose answer needs a single passage, one needing a distant exception, and one whose answer is absent. Compare expansion decisions, actual support, and input size.

A model can be overconfident about incomplete context. Conversely, it can request expansion unnecessarily. Measure the resulting answer and work rather than accepting the model's self-assessment as ground truth.

For production-style experiments, record the percentage of queries expanded and their latency distribution. A policy that helps rare complex questions but doubles input size for every easy lookup may need a more selective threshold or a different approach.`,
    exercise: { title: "Assess evidence sufficiency", steps: ["Use only the standard-cache passage for a comparison question.", "List the exact facts still missing.", "Repeat after adding the Atlas exception and explain whether expansion remains necessary."], solution: "The duration and rationale for Atlas are initially missing. Once the source supplies both and the standard rule, a sufficiency check can keep the current evidence. The decision should depend on the actual question and passages." },
    quiz: { question: "What primarily distinguishes Self Route from Adaptive RAG?", options: ["Self Route assesses retrieved evidence before deciding on expansion", "Self Route always uses no retrieval", "Self Route guarantees the whole document fits the model"], answer: 0, explanation: "Self Route checks evidence sufficiency; Adaptive RAG selects a retrieval strategy from question complexity." },
    sources: [{ title: "Li et al. — RAG or Long-Context LLMs? A Hybrid Approach", url: "https://arxiv.org/abs/2407.16833" }],
  },
  {
    id: "flare", moduleId: "flare",
    title: "FLARE: retrieve while developing an answer",
    summary: "Use upcoming claims to identify evidence gaps before the final reader answers.",
    minutes: 16,
    objectives: ["Explain forward-looking retrieval.", "Distinguish model-reported uncertainty from token probabilities.", "Trace the provenance of evidence added late in a run."],
    content: `## The first search may not answer every sentence

A multi-part response can reveal information needs that were not obvious in the initial question. FLARE, or Forward-Looking Active REtrieval, predicts upcoming answer content and uses uncertainty to trigger additional retrieval. The original research uses low-confidence tokens in predicted sentences. RAGReader uses a **model-reported confidence adaptation**, without token-probability access.

This is a retrieval aid before final generation, not a guarantee that uncertain statements become true.

## Worked example

An answer about the cache incident starts with the known stale-results problem. The next proposed sentence says “The team fixed it by replacing all servers.” If no source supports that action, the pipeline should search for the incident response instead of presenting the guess.

The handbook says the team added explicit invalidation after catalog changes. The new evidence should replace the unsupported proposed explanation. The final reader still answers the original question from source passages.

## In RAGReader

The module predicts upcoming sentences, checks support, retrieves for unsupported claims, and revises those sentences against evidence. It makes at most **three predictions**. The final reader uses the resulting source context; draft text does not become a new source chunk.

When CRAG is enabled, newly retrieved evidence is graded and rejected source IDs remain excluded. FLARE prioritizes new hits, so later evidence can displace earlier passages when the context budget is full. LongRAG or Self Route allows the shared longer cap; FLARE does not get its own unlimited allowance.

## Confidence is not calibration

A model can confidently assert a false statement or be uncertain about a true one. Self-reported confidence is a heuristic, not a measured probability of correctness. A high-confidence draft should still be grounded, and a failed lookup should lead to qualification or abstention rather than invented specificity.

## Cost and inspection

FLARE introduces sequential generation and retrieval calls. It may help questions requiring several supported claims, but an exact lookup often needs only one good passage. Compare latency and source support with the same question and base configuration.

Inspect the extra searches, module statuses, accepted source IDs, and final packed context. If an important earlier fact disappears after a late search, a more complete candidate pool may paradoxically produce a less complete answer. Evaluate the evidence that actually reached the reader, not every passage touched during the run.`,
    exercise: { title: "Repair an unsupported sentence", steps: ["Draft an incident answer containing a hardware replacement claim.", "Use the handbook to search for the documented corrective action.", "Replace the unsupported sentence and identify the exact supporting source."], solution: "The documented action is explicit invalidation after catalog changes. The hardware claim must be removed unless a source establishes it. A successful FLARE-style correction adds real evidence and changes the claim accordingly." },
    quiz: { question: "How is uncertainty detected by this project's FLARE adaptation?", options: ["By training a new model for every sentence", "By reading guaranteed probabilities of factual truth", "By asking the model to assess upcoming content and support"], answer: 2, explanation: "The implementation uses model-reported uncertainty rather than the original token-probability mechanism. Its assessment can still be wrong." },
    sources: [{ title: "Jiang et al. — Active Retrieval Augmented Generation", url: "https://arxiv.org/abs/2305.06983" }],
  },
];
