#!/bin/sh
# Keep interactive terminal windows open so installation errors remain visible.
if cd -- "$(dirname -- "$0")"; then
    /bin/bash scripts/macos/launch.sh install "${1:-}"
    result=$?
else
    result=1
fi
if [ "$result" -eq 0 ]; then
    printf '\n安装完成。\n'
else
    printf '\n安装失败（退出码 %s），请查看上方错误信息。\n' "$result" >&2
fi
if [ -t 0 ] && [ -t 1 ]; then
    printf '按回车键关闭…'
    IFS= read -r reply || :
fi
exit "$result"
