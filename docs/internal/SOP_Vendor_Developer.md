# Standard Operating Procedure: Vendor Developer (Deep Dive)

**Audience:** Internal Engineering Team (Backend, Frontend, DevOps)
**Purpose:** Architecture internals, contribution guidelines, and release engineering.
**Version:** 2.1.0

---

## 📚 Table of Contents
1. [Architecture Internals](#1-architecture-internals)
2. [Development Workflow](#2-development-workflow)
3. [Database Migrations](#3-database-migrations)
4. [Testing Strategy](#4-testing-strategy)
5. [Release Engineering](#5-release-engineering)

---

## 1. Architecture Internals

### **Directory Structure**
```
/
├── agent/          # Python Agent (runs on target servers)
│   ├── agent.py    # Main logic (Flask + Threading)
│   └── main.py     # Entry point & Registration
├── backend/        # FastAPI Master Node
│   ├── api/        # REST Endpoints
│   ├── models/     # SQLAlchemy Models
│   └── main.py     # App Factory
├── frontend/       # React + Vite
│   ├── src/App.js  # Main UI Logic
│   └── nginx.conf  # Reverse Proxy Config
├── vendor/         # License Generator Portal
└── monitoring/     # Prometheus/Grafana Configs
```

### **Core Concepts**
- **Asyncio**: The backend uses `async/await` for all DB and HTTP calls. Do not use blocking code (e.g., `time.sleep`) in API routes.
- **JWT Auth**: `backend/auth.py` handles token issuance. Tokens expire in 8 hours.
- **Agent Polling**: Agents poll `/api/jobs` every 60s. We do *not* push to agents directly (except for specific real-time commands via WebSocket, if implemented).

---

## 2. Development Workflow

### **Setting up the Dev Environment**
1. **Clone**: `git clone ...`
2. **Env**: `cp .env.example .env` (Ask Tech Lead for `JWT_SECRET`).
3. **Start**: `docker-compose up -d`.
   - Backend mounts `./backend` -> `/app` (Hot Reload enabled).
   - Frontend mounts `./frontend` -> `/app` (HMR enabled).

### **Adding a New API Endpoint**
1. **Define Schema**: Add Pydantic model in `backend/schemas.py` (if exists) or inline.
2. **Create Route**: Add function in `backend/api/new_feature.py`.
3. **Register**: Import router in `backend/main.py`.
4. **Test**: Go to `http://localhost:8000/docs` (Swagger UI).

### **Adding a Frontend Page**
1. **Create Component**: `frontend/src/pages/NewPage.js`.
2. **Add Route**: Update `App.js` navigation list.
3. **Permission Check**: Wrap in `{hasPerm('new_feature') && <NewPage />}`.

---

## 3. Database Migrations

We currently use **SQLAlchemy Async**.

### **Modifying the Schema**
1. Edit `backend/models/db_models.py`.
2. **Migration Tool**: alembic (`backend/alembic.ini`, chain in `backend/alembic/versions/`).
   - *Current State*: `database.py` runs `alembic upgrade head` on startup, then adds whatever the models declare and the database is missing (tables, columns, indexes) - additive only, it never drops.
   - *Action*: adding a table/column/index that needs no backfill is just a model change -
     the startup reconcile picks it up. Reversible or data-transforming changes get their
     own revision.

**Best Practice**: generate a revision with `alembic revision --autogenerate -m "<what and why>"` and put the DDL in it, documented in the PR. The dated scripts in `backend/migrations/` are already converted into the chain (revision `20261025_0002`) - do not add new ones.

---

## 4. Testing Strategy

### **Unit Tests**
- **Backend**: `pytest`
  - Mock DB sessions.
  - Test auth decorators.
- **Agent**: Test package manager abstraction (Mock `subprocess.run`).

### **E2E Testing (Manual)**
1. Spin up the full stack (`docker-compose up`).
2. Run a "Dummy Agent" locally:
   ```bash
   cd agent
   python main.py --dev
   ```
3. Verify it registers in Dashboard.
4. Issue a "Ping" command.

---

## 5. Release Engineering

### **Versioning**
- Follow **Semantic Versioning** (MAJOR.MINOR.PATCH).
- Bump version in:
  - `backend/main.py`
  - `frontend/package.json`
  - `agent/agent.py`
  - `scripts/build_release.py`

### **Building Artifacts**

**Prerequisite**: Ensure Agent binaries are built and placed in `backend/static/`:
- `agent-latest.deb` (Debian/Ubuntu)
- `agent-latest.rpm` (RHEL/CentOS)
- `agent-windows.zip` (Windows PyInstaller bundle)

Run the release builder:
```bash
python3 scripts/build_release.py
```
- **Product Tarball**: Contains everything *except* `vendor/`.
- **Vendor Tarball**: Contains *only* `vendor/`.

### **Sanity Check before Publish**
1. Extract `dist/patchmaster-product-X.X.X.tar.gz` to a fresh VM.
2. Run `./packaging/install-bare.sh`.
3. Verify login works.
4. Verify License upload works.
