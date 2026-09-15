"""Optional, composable analysis stages, grouped by purpose for the sidebar."""

RAG_MODULES = [
    {"id": "adaptive_rag", "label": "Adaptive RAG", "description": "Choose direct, single-pass, or multi-step retrieval based on question complexity.", "stage": "Routing"},
    {"id": "rewrite_retrieve_read", "label": "Rewrite Retrieve Read", "description": "Rewrite the search question, retrieve evidence, and answer the original question.", "stage": "Query"},
    {"id": "step_back", "label": "Step Back Prompting", "description": "Also search for the broader concepts behind your question.", "stage": "Query"},
    {"id": "hyde", "label": "HyDE", "description": "Use a hypothetical answer for dense search; only actual document text is evidence.", "stage": "Query"},
    {"id": "rag_fusion", "label": "RAG Fusion (query expansion)", "description": "Search alternative questions and combine their rankings with RRF.", "stage": "Query"},
    {"id": "memo_rag", "label": "MemoRAG", "description": "Use a cached document summary to generate retrieval clues. Summary-memory adaptation.", "stage": "Query"},
    {"id": "rrf_hybrid", "label": "RRF Hybrid", "description": "Fuse dense and keyword rankings using reciprocal rank fusion, without reranking.", "stage": "Retrieval"},
    {"id": "raptor", "label": "RAPTOR", "description": "Cluster and summarize evidence recursively, then retrieve through the summary tree.", "stage": "Retrieval"},
    {"id": "long_rag", "label": "LongRAG", "description": "Search larger groups of adjacent chunks and give the reader their source passages.", "stage": "Retrieval"},
    {"id": "crag", "label": "CRAG", "description": "Grade evidence, discard irrelevant chunks, and retry weak retrieval within this document.", "stage": "Refinement"},
    {"id": "self_route", "label": "Self Route", "description": "Check whether retrieved evidence is sufficient; use longer document context if needed.", "stage": "Refinement"},
    {"id": "contextual_learning", "label": "Contextual Learning", "description": "Learn from example Q&A pairs in the prompt, then answer using the retrieved evidence.", "stage": "Generation"},
    {"id": "flare", "label": "FLARE", "description": "Draft upcoming sentences and retrieve again for uncertain claims. Uses a model confidence check.", "stage": "Generation"},
]
RAG_MODULE_IDS = [module["id"] for module in RAG_MODULES]


def normalize_modules(raw):
    """Unknown/malformed selections are off; an empty selection stays empty."""
    if not isinstance(raw, (list, tuple)):
        return []
    selected = {item for item in raw if isinstance(item, str)}
    return [module for module in RAG_MODULE_IDS if module in selected]
