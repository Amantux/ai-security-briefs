#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"
mkdir -p logs briefs weekly
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
# Cheap dep check (no-op when feedparser is installed)
"$PY" -c "import feedparser" 2>/dev/null || .venv/bin/pip install -q -r requirements.txt

MODE="${1:-}"
case "$MODE" in
  --no-push)     RUN_FETCH=1; RUN_SUMMARY=both; PUSH=0 ;;
  --weekly-only) RUN_FETCH=0; RUN_SUMMARY=weekly; PUSH=1 ;;
  "")            RUN_FETCH=1; RUN_SUMMARY=both; PUSH=1 ;;
  *) echo "usage: run.sh [--no-push|--weekly-only]" ; exit 64 ;;
esac

{
  echo "=== run $(date -u +%FT%TZ) ==="
  [ "$RUN_FETCH" = 1 ] && "$PY" fetcher.py --items items.json
  case "$RUN_SUMMARY" in
    both)   "$PY" summarize.py --items items.json ;;
    weekly) "$PY" summarize.py --items items.json --only weekly ;;
  esac
} 2>&1 | tee -a "logs/run-$(date +%F).log"

if [ "$PUSH" = 1 ]; then
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "git: not a repository; skipping sync (exit 0)"
    exit 0
  fi
  git add -A briefs weekly
  if git diff --cached --quiet; then
    echo "git: nothing new; no-op"
  else
    git commit -m "briefs: auto-update $(date '+%Y-%m-%d %H:%M %Z')"
    git push origin main
  fi
fi
exit 0
