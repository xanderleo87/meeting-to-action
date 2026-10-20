#!/usr/bin/env bash
# Deploy Meeting to Action to a fresh Railway project with the Railway CLI.
# Secrets come from the environment or the gitignored .env next to this repo; nothing is printed.
#   APP_ACCESS_KEY      the X-API-Key the web page will ask for (from .env)
#   ANTHROPIC_API_KEY   from the environment, or copied from the Railway service named in SOURCE_PROJECT_DIR
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
[ -f .env ] && set -a && . ./.env && set +a

if ! railway status >/dev/null 2>&1; then
  railway init --name meeting-to-action --workspace "${RAILWAY_WORKSPACE:-anasopie2's Projects}" >/dev/null 2>&1
  railway status >/dev/null 2>&1 || { echo "STEP init: not linked (Railway still refusing project creation)"; exit 2; }
fi
echo "STEP init: linked"

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${SOURCE_PROJECT_DIR:-}" ]; then
  ANTHROPIC_API_KEY=$(cd "$SOURCE_PROJECT_DIR" && railway variables --service app --kv 2>/dev/null | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2- | tr -d '\r')
fi
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "STEP keys: ANTHROPIC_API_KEY missing"; exit 3; }
[ -n "${APP_ACCESS_KEY:-}" ] || { echo "STEP keys: APP_ACCESS_KEY missing"; exit 3; }
echo "STEP keys: ok"

railway add --database postgres >/dev/null 2>&1 && echo "STEP postgres: added" || echo "STEP postgres: add returned non-zero (may already exist)"
railway add --service app \
  --variables "CLAUDE_MODEL=${CLAUDE_MODEL:-claude-sonnet-5-5}" \
  --variables "APP_ACCESS_KEY=$APP_ACCESS_KEY" \
  --variables "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" \
  --variables 'DATABASE_URL=${{Postgres.DATABASE_URL}}' >/dev/null 2>&1 && echo "STEP service: app created" || echo "STEP service: add returned non-zero"
railway service app >/dev/null 2>&1 || railway service link app >/dev/null 2>&1
echo "STEP variables: $(railway variables --service app --kv 2>/dev/null | cut -d= -f1 | tr '\n' ' ')"
railway up --service app --detach 2>&1 | tail -3
railway domain --service app 2>&1 | tail -2
echo "STEP deploy: triggered"
