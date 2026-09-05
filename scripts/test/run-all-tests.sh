#!/usr/bin/env bash
set -euo pipefail

# Relationship OS - Master Test Runner
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo -e "\033[1;35m================================================================\033[0m"
echo -e "\033[1;36m           ♥ Relationship OS Master Test Suite Runner ♥          \033[0m"
echo -e "\033[1;35m================================================================\033[0m"

VENV_PYTHON="$REPO_ROOT/.venv/bin/python3"
PYTEST="$REPO_ROOT/.venv/bin/pytest"

if [ ! -f "$PYTEST" ]; then
    echo -e "\033[0;31m[!] Pytest not found in .venv. Please install requirements first.\033[0m"
    exit 1
fi

echo -e "\033[0;34m[*] 1. Running System Integrity Verification...\033[0m"
PYTHONPATH="$REPO_ROOT" "$VENV_PYTHON" scripts/verify_integrity.py

echo -e "\n\033[0;34m[*] 2. Executing Automated Test Suite (Unit, Integration, Security, Concurrency, E2E)...\033[0m"
export PYTHONPATH="$REPO_ROOT"
"$PYTEST" tests/ -v --cov=apps/api --cov=packages/shared --cov=integrations --cov-report=term-missing

echo -e "\n\033[0;32m[✓✓✓] ALL TESTS AND INTEGRITY CHECKS COMPLETED SUCCESSFULLY!\033[0m"
