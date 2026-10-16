#!/bin/sh
set -e
cd -- "$(dirname -- "$0")"

# Finder/Terminal may not include Homebrew or uv's user installation in PATH.
PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
for tool in node npm uv; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Missing %s. Install Node 22+ (with npm) and uv, then try again.\n' "$tool" >&2
        exit 1
    fi
done
exec node scripts/dev-desktop.cjs
