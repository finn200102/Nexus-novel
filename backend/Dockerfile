FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal

COPY backend ./backend
COPY rustbindings ./rustbindings

WORKDIR /app/backend

RUN pip install --no-cache-dir uv \
    && uv sync --locked --no-dev \
    && cd /app/rustbindings/pybindings \
    && VIRTUAL_ENV=/app/backend/.venv /app/backend/.venv/bin/maturin develop --release

CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
