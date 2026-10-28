# CheckMK Azure Functions plugin

CheckMK special agent for monitoring Azure Functions invocations.

## Prerequisites

* CheckMK installation
* `azurecommon` MKP installed on the same site, before installing/upgrading this plugin

The special agent uses the dependency-free REST client from `azurecommon`;
Azure SDK packages, `requests` and `aiohttp` are no longer required. Install
`azurecommon` on every site that executes the agent. MKP dependencies are not
resolved automatically.

## Timer schedules

The check evaluates NCRONTAB schedules using an internal standard-library-only
module; no `croniter` or other third-party Python packages are needed.
Schedules are evaluated in **UTC**, with five fields (minutes first, seconds
implicitly zero) or six fields (seconds first). Supported fields include
numeric values, `*`, comma-separated lists, inclusive ranges and positive steps,
plus English month/day names and three-letter abbreviations, case-insensitively.
Sunday is `0`; both day-of-month and day-of-week constraints must match, following
Azure NCRONTAB rather than Unix cron's OR semantics.

The expected invocation is the latest occurrence strictly before the check time.
Invalid or impossible schedules, `%AppSetting%` references, TimeSpan schedules
and extensions such as `L`, `W` or `#` produce an `UNKNOWN` result. Non-UTC
`WEBSITE_TIME_ZONE` settings are not collected or applied; use this check only
for UTC timer schedules.

## Authentication

`--credential-provider` accepts `service-principal` (default), `az-cli` or `auto`.
Service-principal authentication requires tenant ID, client ID and client secret.
CLI authentication uses an existing `az login` session. Automatic mode uses CLI
if `az` is in `PATH`, otherwise service principal. CLI authentication errors do
not fall back to another identity. Existing Checkmk rules continue using service
principals; alternative providers can be selected when invoking the agent directly.

`--use-cli-credentials` remains available as an alias for
`--credential-provider az-cli` for local development.

## Discovery concurrency

The Checkmk rule's optional **Function discovery workers** field sets the
maximum number of Function Apps queried concurrently during discovery. The
default is **8**, including for existing rules without this setting; the minimum
is **1**. Lower values can reduce pressure on Azure APIs.

For direct agent invocation, use `--max-workers N`. This setting controls only
the Function App discovery pool, not the independent Application Insights query
or the common Azure client.

## Collection time budget

The agent shares a **300-second** budget across authentication, discovery,
pagination, queries and retries. Override it for direct invocation with
`--total-timeout SECONDS` (a finite positive number).

On failure or deadline expiry, queued work is cancelled, further client calls
and retry waits are stopped, and no success section is emitted. Running I/O
cannot be forcibly killed by a thread pool; it finishes or reaches its socket
timeout. This is a cooperative budget, not a hard process kill: keep Checkmk's
external special-agent timeout configured as the final runtime limit.
