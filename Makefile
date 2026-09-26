# Preserve an explicit shell override across the defaults loaded from .env.
GALARIS_APP_ENV_ORIGIN := $(origin APP_ENV)
GALARIS_REQUESTED_APP_ENV := $(APP_ENV)
-include .env
ifeq ($(GALARIS_APP_ENV_ORIGIN),environment)
APP_ENV := $(GALARIS_REQUESTED_APP_ENV)
endif
APP_ENV ?= prod
export APP_ENV
# VERSION is passed as an environment value, never interpolated into shell code.
export VERSION

# Application name, overridable through .env and used for container names.
APP_NAME ?= galaris
APP_HOST ?= http://localhost:8484
WEBRTC_TURN_MODE ?= embedded
POSTGRES_MODE ?= embedded
override GALARIS_BUILD_VERSION := $(shell git describe --tags --exact-match 2>/dev/null || git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || printf unknown)
export GALARIS_BUILD_VERSION

# Base compose command configuration
COMPOSE_FILES := -f compose.yaml
COMPOSE_STOP_FILES := -f compose.yaml -f compose.turn.yaml

ifeq ($(POSTGRES_MODE),embedded)
	COMPOSE_FILES += -f compose.postgres.yaml
	COMPOSE_STOP_FILES += -f compose.postgres.yaml
else ifneq ($(POSTGRES_MODE),external)
	$(error POSTGRES_MODE must be 'embedded' or 'external')
endif

ifeq ($(WEBRTC_TURN_MODE),embedded)
	COMPOSE_FILES += -f compose.turn.yaml
endif

# Prefer the current override name, but keep existing installations operational
# until `make install` migrates their legacy file.
ifneq ($(wildcard compose.override.yaml),)
	COMPOSE_FILES += -f compose.override.yaml
	COMPOSE_STOP_FILES += -f compose.override.yaml
else ifneq ($(wildcard docker-compose.override.yaml),)
	COMPOSE_FILES += -f docker-compose.override.yaml
	COMPOSE_STOP_FILES += -f docker-compose.override.yaml
endif

# Development-specific mounts and commands must win over installation defaults.
ifeq ($(APP_ENV),dev)
	COMPOSE_FILES += -f compose.dev.yaml
	COMPOSE_STOP_FILES += -f compose.dev.yaml
endif

# Remove only disabled optional services, without loading their Compose files or
# deleting their volumes. Other project containers remain untouched.
UNUSED_SERVICES := $(if $(filter external,$(POSTGRES_MODE)),postgres) $(if $(filter embedded,$(WEBRTC_TURN_MODE)),,turn)
define STOP_UNUSED_SERVICES
	@for service in $(UNUSED_SERVICES); do \
		containers=$$(docker ps -aq --filter "label=com.docker.compose.project=$(APP_NAME)" --filter "label=com.docker.compose.service=$$service") || exit $$?; \
		if [ -n "$$containers" ]; then docker stop $$containers && docker rm $$containers || exit $$?; fi; \
	done
endef



help: ## List available commands
	@echo "Available commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Use 'make <command>' with one of the commands above."
.PHONY: help





# ====================================================================================
# Usual container administration commands
# ====================================================================================

start: ## Start existing containers; run a full update if missing or failed
	@test -f .env || { echo "Run make install, configure .env, then run make start."; exit 2; }
	@status=0; bash bin/start.sh $(COMPOSE_FILES) || status=$$?; \
	if [ "$$status" -eq 10 ]; then \
		$(MAKE) update GIT_UPDATE=0; \
	elif [ "$$status" -ne 0 ]; then \
		exit "$$status"; \
	fi
	@echo "Open $(APP_HOST) in your browser."
.PHONY: start



stop: ## Stop containers without removing them
	@echo "🛑 Stopping containers..."
	docker compose $(COMPOSE_STOP_FILES) stop
.PHONY: stop

