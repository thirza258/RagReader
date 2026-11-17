"""Retrieval and citation metrics (PRD §27, §28) as pure functions.

Relevance is binary and counted per **expected source**. Each resolved
expected source is the set of chunk ids it matched in the evaluated index
(lab.services.matching); `ranked` is the candidates' chunk ids in final rank
order. Definitions (docs/prd-implementation.md, Phase 4):

- Recall@K: expected sources with at least one chunk in the top K, ÷ m.
- Precision@K: distinct relevant chunks in the top K, ÷ K — also when fewer
  than K passages were retrieved. Two different chunks of one source both
  count; a repeated chunk id counts once.
- Hit rate@K: 1 when the top K holds a relevant chunk, else 0.
- MRR: 1 / rank of the first relevant chunk over the whole candidate list.
- nDCG@K: binary gain — a passage gains 1 only when it covers an expected
  source that no higher-ranked passage covered. IDCG = Σ_{i ≤ min(m, K)}
  1 / log2(i + 1), so a perfect ranking scores 1.
- Context recall / precision: the same over the final context (the passages
  given, or in retrieval-only experiments that would be given, to the model).
- Citation correctness: cited passages that are relevant ÷ cited passages.
- Citation completeness: expected sources covered by a cited passage ÷
  expected sources covered by the context, so a retrieval miss does not
  count against generation.

Repeated ids are removed before ranking (first occurrence kept); a missing
chunk id (None) occupies its rank but is never relevant. Identical resolved
sources (e.g. the same source listed twice) count once. A metric that cannot
be computed is None with a reason code, never 0.
"""
import math

NO_EXPECTED_SOURCES = "no_expected_sources"
SOURCES_UNRESOLVED = "expected_sources_unresolved"
EMPTY_CONTEXT = "empty_context"
ITEM_FAILED = "item_failed"
RETRIEVAL_ONLY = "retrieval_only"
NO_CITATIONS = "no_citations"
NO_SOURCE_IN_CONTEXT = "no_expected_source_in_context"
NO_EXPECTED_ANSWER = "no_expected_answer"
NO_ANSWER = "no_answer"
JUDGE_UNAVAILABLE = "judge_unavailable"
JUDGE_FAILED = "judge_failed"

REASONS = (
    NO_EXPECTED_SOURCES, SOURCES_UNRESOLVED, EMPTY_CONTEXT, ITEM_FAILED, RETRIEVAL_ONLY, NO_CITATIONS,
    NO_SOURCE_IN_CONTEXT, NO_EXPECTED_ANSWER, NO_ANSWER, JUDGE_UNAVAILABLE, JUDGE_FAILED,
)

AT_K_METRICS = ("recall", "precision", "hit_rate", "ndcg")
RANK_METRICS = ("mrr", "context_recall", "context_precision")
JUDGE_METRICS = ("faithfulness", "answer_relevance", "answer_correctness")
CITATION_METRICS = ("citation_correctness", "citation_completeness")
GENERATION_METRICS = JUDGE_METRICS + CITATION_METRICS
DECIMALS = 6


def retrieval_keys(k_values):
    """Retrieval metric keys in display order: per K (ascending), then the rest."""
    keys = []
    for k in sorted(set(k_values)):
        keys.extend(f"{name}@{k}" for name in AT_K_METRICS)
    return keys + list(RANK_METRICS)


def metric_group(key):
    """'retrieval' or 'generation' for a metric key (None if unknown)."""
    name = key.split("@", 1)[0]
    if name in AT_K_METRICS or name in RANK_METRICS:
        return "retrieval"
    if name in GENERATION_METRICS:
        return "generation"
    return None


def _round(value):
    return None if value is None else round(float(value), DECIMALS)


# ── Building blocks ──────────────────────────────────────────────────────────

def unique_ranking(ranked):
    """`ranked` without repeated ids (first occurrence kept); None ids stay in place."""
    seen, kept = set(), []
    for chunk_id in ranked:
        if chunk_id is not None:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
        kept.append(chunk_id)
    return kept


def distinct_sources(sources):
    """Resolved sources as frozensets, empty ones and exact repeats dropped (order kept)."""
    kept = []
    for source in sources:
        chunk_set = frozenset(chunk_id for chunk_id in source if chunk_id is not None)
        if chunk_set and chunk_set not in kept:
            kept.append(chunk_set)
    return kept


def relevant_ids(sources):
    union = set()
    for source in sources:
        union |= source
    return union


def covered_sources(passages, sources):
    """Indexes of `sources` with at least one chunk among `passages`."""
    present = {chunk_id for chunk_id in passages if chunk_id is not None}
    return [index for index, source in enumerate(sources) if source & present]


