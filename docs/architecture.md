# InfraGuard AI — Architecture

## System Overview

```
                        ┌─────────────────────────────────────────┐
                        │              AWS EKS Cluster             │
                        │                                          │
  Daily Trigger ──────► │  ┌─────┐    ┌──────┐    ┌──────┐       │
  (APScheduler)         │  │ EEP │───►│ IEP1 │───►│ IEP2 │       │
                        │  │     │    │YOLO/ │    │ST-   │       │
  Manual Trigger ──────►│  │Orch-│    │Deep  │    │DBSCAN│       │
  POST /run             │  │estr-│    │SORT  │    │      │       │
                        │  │ator │    │      │    │      │       │
                        │  └──┬──┘    └──────┘    └──┬───┘       │
                        │     │                       │           │
                        │     │       ┌──────┐        │           │
                        │     └──────►│ IEP3 │◄───────┘           │
                        │             │ LLM  │                    │
                        │             │Report│                    │
                        │             └──────┘                    │
                        │                  │                      │
                        │          ┌───────▼──────┐               │
                        │          │  PostgreSQL  │               │
                        │          │  (pipeline   │               │
                        │          │   runs,      │               │
                        │          │   events,    │               │
                        │          │   hotspots,  │               │
                        │          │   reports)   │               │
                        │          └──────────────┘               │
                        └─────────────────────────────────────────┘
```

## Component Responsibilities

| Service | Port | Responsibility |
|---------|------|----------------|
| EEP | 8000 | Orchestrator + APScheduler daily trigger |
| IEP1 | 8001 | Video ingestion, YOLO detection, DeepSORT tracking |
| IEP2 | 8002 | ST-DBSCAN hotspot clustering |
| IEP3 | 8003 | LLM report generation, PDF output |
| PostgreSQL | 5432 | Persistent storage for all pipeline data |
| Prometheus | 9090 | Metrics scraping from all services |
| Grafana | 3000 | Dashboards and alerting |
| MLflow | 5000 | Model experiment tracking and registry |

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
