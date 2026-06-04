# RAGReader 


**Next-Generation Document QA with Multi-Method RAG & Multi-LLM Consensus**

RAGReader is an advanced AI-powered application designed to revolutionize how you interact with your documents. While it functions as a high-speed document chat interface using standard Vector Embedding RAG, its true power lies in its **"Deep Dive"** capability—orchestrating multiple retrieval strategies, rigorous evaluation metrics, and a democratic voting system between the world's leading LLMs to ensure the most accurate answer possible.

---

## How to Run This App

### Prerequisites
- **Python 3.9+** and **npm** installed.
- **Redis server** installed and running.

### Steps

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
   celery -A ragreader worker --loglevel=info
   ```

3. **Run Django backend**  
   Start the backend server:  
   ```bash
   python manage.py runserver
   ```

4. **Run the frontend**  
   From the frontend directory, start the development server:  
   ```bash
   npm install     
   npm run dev
   ```

Once all services are running, access the app at [http://localhost:5173](http://localhost:5173) (or as indicated in the terminal).

Or Running it with fill the .env.example to .env and then
   ```bash
    docker compose up -d --build
   ```


## Key Features

### 1. Standard Mode (Fast & Efficient)
*   **Dense RAG:** Utilizes high-performance vector embeddings to quickly retrieve relevant chunks from your uploaded files.
*   **LLM Backend:** Powered by OpenAI GPT for rapid and coherent response generation.

### 2. Deep Dive Mode (The "Click" Feature)
When accuracy is paramount, click the answer to trigger a comprehensive analysis pipeline:
*   **Retrieval Method:** simultaneously employs:
    *   **Dense RAG:** Semantic search.
    *   **Sparse RAG:** Keyword-based search BM25.
    *   **Hybrid RAG:** Combining semantic and keyword scores with reranking model.
   

### 3. Evaluation & Validation
*   **Metrics:** Automatically calculates **MRR (Mean Reciprocal Rank)** , **Recall@K**,  and **Precision@K** scores to grade the quality of retrieved data.
*   **RAGAs:** : 
    


## Tech Stack

*   **LLM Orchestration:** OpenAI GPT, Anthropic Claude, Google Gemini.
*   **Embedding Models:** OpenAI Embeddings and Mini LM.
*   **Retrieval:** Hybrid Search, Dense, Sparse, Reranker
*   **Framework:** LangChain.
*   **Frontend:** React, Vite, Tailwind.
*   **Backend:** Django for the AI/RAG API

## Usage Guide

1.  **Upload:** Drag and drop your PDF, TXT, or MD files into the sidebar.
2.  **Ask:** Type your question in the chat input.
3.  **Read:** Get an immediate answer via Standard Dense RAG.
4.  **Deep Dive:** **Click the answer** to watch your query run through all AIs and methods.
    *   See each retrieval, reranking, and evaluation performed by the system and every AI model.
    *   Observe MRR and other metrics calculated at each step.
    *   See whether the answer is good in semantic (RAGAs)

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

@misc{es2025ragasautomatedevaluationretrieval,
      title={Ragas: Automated Evaluation of Retrieval Augmented Generation}, 
      author={Shahul Es and Jithin James and Luis Espinosa-Anke and Steven Schockaert},
      year={2025},
      eprint={2309.15217},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2309.15217}, 
}