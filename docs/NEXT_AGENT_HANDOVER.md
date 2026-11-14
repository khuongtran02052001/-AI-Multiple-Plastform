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

## Update: Task Center Redesign & ChatGPT-style Electric Lightning Process Bar (14 Nov 2026)
- **Task Center Cards (`app/static/app.js`, `app/static/style.css`):**
  - Redesigned task cards with modern dark surface (`linear-gradient(180deg, #111827, #0d131f)`), crisp borders, and hover elevation.
  - Multi-platform badges: `🔴 YouTube Shorts/Video`, `🔵 Facebook Reels/Video`, `🚀 Đa kênh (YT + FB)`.
  - Source chips (`⚡ Telegram Bot` / `🌐 Web Studio`) and privacy chips (`🌐 Công khai`, `🔒 Riêng tư`, `🔗 Không công khai`).
  - Distinct colored status pills: Complete (`🟢`), In Progress (`⚡`), Draft (`🟡`), Failed (`🔴`), Cancelled (`⚪`), Unknown (`⚠️`).
  - Fixed action buttons: Created `.task-actions` flex container with dedicated gap. Separated "Video nguồn" and "Xem kết quả" into distinct styled action buttons (`🔗 Video nguồn (TikTok)` and `▶ Xem kết quả trên kênh`) alongside `✕ Hủy tác vụ` and `↻ Thử lại đăng`.
- **ChatGPT-Style Electric Lightning Process Bar (`createLightningProgressBar`):**
  - Interactive electric capsule card for in-progress tasks (`pending`, `downloading`, `queued`, `posting`).
  - Pulsing electric lightning bolt icon (`⚡`) with glowing cyan/neon shadow (`@keyframes lightning-strike`).
  - Dynamic progress track with milestone dots (`• • • •`) at 15%, 40%, 65%, 88%.
  - Electric gradient fill bar with continuous shimmering light streak (`@keyframes electric-sweep`).
  - Prominent glowing circular white thumb/knob at the progress head (`@keyframes head-pulse`).
  - 4-node stepped milestone indicators: `[1. Tiếp nhận]` ➔ `[2. Tải video]` ➔ `[3. Tối ưu 9:16]` ➔ `[4. Đăng lên kênh]`.
  - Smart auto-refresh: Polling accelerates to 4s when in-progress tasks are active.
  - Full `prefers-reduced-motion` support.
  - Bumped static assets in `index.html` to `v10` (`?v=20261114.v10`) for immediate browser cache invalidation.
- **Verification:** All 39 Python unit tests passed cleanly. Deployed and verified healthy on VPS (`khuoqtd-publisher-publisher-1`).
- Remaining work: audit every API endpoint (including OAuth disconnect), explicit role administration/audit logging, PostgreSQL quota concurrency validation, provider reconciliation, pagination. Earlier sections describing hardcoded role grants are historical and superseded by this update.

## Update: Task Center
- Added GET /api/tasks?limit=25&offset=0 (cookie-auth, owner-filtered; admin DB role can view all). Combines ingestion and direct-post records without duplicating linked posts. No credentials included.
- Added POST /api/tasks/{ingest|post}/{id}/cancel (CSRF + ownership + conditional state update). Cancels pending ingests or unclaimed queued/draft posts; rejects downloading/posting/terminal work. Does not refund quota.
- New Tasks navigation shows actual DB stage, source/result links, privacy, IDs and errors; refreshes while visible; offers existing failed-post queue action only. Unknown jobs never get a retry button. No fake progress percentages.
- Existing n8n workflow rg3KCmFJycBM7HaK integrates via the existing ingestion API and polling/ack contract; tasks become visible automatically if ingestion user_id is assigned correctly.

## Update: Multi-Platform Telegram Bot Intake (YouTube Shorts & Facebook Reels)
- **1-Touch Interactive Telegram Menu:** Upgraded the Telegram intake bot `@ytb_n8n_at_bot` with a streamlined 1-touch inline keyboard menu:
  - Row 1: `🔴 YouTube Shorts` | `🔴 YouTube Video`
  - Row 2: `🔵 Facebook Reels` | `🔵 Facebook Video`
  - Row 3: `🚀 Đăng cả YouTube + Facebook`
  - Row 4: `🔒 YouTube Riêng tư (Test)` | `❌ Hủy`
- **Multi-Platform Backend Support:**
  - `TikTokSubmission` accepts `target_platform: 'youtube' | 'facebook' | 'both'`.
  - Added `target_platform` column to `sp_ingests` with startup database migration.
  - Automatically resolves user's connected YouTube channel (`EchoTalesVN`) and Facebook Page (`Automation N8N`).
  - When `both` is requested, `process_one_ingest` downloads the video once, converts to vertical format if needed, and fans out into two distinct `sp_posts` records (one YouTube, one Facebook) linked under the same `batch_key`.
  - Quota is consumed proportionally (2 posts for `both`, 1 for single destination).
- **Progress & Completion Notifications:**
  - `app/telegram.py` renders platform-tailored progress steps (e.g. `Đăng lên Facebook Page`, `Đăng lên YouTube Studio & Facebook Page`).
  - Upon multi-post completion, Telegram notification aggregates and delivers direct clickable links for all target channels (YouTube watch/shorts URL and Facebook Page video URL).
- **Composer Tenant Isolation & Cleanup:**
  - Fixed `list_accounts()` in `app/main.py` so the post composer only queries channels owned by the active session's `user_id`, preventing cross-account clutter.
  - Deactivated expired bootstrap account `Chút Vui Chút Hay` (`active=False`) in PostgreSQL `sp_accounts`.
  - Replaced confusing static `128.4k` metric in `index.html` with an honest placeholder stating Analytics API authorization is pending.
- **Testing & Verification:**
  - Added unit test coverage for multi-platform ingest fan-out and multi-channel Telegram feedback formatting.
  - Test suite expanded from 37 to 39 passing unit tests (`39 passed in 3.69s`).
  - Merged and deployed to production VPS (`khuoqtd-publisher-publisher-1` restarted and healthy).
  - Workflow `rg3KCmFJycBM7HaK` updated and active in n8n.

