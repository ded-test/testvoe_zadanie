SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV ?= .venv
PYTHON ?= python3
PY := $(VENV)/bin/python
COMPOSE ?= docker compose

.PHONY: install env up dev stop down ps logs test test-local migrate migrate-local revision psql

install: ## создать .venv и поставить зависимости
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

env: ## создать .env из .env.example (если его нет)
	@test -f .env || (cp .env.example .env && echo "создан .env из .env.example")

up: env ## поднять всё в докере: db + миграции + service + alpha + beta
	$(COMPOSE) up --build -d
	$(COMPOSE) ps

dev: env ## запустить локально: postgres в докере, приложение на хосте
	bash scripts/dev.sh

stop: ## остановить контейнеры (том с базой сохраняется)
	$(COMPOSE) stop

down: ## погасить всё и снести том с базой
	$(COMPOSE) down -v --remove-orphans

ps: ## статус контейнеров
	$(COMPOSE) ps

logs: ## логи в докере, по умолчанию service (make logs S=alpha)
	$(COMPOSE) logs -f $(or $(S),service)

test: ## тесты в докере, вывод прямо в терминал
	$(COMPOSE) up -d --build
	$(COMPOSE) --profile tools run --rm tests

test-local: env ## тесты с хоста (сервис должен быть запущен - make dev или make up)
	$(COMPOSE) up -d db
	$(PY) -m alembic upgrade head
	$(PY) -m pytest -q

migrate: ## накатить миграции в докере
	$(COMPOSE) run --rm migrate

migrate-local: env ## накатить миграции с хоста (нужна поднятая db)
	$(COMPOSE) up -d db
	$(PY) -m alembic upgrade head

revision: ## новая миграция: make revision m="что поменял"
	@test -n "$(m)" || (echo 'usage: make revision m="что поменял"' >&2; exit 1)
	$(COMPOSE) run --rm migrate alembic revision --autogenerate -m "$(m)"

psql: ## psql в базу из докера
	$(COMPOSE) exec db psql -U app -d app
