"""Azure Functions special agent.

In the CheckMK "special agent" framework, this file is responsible to
compute the command line arguments for launching the actual check
script, libexec/agent_azurefunctions.  The command line arguments used
are taken from 'params', that are those configured in the gui via the
rulesets/special_agent.py.

"""
from cmk.server_side_calls.v1 import noop_parser
from cmk.server_side_calls.v1 import SpecialAgentConfig
from cmk.server_side_calls.v1 import SpecialAgentCommand


def _agent_arguments(params, host_config):
    args = [
        "--tenant-id", str(params['tenant_id']),
        "--subscription-id", str(params['subscription_id']),
        "--resource-group", str(params['resource_group']),
        "--client-id", str(params['client_id']),
        "--client-secret", params['client_secret'].unsafe(),
        "--appinsights-app-id", str(params['appinsights_app_id']),
        "--timedelta-kql", str(params['timedelta_kql']),
    ]

    if params.get('proxy', None):
        args.append("--proxy")
        args.append(str(params['proxy']))

    yield SpecialAgentCommand(command_arguments=args)


special_agent_hellospecial = SpecialAgentConfig(
    name="azurefunctions",
    parameter_parser=noop_parser,
    commands_function=_agent_arguments
)
