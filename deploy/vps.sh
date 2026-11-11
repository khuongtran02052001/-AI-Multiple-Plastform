#!/usr/bin/env bash
# Run on the VPS itself. Does not contain or accept credentials as arguments.
set -euo pipefail

readonly TARGET=/root/Khuong/khuoqtd-publisher
readonly PROJECT=khuoqtd-publisher
action=${1:-help}

die() { printf '%s\n' "$*" >&2; exit 1; }

if [[ $action == help ]]; then
  printf '%s\n' 'Usage: bash deploy/vps.sh prepare | check | start [--https] | status'
  printf '%s\n' 'Target: /root/Khuong/khuoqtd-publisher. Existing VPS services are not stopped.'
  exit 0
fi
[[ $EUID -eq 0 ]] || die 'Run as the authorized VPS administrator.'
command -v docker >/dev/null || die 'Docker is missing. Install Docker Engine before deploying.'
docker compose version >/dev/null || die 'Docker Compose plugin is missing.'
docker info >/dev/null 2>&1 || die 'Docker daemon is not available.'
[[ -f $TARGET/Dockerfile && -f $TARGET/compose.yaml ]] || die "Clone the repository into $TARGET first."
cd "$TARGET"

case "$action" in
  prepare)
    chmod 700 /root/Khuong "$TARGET"
    docker build -t khuoqtd-publisher .
    if [[ ! -e .env ]]; then
      docker run --rm -it --user "$(id -u):$(id -g)" \
        -v "$TARGET:/work" -w /work khuoqtd-publisher python -m app.setup
    fi
    chmod 600 .env
    printf '%s\n' 'Prepared. Edit .env locally on this VPS: DATABASE_URL, BASE_URL and OAuth settings.'
    ;;
  check)
    [[ -f .env ]] || die 'Run prepare first.'
    docker compose -p "$PROJECT" config --quiet
    docker compose -p "$PROJECT" build publisher
    docker compose -p "$PROJECT" run --rm --no-deps -T publisher \
      python -c 'from app.config import settings; settings.validate(); print("Configuration valid; no remote schema changed.")'
    printf '%s\n' 'Verify that DATABASE_URL belongs to the intended Supabase project before start.'
    ;;
  start)
    [[ -f .env ]] || die 'Run prepare first.'
    docker compose -p "$PROJECT" config --quiet
    profiles=()
    ports=(8000)
    if [[ ${2:-} == --https ]]; then
      profiles=(--profile https)
      ports+=(80 443)
    elif [[ -n ${2:-} ]]; then
      die 'Unknown option; only --https is supported.'
    fi
    for port in "${ports[@]}"; do
      if ss -ltnH "sport = :$port" | read -r _; then
        die "Port $port is already occupied. No existing service was stopped. Use the existing reverse proxy or manage this project's existing containers explicitly."
      fi
    done
    docker compose -p "$PROJECT" "${profiles[@]}" up -d --build
    printf '%s\n' 'Started this project. Run status and check /healthz through the configured HTTPS domain.'
    ;;
  status)
    docker compose -p "$PROJECT" ps
    ;;
  *) die 'Unknown action. Use help.' ;;
esac
