#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

python -m core.server_mode "$@"

# Every backend start, including ``make update`` in production, asks the single
# DbAdmin entrypoint to converge the public schema and reference data before
# serving traffic. Development hot reload does not rerun this entrypoint; use
# ``make sync-db`` after such changes.
python -m core.dbadmin synchronize

# Check for uvicorn command
if [ "$1" = "uvicorn" ]; then
    # One worker is an application invariant, independent of legacy environment settings.
    unset WEB_CONCURRENCY
    set -- "$@" --workers 1
    # Enable proxy headers for correct redirect generation behind proxies
    case "$*" in
        *"--proxy-headers"*) ;;
        *) set -- "$@" --proxy-headers --forwarded-allow-ips '*' ;;
    esac

    if [ "$APP_ENV" = "dev" ]; then
        echo "Development mode: Enabling hot reload and debugpy"
        
        # Check if --reload is already in the arguments to avoid duplication
        case "$*" in
            *"--reload"*) ;;
            *) set -- "$@" --reload ;;
        esac
        
        # Start with debugpy for remote debugging on port 5678
        echo "Starting debugpy on port 5678 (Reload ENABLED)..."
        # Note: With reload enabled, code runs in a child process.
        # VS Code launch.json must have subProcess: true to debug properly.
        exec python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 -m "$@"
    fi
fi

# Execute the passed command (production mode)
exec "$@"
