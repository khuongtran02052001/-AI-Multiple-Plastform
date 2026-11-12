#!/usr/bin/env bash
# Invoked exclusively from a reviewed GitHub Actions workflow through SSH.
# Reads the existing .env; never prints secrets or touches Caddy/n8n/chatbot.
set -euo pipefail

mode="${1:-}"
expected_sha="${2:-}"
readonly TARGET="/root/Khuong/khuoqtd-publisher"
readonly COMPOSE_PROJECT="khuoqtd-publisher"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "$mode" in preflight|deploy) ;; *) die "Expected preflight or deploy" ;; esac
[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || die "Invalid expected commit"
[[ "$EUID" -eq 0 ]] || die "Run as authorized VPS administrator (project is under /root)."
command -v git >/dev/null || die "git not installed"
command -v docker >/dev/null || die "docker not installed"
docker compose version >/dev/null || die "Docker Compose missing"
docker info >/dev/null 2>&1 || die "Docker daemon unavailable"
[[ -d "$TARGET/.git" && -r "$TARGET/.env" ]] || die "Publisher checkout/.env missing"

cd "$TARGET"
remote="$(git remote get-url origin)"
case "$remote" in
  https://github.com/khuongtran02052001/-AI-Multiple-Plastform|\
  https://github.com/khuongtran02052001/-AI-Multiple-Plastform.git|\
  git@github.com:khuongtran02052001/-AI-Multiple-Plastform|\
  git@github.com:khuongtran02052001/-AI-Multiple-Plastform.git) ;;
  *) die "Unexpected Git origin. Aborting." ;;
esac

# Existing local tracked changes may contain important VPS-specific edits.
# Never overwrite, reset, stash, or implicitly commit them.
git diff --quiet || die "Uncommitted tracked VPS changes. Reconcile before deploying."
git diff --cached --quiet || die "Staged VPS changes. Reconcile before deploying."
test "$(git branch --show-current)" = "main" || die "VPS checkout must be on main."
docker compose -p "$COMPOSE_PROJECT" config --quiet
echo "Publisher checkout: $(git rev-parse --short HEAD)"
echo "Publisher containers:"
docker compose -p "$COMPOSE_PROJECT" ps publisher

if [[ "$mode" == preflight ]]; then
  echo "PREFLIGHT OK. No Git checkout, database or container changed."
  exit 0
fi

# Never deploy a different revision from the manually approved workflow run.
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
remote_sha="$(git rev-parse refs/remotes/origin/main)"
[[ "$remote_sha" == "$expected_sha" ]] || die "main changed after workflow start; run a new reviewed deployment."
git merge --ff-only refs/remotes/origin/main
docker compose -p "$COMPOSE_PROJECT" config --quiet

# No --profile https. Do not recreate/start the existing n8n Caddy.
# Only Publisher is built/recreated, retaining its existing media volume.
docker compose -p "$COMPOSE_PROJECT" up -d --build --no-deps publisher

ok=false
for _ in $(seq 1 15); do
  if docker compose -p "$COMPOSE_PROJECT" exec -T publisher \
      python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" >/dev/null 2>&1; then
    ok=true
    break
  fi
  sleep 3
done
docker compose -p "$COMPOSE_PROJECT" ps publisher
[[ "$ok" == true ]] || die "Publisher did not pass local health check."
echo "DEPLOY OK: Publisher only, commit $(git rev-parse --short HEAD)"
