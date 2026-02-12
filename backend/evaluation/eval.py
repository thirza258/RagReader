import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi
from bert_score import score

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