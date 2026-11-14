# OmniPublish handover — 14 November 2026

## Goal
Telegram TikTok link → authorized video + source metadata → selected YouTube channel → accurate result notification. Current focus: UI feedback and multi-user security.

## Repository / deployment
Repository: khuongtran02052001/-AI-Multiple-Plastform. Production path: /root/Khuong/khuoqtd-publisher. Production URL: https://publisher.toomi.vn.
Base inspected: 7f42acf. Work branch: improve/omnipublish-ui-feedback; PR #6. No production deployment performed by this change. Never reset VPS checkout or overwrite .env/volumes. Never introduce a login bypass. No credentials belong in this document.

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
- Existing n8n workflow rg3KCmFJycBM7HaK integrates via the existing ingestion API and polling/ack contract; tasks become visible automatically if ingestion user_id is assigned correctly. No n8n production workflow was inspected/modified: no n8n connector is available and browser access was previously denied by approval usage limit. Do not claim live integration tested.
- Still needed: detailed timestamps/stage events, downloader retry with a new durable request key and authorization, platform-processing reconciliation, Telegram task-link button, real n8n end-to-end acceptance. No claim of provider processing completion is made.
