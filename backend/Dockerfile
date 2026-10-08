FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./backend/

WORKDIR /app/backend

ARG UV_VERSION=0.8.14

# Keep the installer reproducible while allowing subsequent dependency-layer
# rebuilds to reuse the downloaded uv wheel and resolved package artifacts.
# The cache is optional: clean builders still work by fetching the pinned
# version from PyPI, and no locally named project image is required.
RUN --mount=type=cache,id=nexus-novel-pip,target=/root/.cache/pip,sharing=locked \
    --mount=type=cache,id=nexus-novel-uv,target=/root/.cache/uv,sharing=locked \
    python -m pip install --disable-pip-version-check --no-compile "uv==${UV_VERSION}" \
    && uv sync --locked --no-dev

COPY backend /app/backend

CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
