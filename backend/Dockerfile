# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Torch ────────────────────────────────────────────────────────────────────
# sentence-transformers / bert-score drag torch in. Installing it here, in its
# own layer, means editing requirements.txt never re-downloads it.
#
# We take the wheel from PyTorch's CPU index rather than a pytorch/pytorch base
# image: every tag that registry publishes is CUDA (3-14 GB), and nothing here
# runs on a GPU. Same torch version, ~200 MB instead of ~7 GB of nvidia-* wheels.
ARG TORCH_VERSION=2.13.0
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch==${TORCH_VERSION} --index-url https://download.pytorch.org/whl/cpu

# Keep the transitive deps below from quietly replacing it with the CUDA build.
RUN printf 'torch==%s\n' "${TORCH_VERSION}" > /etc/pip-constraints.txt
ENV PIP_CONSTRAINT=/etc/pip-constraints.txt

# ── Everything else ──────────────────────────────────────────────────────────
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Fail the build loudly if a CUDA torch slipped back in.
RUN python -c "import torch; assert torch.version.cuda is None, f'CUDA torch installed: {torch.__version__}'; print('torch', torch.__version__)"

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
