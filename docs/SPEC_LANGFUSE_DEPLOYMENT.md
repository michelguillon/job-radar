# SPEC_LANGFUSE_DEPLOYMENT.md
## Langfuse — Self-Hosted Deployment on M720q

**Status:** Deployed ✅
**Target host:** Lenovo M720q, Ubuntu Server 24.04, Docker + Caddy + Cloudflare
**Public URL:** https://langfuse.michel-portfolio.co.uk
**Cloudflare DNS:** already configured
**Deployed:** 2026-06-12

> **Note:** This spec was originally written against Langfuse v2-era env vars.
> Section 3 below reflects the corrected v3 compose file that actually works.
> The original spec had wrong variable names for S3/MinIO, missing ClickHouse
> credentials, wrong CLICKHOUSE_MIGRATION_URL protocol, and missing
> CLICKHOUSE_CLUSTER_ENABLED. See Learning Notes for full details.

---

## 1. Why self-hosted

- Trace data (prompts, completions, JD content, CV excerpts) stays on
  the M720q — no third party sees it
- No per-trace pricing at any volume
- PostgreSQL + ClickHouse directly queryable for custom analysis
- MIT licensed — no feature gates
- M720q has confirmed headroom: ~13.7GB free RAM, Langfuse v3 needs 4–6GB

---

## 2. Architecture

Langfuse v3 runs as six Docker containers alongside the existing apps:

| Container | Purpose | Notes |
|---|---|---|
| `langfuse-web` | UI + REST API | Port 3000 internally |
| `langfuse-worker` | Async trace ingestion | Reads from Redis queue, port 3030 |
| `langfuse-postgres` | Metadata, users, projects, API keys | Persistent volume |
| `langfuse-clickhouse` | Trace analytics store | Persistent volume — heavyweight |
| `langfuse-redis` | Queue + API key cache | Ephemeral, no persistence needed |
| `langfuse-minio` | Blob storage for trace batches | Persistent volume |

Caddy handles TLS termination and reverse proxies
`langfuse.michel-portfolio.co.uk` → `langfuse-web:3000`.

All containers join the existing `caddy` Docker network so Caddy can
reach `langfuse-web` by container name.

**Deployment path:** `/opt/apps/langfuse/` (consistent with all other
apps on M720q — not `~/langfuse/` as originally specced).

---

## 3. Docker Compose

File lives at `/opt/apps/langfuse/docker-compose.yml`.

> **v3 gotchas vs original spec:**
> - Images pinned to `:3` not `:latest` — avoids accidental v4 upgrades
> - S3 env vars renamed: `LANGFUSE_S3_EVENT_UPLOAD_*` not `LANGFUSE_S3_*`
> - MinIO requires `LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"`
> - Redis connection: `REDIS_HOST` + `REDIS_PORT` not `REDIS_CONNECTION_STRING`
> - ClickHouse needs credentials on the container itself AND in web/worker
> - `CLICKHOUSE_MIGRATION_URL` uses `clickhouse://` protocol on port 9000, not `http://` on 8123
> - `CLICKHOUSE_CLUSTER_ENABLED: "false"` required — default assumes Zookeeper cluster

