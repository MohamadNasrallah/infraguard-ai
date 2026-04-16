# InfraGuard AI — Claude Code Context

This file is the single source of truth for Claude Code. Read it fully before doing anything.

---

## Project Summary

InfraGuard AI is a production-oriented road safety system that processes pre-recorded traffic videos daily, detects violations, clusters dangerous hotspots, and generates a PDF recommendation report using an LLM.

**This is an academic project graded as a production system. Engineering depth, robustness, and evidence of real deployment matter more than feature count.**

---

## Pipeline Architecture

```
Daily Trigger (EEP scheduler)
        ↓
      EEP                     ← orchestrator, sequences the pipeline, handles failures
        ↓
     IEP1                     ← accepts video path, detects violations (YOLO + DeepSORT)
                              → stores structured events to PostgreSQL
        ↓
     IEP2                     ← pulls events from PostgreSQL
                              → clusters hotspots using ST-DBSCAN
                              → stores hotspots to PostgreSQL
        ↓
     IEP3                     ← pulls hotspots + raw events from PostgreSQL
                              → calls LLM to generate report
                              → outputs PDF report URL
        ↓
      EEP                     ← stores report reference, returns download URL
```

---

## Repo Structure

```
infraguard-ai/
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + test + docker build — runs on every PR
│       ├── integration.yml     # full stack health check — runs on merge to develop
│       └── deploy.yml          # build + push + kubectl apply — runs on merge to main
│
├── eep/
│   ├── app/
│   │   ├── main.py             # FastAPI app entrypoint
│   │   ├── routes/             # API route handlers
│   │   ├── middleware/         # auth, rate limiting, validation
│   │   ├── orchestrator.py     # sequences IEP1→IEP2→IEP3, circuit breaker, fallbacks
│   │   └── scheduler.py        # reserved — manual trigger only for now (POST /run)
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── iep1/
│   ├── app/
│   │   ├── main.py
│   │   ├── detector.py         # YOLO inference (stub for now)
│   │   ├── tracker.py          # DeepSORT (stub for now)
│   │   ├── privacy.py          # face/plate blurring
│   │   └── schemas.py          # input: video_path | output: events[]
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── iep2/
│   ├── app/
│   │   ├── main.py
│   │   ├── clustering.py       # ST-DBSCAN hotspot clustering
│   │   ├── risk_scorer.py      # density + severity scoring
│   │   └── schemas.py          # input: events[] | output: hotspots[]
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── iep3/
│   ├── app/
│   │   ├── main.py
│   │   ├── report_generator.py # LLM call + PDF rendering
│   │   ├── prompt_manager.py   # loads versioned prompts
│   │   ├── pdf_builder.py      # ReportLab PDF generation
│   │   └── schemas.py          # input: hotspots[] + events[] | output: pdf_url
│   ├── prompts/
│   │   └── v1_report.txt       # versioned prompt — never edit in place, create v2
│   ├── tests/
│   │   └── golden/             # fixed input → assert report has required sections
│   ├── Dockerfile
│   └── requirements.txt
│
├── infra/
│   ├── docker-compose.yml      # runs full stack locally with one command
│   ├── k8s/
│   │   ├── eep-deployment.yaml
│   │   ├── iep1-deployment.yaml
│   │   ├── iep2-deployment.yaml
│   │   ├── iep3-deployment.yaml
│   │   ├── postgres-deployment.yaml
│   │   └── services/           # K8s Service objects for each deployment
│   └── monitoring/
│       ├── prometheus.yml
│       └── grafana/
│           └── dashboards/
│
├── mlops/
│   ├── mlflow/                 # MLflow tracking server config
│   ├── training/               # training scripts (populated in Phase 4)
│   └── promotion_logic.py      # checks model metrics, promotes if thresholds met
│
├── notebooks/                  # Colab training notebooks
├── data/
│   └── schemas/                # input/output JSON schemas
├── tests/
│   └── e2e/                    # end-to-end test hitting the full deployed pipeline
├── docs/
│   ├── architecture.md         # system design explanation
│   └── tradeoffs.md            # explicit tradeoff decisions — required by rubric
│
├── CLAUDE.md                   # this file
├── README.md
└── readme_correction.md        # grading map for Dr. Ammar
```

---

## Branch Strategy

