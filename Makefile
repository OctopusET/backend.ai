.PHONY: setup init up down logs clean model

COMPOSE := docker compose

## One-time setup: create host directories and SSL certs
setup:
	sudo mkdir -p /opt/backendai && sudo chown $$(id -u):$$(id -g) /opt/backendai
	mkdir -p /opt/backendai/{scratches,var,vfolders/volume1,cache/tt,runner}
	mkdir -p configs/storage-proxy/ssl
	@if [ ! -f configs/storage-proxy/ssl/manager-api.cert.pem ]; then \
		openssl req -x509 -newkey rsa:2048 \
			-keyout configs/storage-proxy/ssl/manager-api.key.pem \
			-out configs/storage-proxy/ssl/manager-api.cert.pem \
			-days 365 -nodes -subj '/CN=localhost' 2>/dev/null; \
		echo "SSL certs generated"; \
	fi

## Initialize DB, etcd, register images and presets
init: setup
	$(COMPOSE) up -d halfstack-db halfstack-redis halfstack-etcd
	@echo "Waiting for halfstack..."
	@sleep 10
	$(COMPOSE) --profile init up --build
	@echo "Extracting krunner binaries..."
	$(COMPOSE) run --rm krunner-setup

## Start all services
up:
	$(COMPOSE) up -d halfstack-db halfstack-redis halfstack-etcd
	@sleep 5
	$(COMPOSE) --profile services up -d --build

## Stop all services (keep data)
down:
	$(COMPOSE) --profile services down
	$(COMPOSE) down

## Stop and delete all data
clean:
	$(COMPOSE) --profile services --profile init down -v
	$(COMPOSE) down -v
	sudo rm -rf /opt/backendai

## Download and setup model for inference
## Usage: make model MODEL=meta-llama/Llama-3.1-8B-Instruct
model:
	MODEL_NAME=$${MODEL:-meta-llama/Llama-3.1-8B-Instruct} \
	CACHE_DIR=/opt/backendai/cache/tt \
	./scripts/setup-tt-model.sh

## View logs
logs:
	$(COMPOSE) --profile services logs -f

## Full deploy from scratch
deploy: init up
	@echo ""
	@echo "Backend.AI is running!"
	@echo "  WebUI: http://$$(hostname -I | awk '{print $$1}'):8090"
	@echo "  API:   http://$$(hostname -I | awk '{print $$1}'):8081"
	@echo "  Login: admin@lablup.com / wJalrXUt"
