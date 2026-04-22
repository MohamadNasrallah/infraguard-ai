# Service-Level Model Isolation Audit

Each of the four services (EEP, IEP1, IEP2, IEP3) must be its own
independently built, deployed, and scaled unit. This document records
evidence for eight isolation checks per service (32 total) against the
current state of the repository.

**Result summary: 32 / 32 PASS. No drift fixes required.**

Audit performed on branch `feature/model-isolation-audit` against
`develop`, 2026-04-23.

## Checks performed (per service)

1. Dedicated `<service>/Dockerfile` exists.
2. `infra/docker-compose.yml` has an entry with own `build:` context,
   healthcheck, and environment.
3. `infra/k8s/<service>-deployment.yaml` has unique name, own replica
   count, own resources, liveness + readiness probes on `/health`.
4. `infra/k8s/services/services.yaml` exposes the service
   (LoadBalancer for EEP, ClusterIP for IEP1/2/3).
5. `.github/workflows/ci.yml` — docker-build matrix includes the
   service.
6. `.github/workflows/deploy.yml` — the service is built, pushed to
   GHCR, and `kubectl apply`'d.
7. `.github/workflows/integration.yml` — healthchecks the service on
   its declared port.
8. EEP's `IEP{1,2,3}_URL` env vars point at correct compose and K8s
   service names (only applicable to IEP rows; EEP row checks that it
   exports these correctly).

---

