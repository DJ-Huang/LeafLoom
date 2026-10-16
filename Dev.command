#!/bin/sh
# Finder double-click entry point; keep setup errors visible in Terminal.
/bin/sh "$(dirname -- "$0")/Dev.sh"
result=$?
if [ "$result" -ne 0 ] && [ -t 0 ] && [ -t 1 ]; then
    printf '\nDevelopment startup failed (exit %s). Press Return to close…' "$result" >&2
    IFS= read -r reply || :
fi
exit "$result"
