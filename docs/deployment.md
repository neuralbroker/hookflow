# HookFlow deployment

## Local (SQLite, no Redis)

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload      # /docs, /health, /ready, /metrics, /v1/stats
python -m app.worker               # separate terminal
```

## Full stack (Postgres + Redis)

```bash
docker compose -f docker/docker-compose.yml up --build
# app: :8000, postgres: :5432, redis: :6379
```

`DATABASE_URL=postgresql+psycopg://hookflow:hookflow@postgres:5432/hookflow`
`REDIS_URL=redis://redis:6379/0`

## AWS minimal (what "I can operate this" means)

- RDS Postgres (db.t4g.micro to start) + ElastiCache Redis (or self-hosted
  Redis on EC2 if cost matters) + EC2/ECS for `app` + `worker` as separate
  processes. Secrets in AWS Secrets Manager → env vars. ALB terminates TLS.
- CloudWatch: scrape `/metrics`, alert on `queue_depth` (via `/v1/stats`)
  growth + DLQ count + worker restarts + 5xx rate.
- Backups: RDS automated snapshots. Redis holds only wake-up hints (safe to lose).

## Operate

- Health: `/health` (liveness), `/ready` (DB + Redis checks).
- Observe: `/metrics` (ingest/dedupe/requeue counters), `/v1/stats` (by_status + queue_depth).
- Recover: DLQ → `POST /v1/deliveries/{id}/requeue`.
