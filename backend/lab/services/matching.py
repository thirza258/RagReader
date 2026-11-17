"""Expected sources → chunks of the evaluated index (docs/prd-implementation.md, Phase 4).

A dataset names its evidence by document plus chunk, character range or
page. Chunk rows are replaced when a document is re-indexed with other
settings, so an expected source is matched against the index the
experiment actually searches — the one `run_retrieval` loads — in order:

1. `chunk_id`     — the chunk id is in that index's loaded snapshot.
2. `char_overlap` — chunks whose recorded `char_start`/`char_end`
                    (Chunk.metadata) overlap the expected range.
3. `page`         — chunks whose `page_start..page_end` overlap the pages.
4. `document`     — only a document was given: every chunk of it.
5. `unresolved`   — nothing matched; `reason` says why.

The rule that applied is recorded per expected source.
"""
from dataclasses import dataclass, field

from evaluation.models import Chunk

CHUNK_ID, CHAR_OVERLAP, PAGE, DOCUMENT, UNRESOLVED = "chunk_id", "char_overlap", "page", "document", "unresolved"
RULES = (CHUNK_ID, CHAR_OVERLAP, PAGE, DOCUMENT, UNRESOLVED)

NOT_IN_CORPUS = "document_not_in_corpus"
NO_CHUNKS = "document_has_no_chunks"
CHUNK_NOT_IN_INDEX = "chunk_not_in_index"
NO_CHUNK_IN_RANGE = "no_chunk_in_char_range"
NO_CHUNK_ON_PAGE = "no_chunk_on_page"


@dataclass
class IndexChunks:
    """The chunks of one document's evaluated index, with their positions."""
    document_id: int
    index_version_id: int | None
    chunk_ids: tuple = ()
    # chunk id → Chunk.metadata (ordinal, char_start, char_end, page_start, page_end)
    positions: dict = field(default_factory=dict)

    def __post_init__(self):
        self.members = frozenset(chunk_id for chunk_id in self.chunk_ids if chunk_id is not None)


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def chunk_positions(chunk_ids):
    """Chunk.metadata of every integer id in `chunk_ids` (one query)."""
    wanted = [chunk_id for chunk_id in chunk_ids if _int(chunk_id) is not None]
    if not wanted:
        return {}
    return dict(Chunk.objects.filter(pk__in=wanted).values_list("pk", "metadata"))


def index_chunks(document_id, index_version_id, chunk_ids):
    return IndexChunks(document_id=document_id, index_version_id=index_version_id, chunk_ids=tuple(chunk_ids),
                       positions=chunk_positions(chunk_ids))


def _overlap_chars(position, start, end):
    chunk_start, chunk_end = _int((position or {}).get("char_start")), _int((position or {}).get("char_end"))
    if chunk_start is None or chunk_end is None:
        return False
    return chunk_start < end and start < chunk_end


def _overlap_pages(position, first, last):
    page_start = _int((position or {}).get("page_start"))
    if page_start is None:
        return False
    page_end = _int((position or {}).get("page_end"))
    page_end = page_start if page_end is None else page_end
    return page_start <= last and first <= page_end


def _result(rule, chunk_ids=(), reason=None):
    return {"rule": rule, "chunk_ids": list(chunk_ids), "reason": reason}


def resolve_source(source, corpus):
    """{"rule", "chunk_ids", "reason"} for one expected source.

    `corpus` maps document id → IndexChunks of every document searched.
    """
    index = corpus.get(_int(source.get("document_id")))
    if index is None:
        return _result(UNRESOLVED, reason=NOT_IN_CORPUS)
    chunk_id = source.get("chunk_id")
    char_start, char_end = _int(source.get("char_start")), _int(source.get("char_end"))
    page = _int(source.get("page"))
    page_end = _int(source.get("page_end"))
    has_range = char_start is not None and char_end is not None
    if chunk_id is None and not has_range and page is None:
        if not index.members:
            return _result(UNRESOLVED, reason=NO_CHUNKS)
        return _result(DOCUMENT, [value for value in index.chunk_ids if value is not None])
    if chunk_id is not None and chunk_id in index.members:
        return _result(CHUNK_ID, [chunk_id])
    reason = CHUNK_NOT_IN_INDEX
    if has_range:
        hits = [value for value in index.chunk_ids
                if value is not None and _overlap_chars(index.positions.get(value), char_start, char_end)]
        if hits:
            return _result(CHAR_OVERLAP, hits)
        reason = NO_CHUNK_IN_RANGE
    if page is not None:
        last = page_end if page_end is not None and page_end >= page else page
        hits = [value for value in index.chunk_ids
                if value is not None and _overlap_pages(index.positions.get(value), page, last)]
        if hits:
            return _result(PAGE, hits)
        reason = NO_CHUNK_ON_PAGE
    return _result(UNRESOLVED, reason=reason)


def resolve_sources(sources, corpus):
    """One resolution per expected source, tagged with its index in the item."""
    return [{"source": position, **resolve_source(source, corpus)} for position, source in enumerate(sources or [])]
