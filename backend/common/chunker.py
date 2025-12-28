import re
import numpy as np
from typing import List, Literal
from sklearn.metrics.pairwise import cosine_similarity

class DocumentChunker:
    def __init__(self, 
                 strategy: Literal["fixed", "paragraph", "semantic"] = "paragraph",
                 chunk_size: int = 500, 
                 overlap: int = 50,
                 embedding_client=None):
        """
        Args:
            strategy: 'fixed', 'paragraph', or 'semantic'.
            chunk_size: Max chars for fixed/paragraph, or max token estimate for semantic.
            overlap: Overlap in characters (only for fixed strategy).
            embedding_client: Required ONLY for 'semantic' strategy (to calculate distances).
        """
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.client = embedding_client

    def chunk(self, text: str) -> List[str]:
        if self.strategy == "fixed":
            return self._chunk_fixed(text)
        elif self.strategy == "paragraph":
            return self._chunk_paragraph(text)
        elif self.strategy == "semantic":
            return self._chunk_semantic(text)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    # --- Strategy 1: Fixed / Random Window ---
    def _chunk_fixed(self, text: str) -> List[str]:
        """
        Blindly cuts text into chunks of size N with overlap.
        Pro: Consistent size.
        Con: Cuts sentences and words in half.
        """
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            # Move forward by chunk_size minus overlap
            start += (self.chunk_size - self.overlap)
        
        return chunks

    def _chunk_paragraph(self, text: str) -> List[str]:
        """
        Splits by double newlines. Merges small paragraphs until they hit chunk_size.
        Pro: Respects document structure.
        Con: Paragraphs can be huge or tiny.
        """
        # Split by double newlines (standard paragraph break)
        raw_paras = text.split('\n\n')
        raw_paras = [p.strip() for p in raw_paras if p.strip()]
        
        chunks = []
        current_chunk = ""

        for para in raw_paras:
            # If adding this paragraph exceeds size, save current and start new
            if len(current_chunk) + len(para) > self.chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para
            else:
                # Add to current chunk with a spacer
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
        
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    # --- Strategy 3: Semantic (Sentence Similarity) ---
    def _chunk_semantic(self, text: str) -> List[str]:
        """
        Advanced: Splits by sentences. Embeds every sentence.
        If sentence A and sentence B are dissimilar (cosine distance), 
        we break the chunk there (Topic Shift).
        """
        if not self.client:
            raise ValueError("Semantic chunking requires an embedding_client (DenseRAG instance or OpenAI client).")

        # 1. Split text into sentences (Simple regex for demo)
        sentences = re.split(r'(?<=[.?!])\s+', text)
        sentences = [s for s in sentences if s.strip()]
        
        if not sentences:
            return []

        # 2. Embed ALL sentences individually
        # Note: This is API heavy (1 call per sentence). Batch this in production.
        try:
            embeddings_resp = self.client.embeddings.create(
                input=sentences,
                model="text-embedding-3-small"
            )
            vecs = [d.embedding for d in embeddings_resp.data]
        except Exception as e:
            print(f"Embedding failed: {e}")
            return sentences # Fallback to sentence list

        # 3. Calculate similarity between adjacent sentences (i and i+1)
        distances = []
        for i in range(len(vecs) - 1):
            sim = cosine_similarity([vecs[i]], [vecs[i+1]])[0][0]
            distances.append(sim)

        # 4. Group sentences based on similarity Threshold
        # If similarity < 0.5 (for example), it's a topic change.
        threshold = 0.5 
        chunks = []
        current_group = [sentences[0]]

        for i, dist in enumerate(distances):
            if dist > threshold:
                # Sentences are similar -> Group them
                current_group.append(sentences[i+1])
            else:
                # Sentences are different -> Break chunk
                chunks.append(" ".join(current_group))
                current_group = [sentences[i+1]]

        if current_group:
            chunks.append(" ".join(current_group))

        return chunks