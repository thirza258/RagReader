import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi
from bert_score import score
from rouge_score import rouge_scorer
from ai_handler.llm import OpenAILLM, ClaudeLLM, GeminiLLM
from typing import Any

def calculate_retrieval_score(query, chunks, method='dense', model=None):
    """
    Menghitung skor retrieval antara query dan chunks yang diambil.
    
    Args:
        query (str): Input query user.
        chunks (list): List string berisi chunk/dokumen yang diambil.
        method (str): 'dense' (Cosine), 'sparse' (BM25), atau 'hybrid' (RRF).
        model (object): Model SentenceTransformer (diperlukan untuk dense/hybrid).
    
    Returns:
        float/dict: Skor rata-rata atau dictionary skor (tergantung method).
    """
    
    scores = {}

    if method in ['dense', 'hybrid']:
        if model is None:
            model = SentenceTransformer('all-MiniLM-L6-v2') 
            
        query_emb = model.encode([query])
        chunk_embs = model.encode(chunks)
        
        dense_scores = cosine_similarity(query_emb, chunk_embs)[0]
        scores['dense_avg'] = np.mean(dense_scores)
        scores['dense_list'] = dense_scores.tolist()

    if method in ['sparse', 'hybrid']:
        tokenized_corpus = [chunk.split(" ") for chunk in chunks]
        tokenized_query = query.split(" ")
        
        bm25 = BM25Okapi(tokenized_corpus)
        sparse_scores = bm25.get_scores(tokenized_query)
        scores['sparse_avg'] = np.mean(sparse_scores)
        scores['sparse_list'] = sparse_scores.tolist()

    if method == 'hybrid':
        k = 60
        fused_scores = {}
        
        dense_ranks = np.argsort(scores['dense_list'])[::-1]
        sparse_ranks = np.argsort(scores['sparse_list'])[::-1]
        
        rrf_scores = []
        for i in range(len(chunks)):
            rank_dense = np.where(dense_ranks == i)[0][0] + 1
            rank_sparse = np.where(sparse_ranks == i)[0][0] + 1
            
            rrf_val = (1 / (k + rank_dense)) + (1 / (k + rank_sparse))
            rrf_scores.append(rrf_val)
            
        scores['rrf_avg'] = np.mean(rrf_scores)
        scores['rrf_list'] = rrf_scores
        return scores

    return scores.get(f"{method}_avg", 0.0)

def calculate_faithfulness(response, chunks):
    """
    Menghitung Faithfulness menggunakan BERTScore.
    Membandingkan kesamaan semantik antara Response AI dan Context (gabungan chunks).
    
    Args:
        response (str): Jawaban dari AI.
        chunks (list): List string berisi chunk yang diambil (context).
        
    Returns:
        dict: Precision, Recall, dan F1 Score.
    """
    context_text = " ".join(chunks)
    

    P, R, F1 = score([response], [context_text], lang='en', verbose=False)
    
    return {
        "precision": P.item(),
        "recall": R.item(),    
        "f1": F1.item()        
    }
    
def calculate_answer_relevance(query, response, model=None):
    """
    Menghitung relevansi jawaban terhadap pertanyaan (Answer Relevance).
    Menggunakan Cosine Similarity antar embedding.
    
    Args:
        query (str): Pertanyaan user.
        response (str): Jawaban AI.
        model (object): Model SentenceTransformer.
        
    Returns:
        float: Skor kemiripan (0.0 hingga 1.0).
    """
    if model is None:
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
    # Encode Query dan Response
    embeddings = model.encode([query, response])
    
    # Hitung Cosine Similarity antara keduanya
    similarity_score = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
    
    return float(similarity_score)

def calculate_recall_K(chunks, ground_truth_chunks):
    """
    Menghitung Recall@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: Recall@K (0.0 hingga 1.0).
    """
    try:
        if not ground_truth_chunks:
            return 0.0
        
        retrieved_set = set(chunks)
        relevant_set = set(ground_truth_chunks)
        
        true_positives = len(retrieved_set.intersection(relevant_set))
        recall_k = true_positives / len(relevant_set)
        
        return recall_k
    except Exception as e:
        print(f"Error in calculate_recall_K: {e}")
        return 0.0

