# RAGReader 


**Next-Generation Document QA with Multi-Method RAG & Multi-LLM Consensus**

RAGReader is an advanced AI-powered application designed to revolutionize how you interact with your documents. While it functions as a high-speed document chat interface using standard Vector Embedding RAG, its true power lies in its **"Deep Dive"** capability—orchestrating multiple retrieval strategies, rigorous evaluation metrics, and a democratic voting system between the world's leading LLMs to ensure the most accurate answer possible.

---

## How to Run This App

### Prerequisites
- **Python 3.9+** and **npm** installed.
- **Redis server** installed and running.
- **PostgreSQL** (for production mode; SQLite is used in development).

### Steps

#### Option 1: Docker (Recommended)

1. **Configure environment**  
   ```bash
   cp .env.example .env
   cp .env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```
   Edit each `.env` file and fill in your API keys and credentials.

2. **Deploy (tests run first, deploy aborts if they fail)**  
   ```bash
   ./deploy.sh
   ```
   The script builds the backend image, runs the Django test suite inside it,
   type-checks and builds the frontend, then starts all services and waits for
   the backend health check. The app will be available at
   [http://localhost:5150](http://localhost:5150).

   Other modes:
   ```bash
   ./deploy.sh test         # run the test gate only (no deploy)
   ./deploy.sh --skip-tests # emergency deploy without the test gate
   ```

#### Option 2: Manual Setup

1. **Start Redis server**  
   Make sure Redis is running.  
   ```bash
   # Start your local Redis (example for Linux/macOS):
   redis-server
   # Check if Redis is running:
   redis-cli ping
   # Should output: PONG
   ```

2. **Start Celery worker**  
   From the backend directory, start a Celery worker for background tasks:  
   ```bash
   cd backend
   celery -A ragreader worker --loglevel=info
   ```

3. **Run Django backend**  
   From the backend directory:  
   ```bash
   python manage.py runserver
   ```

4. **Run the frontend**  
   From the frontend directory:  
   ```bash
   npm install     
   npm run dev
   ```

Once all services are running, access the app at [http://localhost:5173](http://localhost:5173) (or as indicated in the terminal).

### Running the tests

The backend test suite is hermetic — it needs no Redis, database server,
network access, or API keys:

```bash
cd backend
DEVELOPMENT_MODE=True RAG_DISABLE_ENGINE_INIT=1 python manage.py test
```

`RAG_DISABLE_ENGINE_INIT=1` skips loading the RAG engines (embedding clients,
cross-encoder downloads) so the suite runs fast anywhere. The same suite is
executed inside the backend Docker image by `./deploy.sh` before every deploy.


## Key Features

### 1. Standard Mode (Fast & Efficient)
*   **Dense RAG:** Utilizes high-performance vector embeddings to quickly retrieve relevant chunks from your uploaded files.
*   **LLM Backend:** Powered by OpenAI GPT for rapid and coherent response generation.

### 2. Deep Dive Mode (The "Click" Feature)
When accuracy is paramount, click the answer to trigger a comprehensive analysis pipeline that runs your query through **9 independent pipelines** — every combination of retrieval method and LLM:

*   **3 Retrieval Methods:**
    *   **Dense RAG:** Semantic vector search using embeddings.
    *   **Sparse RAG:** Keyword-based search with BM25.
    *   **Hybrid RAG:** Combines semantic and keyword scores with a cross-encoder reranker.
*   **3 LLMs:**
    *   **OpenAI GPT-4o-mini**
    *   **Anthropic Claude Haiku 4.5**
    *   **Google Gemini 3 Flash**

Results from all 9 pipelines are streamed live via WebSocket, so you can compare answers, context, and evaluation scores in real time.
   

### 3. Evaluation & Validation
Each Deep Dive analysis is automatically evaluated against ground-truth data (if provided) using two layers of metrics:

**Retrieval Quality** — how well the system finds the right chunks:
*   **Precision@K** — fraction of retrieved chunks that are relevant.
*   **Recall@K** — fraction of relevant chunks that were retrieved.
*   **F1@K** — harmonic mean of Precision@K and Recall@K.

**Response Quality** — how good the generated answer is:
*   **ROUGE-L** (Precision, Recall, F1) — measures textual overlap with the ground-truth answer using longest common subsequence.
*   **Faithfulness** (1–5) — LLM-judged: is the answer factually grounded in the retrieved chunks, or does it hallucinate?
*   **Answer Relevance** (1–5) — LLM-judged: how well does the answer address the retrieved context?
*   **Answer Coverage** (1–5) — LLM-judged: does the answer cover all the important points from the retrieved chunks?

These metrics are calculated for every combination of retrieval method × LLM model, giving you a comprehensive view of which pipeline performs best for your documents.
    


## Tech Stack

*   **LLM Orchestration:** OpenAI GPT-4o-mini, Anthropic Claude Haiku 4.5, Google Gemini 3 Flash.
*   **Evaluation LLM:** Mistral Nemo (via OpenRouter) for faithfulness/relevance/coverage scoring.
*   **Embedding Models:** OpenAI Embeddings and Mini LM.
*   **Retrieval:** Dense (vector), Sparse (BM25), Hybrid (semantic + keyword + reranker).
*   **Evaluation Metrics:** Precision@K, Recall@K, F1@K, ROUGE-L, Faithfulness, Answer Relevance, Answer Coverage.
*   **Framework:** LangChain, Django, Celery, Redis, Django Channels (WebSocket).
*   **Frontend:** React, Vite, Tailwind.

## Usage Guide

1.  **Upload:** Drag and drop your PDF, TXT, or MD files into the sidebar.
2.  **Ask:** Type your question in the chat input.
3.  **Read:** Get an immediate answer via Standard Dense RAG.
4.  **Deep Dive:** **Click the answer** to watch your query run through all 9 pipelines (3 retrieval methods × 3 LLMs).
    *   See each retrieval, reranking, and evaluation performed by the system and every AI model.
    *   Observe Precision@K, Recall@K, F1@K, ROUGE-L, Faithfulness, Answer Relevance, and Answer Coverage calculated for each variant.
    *   Compare answers across models and methods to find the most accurate response.

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

## Citation

```bibtex
@misc{es2025ragasautomatedevaluationretrieval,
      title={Ragas: Automated Evaluation of Retrieval Augmented Generation}, 
      author={Shahul Es and Jithin James and Luis Espinosa-Anke and Steven Schockaert},
      year={2025},
      eprint={2309.15217},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2309.15217}, 
}
```