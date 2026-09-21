---
title: RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines
description: Ask questions about your own PDF, URL, or pasted text, then score the answer across 9 RAG pipelines — Dense, Sparse and Hybrid retrieval x three LLMs.
image: https://rag.nevatal.tech/og-image.jpg
---

# RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines

RAGReader is a document question answering and evaluation platform that benchmarks Dense, Sparse, and Hybrid retrieval across multiple large language models (LLMs). It allows users to ask questions against their documents (PDF, URL, or pasted raw text) and evaluates the results across 9 parallel RAG pipelines.

## Key Features

- **Multi-pipeline Comparison**: Benchmarks Dense retrieval (vector embeddings), Sparse retrieval (BM25), and Hybrid retrieval (dense + sparse candidates reranked with cross-encoders).
- **Multi-LLM Benchmarking**: Evaluates responses across models including GPT-4o mini, Gemini 3 Flash, and Claude Haiku 4.5.
- **Evaluation Metrics**:
  - Retrieval quality: Precision@K, Recall@K, F1@K.
  - Answer quality: Ragas faithfulness, response relevance, and factual correctness (F1).
- **Ground Truth Establishment**: Supports manual selection of relevant chunks or automated candidate pooling using Reciprocal Rank Fusion (RRF).
- **Document Ingestion**: Seamless ingestion and chunking of PDFs, web page URLs, or pasted raw text.

## How to Use RAGReader

1. **Sign in**: Enter a username and email to create or load your document workspace.
2. **Add Document Source**: Upload a PDF, submit a website URL, or paste document text directly.
3. **Automatic Indexing**: Text is split into chunks, generating Dense vectors and BM25 sparse indices.
4. **Ask Initial Question**: Query your document to receive a baseline answer using Dense retrieval.
5. **Establish Ground Truth**: Select relevant chunks manually or automatically generate candidate pools using RRF.
6. **Execute Deep Analysis Matrix**: Benchmark 3 retrieval methods across 3 LLMs in parallel and review streamed metric scores.

## Frequently Asked Questions

### What does RAGReader actually do?
You add a document (PDF, URL, or raw text), ask a question, and get an answer from Dense (vector) retrieval. Clicking that answer opens a deep analysis that re-runs the same question through every combination of retrieval method and LLM you select — up to nine pipelines — and scores each one against ground truth.

### What document formats can I upload?
A PDF file, a web page URL (the HTML is fetched and stripped to text), or text pasted directly into the form.

### Which retrieval methods and LLM models are benchmarked?
Dense retrieval (openai/text-embedding-3-small), Sparse retrieval (BM25), and Hybrid retrieval (dense + sparse candidates reranked by cross-encoder/ms-marco-MiniLM-L6-v2). Each runs against GPT-4o mini, Gemini 3 Flash, and Claude Haiku 4.5 via OpenRouter.

### Which evaluation metrics are reported?
Retrieval quality: Precision@K, Recall@K, F1@K, with K matching the saved run's retrieval depth. Answer quality uses only Ragas faithfulness, response relevance, and factual correctness (F1) through the selected OpenRouter judge.

### Is RAGReader open source?
Yes, RAGReader is open source under the MIT License and can be self-hosted using Docker Compose.

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "RAGReader",
  "url": "https://rag.nevatal.tech/",
  "image": "https://rag.nevatal.tech/og-image.jpg",
  "description": "Document question answering platform that benchmarks Dense, Sparse, and Hybrid retrieval across three LLMs, evaluating retrieval with Precision@K, Recall@K, and F1@K, and answers with Ragas faithfulness, response relevance, and factual correctness.",
  "applicationCategory": "DeveloperApplication",
  "operatingSystem": "Any",
  "browserRequirements": "Requires JavaScript and WebSocket support",
  "license": "https://opensource.org/licenses/MIT",
  "softwareVersion": "1.0.0",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "author": {
    "@type": "Organization",
    "name": "RAGReader Team",
    "url": "https://github.com/thirza258/RagReader"
  }
}
```
