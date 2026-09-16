# RAGReader experiment worksheet

Use with the fictional Northstar handbook or your own approved source.
This is a written lab record; the courses do not submit work or run models.

## Hypothesis and requirements

- Failure being investigated:
- Proposed intervention and why it might help:
- Quality requirement:
- Latency or usage constraint:
- Document name and version:
- Ingest settings and embedding configuration:

## Questions and independent references

Prepare at least eight questions, including two reserved for final evaluation.
Use lookup, paraphrase, comparison, multi-step, and unanswerable questions.
Write references before reading generated answers.

| Question | Category | Development / held-out | Relevant source IDs | Expected answer or abstention |
| --- | --- | --- | --- | --- |
| | | | | |

## Configuration and results

Record a baseline, individual modules, and one two-module combination.
For every run, also keep the generation model, evaluation judge, Top-K,
reference mode (manual or pooled), and any changed settings.

| Run / batch | Method | Modules | Final source count | Precision | Recall | F1 | Faithfulness | Relevance | Correctness | Elapsed time | Failures / unavailable reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | | None | | | | | | | | | |
| Module A | | | | | | | | | | | |
| Module B | | | | | | | | | | | |
| A + B | | | | | | | | | | | |

Do not substitute zero for unavailable metrics. Record valid sample counts
when averaging. Note cache reuse and actual context size when comparing time.

## Trace review

- Original question:
- Actual route:
- Search questions:
- Final source IDs and supporting text:
- Completed / skipped / fallback modules:
- One improved answer and the source evidence explaining it:
- One regression and the source evidence explaining it:
- Unsupported claims or missing evidence:

## Final evaluation and recommendation

- Held-out results:
- Recommended configuration and rationale:
- Quality, latency, and availability tradeoffs:
- Source, model, judge, label, and sample-size limitations:
- Next experiment if requirements were not met:
