#!/bin/bash
# One supervisor per state directory, including Finder and login launches.
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
BUNDLE="$HOME/Applications/本地知识库.app"
REVISION=$(/usr/bin/plutil -extract VaultRagMenuRevision raw -o - "$BUNDLE/Contents/Info.plist" 2>/dev/null || true)
if [[ $REVISION == 4 ]]; then
    "$BUNDLE/Contents/MacOS/menubar" &
else
    # The legacy binary targets macOS 15 and does not honor a custom state.
    # System AppKit through JXA needs no end-user compiler or third-party runtime.
    /usr/bin/osascript -l JavaScript "$REPOSITORY/scripts/macos/menu.js" "$REPOSITORY" "$STATE" &
fi
CHILD=$!
trap 'kill -TERM "$CHILD" 2>/dev/null || true' TERM INT
wait "$CHILD" || true
