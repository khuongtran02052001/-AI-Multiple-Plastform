# Production rollout — khuoqtd Publisher

This runbook is for the single-administrator YouTube + Facebook Pages release. Do not use the Briefly Supabase database. Do not commit credentials, token exports, `.env` or database dumps.

## 1. Infrastructure inventory

- A Linux VPS with Docker Engine and Docker Compose plugin; enough persistent disk for `MAX_STORAGE_MB` plus temporary uploads.
- A dedicated, **active** Supabase PostgreSQL project for Publisher (not Briefly).
- A DNS A/AAAA record for your HTTPS subdomain. Ports 80 and 443 need to reach the TLS reverse proxy.
- One administrator password (at least 16 characters), one Fernet encryption key, and dedicated OAuth credentials for Google/Meta.

**No separate Redis, n8n, or Upload-Post service is required.** The single FastAPI process embeds the worker; Supabase is the persistent queue and metadata store.

## 2. Prepare VPS

```bash
git clone https://github.com/khuongtran02052001/-AI-Multiple-Plastform.git publisher
cd publisher
docker compose version
docker build -t khuoqtd-publisher .
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/work" -w /work \
  khuoqtd-publisher python -m app.setup
```

The setup command creates a private `.env` with the password hash and encryption key. Retain that exact encryption key for restoring encrypted OAuth tokens.

Edit `.env` locally on the VPS:

```dotenv
BASE_URL=https://publisher.example.com
APP_DOMAIN=publisher.example.com
ACME_EMAIL=admin@example.com
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
META_APP_ID=
META_APP_SECRET=
```

Use the precise **Session pooler** connection details from Supabase Dashboard > Connect when VPS has IPv4 only. Do not guess the pooler hostname. Use the direct Postgres endpoint instead when the server supports IPv6 and the project allows it. Do not substitute Supabase `anon` or `service_role` keys for the Postgres password.

Production Compose sets `REQUIRE_POSTGRES=true`. If `DATABASE_URL` is still SQLite, startup must fail rather than silently persisting production data into a local file.

## 3. HTTPS and first startup

With no existing reverse proxy on ports 80/443:

```bash
docker compose config --quiet
docker compose --profile https up -d --build
docker compose --profile https ps
docker compose --profile https logs --tail=100 publisher caddy
curl -fsS https://publisher.example.com/healthz
```

The app initializes the `sp_*` tables at startup, enables RLS and revokes browser roles. Check those tables and permissions in the **dedicated** Supabase project before connecting real accounts.

If the VPS already has Nginx, Caddy or Traefik listening on 80/443, **do not start the Caddy profile**. Use `docker compose up -d --build` and have the existing proxy forward `https://publisher.example.com` to `127.0.0.1:8000`. Preserve the original Host, allow at least a 252 MB body for the default 250 MB upload limit, and permit a sufficiently long upload/response timeout.

## 4. OAuth callbacks

Google Cloud: enable YouTube Data API v3, configure the OAuth audience/scopes and a Web application client. Authorized redirect URI:

```text
https://publisher.example.com/oauth/youtube/callback
```

Meta: configure a Page-capable app and Facebook Login, subject to your app's permitted scopes and Meta's current review/permissions requirements. Authorized redirect URI:

```text
https://publisher.example.com/oauth/facebook/callback
```

Enter the credentials in the VPS `.env` only. To apply changed environment variables:

```bash
docker compose up -d --force-recreate publisher
```

Do not log or expose raw authorization codes, access/refresh tokens or client secrets.

## 5. End-to-end acceptance checklist

1. Log in, verify the connected provider statuses, and connect exactly the intended YouTube channel and Facebook Page.
2. Upload a small valid MP4; verify the media metadata and preview.
3. Publish **private** on YouTube first. Check that the returned video ID belongs to the correct channel, and confirm status in YouTube Studio.
4. Publish a test post on an appropriately controlled Facebook Page; check the resulting post directly on the Page.
5. Schedule a post a few minutes ahead using an explicit timezone; verify that it remains queued before its deadline and transitions correctly afterward.
6. Submit the **same idempotency key** again; confirm no duplicate job is created.
7. Simulate a provider timeout only in staging/test accounts; verify `unknown` is not retried automatically until reconciled with the platform.
8. Check retention and free disk space; unresolved media must remain available for reconciliation.

A provider returning a remote ID means the upload was accepted, **not** necessarily that the platform has finished processing or made the content visible.

## 6. Operations, security and recovery

- Keep the Docker named volume `publisher_data`, the VPS `.env` (especially `ENCRYPTION_KEY`) and a PostgreSQL backup together in an encrypted, restricted backup location.
- A Supabase database backup does **not** include MP4s stored on the VPS volume. Losing the encryption key also makes previously stored OAuth tokens unreadable.
- Use Supabase's documented backup/restore workflow for your project tier. Check backup availability on the Free tier rather than assuming automated point-in-time recovery exists.
- Monitor `docker compose ps`, `docker compose logs --tail=100 publisher`, free disk and `/healthz`. A green `/healthz` confirms database connectivity, not completion of social posting.
- Keep `WORKER_ENABLED=true` for normal deployment. Run one app process using the provided Dockerfile. Never operate multiple production instances without reviewing worker/process-level rate limiting.
- For a failed or uncertain social request, inspect the remote platform before making another publish request. Exactly-once publication is not guaranteed across two independent APIs.
- Restore database, volume and the **original encryption key** as a unit; restart and verify health before resuming the worker.

## Known blockers before a real release

- Dedicated Supabase project not yet selected/provisioned.
- No verified admin access to the user's VPS and DNS.
- No confirmed Google/Meta OAuth client setup.
- API calls are tested with mocks; real YouTube/Facebook publishing and scheduling have **not** passed acceptance testing.
