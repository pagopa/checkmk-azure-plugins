#!/bin/sh
set -eu

cd "$(dirname "$0")/../.."
docker-compose -f tests/compose/compose.yaml up -d --wait --wait-timeout 600
docker-compose -f tests/compose/compose.yaml exec -T --user cmk checkmk \
    bash -lc 'bash /workspace/tests/compose/install-plugins.sh'
printf '\nCheckmk is ready. Open http://localhost:8080/cmk/.\n'
printf 'User: cmkadmin; password: localdev (local development only).\n'
