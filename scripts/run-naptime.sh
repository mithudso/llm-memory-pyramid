#!/bin/zsh
# Naptime consolidator wrapper for launchd.
#
# Mirrors the operator's real Claude Code memory files
# (~/.claude/projects/*/memory/*.md) into $NAPMEM_HOME/memory_logs as
# uniquely-named symlinks, then runs one consolidation sweep into
# $NAPMEM_HOME/napmem_pyramid.json. Symlink names are prefixed with the
# project-dir slug so identically-named files (every project has a MEMORY.md)
# map to distinct, stable session ids. Dead symlinks are pruned each run.
#
# Credentials come from the operator's `ant auth login` OAuth profile
# (~/.config/anthropic/), which the anthropic SDK resolves natively — no key
# is stored here or in the plist. Without a profile the consolidator degrades
# to the heuristic extractor.
#
# PRIVACY: everything this mirror sweeps is sent to the Anthropic API (LLM
# extraction) and the Ollama embedding host — the mirror IS the consent
# boundary (docs/SECURITY.md). To exclude a project, delete its symlinks and
# add the project slug to the prune-exceptions below, or edit the glob.
#
# launchd starts jobs with a minimal environment, hence the explicit PATH
# (python3 + ollama live in /opt/homebrew/bin).

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

NAPMEM_HOME="${NAPMEM_HOME:-$HOME/.napmem}"
REPO_DIR="${NAPMEM_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
WATCH_DIR="$NAPMEM_HOME/memory_logs"

mkdir -p "$WATCH_DIR"

# --- Mirror Claude Code memory files as project-prefixed symlinks ----------
setopt null_glob
for src in $HOME/.claude/projects/*/memory/*.md; do
  proj="${src:h:h:t}"          # project dir slug (e.g. -Users-mitch-hudson-dev-foo)
  link="$WATCH_DIR/${proj}__${src:t}"
  [[ -L "$link" && "$(readlink -- "$link")" == "$src" ]] || ln -sf -- "$src" "$link"
done

# Prune symlinks whose target vanished (deleted project or memory file).
for link in "$WATCH_DIR"/*(N@); do
  [[ -e "$link" ]] || rm -f -- "$link"
done

# --- One consolidation sweep ----------------------------------------------
exec python3 "$REPO_DIR/naptime_consolidator.py" \
  --watch-dir "$WATCH_DIR" \
  --pyramid "$NAPMEM_HOME/napmem_pyramid.json" \
  --semantic-dedup \
  --once
