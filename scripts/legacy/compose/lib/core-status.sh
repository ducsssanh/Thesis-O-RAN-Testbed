#!/usr/bin/env bash
if command -v docker >/dev/null && docker ps --filter 'name=^amf$' --format '{{.Names}}' | grep -qx amf; then
    echo '5gdeploy: RUNNING'
else
    echo '5gdeploy: NOT_RUNNING'
fi
