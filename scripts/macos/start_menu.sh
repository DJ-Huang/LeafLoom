#!/bin/bash
# One supervisor per state directory, including manual and login launches.
set -euo pipefail
REPOSITORY=${1:?repository required}
STATE=${2:?state required}
export VAULT_RAG_HOME="$STATE"
LOCK="$STATE/menubar.lock"
mkdir -p "$STATE/logs"
if ! mkdir "$LOCK" 2>/dev/null; then
    OWNER=$(cat "$LOCK/pid" 2>/dev/null || true)
    if [[ $OWNER =~ ^[0-9]+$ ]] && ! kill -0 "$OWNER" 2>/dev/null; then
        /bin/rm -f "$LOCK/pid"; /bin/rmdir "$LOCK"; mkdir "$LOCK"
    else
        exit 0
    fi
fi
echo $$ > "$LOCK/pid"
cleanup() { /bin/rm -f "$LOCK/pid"; /bin/rmdir "$LOCK"; }
trap cleanup EXIT
/bin/rm -f "$STATE/menubar.stop"
# System AppKit through JXA needs no compiler, app bundle or third-party runtime.
/usr/bin/osascript -l JavaScript "$REPOSITORY/scripts/macos/menu.js" "$REPOSITORY" "$STATE" &
CHILD=$!
trap 'kill -TERM "$CHILD" 2>/dev/null || true' TERM INT
wait "$CHILD" || true
