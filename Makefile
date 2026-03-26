.PHONY: init up down clean model logs

COMPOSE := docker compose
MARKER := .init-done
BACKENDAI_HOME ?= $(or $(XDG_DATA_HOME),$(HOME)/.local/share)/backendai

## Initialize DB, etcd, register images and presets
init:
	mkdir -p $(BACKENDAI_HOME)/scratches $(BACKENDAI_HOME)/var $(BACKENDAI_HOME)/vfolders/volume1 $(BACKENDAI_HOME)/cache/tt $(BACKENDAI_HOME)/runner
	mkdir -p configs/storage-proxy/ssl
	@if [ ! -f configs/storage-proxy/ssl/manager-api.cert.pem ]; then \
		openssl req -x509 -newkey rsa:2048 \
			-keyout configs/storage-proxy/ssl/manager-api.key.pem \
			-out configs/storage-proxy/ssl/manager-api.cert.pem \
			-days 365 -nodes -subj '/CN=localhost' 2>/dev/null; \
		echo "SSL certs generated"; \
	fi
	$(COMPOSE) up -d halfstack-db halfstack-redis halfstack-etcd
	@echo "Waiting for halfstack..."
	@sleep 10
	$(COMPOSE) --profile init up --build --force-recreate
	@echo "Setting up AppProxy DB..."
	$(COMPOSE) --profile init-appproxy up --build --force-recreate
	@echo "Extracting krunner binaries..."
	$(COMPOSE) run --rm krunner-setup
	@touch $(MARKER)

## Start all services
up: $(MARKER)
	$(COMPOSE) up -d halfstack-db halfstack-redis halfstack-etcd
	@sleep 5
	$(COMPOSE) --profile services up -d --build
	@echo ""
	@echo "Backend.AI is running!"
	@echo "  WebUI: http://$$(hostname -I | awk '{print $$1}'):8090"
	@echo "  API:   http://$$(hostname -I | awk '{print $$1}'):8081"

$(MARKER):
	$(MAKE) init

## Stop all services (keep data)
down:
	$(COMPOSE) --profile services down
	$(COMPOSE) down

## Stop and delete all data
clean: down
	$(COMPOSE) down -v
	rm -rf $(BACKENDAI_HOME)
	rm -f $(MARKER)

## Download and setup model for inference
## Usage: make model MODEL=meta-llama/Llama-3.1-8B-Instruct
model:
	MODEL_NAME=$${MODEL:-meta-llama/Llama-3.1-8B-Instruct} \
	CACHE_DIR=$(BACKENDAI_HOME)/cache/tt \
	./scripts/setup-tt-model.sh

## View logs
logs:
	$(COMPOSE) --profile services logs -f
