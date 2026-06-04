import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi
from rouge_score import rouge_scorer
from ai_handler.llm import OpenAILLM, ClaudeLLM, GeminiLLM
from typing import Any

from ai_handler.llm import MistralLLM

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
    
def evaluate_response(response, ground_truth_response, chunks=None):
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
        scores = scorer.score(ground_truth_response, response)
        faithfulness_prompt = build_faithfulness_prompt(response, "\n".join(chunks) if chunks else "")
        relevance_prompt = build_relevance_prompt(response, "\n".join(chunks) if chunks else "")
        coverage_prompt = build_coverage_prompt(response, "\n".join(chunks) if chunks else "")
        
        mistral = MistralLLM()
        faithfulness_score = mistral._call_api(faithfulness_prompt)
        relevance_score = mistral._call_api(relevance_prompt)
        coverage_score = mistral._call_api(coverage_prompt)
        
        return {
            "rougeL_precision": scores['rougeL'].precision,
            "rougeL_recall": scores['rougeL'].recall,
            "rougeL_f1": scores['rougeL'].fmeasure,
            "faithfulness": faithfulness_score,
            "answer_relevance": relevance_score,
            "answer_coverage": coverage_score
        }
    except Exception as e:
        print(f"Error in evaluate_response: {e}")
        return {
            "rougeL_precision": 0.0,
            "rougeL_recall": 0.0,
            "rougeL_f1": 0.0,
            "faithfulness": 0.0,
            "answer_relevance": 0.0,
            "answer_coverage": 0.0
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
