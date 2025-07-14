"""Azure Monitor special agent.

In the CheckMK "special agent" framework, this file is responsible to
compute the command line arguments for launching the actual check
script, libexec/agent_azuremonitor.  The command line arguments used
are taken from 'params', that are those configured in the gui via the
rulesets/special_agent.py.

"""
from cmk.server_side_calls.v1 import noop_parser
from cmk.server_side_calls.v1 import SpecialAgentConfig
from cmk.server_side_calls.v1 import SpecialAgentCommand


def _agent_arguments(params, host_config):
    args = [
        "--tenant-id", str(params['tenant_id']),
        "--client-id", str(params['client_id']),
        "--client-secret", params['client_secret'].unsafe(),
        "--resource-id", str(params['resource_id']),
        "--timedelta-seconds", str(params['timedelta_seconds']),
    ]

    if params.get('count_crit', None):
        args.append("--count-crit")
        args.append(str(params['count_crit']))
    if params.get('count_warn', None):
        args.append("--count-warn")
        args.append(str(params['count_warn']))
    if params.get('proxy', None):
        args.append("--proxy")
        args.append(str(params['proxy']))

    # WARNING: MultilineText (--query arg) causes bugs and pains.
    # Here's what I have learned:
    # - replace newlines otherwise it
    #   crashes.  this has a reference in checkmk sources as well:
    #   https://github.com/Checkmk/checkmk/blob/3efe85dba2f8ee390168fd91a9997203d1aacd4b/cmk/plugins/collection/server_side_calls/sql.py#L84
    # - don't know why, but if you don't keep that as LAST argument,
    # it crashes
    args.append("--query")
    kql = str(params['query']).replace("\n", "___cmk_azuremonitor_newline___")
    args.append(kql)

    yield SpecialAgentCommand(command_arguments=args)


special_agent_hellospecial = SpecialAgentConfig(
    name="azuremonitor",
    parameter_parser=noop_parser,
    commands_function=_agent_arguments
)
