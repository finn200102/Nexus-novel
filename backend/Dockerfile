FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cargo curl libpq-dev pkg-config libssl-dev rustc \
    && rm -rf /var/lib/apt/lists/*

COPY backend ./backend
COPY rustbindings ./rustbindings

WORKDIR /app/backend

RUN pip install --no-cache-dir uv \
    && uv sync --locked --no-dev \
    && rm -f /app/rustbindings/Cargo.lock \
    && cd /app/rustbindings/pybindings \
    && VIRTUAL_ENV=/app/backend/.venv /app/backend/.venv/bin/maturin develop --release

CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
