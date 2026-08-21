#!/usr/bin/env bash
# Naptime consolidator wrapper — portable (macOS launchd + Linux systemd).
#
# Mirrors the operator's real agent memory files into $NAPMEM_HOME/memory_logs
# as uniquely-named symlinks, then runs one consolidation sweep into
# $NAPMEM_HOME/napmem_pyramid.json. Sources (each skipped when absent):
#   1. Claude Code:   ~/.claude/projects/*/memory/*.md  (project-slug prefix)
#   2. Antigravity:   ~/.gemini/antigravity/brain/<task-uuid>/*.md
#      (agbrain_<uuid> prefix — every task dir repeats walkthrough.md etc.)
#   3. Mounted twins: /Volumes/mitch/.claude and /Volumes/mitch/.gemini
#      (macOS only) — keep-existing mode: identical copies collapse to one
#      session, mount-only files still get swept.
# Syncthing *sync-conflict* copies are skipped. Dead symlinks are pruned.
#
# Credentials come from the operator's `ant auth login` OAuth profile, which
# the anthropic SDK resolves natively — no key is stored here or in the
# service definitions. Without a profile the consolidator degrades to the
# heuristic extractor.
#
# PRIVACY: everything this mirror sweeps is sent to the Anthropic API (LLM
# extraction) and the Ollama embedding hosts — the mirror IS the consent
# boundary (docs/SECURITY.md).
#
# launchd/systemd start jobs with a minimal environment, hence the explicit
# PATH (python3/ollama live in /opt/homebrew/bin on macOS, /usr/bin +
# ~/.local/bin on Linux).

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"

NAPMEM_HOME="${NAPMEM_HOME:-$HOME/.napmem}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${NAPMEM_REPO:-$(dirname "$SCRIPT_DIR")}"
WATCH_DIR="$NAPMEM_HOME/memory_logs"

mkdir -p "$WATCH_DIR"

# --- Allowed roots (exfiltration guard) ------------------------------------
# The watch dir itself is a vetted root so plain files dropped directly into
# it still ingest; a hostile symlink there RESOLVES outside every root and is
# refused by the consolidator's race-free fd-based read guard.
# Hard requirement: without readlink -f (macOS < 12.3) resolve() would
# silently degrade and mirror() would skip EVERY source — a no-op sweep with
# exit 0. Refuse loudly instead.
if ! readlink -f / >/dev/null 2>&1; then
  echo "run-naptime: this system's readlink lacks -f; cannot run safely" >&2
  exit 1
fi

resolve() { readlink -f -- "$1" 2>/dev/null || echo "$1"; }

ALLOWED_ROOTS="$(resolve "$WATCH_DIR")"
for root in "$HOME/.claude" "$HOME/.gemini" /Volumes/mitch/.claude /Volumes/mitch/.gemini; do
  [ -d "$root" ] && ALLOWED_ROOTS="$ALLOWED_ROOTS:$(resolve "$root")"
done
export NAPMEM_ALLOWED_ROOTS="$ALLOWED_ROOTS"

# --- Mirror agent memory files as uniquely-named symlinks ------------------
mirror() {  # mirror <src> <link-name> [keep-existing]
  local src="$1" link="$WATCH_DIR/$2" keep="${3:-}"
  case "$src" in *sync-conflict*) return 0;; esac  # skip Syncthing conflict copies
  local real
  real="$(readlink -f -- "$src" 2>/dev/null)" || return 0
  [ -f "$real" ] || return 0
  local ok=""
  # set -f: the IFS-split root words must not undergo pathname expansion
  # (a root containing glob chars would silently mis-iterate).
  local IFS=':'
  set -f
  for root in $ALLOWED_ROOTS; do
    case "$real" in "$root"/*) ok=1; break;; esac
  done
  set +f
  if [ -z "$ok" ]; then
    echo "run-naptime: REFUSED out-of-root source: $src -> $real" >&2
    rm -f -- "$link"   # revoke a previously-mirrored link for this name
    return 0
  fi
  if [ -n "$keep" ] && { [ -e "$link" ] || [ -L "$link" ]; }; then
    return 0  # mounted twin: local mirror already owns this name
  fi
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    # A plain file an operator dropped into the watch dir owns its name —
    # never clobber it with a mirror link.
    echo "run-naptime: name collision with operator file, skipping: $link" >&2
    return 0
  fi
  if [ ! -L "$link" ] || [ "$(readlink -- "$link")" != "$src" ]; then
    ln -sf -- "$src" "$link"
  fi
}

mirror_claude() {  # mirror_claude <base-dir> [keep]
  local base="$1" keep="${2:-}"
  [ -d "$base/projects" ] || return 0
  for src in "$base"/projects/*/memory/*.md; do
    [ -e "$src" ] || continue
    local proj
    proj="$(basename "$(dirname "$(dirname "$src")")")"
    mirror "$src" "${proj}__$(basename "$src")" "$keep"
  done
}

mirror_antigravity() {  # mirror_antigravity <brain-dir> [keep]
  local brain="$1" keep="${2:-}"
  [ -d "$brain" ] || return 0
  for src in "$brain"/*/*.md; do
    [ -e "$src" ] || continue
    local task
    task="$(basename "$(dirname "$src")")"
    mirror "$src" "agbrain_${task}__$(basename "$src")" "$keep"
  done
}

mirror_claude "$HOME/.claude"
mirror_antigravity "$HOME/.gemini/antigravity/brain"
mirror_claude /Volumes/mitch/.claude keep
mirror_antigravity /Volumes/mitch/.gemini/antigravity/brain keep

# Prune symlinks whose target vanished (deleted project or memory file).
for link in "$WATCH_DIR"/*; do
  [ -L "$link" ] || continue
  [ -e "$link" ] || rm -f -- "$link"
done

# --- One consolidation sweep ----------------------------------------------
exec python3 "$REPO_DIR/naptime_consolidator.py" \
  --watch-dir "$WATCH_DIR" \
  --pyramid "$NAPMEM_HOME/napmem_pyramid.json" \
  --semantic-dedup \
  --once
