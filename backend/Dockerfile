FROM rust:1.88-bookworm AS rust-toolchain

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CARGO_HOME=/root/.cargo
ENV RUSTUP_HOME=/usr/local/rustup
ENV PATH="/usr/local/cargo/bin:${PATH}"
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
ENV CARGO_NET_RETRY=10
ENV CARGO_HTTP_TIMEOUT=120
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./backend/

WORKDIR /app/backend

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    pip install --no-cache-dir uv \
    && uv sync --locked --no-dev

# Keep the expensive Rust extension layer independent from Python application
# source changes. Backend edits can now reuse this layer and only rebuild the
# final source-copy layer.
COPY rustbindings ./rustbindings

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    cd /app/rustbindings/pybindings \
    && VIRTUAL_ENV=/app/backend/.venv /app/backend/.venv/bin/maturin develop --release

COPY backend ./backend

CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