uninstall: ## Remove containers and networks; ask before purging volumes, images and orphans
	$(STOP_UNUSED_SERVICES)
	@bash bin/uninstall.sh $(COMPOSE_STOP_FILES)
.PHONY: uninstall



restart: ## Restart the software
	@echo "🔄 Restarting containers..."
	$(MAKE) stop
	$(MAKE) start
.PHONY: restart



logs: ## Display logs in real time
	@echo "📋 Container logs (Ctrl+C to quit)..."
	docker compose $(COMPOSE_FILES) logs -f
.PHONY: logs



logs-front: ## Display frontend logs only
	@echo "📋 Frontend logs (Ctrl+C to quit)..."
	docker compose $(COMPOSE_FILES) logs -f frontend
.PHONY: logs-front



logs-back: ## Display backend logs only
	@echo "📋 Backend logs (Ctrl+C to quit)..."
	docker compose $(COMPOSE_FILES) logs -f backend
.PHONY: logs-back



logs-search: ## Display search logs only
	@echo "📋 Search logs (Ctrl+C to quit)..."
	docker compose $(COMPOSE_FILES) logs -f search
.PHONY: logs-search

check-search: ## Probe real search availability using a small public corpus (external requests)
	docker compose $(COMPOSE_FILES) exec -T backend python -m tests.manual.search $(ARGS)
.PHONY: check-search


status: ## Display container status (optional SERVICE=backend|browser-executor|...)
	docker compose $(COMPOSE_FILES) ps $(if $(strip $(SERVICE)),"$(SERVICE)")
.PHONY: status


logs-browser: ## Display isolated browser executor logs only
	docker compose $(COMPOSE_FILES) logs -f browser-executor
.PHONY: logs-browser


restart-service: ## Restart one service without rebuilding (SERVICE=backend|browser-executor|...)
	@test -n "$(strip $(SERVICE))" || { echo "Usage: make restart-service SERVICE=<service>"; exit 2; }
	docker compose $(COMPOSE_FILES) restart "$(SERVICE)"
.PHONY: restart-service


status-executor: ## Display embedded SSH executor status
	docker compose $(COMPOSE_FILES) ps ssh-executor
	docker compose $(COMPOSE_FILES) exec -T ssh-executor python3 /opt/galaris-executor/executord.py healthcheck
.PHONY: status-executor


logs-executor: ## Display embedded SSH executor logs only
	docker compose $(COMPOSE_FILES) logs -f ssh-executor
.PHONY: logs-executor


backup-executor: ## Back up executor homes, keys and user registry
	@mkdir -p backups
	@docker compose $(COMPOSE_FILES) exec -T ssh-executor tar -czf - /data/ssh-executor 2>/dev/null > backups/executor-$$(date +%Y%m%d-%H%M%S).tar.gz
	@echo "Executor backup written to backups/"
.PHONY: backup-executor



clean: ## Clean the environment (removes volumes)
	docker compose $(COMPOSE_STOP_FILES) down -v --remove-orphans
.PHONY: clean



# ====================================================================================
# Installation and initial configuration commands
# ====================================================================================

install: ## Prepare configuration; edit .env, optionally compose.override.yaml, then run make start
	@bash bin/install.sh
	@echo ""
	@echo "✅ Configuration ready."
	@echo "   1. Review .env: APP_HOST is the public address; adjust APP_ENV and TZ as needed. Keep the generated secrets."
	@echo "   2. If needed, edit compose.override.yaml for host ports, volumes and networks. Keep its frontend port consistent with APP_HOST."
	@echo "   3. Run make start to start Galaris and wait for readiness. The first start builds the images automatically."
.PHONY: install

build: ## Build current images with cache without changing containers
	@test -f .env || { echo "Run make install and configure .env first."; exit 2; }
	docker compose $(COMPOSE_FILES) build
.PHONY: build


# Both backend startup paths run DbAdmin before Uvicorn. Wait for readiness so
# startup failures also fail the update command.
update: ## Build and deploy local sources; VERSION explicitly fetches a Git tag or branch first
	@test -f .env || { echo "Run make install, configure .env, then run make update."; exit 2; }
