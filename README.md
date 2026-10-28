# CheckMK Azure plugins

CheckMK special agent plugins for expanding Azure monitoring.

## Plugins

- `azurecommon`: shared, dependency-free Azure REST client.
- `azuremonitor`: query Azure Monitor.
- `azurefunctions`: monitor Azure Functions executions.

Install or upgrade `azurecommon` first, then the consuming plugins, on every
Checkmk site that runs their special agents. MKP dependencies are not resolved
automatically. The checks and special agents use only the Python standard
library and Checkmk's own APIs; no additional Python packages are required.

The agents default to service-principal authentication. When invoked directly,
`--credential-provider az-cli` uses Azure CLI and `--credential-provider auto`
selects CLI if installed, otherwise service principal.

## Local Checkmk environment

See [tests/compose/README.md](tests/compose/README.md) for local setup and usage.

## Tests

Standard-library tests mock Azure requests and do not require Checkmk or Azure
credentials:

```shell
python3 -m unittest discover -s azurecommon/tests
python3 -m unittest discover -s tests
```

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
