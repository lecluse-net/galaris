# Commands
help:
	@echo "Available commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Use 'make <command>' with one of the commands listed above."
.PHONY: help



start: ## Start the application containers
	docker compose up -d --build --wait --wait-timeout 30
.PHONY: start



prepare-delete: ## Return bind-mounted data ownership to the harness manager
	docker compose exec -T --user 0:0 agent /bin/sh -c 'chown -R "$${HERMES_UID}:$${HERMES_GID}" /opt/data' || true
.PHONY: prepare-delete



stop: prepare-delete ## Stop the application containers
	docker compose down
.PHONY: stop



restart:
	docker compose down
	@sleep 2
	docker compose up -d --build --wait --wait-timeout 60
.PHONY: restart



update: ## Update Hermes (pull image, remove hermes-bin, restart)
	docker compose pull
	docker compose down
	@docker volume rm "$$(basename "$$(pwd)")_hermes-bin" >/dev/null 2>&1 || true
	@sleep 2
	docker compose up -d --build --wait --wait-timeout 60
.PHONY: update


hermes: ## Start the Hermes CLI
	docker compose exec agent /opt/hermes/.venv/bin/hermes
.PHONY: hermes


logs: ## Show logs
	docker compose logs -f
.PHONY: logs


clean: ## Clear Docker caches
	@echo "==========================================================="
	@echo "  /!\ ATTENTION: DESTRUCTIVE Docker cleanup operation /!\  "
	@echo "==========================================================="
	@echo "This operation will remove all of the following objects from your Docker instance:"
	@echo "  - All unused containers"
	@echo "  - All unused networks"
	@echo "  - All unused Docker images"
	@echo "  - All unused volumes"
	@echo "  - All build caches"
	@echo ""
	@echo "THIS ACTION CANNOT BE UNDONE!"
	@echo ""
	@read -p "Confirm the full cleanup? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		docker compose down -v; \
		docker system prune -af --volumes; \
		echo "Cleanup completed"; \
	else \
		echo "Cleanup cancelled"; \
	fi
.PHONY: clean