def calculate_precision_K(chunks, ground_truth_chunks):
    """
    Menghitung Precision@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: Precision@K (0.0 hingga 1.0).
    """
    try:
        if not chunks:
            return 0.0
        
        retrieved_set = set(chunks)
        relevant_set = set(ground_truth_chunks)
        
        true_positives = len(retrieved_set.intersection(relevant_set))
        precision_k = true_positives / len(retrieved_set)
        
        return precision_k
    except Exception as e:
        print(f"Error in calculate_precision_K: {e}")
        return 0.0

def calculate_f1_K(chunks, ground_truth_chunks):
    """
    Menghitung F1@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: F1@K (0.0 hingga 1.0).
    """
    try:
        precision_k = calculate_precision_K(chunks, ground_truth_chunks)
        recall_k = calculate_recall_K(chunks, ground_truth_chunks)
        
        if precision_k + recall_k == 0:
            return 0.0
        
        f1_k = 2 * (precision_k * recall_k) / (precision_k + recall_k)
        
        return f1_k
    except Exception as e:
        print(f"Error in calculate_f1_K: {e}")
        return 0.0

def evaluate_chunks(chunks, ground_truth_chunks):
    """
    Evaluasi retrieval dengan menghitung Precision@K, Recall@K, dan F1@K.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        dict: Dictionary berisi skor Precision@K, Recall@K, dan F1@
    """
    try:
        precision_k = calculate_precision_K(chunks, ground_truth_chunks)
        recall_k = calculate_recall_K(chunks, ground_truth_chunks)
        f1_k = calculate_f1_K(chunks, ground_truth_chunks)
        
        return {
            "precision_k": precision_k,
            "recall_k": recall_k,
            "f1_k": f1_k
        }
    except Exception as e:
        print(f"Error in evaluate_chunks: {e}")
        return {
            "precision_k": 0.0,
            "recall_k": 0.0,
            "f1_k": 0.0
        }
    
def evaluate_response(response, ground_truth_response):
    """
    Evaluasi jawaban dengan menghitung ROUGE-L Score.
    
    Args:
        response (str): Jawaban dari AI.
        ground_truth_response (str): Jawaban yang benar (ground truth).
        
    Returns:
        dict: Dictionary berisi skor ROUGE-L Precision, Recall, dan F1.
    """
    try:
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        print("evaluate_response:", response, ground_truth_response)
        scores = scorer.score(ground_truth_response, response)
        
        # bert_score = score([response], [ground_truth_response], lang='en', verbose=False, device="cuda")
        
        return {
            "rougeL_precision": scores['rougeL'].precision,
            "rougeL_recall": scores['rougeL'].recall,
            "rougeL_f1": scores['rougeL'].fmeasure,
            "bert_precision": 0.0,
            "bert_recall": 0.0,
            "bert_f1": 0.0
        }
    except Exception as e:
        print(f"Error in evaluate_response: {e}")
        return {
            "rougeL_precision": 0.0,
            "rougeL_recall": 0.0,
            "rougeL_f1": 0.0,
            "bert_precision": 0.0,
            "bert_recall": 0.0,
            "bert_f1": 0.0
        }

def build_relevance_prompt(response: str, chunks_text: str) -> str:
    return f"""You are an expert RAG evaluator. Score ONLY the Relevance dimension.

            Relevance: How relevant the RESPONSE is to the retrieved CHUNKS.

            RESPONSE:
            {response}

            CANDIDATE CHUNKS:
            {chunks_text}

            Scoring Guide (1–5):
            1 = Very poor  2 = Poor  3 = Acceptable  4 = Good  5 = Excellent

            Output strict JSON only:
            {{"relevance": <score>, "justification": "<reason>"}}"""


