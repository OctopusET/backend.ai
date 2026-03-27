.PHONY: setup up down restart logs ps clean model

COMPOSE := docker compose
BACKENDAI_HOME ?= $(or $(XDG_DATA_HOME),$(HOME)/.local/share)/backendai

## First-time setup: DB schema, fixtures, SSL certs, krunner
setup:
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
	rm -rf $(BACKENDAI_HOME)

## Download and setup model for TT inference
## Usage: make model MODEL=meta-llama/Llama-3.1-8B-Instruct
model:
	MODEL_NAME=$${MODEL:-meta-llama/Llama-3.1-8B-Instruct} \
	CACHE_DIR=$(BACKENDAI_HOME)/cache/tt \
	./scripts/setup-tt-model.sh
