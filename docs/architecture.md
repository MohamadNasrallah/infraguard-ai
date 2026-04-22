# InfraGuard AI — Architecture

## System Overview

```
                   ┌──────────────────────────────────────────────────┐
                   │                  AWS EKS Cluster                  │
                   │                                                   │
 Daily Trigger ──► │  ┌──────────────┐       ┌──────────────┐         │
 (APScheduler)     │  │   Service:   │──────►│   Service:   │         │
                   │  │     EEP      │       │    IEP1      │         │
 Manual Trigger ──►│  │ image: eep   │       │ image: iep1  │         │
 POST /run         │  │ (orchestrator│       │ YOLO +       │         │
                   │  │  — no model) │       │ DeepSORT     │         │
                   │  └──┬─────────┬─┘       └──────┬───────┘         │
                   │     │         │                │                  │
                   │     │         │                ▼                  │
                   │     │         │         ┌──────────────┐         │
                   │     │         └────────►│   Service:   │         │
                   │     │                   │    IEP2      │         │
                   │     │                   │ image: iep2  │         │
                   │     │                   │ ST-DBSCAN    │         │
                   │     │                   └──────┬───────┘         │
                   │     │                          │                  │
                   │     ▼                          ▼                  │
                   │  ┌──────────────┐       ┌──────────────┐         │
                   │  │   Service:   │◄──────│   Service:   │         │
                   │  │    IEP3      │       │    (data     │         │
                   │  │ image: iep3  │       │    flow)     │         │
                   │  │ LLM + PDF    │       └──────────────┘         │
                   │  └──────┬───────┘                                 │
                   │         │                                         │
                   │         ▼                                         │
                   │  ┌───────────────────────────────┐               │
                   │  │          PostgreSQL           │               │
                   │  │ pipeline_runs, events,        │               │
                   │  │ hotspots, reports             │               │
                   │  └───────────────────────────────┘               │
                   └──────────────────────────────────────────────────┘
```

*Four services, four Docker images, four K8s deployments.* Each box
above is a distinct `<service>/Dockerfile` built by CI, pushed to GHCR
as `infraguard-<service>:latest`, and applied as
`infra/k8s/<service>-deployment.yaml`. MLflow, Prometheus, and Grafana
are observability/lifecycle systems around the pipeline, not pipeline
stages, and are omitted from this diagram.

## Component Responsibilities

| Service | Image | Dockerfile | K8s Deployment | Host Port | Responsibility |
|---------|-------|------------|----------------|-----------|----------------|
| EEP | `infraguard-eep` | `eep/Dockerfile` | `infra/k8s/eep-deployment.yaml` | 8001 | Orchestrator + APScheduler daily trigger |
| IEP1 | `infraguard-iep1` | `iep1/Dockerfile` | `infra/k8s/iep1-deployment.yaml` | 8002 | Video ingestion, YOLO detection, DeepSORT tracking |
| IEP2 | `infraguard-iep2` | `iep2/Dockerfile` | `infra/k8s/iep2-deployment.yaml` | 8003 | ST-DBSCAN hotspot clustering |
| IEP3 | `infraguard-iep3` | `iep3/Dockerfile` | `infra/k8s/iep3-deployment.yaml` | 8004 | LLM report generation, PDF output |
| PostgreSQL | `postgres:15` | — | `infra/k8s/postgres-deployment.yaml` | 5432 | Persistent storage for all pipeline data |
| Prometheus | `prom/prometheus` | — | (local compose only) | 9090 | Metrics scraping from all services |
| Grafana | `grafana/grafana` | — | (local compose only) | 3000 | Dashboards and alerting |
| MLflow | `ghcr.io/mlflow/mlflow` | — | (local compose only) | 5000 | Model experiment tracking and registry |

## Data Flow

1. EEP receives trigger (scheduled or manual POST /run)
2. EEP calls IEP1 with video_path → receives events[]
3. EEP calls IEP2 with events[] → receives hotspots[]
4. EEP calls IEP3 with hotspots[] + events[] → receives pdf_url
5. Each step writes to PostgreSQL via asyncpg
6. EEP stores final run record with status "completed"

## Failure Handling

- EEP retries each IEP call 3 times with exponential backoff (tenacity)
- Services return 503 (not crash) when DB is unavailable
- Kubernetes liveness probes restart unhealthy pods automatically
- Kubernetes readiness probes withhold traffic until pods are ready

## CI/CD Pipeline

```
feature/* ──► PR ──► ci.yml (lint + test + docker build)
                         │
                    merge to develop
                         │
               integration.yml (full stack health check)
                         │
                    merge to main
                         │
                deploy.yml (build + push to GHCR + kubectl apply)
```
