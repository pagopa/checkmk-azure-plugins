# CheckMK Azure plugins

CheckMK special agent plugins for expanding Azure monitoring.

## Plugins

- `azuremonitor`: query Azure Monitor.
- `azurefunctions`: monitor Azure Functions executions.

## MKP builder

The folder `mkp-builder` contains a Dockerfile to produce a container
that builds [MKP](https://docs.checkmk.com/latest/en/mkps.html)
packages from sources.  It is used in CI/CD to build plugins and
publish them in releases.

## Versioning

For the sake of simplicity, this whole repo has a single "version"
following SemVer. This means that a breaking change, or minor, or
patch, could impact only one of the published plugins.  Check releases
for the changelog!
