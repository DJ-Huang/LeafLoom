#!/bin/bash
# macOS 14+ Apple Silicon bootstrap. Uses only tools shipped with macOS.
set -euo pipefail
umask 077
REPOSITORY=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ACTION=${1:-open}
NO_OPEN=${2:-}
STATE=${VAULT_RAG_HOME:-"$HOME/Library/Application Support/VaultRag"}
leafloom_text() { /usr/bin/osascript -l JavaScript "$REPOSITORY/scripts/macos/localize.js" "$REPOSITORY" "$STATE" "$1"; }
export VAULT_RAG_HOME="$STATE" PYTHONUTF8=1 PYTHONUNBUFFERED=1
if [[ -f "$STATE/desktop-install.json" ]]; then
    DESKTOP=$(/usr/bin/plutil -extract executable raw -o - "$STATE/desktop-install.json" 2>/dev/null || true)
    if [[ -n "$DESKTOP" && -x "$DESKTOP" ]]; then
        if [[ $ACTION == stop ]]; then
            mkdir -p "$STATE/desktop-control"
            printf '1' > "$STATE/desktop-control/quit"
        else
            "$DESKTOP" >/dev/null 2>&1 &
        fi
        exit 0
    fi
fi
MANIFEST="$REPOSITORY/scripts/runtimes.json"
if [[ $(/usr/bin/uname -m) != arm64 || $(/usr/bin/sw_vers -productVersion | /usr/bin/cut -d. -f1) -lt 14 ]]; then
    leafloom_text '支持 macOS 14+ Apple 芯片。' >&2
    exit 1
fi
read_manifest() { /usr/bin/plutil -extract "$1" raw -o - "$MANIFEST"; }
mkdir -p "$STATE/logs" "$STATE/runtimes"
chmod 700 "$STATE"
export UV_PYTHON_INSTALL_DIR="$STATE/runtimes/python"
export UV_PYTHON_BIN_DIR="$STATE/runtimes/python-bin"
export UV_CACHE_DIR="$STATE/runtimes/uv-cache"
export UV_PYTHON_CACHE_DIR="$STATE/runtimes/python-archives"
PYTHON_VERSION=$(read_manifest python)
UV_VERSION=$(read_manifest uv_version)
UV_DIR="$STATE/runtimes/uv-$UV_VERSION"
UV="$UV_DIR/uv"
PYTHON=''
if [[ -f "$STATE/bootstrap-python.json" ]]; then
    PYTHON=$(/usr/bin/plutil -extract python raw -o - "$STATE/bootstrap-python.json" 2>/dev/null || true)
fi
# Normal launch stays offline. A legacy venv can run the compatibility check.
if [[ ! -x "$PYTHON" && -x "$REPOSITORY/.venv/bin/python" ]]; then PYTHON="$REPOSITORY/.venv/bin/python"; fi
python_current() {
    [[ -x "$PYTHON" ]] && "$PYTHON" -c 'import sys; sys.exit(0 if ".".join(map(str, sys.version_info[:3])) == sys.argv[1] else 1)' "$PYTHON_VERSION"
}
if [[ $ACTION == install ]] && python_current; then
    if "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" --repository "$REPOSITORY" --state "$STATE" --action check && \
       "$REPOSITORY/.venv/bin/python" -X utf8 "$REPOSITORY/scripts/install_actions.py" check >/dev/null 2>&1; then
        ARGS=(--repository "$REPOSITORY" --state "$STATE" --action install)
        if [[ $NO_OPEN == --no-open ]]; then ARGS+=(--no-open); fi
        exec "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" "${ARGS[@]}"
    fi
fi
if [[ $ACTION == stop ]]; then
    if [[ -x "$PYTHON" ]]; then
        exec "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" --repository "$REPOSITORY" --state "$STATE" --action stop --no-open
    fi
    exit 0
fi
if [[ $ACTION == open || $ACTION == menubar ]]; then
    if [[ -x "$PYTHON" ]]; then
        if [[ $ACTION == open ]]; then
            if "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" --repository "$REPOSITORY" --state "$STATE" --action open --no-install; then
                exit 0
            else
                RESULT=$?
                if [[ $RESULT != 3 ]]; then exit "$RESULT"; fi
            fi
        elif "$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" --repository "$REPOSITORY" --state "$STATE" --action check; then
            exec /bin/bash "$REPOSITORY/scripts/macos/start_menu.sh" "$REPOSITORY" "$STATE"
        fi
    fi
fi

# mkdir plus PID avoids concurrent bootstrap extraction; EXIT releases our own lock.
BOOTSTRAP_LOCK="$STATE/bootstrap.lock"
if ! mkdir "$BOOTSTRAP_LOCK" 2>/dev/null; then
    OWNER=$(cat "$BOOTSTRAP_LOCK/pid" 2>/dev/null || true)
    if [[ $OWNER =~ ^[0-9]+$ ]] && ! kill -0 "$OWNER" 2>/dev/null; then
        /bin/rm -f "$BOOTSTRAP_LOCK/pid"
        /bin/rmdir "$BOOTSTRAP_LOCK"
        mkdir "$BOOTSTRAP_LOCK"
    else
        leafloom_text '另一个安装正在进行，请等待完成。' >&2; exit 1
    fi
