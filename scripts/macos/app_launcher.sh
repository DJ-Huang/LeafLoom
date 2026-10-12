#!/bin/bash
set -euo pipefail
BUNDLE=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ADJACENT=$(dirname -- "$BUNDLE")
if [[ -f "$ADJACENT/scripts/macos/launch.sh" ]]; then
    REPOSITORY="$ADJACENT"
else
    REPOSITORY=$(/usr/bin/plutil -extract VaultRagRepository raw -o - "$BUNDLE/Contents/Info.plist")
fi
STATE=$(/usr/bin/plutil -extract VaultRagState raw -o - "$BUNDLE/Contents/Info.plist" 2>/dev/null || true)
if [[ -n "$STATE" ]]; then export VAULT_RAG_HOME="$STATE"; fi
if [[ ! -f "$REPOSITORY/scripts/macos/launch.sh" ]]; then
    /usr/bin/osascript -e 'display alert "无法找到知识库目录" message "请双击仓库内的Install.command，更新应用路径。" as critical'
    exit 1
fi
if [[ ${1:-} == --menubar ]]; then
    exec /bin/bash "$REPOSITORY/scripts/macos/launch.sh" menubar
fi
# The .app uses Terminal only when installation/repair is needed, preserving progress/errors.
PYTHON="$REPOSITORY/.venv/bin/python"
STATE=${VAULT_RAG_HOME:-"$HOME/Library/Application Support/VaultRag"}
if [[ -x "$PYTHON" ]] && "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" --state "$STATE" --action check; then
    exec /bin/bash "$REPOSITORY/scripts/macos/launch.sh" open
fi
/usr/bin/osascript - "$REPOSITORY" "$STATE" <<'APPLESCRIPT'
on run argv
    set repo to item 1 of argv
    set stateDir to item 2 of argv
    tell application "Terminal"
        activate
        do script "VAULT_RAG_HOME=" & quoted form of stateDir & " /bin/bash " & quoted form of (repo & "/scripts/macos/launch.sh") & " install"
    end tell
end run
APPLESCRIPT