```yaml
# /opt/apps/langfuse/docker-compose.yml
# Langfuse v3 self-hosted — M720q
# Start: docker compose up -d
# Stop:  docker compose down (data persists in volumes)

services:

  langfuse-web:
    image: langfuse/langfuse:3
    restart: unless-stopped
    depends_on:
      - langfuse-postgres
      - langfuse-redis
      - langfuse-minio
      - langfuse-clickhouse
    environment:
      DATABASE_URL: postgresql://langfuse:${POSTGRES_PASSWORD}@langfuse-postgres:5432/langfuse
      NEXTAUTH_URL: https://langfuse.michel-portfolio.co.uk
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      SALT: ${SALT}
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
      CLICKHOUSE_URL: http://langfuse-clickhouse:8123
      CLICKHOUSE_MIGRATION_URL: clickhouse://langfuse-clickhouse:9000
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: clickhouse
      CLICKHOUSE_CLUSTER_ENABLED: "false"
      REDIS_HOST: langfuse-redis
      REDIS_PORT: "6379"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
      LANGFUSE_S3_EVENT_UPLOAD_REGION: us-east-1
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: ${MINIO_ACCESS_KEY}
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: ${MINIO_SECRET_KEY}
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://langfuse-minio:9000
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
      AUTH_DISABLE_SIGNUP: "false"   # set to "true" after first admin account created

  langfuse-worker:
    image: langfuse/langfuse-worker:3
    restart: unless-stopped
    depends_on:
      - langfuse-postgres
      - langfuse-redis
      - langfuse-clickhouse
      - langfuse-minio
    environment:
      DATABASE_URL: postgresql://langfuse:${POSTGRES_PASSWORD}@langfuse-postgres:5432/langfuse
      SALT: ${SALT}
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
      CLICKHOUSE_URL: http://langfuse-clickhouse:8123
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: clickhouse
      CLICKHOUSE_CLUSTER_ENABLED: "false"
      REDIS_HOST: langfuse-redis
      REDIS_PORT: "6379"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
      LANGFUSE_S3_EVENT_UPLOAD_REGION: us-east-1
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: ${MINIO_ACCESS_KEY}
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: ${MINIO_SECRET_KEY}
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://langfuse-minio:9000
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"

  langfuse-postgres:
    image: postgres:15
    restart: unless-stopped
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-postgres-data:/var/lib/postgresql/data

  langfuse-clickhouse:
    image: clickhouse/clickhouse-server:24
    restart: unless-stopped
    environment:
      CLICKHOUSE_DB: default
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: clickhouse
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    volumes:
      - langfuse-clickhouse-data:/var/lib/clickhouse
      - ./clickhouse-config.xml:/etc/clickhouse-server/config.d/custom.xml:ro

  langfuse-redis:
    image: redis:7-alpine
    restart: unless-stopped
    # No persistence — Redis is a queue/cache, not a data store here

  langfuse-minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    volumes:
      - langfuse-minio-data:/data

networks:
  default:
    name: caddy
    external: true

volumes:
  langfuse-postgres-data:
  langfuse-clickhouse-data:
  langfuse-minio-data:
```

---

## 4. ClickHouse memory config

Create `/opt/apps/langfuse/clickhouse-config.xml` to cap memory usage on the
M720q. Without this, ClickHouse may claim more RAM than needed:

```xml
<clickhouse>
  <max_server_memory_usage_to_ram_ratio>0.25</max_server_memory_usage_to_ram_ratio>
</clickhouse>
```

This caps ClickHouse at 25% of available RAM (~3.9GB on the M720q).
Sufficient for this trace volume.

---

## 5. Environment file

Create `/opt/apps/langfuse/.env`:

```bash
# PostgreSQL
POSTGRES_PASSWORD=<generate: openssl rand -hex 32>

# MinIO
MINIO_ACCESS_KEY=langfuse
MINIO_SECRET_KEY=<generate: openssl rand -hex 32>

# NextAuth (Langfuse web auth)
NEXTAUTH_SECRET=<generate: openssl rand -hex 32>

# Langfuse encryption
SALT=<generate: openssl rand -hex 32>
ENCRYPTION_KEY=<generate: openssl rand -hex 32>
```

Generate all secrets in one go:
```bash
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)"
echo "MINIO_SECRET_KEY=$(openssl rand -hex 32)"
echo "NEXTAUTH_SECRET=$(openssl rand -hex 32)"
echo "SALT=$(openssl rand -hex 32)"
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)"
```

`.env` is gitignored. Back up separately alongside other `.env` files.

**Note on ClickHouse credentials:** ClickHouse user/password (`clickhouse`/`clickhouse`)
are hardcoded in the compose file rather than in `.env`. Acceptable for a
single-server home deployment where the ClickHouse port is not exposed externally.
For a public deployment, move these to `.env` as well.

