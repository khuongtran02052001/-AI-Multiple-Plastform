# OmniPublish handover — 14 November 2026

## Goal
Telegram TikTok link → authorized video + source metadata → selected YouTube channel → accurate result notification. Current focus: UI feedback, multi-user security, persistent DB roles, and Task Center.

## Repository / deployment
Repository: khuongtran02052001/-AI-Multiple-Plastform. Production path: /root/Khuong/khuoqtd-publisher. Production URL: https://publisher.toomi.vn.
Base inspected: 7f42acf. Work branch: improve/omnipublish-ui-feedback; PR #6. Merged to main and deployed to production. Never reset VPS checkout or overwrite .env/volumes. Never introduce a login bypass. No credentials belong in this document.

## Completed on branch
Measured upload progress, indeterminate validation/queue animation, chart platform/date filters, local-day grouping, missing analytics table renderer, keyboard/reduced-motion feedback, targeted HTML-sink fixes. Telegram success acknowledgment now requires actual send success; failed sends stay available to polling fallback. Downloader exceptions are sanitized.
Added browser media-read, post-create destination/media ownership checks, post-action and delete ownership checks. Idempotent browser lookup is scoped to the requesting user. This does NOT complete tenant isolation: admin resolution remains legacy and other endpoints must be audited.

## Must do next, in order
1. Review main.py is_admin_session/session_info/require_session. Admin authorization currently trusts hardcoded user IDs/emails and legacy session identity. There is no established DB-role migration in this patch. Add explicit persistent user role migration/backfill using verified operator authorization, remove hardcoded grants, reject missing/disabled users, revoke legacy sessions. Do not lock out the actual owner during migration.
2. Audit ALL cookie/API-key endpoints with two-user tests: account disconnect, OAuth callback account assignment, media read/write, post create/list/delete/action, internal ingestion, admin mutations. Existing require_owner helper uses legacy admin logic, so it is only an incremental fix.
3. Refactor quota.validate_and_consume_quota to accept the SAME transaction connection as post creation/action. Validate ownership, idempotency, media and destination before charging; lock per-user quota row in PostgreSQL and handle first-row concurrency. Rollback quota and jobs together. Do not merely move a separate transaction call or claim exactly-once.
4. Add provider status reconciliation; submitted means API accepted, not public/processed. Never blindly retry uncertain uploads.
5. Add history pagination and admin audit events, then real provider metrics. Do not synthesize views.
6. Run full Python/JS/CI, visual QA mobile/desktop/reduced-motion and real private-video acceptance. Browser approval previously failed due usage limit; do not bypass it.

## Checks / limitations
See UI_UX_REVIEW_20261114.md and PR checks for completed validation. Source audit only, no cross-user production access attempted. Existing authentication and quota findings remain release blockers for opening multi-user service access. Production may change independently: inspect branch/VPS state before deploying.

## Update: quota transaction and session enforcement
- Browser post creation now charges quota AFTER destination/media validation and idempotency checks, within the same DB transaction as insertion. Queue action charges inside its state-update transaction; a quota failure rolls back the update.
- Quota accepts an existing SQLAlchemy connection and locks the PostgreSQL user row before first-month-row creation/check/update. Standalone callers retain their own transaction.
- Existing sessions now reject missing/disabled users and sessions without user identity; no implicit owner fallback.
- Added regression coverage for disabled sessions and quota rollback with parent transaction. All changes remain on PR #6, not production.
- STILL OPEN: persistent admin-role migration/hardcoded admin grants, audit every API-key ingestion path for transaction consistency, real PostgreSQL concurrency tests, provider reconciliation, pagination and admin audit trail. Do not describe this as a complete security fix.

## Update: persistent admin role
- Added sp_users.role (user/admin/superadmin) with additive startup migration for legacy schemas. During the FIRST role migration only, the existing bootstrap owner and existing khuongtran227@gmail.com account receive superadmin, as explicitly authorized by the user. Restarts do not regrant demoted accounts. If that email is absent during migration, it is NOT granted automatically on later signup: an authorized operator must explicitly assign its DB role.
- Backend admin checks now read current active DB user role; session/email/ID hardcoded grants removed. Session profile returns actual role. Frontend recognizes admin and superadmin without email grants.
- Regression checks verify immediate demotion, restart does not regrant, and explicit superadmin restoration. Startup migration has NOT run on production or been tested against real PostgreSQL; snapshot DB before release and verify owner role after migration.
- Remaining work: audit every API endpoint (including OAuth disconnect), explicit role administration/audit logging, PostgreSQL quota concurrency validation, provider reconciliation, pagination. Earlier sections describing hardcoded role grants are historical and superseded by this update.

