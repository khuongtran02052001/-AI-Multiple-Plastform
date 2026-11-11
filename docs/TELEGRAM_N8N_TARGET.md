# Telegram → TikTok link → YouTube: staged integration

Status: **implementation added to the repository, disabled by default. VPS deployment and live social API testing are pending.** See [the deployment runbook](TELEGRAM_N8N_DEPLOYMENT.md).

## Boundaries

- **Telegram/n8n** receives authorized requests, orchestrates steps and reports their outcomes.
- **Video adapter** obtains authorized copies of videos from supported sources, validates media and passes it to Publisher. This is not TikTok's official arbitrary-link download API.
- **Publisher (FastAPI)** owns Google OAuth, encrypted tokens, authenticated channel selection, the Postgres queue, idempotency, upload and job statuses.
- **Supabase** stores metadata and token ciphertext; VPS volume stores video files.
- The existing **Facebook Pages** support remains untouched. Do not add Upload-Post dependency.

Do not automate downloading or reposting another person's material without permission. TikTok data-portability endpoints are authorization-based and are not a general downloader for any public link.

## First release: YouTube-only workflow

1. **Telegram Trigger** receives a message from an allowlisted chat or user. Accept a single TikTok URL, reject unrelated domains and unsupported formats, and record the Telegram update ID.
2. **n8n** stores an idempotency correlation ID derived from the bot ID plus Telegram update/message identity. If that ID has already been processed, return the prior result instead of starting another upload.
3. **Download adapter** resolves only supported TikTok source URLs, with redirect/hostname checks to prevent SSRF. It enforces byte limits, timeouts, maximum redirects, media MIME checks, MP4/probe validation and cleanup of temporary files.
4. **Publisher** receives a request through a separate authenticated **machine-to-machine API** (to be implemented; current session/CSRF browser API is not suitable). The API requires narrow-scope credentials, does not return Google tokens and cannot choose arbitrary unapproved channels.
5. **Publisher** creates one durable, idempotent queue job and returns a post/job ID. n8n must not call YouTube directly or bypass the queue.
6. **Status** is polled by a read-only internal API or delivered via a signed webhook. Do not equate a YouTube upload response with full video processing.
7. **Telegram** reports submitted video ID/URL, API rejection, and `unknown` results requiring manual reconciliation. Never auto-retry a job after an uncertain YouTube response.

**The private ingestion API, TikTok adapter and two inactive n8n templates are now in this repository.** Real Google OAuth, TikTok retrieval and Telegram delivery still require VPS setup and acceptance tests.

## Authentication and trust

- Keep Google OAuth browser callback at `https://PUBLISHER_DOMAIN/oauth/youtube/callback`; require public HTTPS to connect the channel for the first time.
- Accept n8n-to-Publisher requests **only** on a private shared Docker network or an authenticated, narrowly restricted endpoint. A dedicated service secret/HMAC and replay protection are required in addition to network isolation.
- Do not store the admin password, database password or OAuth client secret in n8n workflow JSON. n8n credential store is the proper place for bot/service credentials.
- Use Telegram chat/user allowlisting. Reject forwarding/cross-chat attempts when unauthorized.
- Track bot update ID, normalized source URL, job ID, YouTube video ID and error status. Keep raw token values out of all logs.
- Default YouTube uploads to **private** for acceptance testing. Do not silently promote private videos to public.
- If source content cannot be legally or technically obtained, fail with a clear message rather than attempting bypasses.

## Deployment dependencies

- Existing n8n Caddy occupies 80/443; keep it. Join the Caddy container and Publisher service to a shared Docker network and configure the existing proxy to reach `publisher:8000`.
- Host-loopback `127.0.0.1:8090` is for VPS-local diagnostics and **is not** a suitable upstream dial address from a separate container.
- Update `BASE_URL` in the private VPS `.env` when DNS+HTTPS are working; configure Google callback to the exact same domain.
- Verify the actual Supabase project ID before any migrations or direct SQL. Do not target Briefly.
- Rotate exposed administrator credentials on the VPS and revoke sessions before sharing public access.

## Acceptance criteria

1. Unauthorized Telegram chats cannot submit requests.
2. A repeated Telegram update does not produce a second YouTube upload.
3. An authorized, small MP4 enters a single queued job and produces a private video on the expected channel.
4. Scheduled requests wait for their due time.
5. Provider timeout or crash becomes `unknown` without automatic duplicate upload.
6. Results and error codes are visible both in the Publisher UI and the originating Telegram chat.
7. Temporary files are purged when safe; unresolved jobs retain required media.
8. Existing n8n and chatbot domains remain healthy after Publisher proxy changes.

## Official references

- YouTube OAuth: https://developers.google.com/youtube/data/guides/authentication
- YouTube upload API: https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- n8n Telegram node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/
- TikTok user-authorized data download: https://developers.tiktok.com/docs/en/data-portability-api-download