ifneq ($(strip $(RELEASE_DIR)),)
	@test -z "$${VERSION:-}" || { echo "VERSION and RELEASE_DIR cannot be combined."; exit 2; }
	@if [ "$(APP_ENV)" = "dev" ]; then \
		echo "❌ RELEASE_DIR is reserved for prod-like environments."; \
		exit 2; \
	fi
	@bash bin/update-release.sh "$(RELEASE_DIR)" $(COMPOSE_FILES)
else
ifneq ($(if $(filter 0,$(GIT_UPDATE)),,$(strip $(VERSION))),)
	@bash bin/update-source.sh
	@# Reload the selected version's Makefile and recompute Compose/build settings.
	@$(MAKE) update GIT_UPDATE=0
else
	@bash bin/update-secrets.sh
	@bash bin/init-search-config.sh
	@echo "📚 Updating generated documentation before building images..."
	@$(MAKE) docs-prepare
ifeq ($(APP_ENV),dev)
	@echo "🔨 Rebuilding development images with cache..."
	docker compose $(COMPOSE_FILES) build
else
	@echo "📥 Pulling images..."
	docker compose $(COMPOSE_FILES) pull
	@echo "🔨 Rebuilding images with cache..."
	docker compose $(COMPOSE_FILES) build --pull
endif
	@bash bin/init-data-volume.sh $(COMPOSE_FILES)
	$(STOP_UNUSED_SERVICES)
	@# Always rerun DbAdmin and refresh the proxy's backend DNS resolution.
	docker compose $(COMPOSE_FILES) rm --stop --force backend frontend
	@echo "⏳ Waiting for the backend schema/data synchronization to complete..."
	@if ! docker compose $(COMPOSE_FILES) up -d --wait --wait-timeout 300; then \
		echo "❌ Update failed; latest service logs:"; \
		docker compose $(COMPOSE_FILES) logs --tail=200; \
		exit 1; \
	fi
	@bash bin/finalize-internal-secrets.sh $(COMPOSE_FILES)
	@echo "📚 Updating the shared documentation search index..."
	@bash bin/refresh-documentation.sh $(COMPOSE_FILES)
	@echo "✅ Update complete ($(APP_ENV))."
	@echo "Open $(APP_HOST) in your browser."
endif
endif
.PHONY: update

tests-update: ## Verify installation and development/production updates without changing the running stack
	@bash bin/test-update.sh
	@bash bin/test-update-git.sh
.PHONY: tests-update

tests-documentation: ## Verify the offline documentation runner and its real container confinement
	@bash bin/test-documentation.sh
	@bash bin/test-documentation-confinement.sh
.PHONY: tests-documentation

tests-install: ## Test a real fresh installation and stop/start with disposable volumes
	@bash bin/test-install.sh
.PHONY: tests-install



# ====================================================================================
# Development related commands
# ====================================================================================

sync-db: ## Development only: synchronize schema and reference data without restarting
	@if [ "$(APP_ENV)" != "dev" ]; then \
		echo "❌ make sync-db is reserved for APP_ENV=dev."; \
		echo "   Production schema/data synchronization is included in make update."; \
		exit 2; \
	fi
	@echo "Synchronizing database schema and datasets with DbAdmin..."
	docker compose $(COMPOSE_FILES) exec backend python -m core.dbadmin synchronize --mode development
.PHONY: sync-db

rebuild-source-memory: ## Rebuild Agent/Goal memory projections (ARGS='--all|--recreate --provider code')
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/rebuild_source_memories.py $(ARGS)'
.PHONY: rebuild-source-memory

rebuild-messenger-contacts: ## Rebuild private contact memories from the Messenger journal
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/rebuild_messenger_contacts.py'
.PHONY: rebuild-messenger-contacts

rebuild-memory-index: ## Queue semantic memory index rebuilds (ARGS='--all')
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/rebuild_memory_embeddings.py $(ARGS)'
.PHONY: rebuild-memory-index