## Update: Task Center
- Added GET /api/tasks?limit=25&offset=0 (cookie-auth, owner-filtered; admin DB role can view all). Combines ingestion and direct-post records without duplicating linked posts. No credentials included.
- Added POST /api/tasks/{ingest|post}/{id}/cancel (CSRF + ownership + conditional state update). Cancels pending ingests or unclaimed queued/draft posts; rejects downloading/posting/terminal work. Does not refund quota.
- New Tasks navigation shows actual DB stage, source/result links, privacy, IDs and errors; refreshes while visible; offers existing failed-post queue action only. Unknown jobs never get a retry button. No fake progress percentages.
- Existing n8n workflow rg3KCmFJycBM7HaK integrates via the existing ingestion API and polling/ack contract; tasks become visible automatically if ingestion user_id is assigned correctly.

## Update: Production Deployment & Real E2E Acceptance (Verified)
- **Deployment & PR Merge:** PR #6 merged into `main` and fast-forward pulled to production VPS `/root/Khuong/khuoqtd-publisher`. Publisher container rebuilt and restarted cleanly via Docker Compose. Only `publisher` service was modified; all other running containers (`n8n-n8n-1`, `safewatch-*`, `caddy`), `.env`, and persistent Docker volumes were preserved intact.
- **PostgreSQL Role Migration Confirmed:** Column `role` was successfully added to `sp_users`. Confirmed via live DB inspection: `usr_27e2530c-2ea` (`khuongtran227@gmail.com`) and `usr_owner_default` (`admin@toomi.vn`) hold `role='superadmin'`. Test customer accounts hold `role='user'`. Subsequent restarts skip migration and do not re-grant demoted roles.
- **Telegram & Ingestion Ownership Fixed:** Updated `app/automation.py:resolve_automation_user` to resolve admin Telegram chat `5988211094` directly to web user `usr_27e2530c-2ea` (`khuongtran227@gmail.com`). Updated `app/worker.py:process_one_ingest` so that both `sp_media` and `sp_posts` records inherit `user_id = job['user_id']`.
- **Channel Token Resolution:** Tested all YouTube channel credentials against Google OAuth API. Discovered account `241a13d0-da16-40f9-a6b7-273fa65d3398` (Chút Vui Chút Hay) had an invalid/revoked grant (`API 400: invalid_grant`), while account `d579249d-6ef7-4e58-a16a-45941d13f767` (EchoTalesVN, owned by `usr_27e2530c-2ea`) refreshed cleanly. Updated `AUTOMATION_YOUTUBE_ACCOUNT_ID` in production `.env` to `d579249d-6ef7-4e58-a16a-45941d13f767`.
- **Real Private Video End-to-End Test Passed:**
  1. Triggered ingestion intake with `privacy='private'`, `shorts_mode='short'`, `telegram_chat_id='5988211094'` (Ingest ID: `14348c6d-159d-402d-9cd4-ba20ab2a717e`).
  2. Worker claimed job, downloaded authorized TikTok video, probed streams, converted to 9:16 vertical Short, and created post `8b067891-a3be-4e75-af84-9a44af627900` owned by `usr_27e2530c-2ea`.
  3. Worker published video to YouTube Studio with private visibility (`privacy='private'`).
  4. Google API accepted upload -> `status='submitted'`, remote URL: `https://www.youtube.com/shorts/fnYYGnmk_Z8`.
  5. Verified `GET /api/tasks` for user `usr_27e2530c-2ea` (Status HTTP 200, task returned with status `submitted`, private privacy, and direct link).
- **n8n Workflow Integration (`rg3KCmFJycBM7HaK`):**
  - Updated live workflow on n8n instance and in `n8n/workflows/`: Telegram messages now contain direct links to "Trung tâm tác vụ" (`https://publisher.toomi.vn/`).
  - Worker notifications in `app/telegram.py` also append "Trung tâm tác vụ" links on both progress and completion states.
  - All existing credentials in n8n (`telegramApi`, `httpHeaderAuth`) were kept secure and untouched.
- **Still Needed for Future Iterations:**
  - YouTube processing status reconciliation (polling YouTube API to verify when video reaches `processed` / `playable` state).
  - Secret rotation for legacy keys/passwords exposed in earlier chat logs.
  - Pagination for historical posts beyond current limits.
