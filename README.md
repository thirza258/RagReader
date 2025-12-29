# RAGReader 

**Next-Generation Document QA with Multi-Method RAG & Multi-LLM Consensus**

RAGReader is an advanced AI-powered application designed to revolutionize how you interact with your documents. While it functions as a high-speed document chat interface using standard Vector Embedding RAG, its true power lies in its **"Deep Dive"** capability—orchestrating multiple retrieval strategies, rigorous evaluation metrics, and a democratic voting system between the world's leading LLMs to ensure the most accurate answer possible.

---

## Key Features

### 1. Standard Mode (Fast & Efficient)
*   **Dense RAG:** Utilizes high-performance vector embeddings to quickly retrieve relevant chunks from your uploaded files.
*   **LLM Backend:** Powered by OpenAI GPT for rapid and coherent response generation.

### 2. Deep Dive Mode (The "Click" Feature)
When accuracy is paramount, click the answer to trigger a comprehensive analysis pipeline:
*   **Multi-Method Retrieval:** simultaneously employs:
    *   **Dense RAG:** Semantic search.
    *   **Sparse RAG:** Keyword-based search (BM25/SPLADE).
    *   **Hybrid RAG:** Combining semantic and keyword scores.
    *   **Iterative RAG:** Multi-step reasoning to find complex answers.
*   **Advanced Refinement:**
    *   **Reranking:** Re-orders retrieved chunks using a cross-encoder to ensure the highest relevance.

### 3. Evaluation & Validation
*   **Metrics:** Automatically calculates **MRR (Mean Reciprocal Rank)** and **Context Relevance** scores to grade the quality of retrieved data.
*   **The "Council of AI":** A consensus voting mechanism where three distinct LLMs evaluate the generated answers to pick the winner:
    *   **OpenAI GPT**
    *   **Anthropic Claude**
    *   **Google Gemini**

---

## Architecture Workflow

```mermaid
graph TD
    User[User Input] --> Standard[Standard Dense RAG]
    Standard --> Answer[Initial Answer]
    Answer -- User Clicks Deep Dive --> Complex[Advanced Pipeline]
    
    subgraph "Retrieval Strategies"
        Complex --> Dense[Dense Vector Search]
        Complex --> Sparse[Sparse/Keyword Search]
        Complex --> Iterative[Iterative Search]
    end
    
    Dense & Sparse & Iterative --> Hybrid[Hybrid Fusion]
    Hybrid --> Rerank[Reranker Model]
    
    subgraph "Evaluation & Generation"
        Rerank --> Gen[Generate Candidate Answers]
        Gen --> EvalMetrics[Calc MRR & Context Relevance]
    end
    
    subgraph "Voting Council"
        EvalMetrics --> VoteGPT[GPT Vote]
        EvalMetrics --> VoteClaude[Claude Vote]
        EvalMetrics --> VoteGemini[Gemini Vote]
    end
    
    VoteGPT & VoteClaude & VoteGemini --> Dashboard with Score
```

## Tech Stack

*   **LLM Orchestration:** OpenAI GPT, Anthropic Claude, Google Gemini.
*   **Embedding Models:** OpenAI Embeddings and Mini LM.
*   **Retrieval:** Hybrid Search (Dense + Sparse), Rerankers (e.g., Cohere/BGE).
*   **Framework:** LangChain.
*   **Frontend:** (e.g., React, Vite).

## Usage Guide

1.  **Upload:** Drag and drop your PDF, TXT, or MD files into the sidebar.
2.  **Ask:** Type your question in the chat input.
3.  **Read:** Get an immediate answer via Standard Dense RAG.
4.  **Verify:** **Click the answer** to activate the "Deep Dive."
    *   Watch as the system reranks chunks and calculates MRR.
    *   Wait for the "Council of AI" (GPT, Claude, Gemini) to vote.
    *   View the final, consensus-based result.

---

## Contributing

Contributions make the open-source community an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