rebuild-memory-links: ## Reconcile derived memory links (ARGS='--item-id UUID|--without-suggestions')
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/rebuild_memory_links.py $(ARGS)'
.PHONY: rebuild-memory-links



upgrade-deps-back: ## Update backend dependencies
	@echo "🔒 Updating backend dependencies..."
	docker compose $(COMPOSE_FILES) exec backend uv lock
	docker compose $(COMPOSE_FILES) exec backend uv sync --frozen --no-cache
.PHONY: upgrade-deps-back



upgrade-deps-front: ## Update frontend dependencies
	@echo "🔒 Updating frontend dependencies..."
	docker compose $(COMPOSE_FILES) exec frontend npm update
	docker compose $(COMPOSE_FILES) exec frontend npm install
.PHONY: upgrade-deps-front



# ====================================================================================
# Test related commands
# ====================================================================================

project-context: ## Regenerate the deterministic code-derived project map
	@bash bin/documentation.sh generate
.PHONY: project-context


project-context-check: ## Check that the generated project map matches the code
	@bash bin/documentation.sh maps-check
.PHONY: project-context-check

docs-check: ## Verify generated maps and the bilingual agent documentation corpus
	@bash bin/documentation.sh check
.PHONY: docs-check

docs-prepare: ## Regenerate and verify documentation before validation or publication
	@bash bin/documentation.sh prepare
.PHONY: docs-prepare

docs-update: ## Development only: prepare docs and synchronize the live shared search index
	@if [ "$(APP_ENV)" != "dev" ]; then \
		echo "Use make docs-prepare in the source checkout, then the normal make update deployment."; exit 2; \
	fi
	@$(MAKE) docs-prepare
	@bash bin/refresh-documentation.sh $(COMPOSE_FILES)
.PHONY: docs-update


architecture-baseline: ## Update reviewed backend/frontend architecture debt baselines
	@bash bin/documentation.sh architecture-baseline
.PHONY: architecture-baseline


architecture-check: project-context-check ## Check project boundaries and documentation drift
	@echo "🏛️  Checking architecture contracts..."
	@bash bin/documentation.sh architecture-check
	@$(MAKE) tests ARGS='app/agent/tests/test_architecture.py tests/test_architecture_tooling.py tests/test_frontend_architecture_tooling.py'
.PHONY: architecture-check

# Support 'make tests path/to/test'
ifeq (tests,$(firstword $(MAKECMDGOALS)))
  # Use the rest as arguments for "tests"
  TEST_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  # ...and turn them into do-nothing targets
  $(eval $(TEST_ARGS):;@:)
endif

typecheck: ## Run strict backend and frontend type checking
	@echo "🔎 Backend type checking (Pyright strict)..."
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python -m pyright'
	@echo "🔎 Frontend type checking (vue-tsc)..."
	docker compose $(COMPOSE_FILES) exec frontend npm run type-check
	@echo "🧪 Frontend unit tests..."
	docker compose $(COMPOSE_FILES) exec frontend npm test
	@echo "🌐 Frontend translation catalog checking..."
	docker compose $(COMPOSE_FILES) exec frontend npm run i18n-check
.PHONY: typecheck



tests: ## Run backend tests in an isolated, ephemeral PostgreSQL environment
	@echo "🧪 Backend tests (isolated database)..."
	@bash bin/test-back.sh $(TEST_ARGS_BACK) $(ARGS)
.PHONY: tests

tests-recovery: ## Verify durable tool receipts, SSH crash recovery, retries and attempt ownership
	@$(MAKE) tests TEST_ARGS_BACK= ARGS='app/harness/tests app/console/tests app/task/tests/test_agent_run_trace.py app/task/tests/test_task_service.py app/task/tests/test_scheduler.py app/agent/tests/test_facade.py app/agent/tests/test_action_guard.py app/tools/tests'
.PHONY: tests-recovery

