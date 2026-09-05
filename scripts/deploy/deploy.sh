#!/usr/bin/env bash
set -euo pipefail

# Relationship OS - Production Deployment Orchestration Script
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo -e "\033[1;35m================================================================\033[0m"
echo -e "\033[1;36m           ♥ Relationship OS Production Deployment ♥            \033[0m"
echo -e "\033[1;35m================================================================\033[0m"

ACTION="${1:-up}"

case "$ACTION" in
    build)
        echo -e "\033[0;34m[*] Building production Docker images...\033[0m"
        docker compose build
        ;;
    up)
        echo -e "\033[0;34m[*] Starting Relationship OS containers in detached mode...\033[0m"
        docker compose up -d --build
        echo -e "\033[0;32m[✓] Relationship OS is running!\033[0m"
        echo -e "    Web Application: http://localhost"
        echo -e "    Backend API:     http://localhost:8000"
        ;;
    down)
        echo -e "\033[0;33m[*] Stopping Relationship OS containers...\033[0m"
        docker compose down
        ;;
    logs)
        docker compose logs -f
        ;;
    status)
        docker compose ps
        ;;
    seed)
        echo -e "\033[0;34m[*] Seeding production database inside api container...\033[0m"
        docker compose exec api python scripts/seed.py
        ;;
    *)
        echo "Usage: $0 {build|up|down|logs|status|seed}"
        exit 1
        ;;
esac
