# Manual VPS deployment through GitHub Actions (no ChatGPT SSH required)

This project is already running on a shared VPS, based on the last handover report. Its previous running revision was `caff6db1` and the application listened on host loopback port `8090`. The report is not proof of current live state. The existing n8n Caddy is the owner of ports 80/443; the chatbot owns port 8000. Never start this repository's separate `https` Compose profile on that VPS.

## What this enables

The GitHub **Actions → Publisher VPS — manual preflight / deploy** workflow has two actions:
- **preflight**: connect from a GitHub-hosted runner by SSH, inspect the repo and Publisher service without changing the VPS.
- **deploy**: fetch only the exact reviewed `main` revision, fast-forward the repo, rebuild/recreate **publisher only**, then check internal `/healthz`.

The workflow does not edit DNS, Caddy, Google OAuth or n8n, and it cannot work until the server accepts SSH from GitHub-hosted runners. It does not provision an SSH key automatically.

## One-time SSH setup (trusted VPS console)

Use the hosting provider's web console or an already authorized SSH session. On a trusted administrator workstation, generate a *dedicated* keypair:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/publisher_deploy -C publisher-github-actions
```

Install **only the public key** on the intended VPS account, using the VPS console. The project path is under `/root`, and the existing deployment script requires root; this workflow currently requires an administrator SSH account. A dedicated least-privilege deployment account with an allowlisted command is a preferred later hardening step. Never send the private key into ChatGPT or store it in Git.

From the trusted VPS console, inspect the actual SSH service and obtain the server SSH *public host key*:

```bash
sudo sshd -t
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Build a `known_hosts` line for this host using the verified **public** host key and the SSH port. Verify its fingerprint against the console; do **not** trust `ssh-keyscan` without that verification. Ensure outbound/inbound firewall policy permits SSH from the GitHub runner; when SSH is intentionally private-only, this method cannot connect and a privately bootstrapped runner or a separate approved management path is required.

In GitHub repository **Settings → Environments**, create `production` with branch restriction `main` and required reviewers where available. Add secrets to that environment (not repository files):

| Name | Value |
|---|---|
| `PUBLISHER_SSH_HOST` | VPS public IP/hostname |
| `PUBLISHER_SSH_USER` | Dedicated SSH deploy administrator |
| `PUBLISHER_DEPLOY_KEY` | Dedicated private key from trusted workstation |
| `PUBLISHER_KNOWN_HOSTS` | Verified host public-key line |
| Variable `PUBLISHER_SSH_PORT` | SSH port; default is 22 |

**Do not reuse a personal SSH key or expose it to ordinary pull-request workflows.**

## Run sequence

1. In GitHub Actions select **Publisher VPS — manual preflight / deploy**, branch `main`, `mode=preflight`.
2. Resolve any SSH reachability/permissions issues. An exit status 255 usually signals SSH failure but not its exact cause; inspect the *actual* action logs.
3. If preflight reports uncommitted tracked files, reconcile them on the VPS **without** `git reset --hard`. Existing server-local changes may be required.
4. Run the same manually approved workflow with `mode=deploy`.
5. Confirm `DEPLOY OK`, healthy Publisher container and correct Supabase project. The Publisher's schema initializer adds `sp_ingests` to the database used by its existing `DATABASE_URL`. **This writes to that database**: verify the target Supabase project ID independently before selecting deploy.

## HTTPS + YouTube OAuth remain separate

A DNS A record needs to map an authorized domain, for example `publisher.YOUR_DOMAIN`, to your actual VPS IP. Then configure a **new host block** in the *existing* n8n Caddy (do not replace its old blocks). Put Publisher and the Caddy container on a durable shared Docker network; point Caddy upstream to `publisher:8000`, not to `127.0.0.1:8090` from inside another container. Deny `/internal/*` on public HTTPS.

Update `BASE_URL` in the VPS private `.env`, reload/recreate **publisher only**, and verify HTTPS and `/healthz`.

In the Google Cloud console enable YouTube Data API v3 and create an OAuth Web application. Register exactly:

```text
https://publisher.YOUR_DOMAIN/oauth/youtube/callback
```

Enter the client ID/secret directly in the VPS `.env`, recreate Publisher only, then connect the YouTube channel through the web UI. Google verification/API quotas and publisher restrictions are controlled by Google.

## n8n + test publish

Once the channel is linked, select its internal account ID as `AUTOMATION_YOUTUBE_ACCOUNT_ID`; generate `AUTOMATION_TOKEN` securely on the VPS. Set `TIKTOK_INGEST_ENABLED=true`, recreate the Publisher service. Import the two inactive workflow templates in `n8n/workflows` and configure the Telegram bot credential, allowlisted sender/chat IDs and the Publisher HTTP Header Auth credential.

The n8n container must share Publisher's Docker network and reach `http://publisher:8000`. Verify this before activating workflows. The first test must use a small TikTok video you own or have permission to republish and must result in a **private** YouTube upload; check it in YouTube Studio before trusting the Telegram confirmation.

## Mandatory security step

An administrator password was exposed in the previous handover report. Rotate it on the VPS and invalidate existing `sp_sessions` on the **verified production database**, without changing the existing token encryption key.

For detailed workflow setup and endpoints, see [Telegram/n8n deployment](TELEGRAM_N8N_DEPLOYMENT.md).