fi
echo $$ > "$BOOTSTRAP_LOCK/pid"
release_lock() { /bin/rm -f "$BOOTSTRAP_LOCK/pid"; /bin/rmdir "$BOOTSTRAP_LOCK"; }
trap release_lock EXIT
exec > >(/usr/bin/tee -a "$STATE/logs/bootstrap.log") 2>&1
echo "[1/2] $(leafloom_text '准备已校验的依赖安装器…')"
UV_URL=$(read_manifest 'platforms.macos-arm64.uv.url')
UV_SHA=$(read_manifest 'platforms.macos-arm64.uv.sha256')
UV_ARCHIVE="$STATE/runtimes/${UV_URL##*/}"
if [[ ! -x "$UV" || ! -f "$UV_DIR/.verified" || $(cat "$UV_DIR/.verified") != "$UV_SHA" ]] || ! "$UV" --version | /usr/bin/grep -q "^uv $UV_VERSION "; then
    if [[ ! -f "$UV_ARCHIVE" || $(/usr/bin/shasum -a 256 "$UV_ARCHIVE" | /usr/bin/awk '{print $1}') != "$UV_SHA" ]]; then
        /usr/bin/curl --fail --location --retry 2 --connect-timeout 30 --output "$UV_ARCHIVE.part" "$UV_URL"
        [[ $(/usr/bin/shasum -a 256 "$UV_ARCHIVE.part" | /usr/bin/awk '{print $1}') == "$UV_SHA" ]] || { leafloom_text 'uv 下载校验失败'; exit 1; }
        /bin/mv "$UV_ARCHIVE.part" "$UV_ARCHIVE"
    fi
    if [[ -e "$UV_DIR" ]]; then /bin/mv "$UV_DIR" "$UV_DIR-old-$(/usr/bin/uuidgen)"; fi
    mkdir "$UV_DIR"
    /usr/bin/tar -xzf "$UV_ARCHIVE" --strip-components=1 -C "$UV_DIR"
    "$UV" --version | /usr/bin/grep -q "^uv $UV_VERSION "
    printf '%s' "$UV_SHA" > "$UV_DIR/.verified"
fi
echo "[2/2] $(leafloom_text '准备私有 Python，复用已有下载…')"
if python_current; then
    leafloom_text 'Python 版本符合要求，跳过下载安装。'
else
    PYTHON_KEY=$(read_manifest 'platforms.macos-arm64.python.key')
    PYTHON_DOWNLOADS="$STATE/runtimes/python-downloads.json"
    printf '{"%s":%s}' "$PYTHON_KEY" "$(/usr/bin/plutil -extract 'platforms.macos-arm64.python' json -o - "$MANIFEST")" > "$PYTHON_DOWNLOADS"
    for ATTEMPT in 1 2 3; do
        if "$UV" python install --no-bin --python-downloads-json-url "$PYTHON_DOWNLOADS" "$PYTHON_VERSION" 2>&1 | /usr/bin/tee "$STATE/logs/python-bootstrap-last.log"; then break; fi
        if [[ $ATTEMPT == 3 ]] || ! /usr/bin/grep -Eiq 'timed? ?out|connection (reset|refused|aborted)|temporar|429|502|503|504|name resolution' "$STATE/logs/python-bootstrap-last.log"; then
            echo "$(leafloom_text 'Python 准备失败。') $(leafloom_text '日志：')$STATE/logs/bootstrap.log $(leafloom_text '再次双击入口可重试。')" >&2; exit 1
        fi
        echo "$(leafloom_text '暂时性网络错误，重试 ')$ATTEMPT/2…"
        /bin/sleep $((ATTEMPT * 2))
    done
    PYTHON=$("$UV" python find --system --managed-python --no-project --no-python-downloads "$PYTHON_VERSION")
    "$PYTHON" -c 'import json,sys,pathlib,os; p=pathlib.Path(sys.argv[1]); t=p.with_suffix(".tmp"); t.write_text(json.dumps({"python":sys.executable,"version":sys.argv[2]})); os.replace(t,p)' "$STATE/bootstrap-python.json" "$PYTHON_VERSION"
fi
ARGS=(--repository "$REPOSITORY" --state "$STATE" --action install)
if [[ $NO_OPEN == --no-open || $ACTION == menubar ]]; then ARGS+=(--no-open); fi
"$PYTHON" -X utf8 "$REPOSITORY/scripts/installer.py" "${ARGS[@]}"
if [[ $ACTION == menubar ]]; then
    /bin/bash "$REPOSITORY/scripts/macos/start_menu.sh" "$REPOSITORY" "$STATE" &
fi