tests-harness-contracts: ## Qualify the Harness boundary, concrete adapters and durable Task integration
	@$(MAKE) tests TEST_ARGS_BACK= ARGS='app/agent/tests app/harness/tests app/harnesses/tests app/tools/tests app/image/tests/test_image_mcp.py bridge/hermes/tests bridge/codex/tests bridge/claude_agent/tests bridge/deepseek_harness/tests app/task/tests/test_scheduler.py app/task/tests/test_agent_run_trace.py tests/test_harness_boundaries.py tests/test_driver_conformance.py'
.PHONY: tests-harness-contracts

tests-harness-runtimes: ## Execute the real pinned Harness SDKs against an isolated deterministic model
	@bash bin/test-harness-runtimes.sh
.PHONY: tests-harness-runtimes

tests-providers: ## Verify provider parameter contracts without external subscriptions or API calls
	@PYTEST_ADDOPTS= $(MAKE) tests TEST_ARGS_BACK= ARGS='tests/test_provider_parameters.py tests/test_provider_catalog.py tests/test_pydantic_ai_internal_model.py tests/test_codex_provider.py tests/test_llm_call_trace.py app/llm/tests/test_structured_service.py app/conversation/tests/test_task_objective.py app/conversation/tests/test_task_admission.py app/conversation/tests/test_service.py --junitxml=/repo/artifacts/provider-contracts.xml'
.PHONY: tests-providers

tests-dbadmin-load: ## Qualify nullable staging, backfill and indexing on 100k rows in isolation
	DBADMIN_LOAD_TEST=1 $(MAKE) tests ARGS='core/dbadmin/tests/test_volume_transitions.py -v'
.PHONY: tests-dbadmin-load

tests-load: ## Exercise mixed local WebRTC, HTTP and file load with a sustained lease heartbeat
	MIXED_LOAD_SECONDS=60 $(MAKE) tests ARGS='tests/test_durable_concurrency.py -k buffered_saturation -s'
.PHONY: tests-load


tests-browser: ## Run isolated browser executor unit tests
	@echo "🌐 Browser executor tests..."
	docker compose $(COMPOSE_FILES) run --rm --no-deps \
		-v $(CURDIR)/browser-executor:/opt/galaris-browser/source:ro \
		-w /opt/galaris-browser/source browser-executor npm test
.PHONY: tests-browser

tests-executor: ## Test SSH registry concurrency and real Unix peer permissions in isolation
	docker run --rm --network none --user 0:0 --entrypoint python3 \
		-v $(CURDIR)/ssh-executor:/audit:ro python:3.14-slim-trixie \
		-m unittest discover -s /audit/tests -v
.PHONY: tests-executor


tests-e2e: ## Run browser workflows and PWA updates in a fully isolated stack
	@bash bin/test-e2e.sh $(ARGS)
.PHONY: tests-e2e

tests-front-tooling: ## Verify that the TypeScript gate rejects invalid application and build code
	docker compose $(COMPOSE_FILES) exec -T frontend npm run test:tooling
.PHONY: tests-front-tooling

tests-front-components: ## Exercise actual Vue/Quasar components in an isolated browser
	@bash bin/test-front-components.sh $(ARGS)
.PHONY: tests-front-components

tests-focus-gates: ## Prove both Playwright configurations reject focused tests
	@bash bin/test-focus-gates.sh
.PHONY: tests-focus-gates

validate: ## Validate a frozen local snapshot without a CI server or development stack
	@bash bin/validate.sh
.PHONY: validate

tests-validation-source: ## Prove local validation preserves and fingerprints uncommitted changes
	@bash bin/test-validation-source.sh
.PHONY: tests-validation-source

quality: typecheck lint format-check tests-front-tooling tests-focus-gates tests-front-components tests-browser tests-executor tests-harness-manager architecture-check tests-providers tests-coverage tests-mutations tests-e2e ## Run the complete local quality gate
	@$(MAKE) regression-check
.PHONY: quality

security-check: ## Scan versioned dependencies, secrets and security-sensitive code
	@bash bin/security-check.sh
