#!/usr/bin/env bash
set -euo pipefail

# Relationship OS - Local Development Startup Script
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo -e "\033[1;35m================================================================\033[0m"
echo -e "\033[1;36m           ♥ Relationship OS Local Development Server ♥         \033[0m"
echo -e "\033[1;35m================================================================\033[0m"

VENV_PYTHON="$REPO_ROOT/.venv/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "\033[0;31m[!] Virtual environment not found at .venv. Please create it first.\033[0m"
    exit 1
fi

# 1. Run database seeding if db doesn't exist
if [ ! -f "$REPO_ROOT/relationship_os.db" ]; then
    echo -e "\033[0;34m[*] Initializing and seeding local database...\033[0m"
    PYTHONPATH="$REPO_ROOT" "$VENV_PYTHON" scripts/seed.py
fi

# 2. Check if web assets exist
if [ ! -d "$REPO_ROOT/apps/web/dist" ]; then
    echo -e "\033[0;33m[*] Web distribution not found. Building web client...\033[0m"
    (cd apps/web && npm run build)
fi

echo -e "\033[0;32m[✓] Starting FastAPI server on http://127.0.0.1:8000 ...\033[0m"
echo -e "\033[0;36m    - Web Interface: http://localhost:8000\033[0m"
echo -e "\033[0;36m    - API Docs:      http://localhost:8000/docs\033[0m"
echo -e "\033[0;36m    - Press CTRL+C to stop the server.\033[0m\n"

export PYTHONPATH="$REPO_ROOT"
exec "$VENV_PYTHON" -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload
