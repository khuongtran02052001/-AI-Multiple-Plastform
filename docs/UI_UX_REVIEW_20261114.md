# OmniPublish UI/UX review — 14/11/2026

Base: `7f42acf`. This report describes source changes, not a production deployment.

## Implemented
- Upload progress uses XHR bytes; processing is indeterminate until the server validates the file. No timer invents percentages. Upload, error and ready states have accessible labels; submit controls stay disabled during upload.
- Publishing queue animates only while jobs are pending. This is an activity indicator, not a provider-upload percentage.
- Analytics now honors platform and period filters, groups dates in the viewer's local timezone, excludes drafts/cancelled items from the pending/error series and shows an em dash when no success-rate denominator exists.
- Chart instances update instead of being destroyed on each refresh; reduced-motion disables chart animation. Empty data and missing view metrics are explicit.
- Implemented the previously missing analytics detail-table renderer/search/filter. Remote links require HTTPS; table content uses DOM text nodes. No invented view counts.
- Added short view transitions, focus-visible rings, hover/pressed states and upload feedback. Existing per-platform settings are preserved.
- Removed dynamic channel/API-key-name HTML interpolation and an API-key error-message HTML sink. This is a targeted XSS reduction, not a complete XSS audit.
- Fixed two inherited notification regressions: only acknowledge direct Telegram notifications after an actual API success; leave failures available for poll/ack fallback. Raw downloader exceptions no longer reach logs, DB error text or Telegram. Telegram text variables are HTML-escaped.

## Verification
- JavaScript syntax, isolated UI transport/data fixtures and existing n8n checks.
- Python suite: 31 passed, including notification/escaping tests. One existing Starlette/httpx deprecation warning remains.
- The two original Python failures were reproduced on untouched `7f42acf` before repairing them.
- No production login bypass, real upload, public post or VPS deployment performed.
- Browser visual QA was unavailable because the cloud-browser approval service hit its usage limit. Responsive appearance and real network upload remain to be checked before deployment.

## Security findings that remain open
| Priority | Source evidence | Required follow-up |
| --- | --- | --- |
| P0 | `GET /api/media/{media_id}` checks session but not media owner; `POST /api/posts` loads destinations/media by ID without matching owner | Enforce user ownership in every browser/API operation; add two-user isolation tests before offering multi-user access |
| P0 | `is_admin_session` and session profile grant admin by hardcoded IDs/emails; legacy sessions default to owner | Use DB role/status as authority, invalidate legacy sessions and verify disabled users on each request |
| P1 | Post quota is consumed before idempotency/validation in browser creation | Reserve quota and create posts transactionally; retries must not consume quota again |
| P1 | Credentials have appeared in handover/chat | Rotate exposed root/admin/deploy/API secrets using protected configuration; do not print replacement secrets |
| P1 | Frontend changes do not establish Google token longevity or tenant isolation | Audit token encryption, refresh/revocation, OAuth account ownership and redirect constraints |

These are source findings, not a penetration test. No attempts were made to access another user's data.

## Functional next steps
1. Reconcile platform processing/publication status after API submission; keep submitted distinct from publicly available.
2. Add post-stage timestamps and safe error codes so UI can show queue/download/upload/processing without fake percentages.
3. Add paginated history, date search and audit events for admin tier/status actions.
4. Implement real metrics collection before presenting views/engagement; current analytics summarizes app post records by creation date.
5. Validate Telegram → owned TikTok video → private YouTube upload → notification, including timeout/duplicate behavior.

## Deployment
Merge only after review and required checks. Use the existing manual Publisher-only deployment workflow; preserve `.env`, persistent volumes and other VPS services. Verify static asset version `20261114.v8`, upload success/failure, filters, keyboard navigation, mobile layout and reduced-motion. The open P0 multi-user findings are separate release blockers for exposing the service to other users.
