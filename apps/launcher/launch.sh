#!/usr/bin/env bash
set -euo pipefail

# Relationship OS - Safe Terminal Launcher for Linux & macOS
SERVER_URL="${1:-http://127.0.0.1:8000}"
ENROLL_TOKEN="${2:-}"

echo -e "\033[1;35m================================================================\033[0m"
echo -e "\033[1;36m                ♥ Relationship OS Launcher ♥                    \033[0m"
echo -e "\033[1;35m================================================================\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_VENV="$SCRIPT_DIR/../../.venv"
INSTALL_DIR="$HOME/.relationship_os"
LOCAL_CLI="$SCRIPT_DIR/../cli/src/cli.py"

if [ -d "$REPO_VENV" ]; then
    PYTHON_EXE="$REPO_VENV/bin/python3"
else
    mkdir -p "$INSTALL_DIR"
    VENV_DIR="$INSTALL_DIR/venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "\033[0;34m[*] Creating isolated client environment...\033[0m"
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip rich httpx websockets
    fi
    PYTHON_EXE="$VENV_DIR/bin/python3"
fi

if [ -f "$LOCAL_CLI" ]; then
    CLI_PATH="$LOCAL_CLI"
else
    CLI_PATH="$INSTALL_DIR/relationship_os_cli.py"
    curl -fsSL "$SERVER_URL/static/relationship_os_cli.py" -o "$CLI_PATH"
fi

ARGS=("$CLI_PATH" "--server" "$SERVER_URL")
if [ -n "$ENROLL_TOKEN" ]; then
    ARGS+=("--enroll" "$ENROLL_TOKEN")
fi

echo -e "\033[0;32m[✓] Launching Relationship OS terminal client...\033[0m"
PYTHONPATH="$SCRIPT_DIR/../.." "$PYTHON_EXE" "${ARGS[@]}"
