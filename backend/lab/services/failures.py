"""Failure analysis (PRD §31): why an evaluation item went wrong.

Labels are `{"category", "code", "detail", "sources"}` (`sources` are the
indexes of the expected sources concerned); an item can carry several.

retrieval   relevant_not_retrieved  a resolved source has no chunk among the candidates
            insufficient_k          a resolved source is a candidate, but only beyond the context
            wrong_document          a source is missing from the context and most context
                                    passages come from documents no expected source names
            query_mismatch          the query used missed a source the other formulation
                                    (original question vs rewritten query) retrieved
generation  unsupported_claim       faithfulness below the threshold
            citation_mismatch       a cited passage is not relevant, or expected evidence
                                    in the context was not cited at all
            incomplete_answer       answer correctness below the threshold
dataset     ambiguous_question      no expected source, so retrieval cannot be judged
            missing_evidence        an expected source could not be found in the documents
            duplicate_question      another item asks the same question
"""
from lab.services.metrics import covered_sources

CATEGORIES = {
    "retrieval": ("relevant_not_retrieved", "wrong_document", "insufficient_k", "query_mismatch"),
    "generation": ("unsupported_claim", "citation_mismatch", "incomplete_answer"),
    "dataset": ("ambiguous_question", "missing_evidence", "duplicate_question"),
}
CODES = {code: category for category, codes in CATEGORIES.items() for code in codes}


def label(code, detail, sources=()):
    return {"category": CODES[code], "code": code, "detail": detail, "sources": list(sources)}


def _sources_text(indexes):
    numbers = ", ".join(f"#{index + 1}" for index in indexes)
    return f"expected source{'s' if len(indexes) != 1 else ''} {numbers}"


def retrieval_labels(resolved, ranked, context_size, expected_documents, alternative=None):
    """Labels for one item's retrieval.

    `resolved`: [(source index, chunk-id set)] of the resolved expected
    sources; `ranked`: [{"chunk_id", "document_id"}] in final order;
    `alternative`: None or {"kind": "original" | "rewritten" (the formulation
    *not* used), "ranked": [...], "context_size": n}.
    """
    labels = []
    if not resolved:
        return labels
    sets = [chunk_set for _index, chunk_set in resolved]
    ids = [row.get("chunk_id") for row in ranked]
    context = ids[:context_size]
    anywhere = set(covered_sources(ids, sets))
    in_context = set(covered_sources(context, sets))
    missing = [resolved[position][0] for position in range(len(sets)) if position not in anywhere]
    beyond = [resolved[position][0] for position in range(len(sets)) if position in anywhere and position not in in_context]
    if missing:
        labels.append(label("relevant_not_retrieved", f"No candidate matched {_sources_text(missing)}.", missing))
    if beyond:
        ranks = []
        for position in range(len(sets)):
            if position in anywhere and position not in in_context:
                ranks.append(next(rank for rank, chunk_id in enumerate(ids, 1) if chunk_id in sets[position]))
        labels.append(label(
            "insufficient_k",
            f"{_sources_text(beyond).capitalize()} ranked {', '.join(str(rank) for rank in ranks)}, "
            f"outside the {context_size} passages given to the model.", beyond,
        ))
    not_in_context = [resolved[position][0] for position in range(len(sets)) if position not in in_context]
    rows = ranked[:context_size]
    if not_in_context and rows:
        foreign = sum(1 for row in rows if row.get("document_id") not in expected_documents)
        if foreign * 2 > len(rows):
            labels.append(label(
                "wrong_document",
                f"{foreign} of {len(rows)} context passages come from documents no expected source names.",
                not_in_context,
            ))
    if alternative:
        other_ids = [row.get("chunk_id") for row in alternative.get("ranked") or []]
        other_context = set(covered_sources(other_ids[:alternative.get("context_size") or 0], sets))
        lost = [resolved[position][0] for position in range(len(sets)) if position in other_context and position not in in_context]
        if lost:
            if alternative.get("kind") == "original":
                detail = f"The rewritten query missed {_sources_text(lost)}, which the original question retrieved."
            else:
                detail = f"The original question missed {_sources_text(lost)}, which the rewritten query retrieved."
            labels.append(label("query_mismatch", detail, lost))
    return labels


def generation_labels(values, thresholds):
    labels = []
    faithfulness = values.get("faithfulness")
    if faithfulness is not None and faithfulness < thresholds["faithfulness"]:
        labels.append(label("unsupported_claim",
                            f"Faithfulness {faithfulness:.2f} is below {thresholds['faithfulness']:.2f}: "
                            "the answer makes claims the passages do not support."))
    correctness, completeness = values.get("citation_correctness"), values.get("citation_completeness")
    if correctness is not None and correctness < 1:
        labels.append(label("citation_mismatch", f"Only {correctness:.0%} of the cited passages are expected evidence."))
    elif completeness is not None and completeness == 0:
        labels.append(label("citation_mismatch", "The context held expected evidence, but the answer cited none of it."))
    answer_correctness = values.get("answer_correctness")
    if answer_correctness is not None and answer_correctness < thresholds["answer_correctness"]:
        labels.append(label("incomplete_answer",
                            f"Answer correctness {answer_correctness:.2f} is below {thresholds['answer_correctness']:.2f} "
                            "against the expected answer."))
    return labels


def dataset_labels(expected_count, matching, duplicate_of):
    labels = []
    if expected_count == 0:
        labels.append(label("ambiguous_question", "The item has no expected source, so retrieval cannot be judged."))
    unresolved = [entry["source"] for entry in matching or [] if entry.get("rule") == "unresolved"]
    if unresolved:
        reasons = sorted({entry.get("reason") or "unresolved" for entry in matching if entry.get("rule") == "unresolved"})
        labels.append(label("missing_evidence",
                            f"{_sources_text(unresolved).capitalize()} could not be found in the documents ({', '.join(reasons)}).",
                            unresolved))
    if duplicate_of:
        labels.append(label("duplicate_question", f"Same question as {', '.join(duplicate_of)}."))
    return labels


def empty_counts():
    return {category: {code: 0 for code in codes} for category, codes in CATEGORIES.items()}


def count_labels(label_lists):
    """Per-category counts of items carrying each code, plus `items_with_failures`."""
    counts = empty_counts()
    with_failures = 0
    for labels in label_lists:
        codes = {entry.get("code") for entry in labels or [] if entry.get("code") in CODES}
        for code in codes:
            counts[CODES[code]][code] += 1
        with_failures += bool(codes)
    return {**counts, "items_with_failures": with_failures}
