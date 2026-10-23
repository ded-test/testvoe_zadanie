#!/usr/bin/env bash
# Локальный запуск: docker только для postgres, приложение — процессами на хосте.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY=".venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "!! нет .venv — сначала: make install" >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "==> создан .env из .env.example"
fi

if ! docker info >/dev/null 2>&1; then
    echo "!! docker не запущен (нужен для postgres)" >&2
    exit 1
fi

echo "==> postgres в docker (localhost:5433)"
docker compose up -d db

echo -n "==> ждём postgres "
for _ in $(seq 1 60); do
    if docker compose exec -T db pg_isready -U app -d app >/dev/null 2>&1; then
        echo "ok"
        break
    fi
    echo -n "."
    sleep 1
done

if ! docker compose exec -T db pg_isready -U app -d app >/dev/null 2>&1; then
    echo
    echo "!! postgres не поднялся: docker compose logs db" >&2
    exit 1
fi

echo "==> alembic upgrade head"
"$PY" -m alembic upgrade head

# Освобождаем 8000/8001/8002, если стек уже был поднят в докере.
docker compose stop service alpha beta >/dev/null 2>&1 || true

pids=()
cleanup() {
    trap - EXIT INT TERM
    echo
    echo "==> останавливаю локальные процессы"
    if ((${#pids[@]})); then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
    echo "==> postgres оставлен запущенным (остановить: make stop, снести том: make down)"
}
trap cleanup EXIT INT TERM

echo "==> alpha :8001 | beta :8002 | service :8000  (Ctrl+C — остановить всё)"
echo

PROVIDER_NAME=alpha PYTHONUNBUFFERED=1 "$PY" -m uvicorn providers.main:app \
    --host 127.0.0.1 --port 8001 --log-level info &
pids+=($!)

PROVIDER_NAME=beta PYTHONUNBUFFERED=1 "$PY" -m uvicorn providers.main:app \
    --host 127.0.0.1 --port 8002 --log-level info &
pids+=($!)

PYTHONUNBUFFERED=1 "$PY" -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --log-level info --reload --reload-dir app &
pids+=($!)

wait
