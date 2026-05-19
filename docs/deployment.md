# Deployment

## Production checklist

- [ ] Rotate `JWT_SECRET` (`openssl rand -hex 32`).
- [ ] Change the seeded admin password immediately.
- [ ] Set `APP_DEBUG=false`, `APP_ENV=production`.
- [ ] Configure `CORS_ORIGINS` explicitly (no `*`).
- [ ] `BILLING_PROVIDER=stripe` + real `STRIPE_API_KEY` + webhook secret.
- [ ] Webhook URL configured in the provider dashboard, signing secret matches.
- [ ] Postgres backups (PITR if possible). DB is the source of truth.
- [ ] Redis replication or accept ephemeral cache loss (rate-limit + reminder
      dedupe will reset, no data loss).
- [ ] Run `alembic upgrade head` as a pre-deploy step.
- [ ] Two replicas minimum behind a load balancer.
- [ ] One worker replica minimum.
- [ ] Health checks: `/health` (liveness), `/ready` (readiness, includes DB +
      Redis).
- [ ] Log shipping picks up stdout JSON.
- [ ] Set `API_WORKERS` to `(2 × cores) + 1` for gunicorn.

## Sample container args

```
gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 -b 0.0.0.0:8000 \
  --access-logfile - --error-logfile - \
  --timeout 30 --graceful-timeout 30 --keep-alive 5
```

## Database tuning

- `max_connections` ≥ `(api_workers × pool_size) + worker_pool` with headroom.
- `pgbouncer` in transaction-pool mode in front if you scale wide.
- Indexes provided cover the obvious hot paths. After 6 months in prod, run
  `EXPLAIN ANALYZE` on top 10 queries and add covering indexes as needed.

## Secrets

Read from your secret manager (AWS Secrets Manager, Vault, Doppler). Never
bake into images. `pydantic-settings` will read env vars in any order.

## Observability

- structlog JSON → ship via your log agent (Vector, Fluent Bit).
- Metrics: add `prometheus-fastapi-instrumentator` if you want `/metrics`.
- Traces: add `opentelemetry-instrumentation-fastapi` +
  `…-sqlalchemy` and an OTLP exporter.

## Zero-downtime migrations

- Additive only on the deploy that runs the migration (new column nullable,
  new index `CONCURRENTLY`).
- Backfill in a second deploy.
- Switch reads/writes in a third deploy.
- Drop the old shape in a fourth deploy.

Never combine schema break + code break in a single release.