```
main          ← production only, protected, no direct push
└── develop   ← integration branch, always deployable, protected
    ├── feature/eep
    ├── feature/iep1
    ├── feature/iep2
    ├── feature/iep3
    ├── feature/infra
    ├── feature/mlops
    └── feature/tests
```

**Rules:**
- Never push directly to `main` or `develop`
- Every change goes through a PR
- `ci.yml` must pass before any PR can merge into `develop`
- `develop` merges into `main` only at sprint milestones

---

## Software Engineering Phases

### Phase 1 — CI/CD + Infrastructure (current phase)

**Goal:** full automation pipeline so every code push is automatically tested, containerized, and deployed.

**Part A — GitHub Actions**

`ci.yml` — triggers on every PR to `develop`:
- Ruff linting on all Python files
- Mypy type checking per service
- Pytest unit tests per service
- Docker build check for each service Dockerfile
- Block merge if anything fails

`integration.yml` — triggers on merge to `develop`:
- `docker-compose up` the full stack
- Hit `/health` on all 4 services — all must return 200
- Run a mock pipeline: EEP → IEP1 stub → IEP2 stub → IEP3 stub
- Verify a PDF URL is returned at the end

`deploy.yml` — triggers on merge to `main` OR manually via `workflow_dispatch`:
- Build Docker images, tag with commit SHA
- Push to container registry (GitHub Container Registry)
- Run `kubectl apply` on AWS EKS
- Requires manual approval before executing

**Part B — Docker**

- One `Dockerfile` per service (eep, iep1, iep2, iep3) — Python 3.11 slim base
- `infra/docker-compose.yml` — wires all services + PostgreSQL for local development
- Every service exposes a `/health` endpoint returning `{"status": "ok"}`

**Part C — Kubernetes**

- One `deployment.yaml` per service in `infra/k8s/`
- Each deployment: 2 replicas, liveness probe on `/health`, resource limits set
- PostgreSQL deployment with persistent volume claim
- K8s Service objects to expose each deployment internally
- Target platform: AWS EKS

---

### Phase 2 — Backend / Internal APIs

Each service becomes a real FastAPI app with working endpoints. Stubs return realistic fake data using the correct schemas. Real logic (YOLO, ST-DBSCAN, LLM) is added in later phases without changing the API contracts.

**EEP endpoints:**
- `POST /run` — manually trigger the full pipeline
- `GET /status/{run_id}` — check pipeline run status
- `GET /reports` — list generated reports
- `GET /health`

**IEP1 endpoints:**
- `POST /process` — accepts `{video_path: str}`, returns `{events: [...]}`
- `GET /health`

**IEP2 endpoints:**
- `POST /cluster` — accepts `{events: [...]}`, returns `{hotspots: [...]}`
- `GET /health`

**IEP3 endpoints:**
- `POST /generate` — accepts `{hotspots: [...], events: [...]}`, returns `{pdf_url: str}`
- `GET /health`

**PostgreSQL schema:**
- `events` table — stores IEP1 output
- `hotspots` table — stores IEP2 output
- `reports` table — stores IEP3 output with PDF URL
- `pipeline_runs` table — tracks EEP run status and timestamps

---

### Phase 3 — Frontend Dashboard

Single-page dashboard:
- Map view showing hotspot clusters with severity color coding
- Reports list with PDF download links
- Manual pipeline trigger button
- System health panel (status of each service)
- Built with React or plain HTML/JS — keep it simple

---

### Phase 4 — Model Integration

- Slot real YOLO + DeepSORT into `iep1/app/detector.py` and `iep1/app/tracker.py`
- API contract for IEP1 does not change — only the internals
- Slot real ST-DBSCAN into `iep2/app/clustering.py`
- Slot real LLM call into `iep3/app/report_generator.py`
- All other phases remain untouched

---

## Observability Requirements

Every service must expose a `/metrics` endpoint (Prometheus format) tracking:
- Request count
- Request latency (p50, p95)
- Error rate
- Service-specific: IEP1 → events detected per run, IEP2 → hotspots per run, IEP3 → report generation time

Grafana dashboards in `infra/monitoring/grafana/dashboards/` — one per service.

---

## LLM-Specific Requirements (IEP3)

