# InfraGuard AI — Grading Map

Maps every rubric component to the exact file and line where it is implemented.

| Rubric Component | Location | Detail |
|---|---|---|
| Architecture diagram | docs/architecture.md | Full system diagram with all services |
| Tradeoffs documented | docs/tradeoffs.md | 6 Phase 2 decisions + CI/CD tradeoffs |
| Unit tests | eep/app/tests/, iep1/app/tests/, iep2/app/tests/, iep3/app/tests/ | 9+5+6+6 = 26 tests total |
| Integration tests | .github/workflows/integration.yml | Full stack health check on merge to develop |
| E2E tests | tests/e2e/test_e2e.py | Hits deployed EEP /run, polls to completion |
| LLM golden tests | iep3/tests/golden/test_golden.py | Fixed input, asserts 3 required sections present |
| MLOps pipeline | mlops/promotion_logic.py, mlops/mlflow/ | MLflow promotion logic with map50 + f1 thresholds |
| Docker | eep/Dockerfile, iep1/Dockerfile, iep2/Dockerfile, iep3/Dockerfile, infra/docker-compose.yml | Four services → four independent Docker images (Python 3.11-slim). Compose wires all four + postgres + prometheus + grafana + mlflow with healthcheck-gated `depends_on`. Isolation verified in docs/model_isolation_audit.md. |
| Kubernetes | infra/k8s/eep-deployment.yaml, infra/k8s/iep1-deployment.yaml, infra/k8s/iep2-deployment.yaml, infra/k8s/iep3-deployment.yaml, infra/k8s/postgres-deployment.yaml, infra/k8s/services/services.yaml | One deployment manifest per service (4 app + 1 db). Each: 2 replicas, liveness + readiness on `/health`, own resources. EEP exposed via LoadBalancer; IEPs + postgres via ClusterIP. |
| CI/CD | .github/workflows/ | ci.yml + integration.yml + deploy.yml |
| Observability | infra/monitoring/, all service main.py | Prometheus /metrics + Grafana dashboards |
| Failure handling | eep/app/orchestrator.py | tenacity 3 retries, exponential backoff, PipelineStepError |
| Prompt versioning | iep3/prompts/, iep3/app/prompt_manager.py | Versioned prompt files, PROMPT_VERSION env var |
| Robustness | All service main.py | 503 degradation without DB, not crash |
| Model isolation audit | docs/model_isolation_audit.md | 32 PASS/FAIL checks (4 services × 8) with file:line evidence for Dockerfile, compose entry, K8s deployment, K8s service, CI build, deploy, integration healthcheck, and EEP→IEP URL wiring |