# ── Retrieval metrics (sources must be non-empty: see `retrieval_metrics`) ───

def recall_at_k(ranked, sources, k):
    top = unique_ranking(ranked)[:k]
    return len(covered_sources(top, sources)) / len(sources)


def precision_at_k(ranked, sources, k):
    relevant = relevant_ids(sources)
    top = unique_ranking(ranked)[:k]
    return sum(1 for chunk_id in top if chunk_id is not None and chunk_id in relevant) / k


def hit_rate_at_k(ranked, sources, k):
    relevant = relevant_ids(sources)
    return 1.0 if any(chunk_id in relevant for chunk_id in unique_ranking(ranked)[:k] if chunk_id is not None) else 0.0


def reciprocal_rank(ranked, sources):
    relevant = relevant_ids(sources)
    for rank, chunk_id in enumerate(unique_ranking(ranked), 1):
        if chunk_id is not None and chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked, sources, k):
    covered, dcg = set(), 0.0
    for rank, chunk_id in enumerate(unique_ranking(ranked)[:k], 1):
        if chunk_id is None:
            continue
        new = {index for index, source in enumerate(sources) if chunk_id in source and index not in covered}
        if new:
            dcg += 1.0 / math.log2(rank + 1)
            covered |= new
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(sources), k) + 1))
    return dcg / ideal


def context_recall(context, sources):
    return len(covered_sources(context, sources)) / len(sources)


def context_precision(context, sources):
    context = unique_ranking(context)
    if not context:
        return None
    relevant = relevant_ids(sources)
    return sum(1 for chunk_id in context if chunk_id is not None and chunk_id in relevant) / len(context)


def retrieval_metrics(ranked, sources, k_values, context_size, *, has_expected_sources):
    """({key: value or None}, {key: reason}) for one item.

    `sources` are the resolved expected sources (chunk-id sets);
    `has_expected_sources` says whether the item named any at all, which
    separates `no_expected_sources` from `expected_sources_unresolved`.
    `context_size` is how many of the first candidates formed the context.
    """
    keys = retrieval_keys(k_values)
    sources = distinct_sources(sources)
    if not has_expected_sources or not sources:
        reason = NO_EXPECTED_SOURCES if not has_expected_sources else SOURCES_UNRESOLVED
        return {key: None for key in keys}, {key: reason for key in keys}
    values, reasons = {}, {}
    for k in sorted(set(k_values)):
        values[f"recall@{k}"] = _round(recall_at_k(ranked, sources, k))
        values[f"precision@{k}"] = _round(precision_at_k(ranked, sources, k))
        values[f"hit_rate@{k}"] = _round(hit_rate_at_k(ranked, sources, k))
        values[f"ndcg@{k}"] = _round(ndcg_at_k(ranked, sources, k))
    values["mrr"] = _round(reciprocal_rank(ranked, sources))
    context = list(ranked)[:max(0, context_size)]
    values["context_recall"] = _round(context_recall(context, sources))
    precision = context_precision(context, sources)
    values["context_precision"] = _round(precision)
    if precision is None:
        reasons["context_precision"] = EMPTY_CONTEXT
    return values, reasons


# ── Citation metrics (§28, computed from the stored evidence) ────────────────

def citation_metrics(context, cited, sources, *, has_expected_sources):
    """Citation correctness and completeness for one answer.

    `context` are the chunk ids given to the model, `cited` those the answer
    cites with `[n]` markers.
    """
    keys = CITATION_METRICS
    sources = distinct_sources(sources)
    if not has_expected_sources or not sources:
        reason = NO_EXPECTED_SOURCES if not has_expected_sources else SOURCES_UNRESOLVED
        return {key: None for key in keys}, {key: reason for key in keys}
    values, reasons = {}, {}
    relevant = relevant_ids(sources)
    cited = unique_ranking(cited)
    if cited:
        values["citation_correctness"] = _round(
            sum(1 for chunk_id in cited if chunk_id is not None and chunk_id in relevant) / len(cited)
        )
    else:
        values["citation_correctness"], reasons["citation_correctness"] = None, NO_CITATIONS
    in_context = set(covered_sources(context, sources))
    if in_context:
        by_citation = set(covered_sources(cited, sources))
        values["citation_completeness"] = _round(len(by_citation & in_context) / len(in_context))
    else:
        values["citation_completeness"], reasons["citation_completeness"] = None, NO_SOURCE_IN_CONTEXT
    return values, reasons


def unavailable(keys, reason):
    """Every key None with one reason (failed items, retrieval-only generation)."""
    return {key: None for key in keys}, {key: reason for key in keys}
