# Relationship OS - Production Deployment Guide

This guide covers production deployment strategies for Relationship OS, including container orchestration with Docker Compose, Nginx reverse proxying, TLS termination, persistent storage, and backup procedures.

---

## 1. System Requirements

| Resource | Minimum | Recommended (High Traffic) |
| :--- | :--- | :--- |
| **CPU** | 1 Core | 2 - 4 Cores |
| **RAM** | 1 GB | 2 - 4 GB |
| **Storage** | 10 GB SSD | 50+ GB SSD (for attachments) |
| **OS** | Ubuntu 22.04 LTS / Debian 12 | Linux (kernel 5.15+) |
| **Runtimes** | Docker 24+ & Compose v2 | Docker Engine with systemd |

---

## 2. Environment Variables Configuration

Create a production `.env` file in the root directory:

```ini
# Core Configuration
ENVIRONMENT=production
DEBUG=False
APP_NAME="Relationship OS"
APP_VERSION="1.0.0"

# Cryptographic Secret (MUST be 32+ characters of random entropy)
SECRET_KEY=generate-a-strong-random-secret-key-32-chars-minimum

# Database Connection (SQLite or PostgreSQL)
# Option A: SQLite (Default)
DATABASE_URL=sqlite+aiosqlite:////app/data/relationship_os.db

# Option B: PostgreSQL
# DATABASE_URL=postgresql+asyncpg://relationship_user:relationship_secure_password@postgres:5432/relationship_os

# Attachment Storage
STORAGE_LOCAL_PATH=/app/storage_uploads
STORAGE_MAX_FILE_SIZE_BYTES=26214400 # 25MB

# CORS & Network Origins
ALLOWED_ORIGINS=https://relationship.yourdomain.com,https://api.yourdomain.com

# Integrations: Discord
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=

# Outbox Worker Tuning
OUTBOX_POLL_INTERVAL=1.0
OUTBOX_MAX_RETRIES=5
```

---

## 3. Deployment with Docker Compose

### Step 1: Clone Repository
```bash
git clone https://github.com/relationship-os/relationship-os.git /opt/relationship-os
cd /opt/relationship-os
```

### Step 2: Configure Environment
```bash
cp .env.example .env
# Edit .env with your production secrets and domain name
nano .env
```

### Step 3: Build and Start Services
```bash
./scripts/deploy/deploy.sh up
```

### Step 4: Seed Database and Generate Credentials
```bash
./scripts/deploy/deploy.sh seed
```
This initializes the database, creates the primary Owner and Recipient accounts, sets up the private canonical conversation, and generates the initial enrollment token.

---

## 4. Production Nginx & TLS Termination

When deploying behind an external domain, terminate TLS at the Nginx edge using Let's Encrypt:

```nginx
server {
    listen 80;
    server_name relationship.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name relationship.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/relationship.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/relationship.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 50M;

    # REST API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket Hub
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
    }

    # Web UI SPA
    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 5. Database Backup and Disaster Recovery

### SQLite Backup Procedure
SQLite with WAL mode can be safely backed up online using the `.backup` API:

```bash
# Execute safe point-in-time backup
docker compose exec api python -c '
import sqlite3
src = sqlite3.connect("/app/data/relationship_os.db")
dst = sqlite3.connect("/app/data/backup_$(date +%Y%m%d_%H%M%S).db")
src.backup(dst)
dst.close()
src.close()
'
```

### Attachment Storage Backup
```bash
# Archive media uploads directory
tar -czvf /var/backups/relationship_os_attachments_$(date +%Y%m%d).tar.gz /opt/relationship-os/storage_uploads
```

### Restoration
1. Stop running containers: `docker compose down`
2. Restore database file to `/opt/relationship-os/data/relationship_os.db`
3. Extract attachment archive to `/opt/relationship-os/storage_uploads`
4. Start services: `docker compose up -d`
5. Run integrity verification: `docker compose exec api python scripts/verify_integrity.py`
