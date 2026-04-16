# InfraGuard AI

InfraGuard AI is a production-oriented road safety system that processes pre-recorded traffic videos daily, detects violations, clusters dangerous hotspots, and generates a PDF recommendation report using an LLM. It is built as an academic capstone project graded on engineering depth, robustness, and evidence of real deployment practices — CI/CD, containerization, Kubernetes orchestration, observability, and MLOps are all implemented from the ground up.

---

## Architecture Overview

```
Daily Trigger (EEP scheduler)
        |
      EEP                     <- orchestrator, sequences the pipeline, handles failures
        |
     IEP1                     <- accepts video path, detects violations (YOLO + DeepSORT)
                               -> stores structured events to PostgreSQL
        |
     IEP2                     <- pulls events from PostgreSQL
                               -> clusters hotspots using ST-DBSCAN
                               -> stores hotspots to PostgreSQL
        |
     IEP3                     <- pulls hotspots + raw events from PostgreSQL
                               -> calls LLM to generate report
                               -> outputs PDF report URL
        |
      EEP                     <- stores report reference, returns download URL
```

| Service    | Role                                                                 |
|------------|----------------------------------------------------------------------|
| **EEP**    | Orchestrator. Sequences IEP1 -> IEP2 -> IEP3, retries on failure, tracks pipeline runs in PostgreSQL. |
| **IEP1**   | Video ingestion and violation detection using YOLO + DeepSORT. Writes structured events to the database. |
| **IEP2**   | Hotspot clustering using ST-DBSCAN. Groups violation events into geographic clusters with severity scores. |
| **IEP3**   | Report generation. Loads a versioned LLM prompt, generates a safety report, and outputs a PDF via ReportLab. |
| **PostgreSQL** | Persistent storage for pipeline runs, events, hotspots, and reports. |

---

## Tech Stack

| Component       | Technology                  |
|-----------------|-----------------------------|
| Services        | FastAPI, Python 3.11        |
| Database        | PostgreSQL                  |
| Detection       | YOLO + DeepSORT             |
| Clustering      | ST-DBSCAN                   |
| LLM             | Claude API                  |
| PDF generation  | ReportLab                   |
| Containerization| Docker                      |
| Orchestration   | Kubernetes (AWS EKS)        |
| CI/CD           | GitHub Actions              |
| Monitoring      | Prometheus + Grafana        |
| ML tracking     | MLflow                      |

---

## How to Run Locally

```bash
git clone https://github.com/<your-org>/infraguard-ai.git
cd infraguard-ai/infra
docker compose up --build
```

Once all services are healthy, trigger the pipeline:

```bash
curl -X POST http://localhost:8001/run
```

This returns a JSON response with `run_id` and `pdf_url`.

---

## How CI/CD Works

Every pull request targeting `develop` triggers `ci.yml`, which runs Ruff linting, Pytest unit tests per service, and a Docker build check for all four Dockerfiles — the PR is blocked if anything fails. When a PR merges into `develop`, `integration.yml` starts the full stack via Docker Compose, waits for all services to become healthy, hits `/health` on each, runs the mock pipeline end-to-end, and verifies a `pdf_url` is returned. When `develop` merges into `main`, `deploy.yml` builds all images, pushes them to GitHub Container Registry, and applies the Kubernetes manifests to AWS EKS.

---

## Repository Structure

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

## Rubric Components

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
