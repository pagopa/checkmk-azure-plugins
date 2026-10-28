# CheckMK Azure Monitor plugin

CheckMK special agent for querying Azure Monitor logs and metrics.

## Prerequisites

* CheckMK installation
* `azurecommon` MKP installed on the same site, before installing/upgrading this plugin

The special agent uses the dependency-free REST client from `azurecommon`;
no Azure SDK or additional Python packages are required. Install `azurecommon`
on every site that executes the agent. MKP dependencies are not resolved
automatically.

## Authentication

`--credential-provider` accepts `service-principal` (default), `az-cli` or `auto`.
Service-principal authentication requires tenant ID, client ID and client secret.
CLI authentication uses an existing `az login` session. Automatic mode uses CLI
if `az` is in `PATH`, otherwise service principal. CLI authentication errors do
not fall back to another identity. Existing Checkmk rules continue using service
principals; alternative providers can be selected when invoking the agent directly.

## Collection time budget

The agent shares a **300-second** budget across authentication, the query and
all retries. Override it for direct invocation with `--total-timeout SECONDS`
(a finite positive number). Retry delays must fit within the remaining budget;
responses received after expiry are rejected.

This is a cooperative budget: blocking DNS/socket operations cannot be forcibly
interrupted. Checkmk's external special-agent timeout remains the hard runtime
limit.
