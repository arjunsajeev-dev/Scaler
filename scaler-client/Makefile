COMPOSE := docker compose -f deploy/compose.yaml

.PHONY: build up down test start stop

build:
	$(COMPOSE) build demo alpha beta

up:
	$(COMPOSE) up -d redis traefik docker-socket-proxy

down:
	$(COMPOSE) down

test:
	pytest

start:
	scaler start

stop:
	scaler stop