- Prompts live in `iep3/prompts/` as versioned text files (`v1_report.txt`, `v2_report.txt`)
- Never edit a prompt file in place — always create a new version
- `prompt_manager.py` loads the correct version based on config
- Golden tests in `iep3/tests/golden/`: fixed input → assert that output contains required sections (Executive Summary, Hotspot Analysis, Recommendations) regardless of exact wording
- Document prompt versioning decisions in `docs/tradeoffs.md`

---

## Rubric Checklist

| Component | Location | Status |
|---|---|---|
| Architecture diagram | docs/architecture.md | done |
| Tradeoffs documented | docs/tradeoffs.md | done |
| Unit tests | */tests/ | done |
| Integration tests | .github/workflows/integration.yml | done |
| E2E tests | tests/e2e/test_e2e.py | done |
| LLM golden tests | iep3/tests/golden/test_golden.py | done |
| MLOps pipeline | mlops/promotion_logic.py, mlops/mlflow/ | done |
| Docker | */Dockerfile, infra/docker-compose.yml | done |
| Kubernetes | infra/k8s/ | done |
| CI/CD | .github/workflows/ | done |
| Observability | infra/monitoring/, all service main.py | done |
| Failure handling | eep/app/orchestrator.py | done |
| Prompt versioning | iep3/prompts/, iep3/app/prompt_manager.py | done |
| Grading map | readme_correction.md | done |

---

## Key Rules

- Never commit secrets, API keys, or `.env` files
- Never push model weights to Git — use DVC or external storage
- Every service must have a `/health` endpoint
- API schemas (input/output) are contracts — do not change them once set
- All tradeoff decisions must be written in `docs/tradeoffs.md` with justification
- `readme_correction.md` must point to every rubric component by file path

---

## Tech Stack

| Component | Technology |
|---|---|
| Services | FastAPI, Python 3.11 |
| Database | PostgreSQL |
| Detection | YOLO + DeepSORT (Phase 4) |
| Clustering | ST-DBSCAN |
| LLM | Claude API or OpenAI |
| PDF generation | ReportLab |
| Containerization | Docker |
| Orchestration | Kubernetes (AWS EKS) |
| CI/CD | GitHub Actions |
| Monitoring | Prometheus + Grafana |
| ML tracking | MLflow |

---

## Current Status

**Active phase:** Phase 3 — Frontend Dashboard

### Completed

**Phase 1 — Part B (Docker)**
- `eep/Dockerfile`, `iep1/Dockerfile`, `iep2/Dockerfile`, `iep3/Dockerfile` — Python 3.11-slim, uvicorn entrypoint; all 4 now install `curl` via `apt-get` (required for Docker healthchecks)
- `infra/docker-compose.yml` — all 4 services + PostgreSQL, healthcheck-gated `depends_on`; all 4 app services now have `healthcheck` blocks using `curl -f http://localhost:8000/health`
- `{service}/app/main.py` — FastAPI stub with `GET /health` returning `{"status": "ok"}` on each service
- `{service}/app/tests/test_health.py` — TestClient health check test per service

**Phase 1 — Part A (GitHub Actions)**
- `.github/workflows/ci.yml` — triggers on every PR to `develop`
  - `lint` job: ruff check across all services
  - `test` job: pytest per service (health tests passing)
  - `docker-build` job: matrix build for all 4 service Dockerfiles
- `.github/workflows/integration.yml` — triggers on push (merge) to `develop`
  - Builds and starts full stack via `docker compose`
  - Waits up to 120s for all 4 services to become healthy
  - Asserts `/health` returns `{"status": "ok"}` on all 4 services (ports 8001–8004)
  - Runs mock pipeline: `POST /run` on EEP → IEP1 → IEP2 → IEP3, asserts `pdf_url` returned
  - Tears down stack with `docker compose down -v`
- `pyproject.toml` — ruff config (E/F/I rules, py311 target)

**Phase 1 — Part B (Docker) — stub endpoints added**
- `eep/app/main.py` — added `POST /run` stub (calls IEP1→IEP2→IEP3, returns `{run_id, pdf_url}`)
- `iep1/app/main.py` — added `POST /process` stub (returns 2 fake violation events)
- `iep2/app/main.py` — added `POST /cluster` stub (returns 1 fake hotspot)
- `iep3/app/main.py` — added `POST /generate` stub (returns fake `pdf_url`)
- `eep/requirements.txt` — added `httpx==0.27.2` for inter-service HTTP calls
- `infra/docker-compose.yml` — added `IEP1_URL`, `IEP2_URL`, `IEP3_URL` env vars to EEP; EEP `depends_on` all three IEPs

