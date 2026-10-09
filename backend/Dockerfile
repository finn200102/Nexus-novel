FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# kepubify (MIT, github.com/pgaskin/kepubify) converts the generated EPUBs to
# KEPUB for Kobo sync, which gives the device precise reading positions.
# Pinned release binaries, checked by SHA-256; other architectures fall back
# to plain EPUB.
ARG KEPUBIFY_VERSION=4.0.4
ARG TARGETARCH
RUN case "${TARGETARCH:-amd64}" in \
        amd64) file=kepubify-linux-64bit; sum=37d7628d26c5c906f607f24b36f781f306075e7073a6fe7820a751bb60431fc5 ;; \
        arm64) file=kepubify-linux-arm64; sum=5a15b8f6f6a96216c69330601bca29638cfee50f7bf48712795cff88ae2d03a3 ;; \
        *) file= ;; \
    esac \
    && if [ -n "$file" ]; then \
        curl -fsSL -o /usr/local/bin/kepubify "https://github.com/pgaskin/kepubify/releases/download/v${KEPUBIFY_VERSION}/${file}" \
        && echo "${sum}  /usr/local/bin/kepubify" | sha256sum -c - \
        && chmod 0755 /usr/local/bin/kepubify \
        && mkdir -p /usr/share/licenses/kepubify \
        && curl -fsSL -o /usr/share/licenses/kepubify/LICENSE "https://raw.githubusercontent.com/pgaskin/kepubify/v${KEPUBIFY_VERSION}/LICENSE"; \
    fi

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
