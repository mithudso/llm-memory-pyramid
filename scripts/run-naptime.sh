#!/bin/zsh
# Naptime consolidator wrapper for launchd.
#
# Mirrors the operator's real agent memory files into $NAPMEM_HOME/memory_logs
# as uniquely-named symlinks, then runs one consolidation sweep into
# $NAPMEM_HOME/napmem_pyramid.json. Sources:
#   1. Claude Code:   ~/.claude/projects/*/memory/*.md  (project-slug prefix)
#   2. Antigravity:   ~/.gemini/antigravity/brain/<task-uuid>/*.md
#      (agbrain_<uuid> prefix — every task dir repeats walkthrough.md etc.)
#   3. Volume twins:  /Volumes/mitch/.claude and /Volumes/mitch/.gemini —
#      Syncthing copies of 1-2. Only files whose link name is not already
#      mirrored locally are added, so identical twins collapse to one session
#      while volume-only files still get swept if the copies diverge.
# Dead symlinks are pruned each run.
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

# --- Mirror agent memory files as uniquely-named symlinks ------------------
setopt null_glob

# Exfiltration guard: the sources are Syncthing-synced, so a compromised peer
# could sync a symlink named foo.md pointing at an arbitrary local file (SSH
# keys, tokens) and this pipeline would upload the target's content. Mirror
# only files that RESOLVE inside the vetted memory roots — anything else is
# refused and logged.
ALLOWED_ROOTS=()
for root in "$HOME/.claude" "$HOME/.gemini" /Volumes/mitch/.claude /Volumes/mitch/.gemini; do
  [[ -d "$root" ]] && ALLOWED_ROOTS+=("$(readlink -f -- "$root")")
done

# Race-free second layer: the consolidator re-verifies every file AT READ TIME
# against the same roots (fd-based, cannot be raced by a post-mirror swap).
export NAPMEM_ALLOWED_ROOTS="${(j.:.)ALLOWED_ROOTS}"

mirror() {  # mirror <src> <link-name> [keep-existing]
  local src="$1" link="$WATCH_DIR/$2" keep="${3:-}"
  [[ "$src" == *sync-conflict* ]] && return 0  # skip Syncthing conflict copies
  local real ok=""
  real="$(readlink -f -- "$src" 2>/dev/null)" || return 0
  [[ -f "$real" ]] || return 0
  for root in "${ALLOWED_ROOTS[@]}"; do
    [[ "$real" == "$root"/* ]] && ok=1 && break
  done
  if [[ -z "$ok" ]]; then
    print -u2 "run-naptime: REFUSED out-of-root source: $src -> $real"
    rm -f -- "$link"   # revoke a previously-mirrored link for this name
    return 0
  fi
  if [[ -n "$keep" && ( -L "$link" || -e "$link" ) ]]; then
    return 0  # volume twin: local mirror already owns this name
  fi
  [[ -L "$link" && "$(readlink -- "$link")" == "$src" ]] || ln -sf -- "$src" "$link"
}

# 1. Claude Code project memory (project-dir slug prefix)
for src in $HOME/.claude/projects/*/memory/*.md; do
  mirror "$src" "${src:h:h:t}__${src:t}"
done

# 2. Antigravity task-brain artifacts (task-uuid prefix)
for src in $HOME/.gemini/antigravity/brain/*/*.md; do
  mirror "$src" "agbrain_${src:h:t}__${src:t}"
done

# 3. Volume twins — add only names the local mirror does not already carry.
if [[ -d /Volumes/mitch ]]; then
  for src in /Volumes/mitch/.claude/projects/*/memory/*.md; do
    mirror "$src" "${src:h:h:t}__${src:t}" keep
  done
  for src in /Volumes/mitch/.gemini/antigravity/brain/*/*.md; do
    mirror "$src" "agbrain_${src:h:t}__${src:t}" keep
  done
fi

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
