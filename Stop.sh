#!/bin/sh
set -e
cd -- "$(dirname -- "$0")"
exec /bin/bash scripts/macos/launch.sh stop