**Phase 1 — Part A (deploy)**
- `.github/workflows/deploy.yml` — triggers on push to `main` OR manually via `workflow_dispatch`
  - Single job: builds all 4 images, pushes to GHCR tagged `latest`, runs `kubectl apply`, waits for rollouts

**Phase 1 — Part C (Kubernetes)**
- `infra/k8s/postgres-deployment.yaml` — Namespace + PVC (10Gi, `gp2` StorageClass) + Deployment (1 replica, liveness `pg_isready`, secrets via `infraguard-db-secret`)
- `infra/k8s/eep-deployment.yaml` — 2 replicas, IEP URLs as plain env vars, liveness + readiness probes on `/health`
- `infra/k8s/iep1-deployment.yaml`, `iep2-deployment.yaml`, `iep3-deployment.yaml` — 2 replicas each, liveness + readiness on `/health`, resource limits (500m CPU / 256Mi RAM)
- `infra/k8s/services/services.yaml` — EEP as `LoadBalancer` (public), IEP1/2/3 + postgres as `ClusterIP` (internal only)

### Phase 1 — CI Debugging (complete)

All services healthy, mock pipeline passes (POST /run returns run_id + pdf_url), 33/33 unit tests pass locally.

**CI fixes applied:**
- All 4 Dockerfiles — added `RUN apt-get update && apt-get install -y curl` so Docker healthchecks can execute
- `infra/docker-compose.yml` — added `healthcheck` blocks on eep, iep1, iep2, iep3 (`curl -f http://localhost:8000/health`, interval 10s, retries 5, start_period 15s); changed iep1/iep2/iep3 `depends_on` condition from `service_started` to `service_healthy`
- `eep/app/main.py` — all DB calls in `POST /run` wrapped in `try/except`; endpoint returns `run_id` + `pdf_url` even if migrations haven't run or tables don't exist yet
- `iep3/app/prompt_manager.py` — fixed `_PROMPTS_DIR` path from `os.path.join(__file__, "..", "prompts")` to `os.path.join(__file__, "prompts")` (prompts now co-located under `/app/prompts/` inside container)
- `iep3/Dockerfile` — added `COPY prompts/ prompts/` so `v1_report.txt` is present inside the container at `/app/prompts/`

**Local verification (2026-04-16):**
- 8/8 services up: eep, iep1, iep2, iep3, postgres (all healthy), prometheus, grafana, mlflow
- `POST /run` → `{"run_id": "...", "pdf_url": "https://reports.infraguard.local/runs/.../report_1hs_2ev.pdf"}`
- EEP: 11 passed, IEP1: 6 passed, IEP2: 8 passed, IEP3: 8 passed (33 total)

---

### Phase 2 — Complete

**Database foundation**
- `eep/app/alembic.ini` — Alembic config; `sqlalchemy.url` overridden at runtime from `DATABASE_URL` env var
- `eep/app/migrations/env.py` — standard Alembic env; reads `DATABASE_URL`
- `eep/app/migrations/versions/001_create_tables.py` — creates `pipeline_runs`, `events`, `hotspots`, `reports` tables with FK constraints and `ON DELETE CASCADE`
- Migrations run automatically on EEP startup via `alembic upgrade head` in the lifespan event (psycopg2-binary + SQLAlchemy for sync migration; asyncpg for all runtime queries)

**EEP — orchestrator + endpoints**
- `eep/app/db.py` — asyncpg pool management (`init_pool`, `close_pool`, `get_pool`)
- `eep/app/orchestrator.py` — `call_iep1 / call_iep2 / call_iep3` each wrapped with tenacity (3 attempts, exponential back-off 1 s → 10 s); raises `PipelineStepError` on exhaustion
- `eep/app/main.py` — async FastAPI with lifespan (migrations + pool); `POST /run` writes `pipeline_runs` (RUNNING → DONE/FAILED) and `reports`; `GET /status/{run_id}` reads `pipeline_runs`; `GET /reports` reads `reports`; degrades gracefully (503) when DB unavailable
- `eep/app/scheduler.py` — stub; pipeline is manually triggered via `POST /run`
- `eep/app/tests/test_pipeline.py` — unit tests for all three EEP endpoints (asyncpg pool mocked)
- `eep/requirements.txt` — added `asyncpg`, `tenacity`, `alembic`, `sqlalchemy`, `psycopg2-binary`

