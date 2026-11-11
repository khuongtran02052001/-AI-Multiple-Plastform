# Telegram → TikTok → YouTube → Telegram

**Status:** Implementation is committed to GitHub; it is not deployed to the VPS or tested against a real TikTok video, YouTube channel, or Telegram bot.

The first release uses:
- n8n Telegram Trigger for the `/publish <https://...tiktok.com/...>` command
- a bearer-token authenticated internal Publisher endpoint
- the Publisher PostgreSQL ingestion queue and `yt-dlp` media adapter
- the existing official YouTube Data API upload code
- a second n8n workflow to send results back to Telegram

Facebook Pages remain supported by the existing browser application but are not in this automation flow.

## Trust and rights

Only the explicitly allowlisted Telegram **chat ID and sender user ID** can submit commands. The `/publish` command is the operator's assertion that the video is owned or licensed for downloading and republication; the software cannot independently verify that assertion. Do not use this on third-party content without authorization. The adapter does not bypass login, use cookies, strip watermarks, or circumvent disabled downloads. Some links will fail because TikTok changes its delivery format or restricts download.

The backend accepts HTTPS TikTok video URL patterns from `tiktok.com`, `www.tiktok.com`, `m.tiktok.com`, `vm.tiktok.com`, and `vt.tiktok.com`. It rejects userinfo, arbitrary hosts, non-default ports and non-video paths. There is still residual outbound request/redirect risk from a third-party downloader: run the importer behind appropriate outbound egress controls on a private VPS network when operating at scale.

## Configuration on VPS

Do not commit secrets or paste them into chat. Update **only** the publisher's VPS environment after the correct GitHub commit is deployed:

```dotenv
BASE_URL=https://publisher.YOUR_DOMAIN
PUBLISHER_PORT=8090
TIKTOK_INGEST_ENABLED=true
AUTOMATION_TOKEN=<GENERATE_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS>
AUTOMATION_YOUTUBE_ACCOUNT_ID=<THE_ID_RETURNED_BY_AUTHENTICATED_API_ACCOUNTS>
```

Generate the service token directly on the VPS, e.g. using `openssl rand -hex 32`; place the result in the Publisher's private `.env` and separately configure the **n8n HTTP Header Auth credential** as `Authorization: Bearer <same token>`. Do not copy it into exported workflows.

Before enabling this functionality, connect the intended YouTube channel using the browser's OAuth flow and obtain the **internal account UUID**, not the public YouTube channel URL. Use the same `BASE_URL` and exact Google redirect URI.

Restart Publisher only, preserving its persistent Docker volume. The new `sp_ingests` table is created during app initialization and protected with RLS + revoked browser roles just like other `sp_*` tables; use `deploy/supabase-bootstrap.sql` for first-time SQL initialization if desired.

When deploying onto the shared VPS, leave its n8n and chatbot containers untouched. Attach the actual n8n application container to the Publisher Docker network so the HTTP nodes can resolve `http://publisher:8000`. This name is a **container-network** hostname, not the host-loopback port `127.0.0.1:8090`. Determine real container and network names with `docker ps` and `docker network ls`, then persist the shared network in the n8n Compose configuration. Attach the existing Caddy container in the same way only to serve the web interface over HTTPS.

**Do not expose the automation API through public Caddy.** Add these handlers to the dedicated Publisher host block on the existing Caddy installation (not to an n8n host):

```caddy
publisher.YOUR_DOMAIN {
    handle /internal/* {
        respond 404
    }
    handle {
        reverse_proxy publisher:8000
    }
}
```

Keep Caddy upload and timeout limits appropriate for browser video uploads.

## Import the n8n workflows

In n8n, import both JSON files:

- `n8n/workflows/telegram-tiktok-intake.json`
- `n8n/workflows/telegram-notify-results.json`

Do **not** activate the workflows until the following are configured:

1. Set the Telegram Trigger and Telegram send nodes to your real **Telegram credential**, stored in the n8n credential store.
2. Edit the **Validate publish command** Code node: replace both `REPLACE_WITH_ALLOWED_TELEGRAM_CHAT_ID` and `REPLACE_WITH_ALLOWED_TELEGRAM_USER_ID`. Only one explicit operator is allowed by this template.
3. Create one **HTTP Header Auth** credential in n8n, header name `Authorization`, value `Bearer <AUTOMATION_TOKEN>`. Assign it to **every** Publisher HTTP Request node in both workflows.
4. Confirm `http://publisher:8000/healthz` works **from the n8n container**. It must not rely on publicly exposing port 8090.
5. Set the correct `AUTOMATION_YOUTUBE_ACCOUNT_ID` on Publisher. The endpoint never accepts a caller-selected destination account.
6. Confirm all videos in this workflow are **not made for kids**. The template deliberately supplies `made_for_kids: false`; change this parameter when processing other content. YouTube compliance remains the publisher's responsibility.
7. Activate the **Telegram intake** and **result notification** workflows only after the tests below pass.

## HTTP API contract

The following endpoints are authenticated with the service bearer token, not the admin browser cookie:

`POST /internal/v1/tiktok`

```json
{
  "request_key": "tg_123456789_456_publisher_v1",
  "telegram_chat_id": "123456789",
  "source_url": "https://www.tiktok.com/@youraccount/video/7281234567890123456",
  "title": "My authorized video",
  "description": "",
  "made_for_kids": false,
  "rights_confirmed": true,
  "scheduled_at": null
}
```

The response returns an `id`, `status`, `deduplicated`, and associated non-secret job metadata. Reusing a request key for the same video yields the existing job; reusing a key for another source returns HTTP 409.

`GET /internal/v1/tiktok/{id}` returns the current import/publish outcome. No Google credentials are returned.

`GET /internal/v1/notifications` returns up to 30 terminal, unacknowledged Telegram results, including their chat IDs and YouTube URL or failure status.

`POST /internal/v1/tiktok/{id}/ack` marks a terminal result as notified. The n8n workflow sends the message **before** acknowledging it. This is at-least-once delivery (a notification may repeat if the response is lost); it does not guarantee exactly-once Telegram messages.

## Acceptance test

1. Unauthorized chat or sender must be ignored by the Telegram command validator.
2. Authorized operator sends `/publish https://www.tiktok.com/@youraccount/video/...` for a short video they own.
3. Publisher returns one pending job. Repeating the same Telegram update does not create another job.
4. The importer downloads an MP4, verifies dimensions/duration and queues it with `privacy='private'`.
5. The worker uploads it using the connected Google OAuth account. Verify the **private** video in YouTube Studio, not only the returned ID.
6. n8n's minute poll sends a result to the originating chat and acknowledges it after Telegram succeeds.
7. A deliberately invalid/blocked link yields a single failure, and a provider timeout becomes `unknown` without automatic re-upload.
8. Verify that no existing n8n, Caddy, pett-chatbot, or other published services are disrupted.

No real OAuth/Telegram/TikTok/YouTube acceptance test has been run from GitHub CI. Unit tests use fake providers and media and cannot prove external API compatibility.

## Follow-on hardening

- Restrict outgoing DNS/IP ranges of the downloader at the network layer; `yt-dlp` can contact TikTok-controlled CDNs not listed in the user-submitted URL.
- Add monitoring, orphan-file recovery, token rotation and resilient status reconciliation against YouTube.
- Add a workflow to submit a video **file already held by the user** when a TikTok link is not downloadable.
