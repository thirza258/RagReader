# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Dependencies ─────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# ── NLTK corpora ─────────────────────────────────────────────────────────────
# SparseRAG reads NLTK's English stopword list in its constructor and tokenizes
# with punkt. sparse_rag.py tries to download both on import, but that download
# is quiet: with no network (or a blocked one) it does nothing and the next
# SparseRAG(...) raises LookupError, taking sparse and hybrid retrieval with it.
# Baking the corpora in makes the image self-contained.
ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -m nltk.downloader -d ${NLTK_DATA} punkt punkt_tab stopwords \
    && python -c "from nltk.corpus import stopwords; from nltk.tokenize import word_tokenize; \
assert stopwords.words('english'); print(word_tokenize('corpora are present'))"

COPY . .

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
