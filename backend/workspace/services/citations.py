"""Citation markers in answers and the evidence objects they point at (PRD §13–14)."""
import re

# [1]  [1, 2]  [1][3] (two matches)
CITATION_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def cited_ids(answer, source_count):
    """Source numbers the answer cites, in first-cited order.

    Numbers outside 1..source_count are ignored: the model was told not to
    invent citations, and a marker that resolves to nothing must not become a
    link to the wrong passage.
    """
    seen = []
    for match in CITATION_MARKER.finditer(answer or ""):
        for part in match.group(1).split(","):
            number = int(part.strip())
            if 1 <= number <= source_count and number not in seen:
                seen.append(number)
    return seen


def evidence(citation_id, *, document, vector_id, chunk_id, text, score, position=None):
    position = position or {}
    return {
        "citation_id": citation_id,
        "document_id": document.pk,
        "document_title": document.name,
        "index_version_id": vector_id,
        "chunk_id": chunk_id,
        "page_number": position.get("page_start"),
        "page_end": position.get("page_end"),
        "char_start": position.get("char_start"),
        "char_end": position.get("char_end"),
        "text": text,
        "retrieval_score": round(float(score), 6),
        "rerank_score": None,
        "cited": False,
    }


def mark_cited(sources, answer):
    """Copies of `sources` with `cited` set from the answer's markers."""
    cited = set(cited_ids(answer, len(sources)))
    return [{**source, "cited": source["citation_id"] in cited} for source in sources]
