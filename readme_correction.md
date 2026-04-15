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
| Docker | */Dockerfile, infra/docker-compose.yml | Python 3.11-slim, all services + monitoring |
| Kubernetes | infra/k8s/ | 2 replicas, liveness/readiness probes, resource limits |
| CI/CD | .github/workflows/ | ci.yml + integration.yml + deploy.yml |
| Observability | infra/monitoring/, all service main.py | Prometheus /metrics + Grafana dashboards |
| Failure handling | eep/app/orchestrator.py | tenacity 3 retries, exponential backoff, PipelineStepError |
| Prompt versioning | iep3/prompts/, iep3/app/prompt_manager.py | Versioned prompt files, PROMPT_VERSION env var |
| Robustness | All service main.py | 503 degradation without DB, not crash |