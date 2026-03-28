.PHONY: setup up down restart logs ps clean model

COMPOSE := docker compose
BA_HOME ?= $(or $(XDG_DATA_HOME),$(HOME)/.local/share)/backendai

## First-time setup: DB schema, fixtures, SSL certs, krunner
setup:
	mkdir -p $(BA_HOME)/scratches $(BA_HOME)/var/commit $(BA_HOME)/vfolders/volume1 $(BA_HOME)/cache/tt $(BA_HOME)/runner
	$(COMPOSE) --profile init up --build -d
	$(COMPOSE) wait init init-appproxy krunner-setup

## Start all services
up:
	$(COMPOSE) --profile services up -d --build
	@echo ""
	@echo "Backend.AI is running!"
	@echo "  WebUI: http://$$(hostname -I | awk '{print $$1}'):8090"
	@echo "  API:   http://$$(hostname -I | awk '{print $$1}'):8081"

## Stop all services (keep data)
down:
	$(COMPOSE) --profile services down
	$(COMPOSE) down

## Restart all services
restart: down up

## Tail service logs
logs:
	$(COMPOSE) --profile services logs -f

## Show running services
ps:
	$(COMPOSE) --profile services ps

## Stop and delete all data
clean: down
	$(COMPOSE) down -v
	rm -rf $(BA_HOME)

## Download and setup model for TT inference
## Usage: make model MODEL=meta-llama/Llama-3.1-8B-Instruct
model:
	@command -v hf >/dev/null 2>&1 || { command -v uv >/dev/null 2>&1 && uv tool install huggingface_hub || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }; }
	MODEL_NAME=$${MODEL:-meta-llama/Llama-3.1-8B-Instruct} \
	CACHE_DIR=$(BA_HOME)/cache/tt \
	./scripts/setup-tt-model.sh