.PHONY: security-check

tests-restore: ## Rehearse database, files and encryption-key restoration in isolation
	@bash bin/test-restore.sh
.PHONY: tests-restore

tests-upgrade: ## Rehearse explicit UPGRADE_PREVIOUS_IMAGE or UPGRADE_FROM on isolated data
	@bash bin/test-upgrade.sh
.PHONY: tests-upgrade

build-release: ## Build/export immutable images from RELEASE_REF (default committed HEAD)
	@bash bin/build-release.sh
.PHONY: build-release

tests-release: ## Qualify the exact production images in RELEASE_DIR before promotion
	@bash bin/test-release.sh
.PHONY: tests-release

lint: ## Check high-confidence Python errors in the development container
	docker compose $(COMPOSE_FILES) exec -T backend uv run --frozen ruff check app core bridge scripts main.py
	docker compose $(COMPOSE_FILES) exec -T frontend npm run lint
.PHONY: lint

format-check: ## Check formatting of the newly extracted reliability modules
	docker compose $(COMPOSE_FILES) exec -T backend python scripts/check_format.py --check
.PHONY: format-check

tests-coverage: ## Measure all backend sources once and enforce the existing critical floors
	@mkdir -p artifacts
	$(MAKE) tests ARGS='$(COVERAGE_TEST_ARGS) --cov --cov-config=coverage-all.ini --cov-branch --cov-report=term --cov-report=xml:/repo/artifacts/coverage-full.xml --junitxml=/repo/artifacts/backend-junit.xml'
	docker compose -f compose.test.yaml run --rm --no-deps backend python -m scripts.report_full_coverage
	$(MAKE) coverage-check
.PHONY: tests-coverage

coverage-check: ## Enforce reviewed critical domain floors and changed-branch coverage
	@bash bin/check-coverage.sh
.PHONY: coverage-check

tests-mutations: ## Check selected lifecycle mutations in disposable source copies
	@bash bin/test-back.sh --mutations
.PHONY: tests-mutations

regression-check: ## Verify regression test links against successful test and mutation reports
	docker compose -f compose.test.yaml run --rm --no-deps backend python scripts/check_regression_evidence.py
.PHONY: regression-check

qualify-lab: ## Start an explicitly budgeted Lab run or compare completed runs (ARGS, LAB_ACCESS_TOKEN)
	docker compose -f compose.test.yaml run --rm --no-deps -e LAB_ACCESS_TOKEN backend python scripts/qualify_lab.py $(ARGS)
.PHONY: qualify-lab

qualify-matrix: ## Send synthetic text/file to an explicitly authorized Matrix test room (ARGS)
	docker compose -f compose.test.yaml run --rm --no-deps -e MATRIX_QUALIFICATION_SENDER_TOKEN -e MATRIX_QUALIFICATION_OBSERVER_TOKEN backend python scripts/qualify_matrix.py $(ARGS)
.PHONY: qualify-matrix


test-hermes-management: ## Check Hermes management configuration and connectivity
	@echo "🔍 Testing Hermes management..."
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/test_bridge_hermes.py'
.PHONY: test-hermes-management

test-harness-management: ## Check low-level harness manager configuration and connectivity
	@echo "🔍 Testing harness management..."
	docker compose $(COMPOSE_FILES) exec backend sh -c 'python scripts/test_bridge_harness.py'
.PHONY: test-harness-management

tests-harness-manager: ## Run the generic harness manager unit tests in Docker
	docker run --rm -v "$(PWD)/harness_manager:/harness_manager:ro" \
		-w /harness_manager -e PYTHONDONTWRITEBYTECODE=1 \
		-e UV_PROJECT_ENVIRONMENT=/tmp/harness-venv -e UV_CACHE_DIR=/tmp/uv-cache \
		ghcr.io/astral-sh/uv:python3.14-bookworm \
		uv run --locked --with pytest --with httpx pytest -p no:cacheprovider tests
.PHONY: tests-harness-manager
