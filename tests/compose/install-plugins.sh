#!/bin/bash
set -euo pipefail

if [[ ${OMD_SITE:-} != cmk ]]; then
    printf 'Run this script as the cmk site user inside the Checkmk container.\n' >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

for plugin in azurecommon azuremonitor azurefunctions; do
    destination="$OMD_ROOT/local/lib/python3/cmk_addons/plugins/$plugin"
    mkdir -p "$destination"
    tar -C "/workspace/$plugin/$plugin" \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='_vendor' -cf - . |
        tar -C "$destination" -xf -
    sed "s/'version': 'x.x.x'/'version': '0.1.0'/" \
        "/workspace/$plugin/$plugin.manifest" > "$work/$plugin.manifest"
    mkp package "$work/$plugin.manifest"
done

cmk --version
mkp list
printf '\nPlugin sources deployed and MKPs built in the site package directory.\n'
