#!/bin/zsh
# Naptime consolidator wrapper for launchd.
#
# Runs one consolidation sweep over $NAPMEM_HOME/memory_logs into
# $NAPMEM_HOME/napmem_pyramid.json. Credentials come from the operator's
# `ant auth login` OAuth profile (~/.config/anthropic/), which the anthropic
# SDK resolves natively — no key is stored here or in the plist. Without a
# profile the consolidator degrades to the heuristic extractor by itself.
#
# launchd starts jobs with a minimal environment, hence the explicit PATH
# (python3 + ollama live in /opt/homebrew/bin).

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

NAPMEM_HOME="${NAPMEM_HOME:-$HOME/.napmem}"
REPO_DIR="${NAPMEM_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

mkdir -p "$NAPMEM_HOME/memory_logs"

exec python3 "$REPO_DIR/naptime_consolidator.py" \
  --watch-dir "$NAPMEM_HOME/memory_logs" \
  --pyramid "$NAPMEM_HOME/napmem_pyramid.json" \
  --semantic-dedup \
  --once
