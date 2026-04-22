# InfraGuard AI — Tradeoff Decisions

## CI/CD and Infrastructure Tradeoffs

**mypy --strict removed**
Strict type checking adds friction without proportional benefit for a 2-person team at this scale. Type safety is enforced through Pydantic models on all API contracts instead, which catches the same class of errors at the system boundary where it matters.

**SHA-pinned image tags removed**
The `latest` tag is sufficient at this project scope. Rollback is handled at the git level — revert the commit and redeploy. SHA-pinned tags add traceability overhead that only pays off in larger teams with multiple concurrent releases.

**Manual deploy approval gate removed**
A 2-person team coordinates verbally. The `environment: production` gate in GitHub Actions adds ceremony without a meaningful safety benefit when the team is small enough to communicate directly before every deploy.

**Bash retry loop replaced with `sleep 15`**
The associative array pattern (`declare -A`) in the integration workflow was unreadable and non-obvious. A fixed 15-second wait is honest about what it does, easy to adjust, and sufficient for containers that start in under 10 seconds in CI.

**Single-job deploy workflow**
Splitting build and deploy into separate jobs with `$GITHUB_OUTPUT` passing the image tag added complexity with no gain at this project size. A single linear job is easier to read, debug, and maintain.

## Prompt Versioning (IEP3)

Prompts are stored as versioned text files (`v1_report.txt`, `v2_report.txt`, etc.) rather than in a database or inline in code. This keeps prompts auditable in git history, allows rollback by config change, and separates prompt iteration from code deployments. The tradeoff is that changing a prompt requires a code commit rather than an admin UI action — acceptable for a small team.

---

## Phase 2 — Backend / Internal APIs

**asyncpg over SQLAlchemy ORM**
asyncpg is a bare-metal async PostgreSQL driver with no ORM layer. For this project's read/write patterns (insert rows, fetch by run_id), raw SQL with $N placeholders is more readable and faster than building SQLAlchemy models. The tradeoff is no schema-level migration safety from the ORM — this is mitigated by Alembic managing all schema changes.

**Alembic + psycopg2-binary for migrations, asyncpg for runtime**
Alembic's migration engine is synchronous (built on SQLAlchemy + psycopg2). Rather than replacing the standard Alembic toolchain with an async alternative, we use psycopg2-binary only at startup for migrations and asyncpg for all runtime queries. This keeps migrations orthodox (Alembic docs, community examples all assume sync) while keeping request-path I/O fully async. The cost is two DB drivers in eep/requirements.txt.

**Migrations run on EEP startup (not as a separate init container)**
Running `alembic upgrade head` inside EEP's lifespan event is simpler than adding a K8s init container and avoids a separate deploy step. The tradeoff is that every EEP replica races to run migrations on startup — Alembic's version table uses an advisory lock on Postgres, so concurrent migrations are safe. For larger teams, a dedicated migration job would be preferable.

**run_id passed through request bodies (not DB-only correlation)**
IEP1, IEP2, and IEP3 receive `run_id` in the POST body rather than reading it back from Postgres. This keeps IEPs stateless and the call path simple: EEP generates the UUID, each IEP writes its rows using that ID, and EEP reads results from the responses. The tradeoff is that IEPs don't validate that the run_id exists in `pipeline_runs` before inserting — acceptable since EEP always inserts the run before calling any IEP.

**tenacity retry policy: 3 attempts, exponential back-off (1 s → 10 s)**
Three attempts covers transient network glitches and container-restart races without blocking the pipeline indefinitely. Exponential back-off (1 s, 2 s, 4 s capped at 10 s) reduces thundering-herd pressure during partial outages. A higher attempt count would increase worst-case latency proportionally — not worthwhile for a daily-batch workload.

**Degraded mode: DB optional at startup**
If `DATABASE_URL` is empty or Postgres is unreachable, EEP starts and serves requests without a DB pool. In degraded mode, `/run` still returns a valid response (the pipeline still calls IEPs); `/status` and `/reports` return 503. This allows running the stack locally without Postgres for quick iteration. The tradeoff is that data is silently not persisted — degraded mode is development-only and must not reach production.

## Combined Test Run Cross-Contamination

Running all 4 test suites in a single pytest process causes sys.path
collisions between identically-named modules (main, db, schemas) across
services. Each suite passes fully in isolation (11+6+8+8 = 33 tests).
CI runs them per-service, not combined. Fix would require namespace
packages or separate virtual environments per service — unnecessary
complexity for this project scope.

## Service-level model isolation

Each IEP is its own Docker image, compose service, and Kubernetes
deployment. The boundary is one model domain per service: IEP1 owns
detection + tracking, IEP2 owns clustering, IEP3 owns LLM reporting,
EEP owns orchestration. This lets each model be rebuilt, rolled out,
and rolled back independently — a failure in the LLM path cannot
block detection, and scaling detection up does not force clustering
to scale with it.

We do **not** split further. YOLO and DeepSORT stay inside IEP1
because they are tightly coupled in the inference path: DeepSORT
consumes YOLO's bounding boxes frame-by-frame, and splitting them
across containers would force every frame's detections over the
network for no scaling benefit at our batch workload. The same logic
would apply to any future attempt to split IEP3's prompt loading from
PDF rendering — co-location is correct when the data path is tight.

Per-model engineering depth is delivered at the lifecycle layer,
not by multiplying containers. `mlops/promotion_logic.py` applies
per-model metric thresholds (YOLO mAP@0.5, F1) to promote versions
in MLflow, and Grafana dashboards render per-service request rate,
P95 latency, and error rate scraped from each service's `/metrics`
endpoint. The combination — one image per model service, MLflow for
offline lifecycle, Grafana for online behavior — covers scalability,
deployment, and observability without container sprawl.