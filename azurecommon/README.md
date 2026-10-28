# Azure Common

Synchronous Azure REST client for Checkmk plugins, using only the Python
standard library. Install the `azurecommon` MKP on each consuming Checkmk site.

```python
from cmk_addons.plugins.azurecommon.lib.client import AzureClient, AzureError

azure = AzureClient(
    tenant_id, client_id, client_secret,
    proxy=None, timeout=60, max_retries=4,
)

sites_path = (
    f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
    "/providers/Microsoft.Web/sites"
)
apps = azure.web.get_paged(sites_path)
functions = azure.web.get_paged(f"{sites_path}/{app_name}/functions")

logs = azure.logs.post(
    f"/v1{resource_id}/query",
    payload={"query": kusto_query, "timespan": "PT3600S"},
)
invocations = azure.appinsights.get(
    f"/v1/apps/{appinsights_app_id}/query",
    params={"query": kusto_query},
)
```

Encode dynamic path segments with `urllib.parse.quote(value, safe="")` when
constructing paths. The library does not encode whole paths, which would also
encode their separators.

## Public contract

`AzureClient` exposes three `AzureServiceClient` instances:

| Client | Base URL | Scope | Automatic API version |
|---|---|---|---|
| `web` | `https://management.azure.com` | `https://management.azure.com/.default` | Microsoft.Web `2023-12-01` |
| `logs` | `https://api.loganalytics.io` | `https://api.loganalytics.io/.default` | None |
| `appinsights` | `https://api.applicationinsights.io` | `https://api.applicationinsights.io/.default` | None |

Each service exposes:

- `get(path, *, params=None)`: return a decoded JSON object.
- `post(path, *, payload)`: send a JSON object and return a decoded JSON object.
- `get_paged(path, *, params=None)`: lazily yield objects from `value`, following
  `nextLink` or `@odata.nextLink`. Parameters apply only to the initial request;
  continuation URLs supply subsequent query parameters.

Paths start at the service origin, including `/v1` where needed. Absolute
same-origin continuation URLs are supported; cross-origin requests and HTTP
redirects are rejected. The web client's API version is applied on every page
and cannot be overridden by request parameters.

All clients share credentials and a synchronized, per-scope token cache.
HTTP openers are local to each thread, so the client can be shared by caller-owned
thread pools. The library does not create threads or orchestrate operations.
Without an explicit proxy, urllib's standard environment proxy settings apply.

`timeout` is a positive per-request socket timeout, not an overall operation
deadline. `max_retries` is the number of retries after the initial attempt.
Connection/protocol failures (including truncated HTTP responses) and
HTTP 429/500/502/503/504 use exponential backoff;
HTTP retry delays honor seconds or HTTP-date `Retry-After` values.
An authenticated HTTP 401 triggers one token refresh and replay.

An optional `deadline=time.monotonic() + seconds` shares one absolute budget
across every call on the client, including token acquisition, pagination and
concurrent requests. It is not reset for each retry or page. Socket and CLI
timeouts are limited to the remaining budget, token-lock waits are bounded,
and retry delays that cannot fit fail immediately. Responses received after
the deadline are rejected; body reads check the budget between chunks.
No deadline is imposed by the library unless supplied by the caller.

`cancel()` permanently stops further calls on that client and wakes retry
backoffs. It does not kill a running thread, CLI process or blocking network
operation. The deadline is cooperative, not a hard process-runtime guarantee:
DNS resolution and blocking socket reads may outlive it. Checkmk's external
special-agent timeout remains the hard limit.

`AzureError` exposes `status` (HTTP status when available), `code` (Azure error
code when available) and `details` (decoded error response or raw text).
Empty successful responses return `{}`. Invalid JSON, non-object JSON and
malformed paginated responses raise `AzureError`. Missing credentials or invalid
timeout/retry configuration raise `ValueError`.

Service responses are otherwise uninterpreted. Plugins own resource paths,
queries, filtering, concurrency, table parsing, partial-query-error handling,
thresholds and Checkmk output. There are no discovery or query-domain helpers.

## Credential providers

The shorthand `AzureClient(tenant_id, client_id, client_secret)` uses a service
principal. Alternatively pass one of three explicit providers:

```python
from cmk_addons.plugins.azurecommon.lib.credentials import (
    AutoProvider, AzureCliProvider, ServicePrincipalProvider,
)

azure = AzureClient(
    credential=ServicePrincipalProvider(tenant_id, client_id, client_secret),
    proxy=proxy,
)
azure = AzureClient(credential=AzureCliProvider(proxy=proxy), proxy=proxy)
azure = AzureClient(
    credential=AutoProvider(tenant_id, client_id, client_secret, proxy=proxy),
    proxy=proxy,
)
```

`AzureCliProvider` invokes `az account get-access-token` for the requested scope,
using an existing `az login` session. It needs the CLI executable, not Azure SDK
packages in the Checkmk Python environment.

`AutoProvider` selects CLI when `az` exists in `PATH`, otherwise service
principal, once when constructed. Credentials are required only if service
principal is selected. A missing login, CLI error or subsequent disappearance
of the executable is an explicit error, not a silent identity switch.

All providers use the client's synchronized token cache and 401 refresh.
Service-principal token requests use the same HTTP transport, proxy, timeout
and retries as service requests. CLI providers accept their own proxy and
process timeout (60 seconds by default). Do not combine `credential=` with
positional service-principal credentials.
The client also passes the optional monotonic `deadline` to `get_token`; CLI
providers reduce their process timeout to the remaining budget.

## Packaging

Build using the repository's `mkp-builder` instructions with
`PLUGIN=azurecommon`. The release workflow publishes this MKP alongside the
plugins when its files change. Install or upgrade it before the consuming
plugins on every relevant site; MKP dependencies are not resolved automatically.

## Tests

The source-tree tests use standard-library `unittest` and mocked HTTP responses,
without Azure credentials or network requests. From the repository root:

```shell
python3 -m unittest discover -s azurecommon/tests
```
