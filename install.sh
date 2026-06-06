#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-$HOME/.claude/skills/epiphany-plan}"
mkdir -p "$DEST"
HERE="$(cd "$(dirname "$0")" && pwd)"
cp -r "$HERE"/* "$DEST"/
echo "installed epiphany-plan -> $DEST"