def build_faithfulness_prompt(response: str, chunks_text: str) -> str:
    return f"""You are an expert RAG evaluator. Score ONLY the Faithfulness dimension.

            Faithfulness: Whether the RESPONSE is factually supported by the CHUNKS.
            Penalise any claim not grounded in the chunks (hallucination).

            RESPONSE:
            {response}

            CANDIDATE CHUNKS:
            {chunks_text}

            Scoring Guide (1–5):
            1 = Very poor  2 = Poor  3 = Acceptable  4 = Good  5 = Excellent

            Output strict JSON only:
            {{"faithfulness": <score>, "justification": "<reason>"}}"""


def build_coverage_prompt(response: str, chunks_text: str) -> str:
    return f"""You are an expert RAG evaluator. Score ONLY the Coverage dimension.

            Coverage: How well the RESPONSE covers the important information in the CHUNKS.
            Penalise if key information from the chunks is missing.

            RESPONSE:
            {response}

            CANDIDATE CHUNKS:
            {chunks_text}

            Scoring Guide (1–5):
            1 = Very poor  2 = Poor  3 = Acceptable  4 = Good  5 = Excellent

            Output strict JSON only:
            {{"coverage": <score>, "justification": "<reason>"}}"""


def build_fluency_prompt(response: str, chunks_text: str) -> str:
    return f"""You are an expert RAG evaluator. Score ONLY the Fluency dimension.

            Fluency: Grammatical correctness and readability of the RESPONSE.

            RESPONSE:
            {response}

            CANDIDATE CHUNKS:
            {chunks_text}

            Scoring Guide (1–5):
            1 = Very poor  2 = Poor  3 = Acceptable  4 = Good  5 = Excellent

            Output strict JSON only:
            {{"fluency": <score>, "justification": "<reason>"}}"""


PROMPT_BUILDERS = {
    "relevance":    build_relevance_prompt,
    "faithfulness": build_faithfulness_prompt,
    "coverage":     build_coverage_prompt,
    "fluency":      build_fluency_prompt,
}


def evaluate_with_llm(
    llm: OpenAILLM | GeminiLLM | ClaudeLLM,
    prompt: str,
) -> str | dict:
    """Send a single prompt to one LLM instance and return raw output."""
    try:
        return llm.generate(prompt)
    except Exception as e:
        return {"error": str(e)}

def llm_as_a_judge(
    response: str,
    retrieved_chunks: list[str],
    llm_list: list[tuple[str, OpenAILLM | GeminiLLM | ClaudeLLM]],
    criteria: list[str] | None = None,
) -> dict[str, Any]:
    """
    LLM-as-a-judge: evaluate a RAG response using one or more LLMs.

    Args:
        response:         The AI answer to evaluate.
        retrieved_chunks: Context chunks used to generate the answer.
        llm_list:         List of (name, llm_instance) pairs, e.g.
                            [("openai",  OpenAILLM(...)),
                             ("gemini",  GeminiLLM(...)),
                             ("claude",  ClaudeLLM(...))]
        criteria:         Subset of dimensions to evaluate.
                          Defaults to all four: relevance, faithfulness,
                          coverage, fluency.

    Returns:
        {
          "openai":  {"relevance": "...", "faithfulness": "...", ...},
          "gemini":  {"relevance": "...", ...},
          "claude":  {"relevance": "...", ...},
        }
    """
    if criteria is None:
        criteria = list(PROMPT_BUILDERS.keys())

    chunks_text = "\n".join(
        f"[Chunk {i}] {chunk}" for i, chunk in enumerate(retrieved_chunks)
    )

    results: dict[str, Any] = {}

    for llm_name, llm_instance in llm_list:
        dimension_results: dict[str, Any] = {}

        for criterion in criteria:
            if criterion not in PROMPT_BUILDERS:
                dimension_results[criterion] = {
                    "error": f"Unknown criterion '{criterion}'"
                }
                continue

            prompt = PROMPT_BUILDERS[criterion](response, chunks_text)
            dimension_results[criterion] = evaluate_with_llm(llm_instance, prompt)

        results[llm_name] = dimension_results

    return results