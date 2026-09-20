# --- Load .env ---
# The leading dash keeps Make working before the file exists.
-include .env
export

MAKEFLAGS += --no-print-directory

# Defaults used when .env is missing or incomplete.
API_HOST ?= 127.0.0.1
API_PORT ?= 8485


# 1. Local directories.
LOCAL_DIR := $(CURDIR)/.local
UV_BIN := $(LOCAL_DIR)/bin/uv
UVICORN_BIN = $(UV_PROJECT_ENVIRONMENT)/bin/uvicorn

# PID and log files for the background process.
PID_FILE := $(LOCAL_DIR)/api.pid
LOG_FILE := $(LOCAL_DIR)/api.log

# 2. Keep every uv-managed file inside this directory.
export UV_CACHE_DIR := $(LOCAL_DIR)/cache
export UV_PYTHON_INSTALL_DIR := $(LOCAL_DIR)/python
export UV_PROJECT_ENVIRONMENT := $(LOCAL_DIR)/venv

export PYTHONPYCACHEPREFIX := $(LOCAL_DIR)/pycache

# Commands.
help:
	@echo "Available commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Run 'make <command>' with one of the commands above."
.PHONY: help



install: ## Install the Galaris harness manager
	@echo "🚀 Installing..."
	@mkdir -p $(LOCAL_DIR)/bin
	@if [ ! -f "$(UV_BIN)" ]; then \
		echo "⬇️ Downloading uv locally..."; \
		curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$(LOCAL_DIR)/bin" INSTALLER_NO_MODIFY_PATH=1 sh; \
	else \
		echo "✅ uv is already installed locally."; \
	fi
	@echo "📝 Initializing configuration..."
	@if [ ! -f .env ]; then \
		SECRET=$$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"); \
		cp .env.example .env; \
		sed -i "s|^HARNESS_MANAGER_SECRET=.*|HARNESS_MANAGER_SECRET=$$SECRET|" .env; \
		sed -i "s|^BASE_DIR=.*|BASE_DIR=$(HOME)/galaris-harnesses|" .env; \
		mkdir -p "$(HOME)/galaris-harnesses"; \
		echo "✅ Created .env with an automatically generated secret."; \
		echo "⚠️  Configure the same harness-manager secret in each Galaris consumer."; \
	else \
		echo "✅ .env already exists and will not be overwritten."; \
	fi
	@if [ -x "$(UVICORN_BIN)" ] && ! "$(UVICORN_BIN)" --version >/dev/null 2>&1; then \
		echo "♻️  Rebuilding the moved or invalid virtual environment..."; \
		"$(UV_BIN)" venv --clear "$(UV_PROJECT_ENVIRONMENT)"; \
	fi
	@echo "📥 Synchronizing the environment..."
	@$(UV_BIN) sync --frozen
	@echo "🎉 Installation complete!"
.PHONY: install

update: ## Download the release from Galaris, preserve .env and instances, restart if running
	@"$(UV_PROJECT_ENVIRONMENT)/bin/python" update.py
.PHONY: update



create-secret: ## Generate HARNESS_MANAGER_SECRET and write it to .env
	@SECRET=$$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"); \
	if [ ! -f .env ]; then \
		cp .env.example .env; \
		sed -i "s|^HARNESS_MANAGER_SECRET=.*|HARNESS_MANAGER_SECRET=$$SECRET|" .env; \
		echo "✅ Created .env with the secret."; \
	elif grep -q "^HARNESS_MANAGER_SECRET=" .env; then \
		sed -i "s|^HARNESS_MANAGER_SECRET=.*|HARNESS_MANAGER_SECRET=$$SECRET|" .env; \
		echo "✅ Updated HARNESS_MANAGER_SECRET in .env."; \
	else \
		echo "HARNESS_MANAGER_SECRET=$$SECRET" >> .env; \
		echo "✅ Added HARNESS_MANAGER_SECRET to .env."; \
	fi; \
	echo ""; \
	echo "👉 Configure this value in every authorized Galaris harness consumer:"; \
	echo "   HARNESS_MANAGER_SECRET=$$SECRET"
.PHONY: create-secret



uninstall: ## Uninstall the harness manager
	@echo "🧹 Uninstalling the harness manager..."
	@if [ -f $(PID_FILE) ]; then kill $$(cat $(PID_FILE)) 2>/dev/null || true; fi
	@rm -rf .local
.PHONY: uninstall



