# Cloudflare Pages & Render Deployment Guide (Relationship OS)

This guide provides instructions for deploying the **Frontend on Cloudflare Pages** and the **Backend on Render** from the private repository (`DHIRAJ-GHOLAP/relationship-os-private`).

---

## 1. Architecture Overview

```mermaid
flowchart LR
    subgraph Cloudflare["Cloudflare Edge"]
        CP["Cloudflare Pages<br/>(React 18 SPA)"]
    end

    subgraph RenderCloud["Render Cloud"]
        API["Render Web Service<br/>(FastAPI / Docker)"]
        DISK[("1 GB Persistent Disk<br/>SQLite & Attachments")]
        API --- DISK
    end

    subgraph Clients["Users"]
        OWNER["Owner (Discord / Web)"]
        RECIP["Recipient (Browser / Terminal)"]
    end

    RECIP -->|HTTPS / WSS| CP
    CP -->|REST API & WebSockets| API
    OWNER -->|Discord Webhook / Bot| API
```

---

## 2. Backend on Render (Web Service)

The repository includes a ready-to-deploy [`render.yaml`](file:///home/flash/relationship-os/render.yaml) blueprint.

### Automatic Blueprint Deployment:
1. Log into your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** $\rightarrow$ **Blueprint**.
3. Connect your private repository: `DHIRAJ-GHOLAP/relationship-os-private`.
4. Render will automatically detect `render.yaml` and configure:
   - **Service Name:** `relationship-os-backend`
   - **Runtime:** `docker` (using `Dockerfile.api`)
   - **Health Check Path:** `/api/v1/health`
   - **Persistent Disk:** 1 GB mounted at `/app/data` (preserves your SQLite messages and users across deploys)
   - **Environment Variables:** Automatically generates a cryptographically secure `SECRET_KEY`.
5. Click **Apply**.
6. Once deployed, Render will assign an HTTPS URL, for example:
   `https://relationship-os-backend.onrender.com`

---

## 3. Frontend on Cloudflare Pages

### Option A: Connect via Cloudflare Dashboard (Recommended)
1. Log into your [Cloudflare Dashboard](https://dash.cloudflare.com) and go to **Compute (Workers & Pages)** $\rightarrow$ **Pages**.
2. Click **Create a project** $\rightarrow$ **Connect to Git**.
3. Select the private repository: `DHIRAJ-GHOLAP/relationship-os-private`.
4. Configure Build Settings:
   - **Framework preset:** `Vite`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Root directory:** `apps/web`
5. In **Environment variables (Advanced)**, add:
   - `NODE_VERSION`: `20`
   - `VITE_API_BASE_URL`: `https://relationship-os-backend.onrender.com` (your Render service URL)
6. Click **Save and Deploy**.

### Option B: Automated Deployment via GitHub Actions
The repository includes `.github/workflows/deploy-cloudflare-pages.yml`.
In your GitHub repository settings under **Secrets and variables $\rightarrow$ Actions**, add:
- `CLOUDFLARE_API_TOKEN`: Cloudflare API token with Pages edit permissions.
- `CLOUDFLARE_ACCOUNT_ID`: Your Cloudflare Account ID.
- `VITE_API_BASE_URL`: `https://relationship-os-backend.onrender.com`.

Every push to `master` will build the frontend and deploy to Cloudflare Pages automatically.

---

## 4. CORS & WebSockets Verification

Render's backend service allows connections from Cloudflare Pages via:
```yaml
- key: ALLOWED_ORIGINS
  value: "https://*.pages.dev,https://*.render.com,http://localhost:3000,http://localhost:8000"
```
Both REST API requests and WebSocket subscriptions (`wss://relationship-os-backend.onrender.com/ws/chat/{conversation_id}`) will connect seamlessly across origins.
