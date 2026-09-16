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

# Served with the catalogue so the sidebar can explain the current selection
# without another request. There are no forbidden pairs in this implementation;
# conditional routing, evidence filtering, and work budgets still apply.
MODULE_COMPATIBILITY = {
    "all_modules_supported": True,
    "summary": "All 13 modules can be enabled in one run. They execute in ordered stages and share evidence.",
    "stages": [
        {"id": "routing", "label": "Routing", "modules": ["adaptive_rag"]},
        {"id": "retrieval", "label": "Queries & retrieval", "modules": ["rewrite_retrieve_read", "step_back", "rag_fusion", "memo_rag", "rrf_hybrid", "hyde"]},
        {"id": "evidence", "label": "Evidence", "modules": ["raptor", "long_rag", "crag", "self_route"]},
        {"id": "answer", "label": "Answer", "modules": ["flare", "contextual_learning"]},
    ],
    "rules": [
        {
            "id": "adaptive_route", "kind": "conditional",
            "modules": ["adaptive_rag"], "min_selected": 1,
            "title": "Adaptive RAG can skip other modules",
            "description": "A direct-answer decision skips all later stages. Single-pass and multi-step decisions continue through your selection; multi-step adds two follow-up searches.",
        },
        {
            "id": "self_route_context", "kind": "conditional",
            "modules": ["self_route"], "min_selected": 1,
            "title": "Self Route can broaden the context",
            "description": "It checks the retrieved evidence first. If more is needed, it adds document passages while prioritizing earlier hits within the context limit.",
        },
        {
            "id": "crag_self_route", "kind": "compatible",
            "modules": ["crag", "self_route"], "min_selected": 2,
            "title": "CRAG + Self Route preserve filtering",
            "description": "CRAG grades the expanded context too. Previously rejected chunks stay excluded, including when a later stage fails.",
        },
        {
            "id": "crag_flare", "kind": "compatible",
            "modules": ["crag", "flare"], "min_selected": 2,
            "title": "CRAG checks FLARE’s new evidence",
            "description": "FLARE’s extra retrieval passes through the same relevance filter before reaching the answer. Rejected chunks cannot return.",
        },
        {
            "id": "fusion_rrf", "kind": "compatible",
            "modules": ["rag_fusion", "rrf_hybrid"], "min_selected": 2,
            "title": "RAG Fusion + RRF Hybrid work together",
            "description": "RRF Hybrid combines dense and keyword results for each search. RAG Fusion then combines the rankings from the different questions.",
        },
        {
            "id": "hyde_rrf", "kind": "compatible",
            "modules": ["hyde", "rrf_hybrid"], "min_selected": 2,
            "title": "HyDE keeps its dense search",
            "description": "The hypothetical passage uses dense retrieval. Its source hits are combined with the hybrid results from the original and expanded questions.",
        },
        {
            "id": "rrf_method", "kind": "conditional",
            "modules": ["rrf_hybrid"], "min_selected": 1,
            "title": "RRF Hybrid changes the retrieval method",
            "description": "Every selected base method uses dense + BM25 fusion while this is on. The normal Hybrid reranker is bypassed, so its reranker setting has no effect.",
        },
        {
            "id": "query_work", "kind": "cost",
            "modules": ["rewrite_retrieve_read", "step_back", "hyde", "rag_fusion", "memo_rag"], "min_selected": 2,
            "title": "Query modules add work",
            "description": "Multiple query modules add generation and retrieval calls. Repeated search questions are deduplicated; enabling more modules does not guarantee a better answer.",
        },
        {
            "id": "raptor_long", "kind": "cost",
            "modules": ["raptor", "long_rag"], "min_selected": 2,
            "title": "RAPTOR + LongRAG build separate indexes",
            "description": "RAPTOR searches a summary tree; LongRAG searches groups of adjacent passages. Their evidence is combined, with earlier hits prioritized within the context limit.",
        },
        {
            "id": "sparse_embeddings", "kind": "requirement",
            "modules": ["hyde", "rrf_hybrid", "raptor", "long_rag"], "min_selected": 1,
            "methods": ["Sparse Retrieval"],
            "title": "These modules need embeddings for Sparse runs",
            "description": "HyDE, RRF Hybrid, RAPTOR, and LongRAG use dense embeddings, even with Sparse retrieval selected. They need the configured embedding provider as well as the answer model.",
        },
        {
            "id": "flare_budget", "kind": "conditional",
            "modules": ["flare"], "min_selected": 1,
            "title": "FLARE shares the context limit",
            "description": "When the context is full, new evidence can replace lower-priority earlier passages. FLARE makes at most three sentence checks.",
        },
        {
            "id": "examples", "kind": "compatible",
            "modules": ["contextual_learning"], "min_selected": 1,
            "title": "Q&A examples are added last",
            "description": "Contextual Learning uses the final evidence after retrieval and refinement. It is skipped when there is no evidence; the target reference answer is never an example.",
        },
    ],
}


def normalize_modules(raw):
    """Unknown/malformed selections are off; an empty selection stays empty."""
    if not isinstance(raw, (list, tuple)):
        return []
    selected = {item for item in raw if isinstance(item, str)}
    return [module for module in RAG_MODULE_IDS if module in selected]
