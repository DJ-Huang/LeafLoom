#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
exec /bin/bash scripts/macos/launch.sh install "${1:-}"