start: ## Start the server
	@echo "🚀 Starting the API on $(API_HOST):$(API_PORT) in the background..."
	@if [ ! -x "$(UVICORN_BIN)" ] || ! "$(UVICORN_BIN)" --version >/dev/null 2>&1; then \
		echo "❌ uvicorn is missing or invalid at $(UVICORN_BIN). Run 'make install' first."; \
		exit 1; \
	fi
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "⚠️ The API appears to be running already (PID: $$(cat $(PID_FILE))). Run 'make stop' first."; \
	else \
		rm -f $(PID_FILE); \
		nohup $(UVICORN_BIN) main:app --host $(API_HOST) --port $(API_PORT) > $(LOG_FILE) 2>&1 & \
		echo $$! > $(PID_FILE); \
		sleep 1; \
		if ! kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
			echo "❌ The API failed to start. Inspect $(LOG_FILE)."; \
			rm -f $(PID_FILE); \
			exit 1; \
		fi; \
		echo "✅ API started (PID: $$(cat $(PID_FILE)))."; \
		echo "📄 Run 'make logs' to follow the logs."; \
	fi
.PHONY: start



stop: ## Stop the server
	@echo "🛑 Stopping the API..."
	@if [ -f $(PID_FILE) ]; then \
		PID=$$(cat $(PID_FILE)); \
		if kill -0 $$PID 2>/dev/null; then \
			CMD=$$(tr '\0' ' ' < /proc/$$PID/cmdline 2>/dev/null || true); \
			case "$$CMD" in \
				*"$(UVICORN_BIN) main:app"*|*"$(UV_BIN) run uvicorn main:app"*) kill $$PID ;; \
				*) echo "❌ PID $$PID does not belong to this manager; refusing to stop it."; exit 1 ;; \
			esac; \
			for i in 1 2 3 4 5; do \
				kill -0 $$PID 2>/dev/null || break; \
				sleep 1; \
			done; \
			if kill -0 $$PID 2>/dev/null; then \
				echo "❌ Manager process $$PID did not stop."; \
				exit 1; \
			fi; \
		fi; \
		rm -f $(PID_FILE); \
	fi
	@echo "✅ API stopped."
.PHONY: stop



restart: ## Restart the server
	@$(MAKE) stop
	@$(MAKE) start
.PHONY: restart



logs: ## Follow server logs
	@echo "📄 Following API logs (Ctrl+C to quit)..."
	@tail -f $(LOG_FILE)
.PHONY: logs



# --- systemd service with automatic restart and boot startup ---
# The machine-specific unit file is generated and ignored by Git.
SERVICE_NAME := galaris-harness-manager.service
SERVICE_FILE := $(CURDIR)/$(SERVICE_NAME)
SYSTEMD_USER_DIR := $(HOME)/.config/systemd/user
service-file: ## Generate the complete machine-specific systemd unit
	@if [ ! -x "$(UVICORN_BIN)" ] || ! "$(UVICORN_BIN)" --version >/dev/null 2>&1; then \
		echo "❌ uvicorn is missing or invalid at $(UVICORN_BIN). Run 'make install' first."; \
		exit 1; \
	fi
	@printf '%s\n' \
		'[Unit]' \
		'Description=Galaris generic harness container manager' \
		'# Restart at most five times in 60 seconds to prevent a crash loop.' \
		'StartLimitIntervalSec=60' \
		'StartLimitBurst=5' \
		'' \
		'[Service]' \
		'Type=exec' \
		'WorkingDirectory=$(CURDIR)' \
		'EnvironmentFile=$(CURDIR)/.env' \
		'ExecStart=$(UVICORN_BIN) main:app --host $${API_HOST} --port $${API_PORT}' \
		'Restart=always' \
		'RestartSec=3' \
		'' \
		'[Install]' \
		'WantedBy=default.target' \
		> $(SERVICE_FILE)
	@echo "✅ Generated $(SERVICE_NAME)."
.PHONY: service-file

service-install: service-file ## Install and start the user systemd service
	@echo "🔧 Installing the user service in $(SYSTEMD_USER_DIR)..."
	@mkdir -p $(SYSTEMD_USER_DIR)
	@cp $(SERVICE_FILE) $(SYSTEMD_USER_DIR)/$(SERVICE_NAME)
	@systemctl --user daemon-reload
	@systemctl --user enable $(SERVICE_NAME)
	@systemctl --user reset-failed $(SERVICE_NAME) 2>/dev/null || true
	@systemctl --user restart $(SERVICE_NAME)
	@echo "✅ Service installed and started."
	@echo "⚠️  To run it without an open session: sudo loginctl enable-linger $(USER)"
	@echo "👉 Use 'make service-status' to check it and 'make service-logs' for logs."
.PHONY: service-install

service-uninstall: ## Uninstall the user systemd service
	@echo "🧹 Removing the user service..."
	@systemctl --user disable --now $(SERVICE_NAME) 2>/dev/null || true
	@rm -f $(SYSTEMD_USER_DIR)/$(SERVICE_NAME)
	@systemctl --user daemon-reload
	@echo "✅ Service removed."
.PHONY: service-uninstall

service-status: ## Show systemd service status
	@systemctl --user status $(SERVICE_NAME) --no-pager || true
.PHONY: service-status

service-logs: ## Follow systemd service logs with journalctl
	@journalctl --user -u $(SERVICE_NAME) -f
.PHONY: service-logs
