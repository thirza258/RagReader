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

COPY . .

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