---

## 6. Caddy configuration

Add to `/opt/caddy/Caddyfile`:

```
langfuse.michel-portfolio.co.uk {
    reverse_proxy langfuse-web:3000
}
```

Caddy handles TLS automatically via Cloudflare.

Validate and reload:
```bash
# Validate
docker run --rm -v /opt/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
    caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile

# Reload
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

**Network note:** All Langfuse containers join the existing `caddy` network
via the `networks` block at the bottom of the compose file. This is what
allows Caddy to reach `langfuse-web` by container name.

---

## 7. First-run setup

```bash
cd /opt/apps/langfuse

# 1. Start the stack
docker compose up -d

# 2. Verify all 6 containers are running
docker compose ps

# 3. Add Caddy block to /opt/caddy/Caddyfile, validate and reload

# 4. Visit https://langfuse.michel-portfolio.co.uk
#    Sign up to create the first (admin) account

# 5. In docker-compose.yml, set AUTH_DISABLE_SIGNUP: "true"
#    docker compose up -d   (applies change, no data loss)

# 6. In the UI: Settings → Projects → New Project
#    Create two projects: cv-tailor, job-radar

# 7. In each project: Settings → API Keys → Create API Key
#    Save both public/secret key pairs to each app's .env
```

**No MinIO pre-init needed.** Unlike the original spec, MinIO auto-creates
the bucket on first write. The `mc` client is not available in the MinIO
server image — the pre-init step in the original spec would have failed.

---

## 8. App env vars (add to each app after first-run setup)

**cv-tailor `.env`:**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://langfuse.michel-portfolio.co.uk
```

**job-radar `.env`:**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://langfuse.michel-portfolio.co.uk
```

Each app gets its own API key pair — separate projects in Langfuse,
separate trace streams, no cross-contamination.

---

## 9. Backup

Daily backup of PostgreSQL. Add to the existing cron schedule on M720q:

```bash
# /opt/apps/langfuse/backup_langfuse.sh
#!/bin/bash
set -e
DATE=$(date +%Y%m%d)
BACKUP_DIR="/var/backups/langfuse"
mkdir -p "$BACKUP_DIR"

# PostgreSQL dump — recovers users, projects, API keys
docker compose -f /opt/apps/langfuse/docker-compose.yml exec -T langfuse-postgres \
  pg_dump -U langfuse langfuse | gzip > "$BACKUP_DIR/postgres_$DATE.sql.gz"

# Retain last 7 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete

echo "Langfuse backup complete: $DATE"
```

**Note on ClickHouse backup:** ClickHouse native backup requires additional
disk configuration. For v1, PostgreSQL backup alone is sufficient — it
recovers users, projects, and API keys. Trace data in ClickHouse is
observability data; losing it is inconvenient but not catastrophic.

---

## 10. Update process

Langfuse releases frequently. Images are pinned to `:3` (major version)
to avoid accidental breaking changes.

```bash
cd /opt/apps/langfuse
docker compose pull          # pull latest v3 images
docker compose up -d         # restart with new images (~30s downtime)
```

Check Langfuse release notes before pulling — ClickHouse schema
migrations occasionally require a manual migration step.

---

## 11. Definition of Done

1. All 6 containers running: `docker compose ps` shows all Up ✅
2. `https://langfuse.michel-portfolio.co.uk` loads the UI
3. Admin account created, sign-up disabled
4. Two projects created (cv-tailor, job-radar) with API key pairs
5. Each app's `.env` updated with Langfuse keys
6. Backup script in place
7. ClickHouse memory cap confirmed in `clickhouse-config.xml` ✅

---

## 12. What comes after

Once deployment is confirmed healthy, execute
`SPEC_LANGFUSE_INSTRUMENTATION.md` — instrumenting cv-tailor first,
then Job Radar.