## EEP (orchestration, no model)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Dedicated Dockerfile | PASS | [eep/Dockerfile](../eep/Dockerfile) — Python 3.11-slim, installs curl for healthcheck, uvicorn entrypoint |
| 2 | Compose entry with own build, healthcheck, env | PASS | [infra/docker-compose.yml:18-41](../infra/docker-compose.yml#L18-L41) — `build: ../eep`, own healthcheck (`curl -f http://localhost:8000/health`), env block includes `DATABASE_URL`, `IEP1_URL`, `IEP2_URL`, `IEP3_URL` |
| 3 | K8s deployment unique, own replicas + resources + probes | PASS | [infra/k8s/eep-deployment.yaml](../infra/k8s/eep-deployment.yaml) — `name: eep`, `replicas: 2`, CPU 100m/500m, memory 128Mi/256Mi, `livenessProbe` + `readinessProbe` both on `/health` (lines 40-52) |
| 4 | K8s service exposed | PASS | [infra/k8s/services/services.yaml:2-13](../infra/k8s/services/services.yaml#L2-L13) — `type: LoadBalancer` (public entrypoint on EKS) |
| 5 | CI docker-build matrix | PASS | [.github/workflows/ci.yml:46](../.github/workflows/ci.yml#L46) — matrix `service: [eep, iep1, iep2, iep3]`; build step at line 50 runs `docker build ./${{ matrix.service }}` |
| 6 | Deploy builds, pushes, applies, waits for rollout | PASS | [.github/workflows/deploy.yml:29-32](../.github/workflows/deploy.yml#L29-L32) (loop builds + pushes `infraguard-eep:latest` to GHCR), [.github/workflows/deploy.yml:54](../.github/workflows/deploy.yml#L54) (`kubectl apply -f infra/k8s/eep-deployment.yaml`), [.github/workflows/deploy.yml:58-60](../.github/workflows/deploy.yml#L58-L60) (rollout status loop) |
| 7 | Integration healthcheck on declared port | PASS | [.github/workflows/integration.yml:24](../.github/workflows/integration.yml#L24) — port 8001 in the loop (matches host mapping in [infra/docker-compose.yml:21](../infra/docker-compose.yml#L21)) |
| 8 | IEP URLs point at correct service names | PASS | Compose env: `IEP1_URL=http://iep1:8000`, `IEP2_URL=http://iep2:8000`, `IEP3_URL=http://iep3:8000` at [infra/docker-compose.yml:24-26](../infra/docker-compose.yml#L24-L26). K8s env: same values at [infra/k8s/eep-deployment.yaml:27-32](../infra/k8s/eep-deployment.yaml#L27-L32). Compose service names (`iep1`, `iep2`, `iep3`) and K8s Service names (at [services.yaml:18-56](../infra/k8s/services/services.yaml#L18-L56)) match exactly. |

---

## IEP1 (YOLO + DeepSORT)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Dedicated Dockerfile | PASS | [iep1/Dockerfile](../iep1/Dockerfile) — Python 3.11-slim, own requirements, uvicorn entrypoint |
| 2 | Compose entry with own build, healthcheck, env | PASS | [infra/docker-compose.yml:43-57](../infra/docker-compose.yml#L43-L57) — `build: ../iep1`, port 8002:8000, own healthcheck, `DATABASE_URL` |
| 3 | K8s deployment unique, own replicas + resources + probes | PASS | [infra/k8s/iep1-deployment.yaml](../infra/k8s/iep1-deployment.yaml) — `name: iep1`, `replicas: 2`, CPU 100m/500m, memory 128Mi/256Mi, liveness + readiness on `/health` (lines 34-46) |
| 4 | K8s service exposed | PASS | [infra/k8s/services/services.yaml:18-28](../infra/k8s/services/services.yaml#L18-L28) — `type: ClusterIP` (internal only) |
| 5 | CI docker-build matrix | PASS | [.github/workflows/ci.yml:46](../.github/workflows/ci.yml#L46) — matrix includes `iep1` |
| 6 | Deploy builds, pushes, applies, waits for rollout | PASS | [.github/workflows/deploy.yml:29-32](../.github/workflows/deploy.yml#L29-L32) (build+push loop), [.github/workflows/deploy.yml:51](../.github/workflows/deploy.yml#L51) (`kubectl apply -f infra/k8s/iep1-deployment.yaml`), [.github/workflows/deploy.yml:58-60](../.github/workflows/deploy.yml#L58-L60) (rollout) |
| 7 | Integration healthcheck on declared port | PASS | [.github/workflows/integration.yml:24](../.github/workflows/integration.yml#L24) — port 8002 in the loop (matches [infra/docker-compose.yml:46](../infra/docker-compose.yml#L46)) |
| 8 | EEP reaches IEP1 at correct name | PASS | `IEP1_URL=http://iep1:8000` resolves to compose service `iep1` at [infra/docker-compose.yml:43](../infra/docker-compose.yml#L43) and K8s Service `iep1` at [services.yaml:20](../infra/k8s/services/services.yaml#L20) |

---

## IEP2 (ST-DBSCAN clustering)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Dedicated Dockerfile | PASS | [iep2/Dockerfile](../iep2/Dockerfile) — Python 3.11-slim, own requirements, uvicorn entrypoint |
| 2 | Compose entry with own build, healthcheck, env | PASS | [infra/docker-compose.yml:59-73](../infra/docker-compose.yml#L59-L73) — `build: ../iep2`, port 8003:8000, own healthcheck, `DATABASE_URL` |
| 3 | K8s deployment unique, own replicas + resources + probes | PASS | [infra/k8s/iep2-deployment.yaml](../infra/k8s/iep2-deployment.yaml) — `name: iep2`, `replicas: 2`, CPU 100m/500m, memory 128Mi/256Mi, liveness + readiness on `/health` (lines 34-46) |
| 4 | K8s service exposed | PASS | [infra/k8s/services/services.yaml:32-42](../infra/k8s/services/services.yaml#L32-L42) — `type: ClusterIP` |
| 5 | CI docker-build matrix | PASS | [.github/workflows/ci.yml:46](../.github/workflows/ci.yml#L46) — matrix includes `iep2` |
| 6 | Deploy builds, pushes, applies, waits for rollout | PASS | [.github/workflows/deploy.yml:29-32](../.github/workflows/deploy.yml#L29-L32), [.github/workflows/deploy.yml:52](../.github/workflows/deploy.yml#L52) (`kubectl apply -f infra/k8s/iep2-deployment.yaml`), [.github/workflows/deploy.yml:58-60](../.github/workflows/deploy.yml#L58-L60) (rollout) |
| 7 | Integration healthcheck on declared port | PASS | [.github/workflows/integration.yml:24](../.github/workflows/integration.yml#L24) — port 8003 (matches [infra/docker-compose.yml:62](../infra/docker-compose.yml#L62)) |
| 8 | EEP reaches IEP2 at correct name | PASS | `IEP2_URL=http://iep2:8000` resolves to compose service `iep2` at [infra/docker-compose.yml:59](../infra/docker-compose.yml#L59) and K8s Service `iep2` at [services.yaml:34](../infra/k8s/services/services.yaml#L34) |

---

## IEP3 (LLM report generation)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Dedicated Dockerfile | PASS | [iep3/Dockerfile](../iep3/Dockerfile) — Python 3.11-slim, also copies `prompts/` into the image so `prompt_manager.py` can load versioned prompts |
| 2 | Compose entry with own build, healthcheck, env | PASS | [infra/docker-compose.yml:75-89](../infra/docker-compose.yml#L75-L89) — `build: ../iep3`, port 8004:8000, own healthcheck, `DATABASE_URL` |
| 3 | K8s deployment unique, own replicas + resources + probes | PASS | [infra/k8s/iep3-deployment.yaml](../infra/k8s/iep3-deployment.yaml) — `name: iep3`, `replicas: 2`, CPU 100m/500m, memory 128Mi/256Mi, liveness + readiness on `/health` (lines 34-46) |
| 4 | K8s service exposed | PASS | [infra/k8s/services/services.yaml:46-56](../infra/k8s/services/services.yaml#L46-L56) — `type: ClusterIP` |
| 5 | CI docker-build matrix | PASS | [.github/workflows/ci.yml:46](../.github/workflows/ci.yml#L46) — matrix includes `iep3` |
| 6 | Deploy builds, pushes, applies, waits for rollout | PASS | [.github/workflows/deploy.yml:29-32](../.github/workflows/deploy.yml#L29-L32), [.github/workflows/deploy.yml:53](../.github/workflows/deploy.yml#L53) (`kubectl apply -f infra/k8s/iep3-deployment.yaml`), [.github/workflows/deploy.yml:58-60](../.github/workflows/deploy.yml#L58-L60) (rollout) |
| 7 | Integration healthcheck on declared port | PASS | [.github/workflows/integration.yml:24](../.github/workflows/integration.yml#L24) — port 8004 (matches [infra/docker-compose.yml:78](../infra/docker-compose.yml#L78)) |
| 8 | EEP reaches IEP3 at correct name | PASS | `IEP3_URL=http://iep3:8000` resolves to compose service `iep3` at [infra/docker-compose.yml:75](../infra/docker-compose.yml#L75) and K8s Service `iep3` at [services.yaml:48](../infra/k8s/services/services.yaml#L48) |

---

## Non-blocking observations (not failures, recorded for context)

- **Identical replica counts and resource limits across IEP1/IEP2/IEP3.**
  All three deployments currently set `replicas: 2`, CPU 100m/500m,
  memory 128Mi/256Mi. The check only requires that each deployment
  owns its values independently, which it does — they can diverge
  later without touching shared config. Current uniformity reflects
  the stub-workload phase; Phase 4 (real YOLO + DeepSORT in IEP1) is
  where IEP1 will likely need higher limits than IEP2/IEP3.
- **Architecture is symmetric by design.** Every service exposes
  `/health` on container port 8000 and is mapped to a distinct host
  port (8001–8004). This symmetry is a convenience, not a coupling;
  each port, deployment, and image is declared independently.
- **Isolation is verifiable at four layers**: image (Dockerfile per
  service), local orchestration (compose service per service), cluster
  orchestration (K8s Deployment + Service per service), and CI
  (matrix build + per-service test job + per-service rollout wait).
