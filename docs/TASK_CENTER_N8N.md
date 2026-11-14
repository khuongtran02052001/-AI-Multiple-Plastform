# Task Center and existing n8n workflow

Target: https://n8n.toomi.vn/workflow/rg3KCmFJycBM7HaK.

Keep the Telegram trigger/credentials, allowlist and existing routes unchanged. The intake must call the existing Publisher ingestion endpoint with stable request_key, telegram_chat_id, telegram_message_id and validated source_url. Never create another post in parallel with Publisher's worker. A successful intake response means accepted, not published.

Publisher stores sp_ingests and associated sp_posts. GET /api/tasks projects these for the signed-in owner. n8n must not use browser cookies: keep its current service/API-key credential and API contract. For the legacy service route use the existing /internal/v1/tiktok/{id} status and /internal/v1/notifications + terminal /ack endpoints on the private Docker network. Keep /internal/* blocked at the public reverse proxy.

For a Telegram task-view link, use https://publisher.toomi.vn/ with label “Trung tâm tác vụ”; it requires normal browser login. Do not put service keys or cookies into a URL. Only one notification owner should acknowledge completion: direct worker Telegram send on API success, otherwise existing polling fallback. Sending and acknowledgement are separate operations; duplicate notification delivery remains possible if acknowledgement fails.

Before activation: verify the ingestion row user_id belongs to the connected operator (not a provisioned Telegram-only user if the operator logs in by email). Test one authorized private video, an invalid URL, a repeated update and unknown outcome. Verify a second user cannot see or cancel the task. Do not automatically retry a timed-out provider write.

This file is an integration contract, not proof the live n8n workflow has been configured.