**IEP1 — violation detection**
- `iep1/app/schemas.py` — `ProcessRequest` (video_path, run_id), `ViolationEvent`, `ProcessResponse`
- `iep1/app/main.py` — async FastAPI with asyncpg pool; `POST /process` generates 2 stub events, writes to `events` table, returns `{run_id, events}`
- `iep1/app/tests/test_process.py` — unit tests (pool mocked)
- `iep1/requirements.txt` — added `asyncpg`

**IEP2 — hotspot clustering**
- `iep2/app/schemas.py` — `ClusterRequest` (events, run_id), `Hotspot`, `ClusterResponse`
- `iep2/app/main.py` — async FastAPI with asyncpg pool; `POST /cluster` produces 1 stub hotspot (centroid of input events), writes to `hotspots` table, returns `{run_id, hotspots}`
- `iep2/app/tests/test_cluster.py` — unit tests (pool mocked)
- `iep2/requirements.txt` — added `asyncpg`

**IEP3 — report generation**
- `iep3/app/schemas.py` — `GenerateRequest` (hotspots, events, run_id), `GenerateResponse`
- `iep3/app/prompt_manager.py` — `load_prompt(version)` reads versioned prompt files from `iep3/prompts/`; version controlled by `PROMPT_VERSION` env var (default: `v1`)
- `iep3/prompts/v1_report.txt` — versioned prompt with required sections: Executive Summary, Hotspot Analysis, Recommendations
- `iep3/app/main.py` — async FastAPI with asyncpg pool; `POST /generate` loads prompt (validates file exists), returns stub `pdf_url` embedding `run_id`, writes to `reports` table
- `iep3/app/tests/test_generate.py` — unit tests (pool mocked, prompt-not-found 500 path covered)
- `iep3/requirements.txt` — added `asyncpg`

**API contract additions (run_id threading)**
- All IEP `POST` request bodies now include `run_id: str` — generated by EEP and passed through the pipeline for DB row correlation
- All IEP `POST` responses now include `run_id: str` in addition to the data payload
- `docs/tradeoffs.md` updated with all Phase 2 decisions

### Remaining

**Phase 3 — Frontend Dashboard**
- Single-page dashboard (map, reports list, trigger button, health panel)
- Built with React or plain HTML/JS

**Phase 4 — Model Integration**
- Real YOLO + DeepSORT in iep1/app/detector.py / iep1/app/tracker.py
- Real ST-DBSCAN in iep2/app/clustering.py
- Real LLM call + ReportLab PDF in iep3/app/report_generator.py / iep3/app/pdf_builder.py

### Completed (Step 6)

**Observability**
- prometheus-fastapi-instrumentator wired into all 4 service main.py files
- /metrics endpoint live on all services
- infra/monitoring/prometheus.yml — scrape configs for all 4 services
- infra/monitoring/grafana/dashboards/infraguard.json — 4 panels: title, request rate, P95 latency, error rate
- Prometheus + Grafana + MLflow added to infra/docker-compose.yml

**Tests**
- iep3/tests/golden/test_golden.py — 4 golden tests: 3 section header assertions + 1 endpoint test
- tests/e2e/test_e2e.py — E2E test with pytest.mark.e2e, polls /status/{run_id} up to 10 times
- conftest.py added to all 4 service test dirs + iep3/tests/golden/ + tests/e2e/
- --import-mode=importlib added to pyproject.toml

**MLOps**
- mlops/promotion_logic.py — full MLflow promotion logic (map50 + f1 thresholds)
- mlops/requirements.txt — mlflow==2.14.1
- mlops/mlflow/mlflow.env — env vars for tracking URI, model name, thresholds

**Docs**
- docs/architecture.md — ASCII system diagram, component table, data flow, failure handling, CI/CD pipeline
- readme_correction.md — 14-row rubric → file mapping table
- docs/tradeoffs.md — includes combined pytest cross-contamination tradeoff

### Completed (Phase 3 — Docs)
- README.md — rewritten with full project overview, architecture, tech stack, run instructions, CI/CD summary, repo structure, rubric checklist
- docs/progress.md — created as engineering log covering all completed phases, decisions, challenges, and remaining work