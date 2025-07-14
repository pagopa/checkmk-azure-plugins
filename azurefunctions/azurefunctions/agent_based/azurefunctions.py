#!/usr/bin/env python3

from cmk.agent_based.v2 import AgentSection
from cmk.agent_based.v2 import CheckPlugin
from cmk.agent_based.v2 import Service
from cmk.agent_based.v2 import Result
from cmk.agent_based.v2 import State
from cmk.utils import debug
from pprint import pprint
import json
import traceback
from itertools import chain


def parse_azurefunctions(string_table):
    # string_table is a list of lists, each inner list is one line of
    # the stdout in ../libexec/agent_azurefunctions

    try:
        # flatten the list because it has every element wrapped in another list
        input_list = list(chain.from_iterable(string_table))

        count_thresholds_dict = input_list[0]
        failure_thresholds_dict = input_list[1]
        logs = input_list[2:]

        parsed = {
            'logs': logs,
            'count_thresholds': json.loads(count_thresholds_dict),
            'failure_thresholds': json.loads(failure_thresholds_dict),
            'error': None,
        }

        if debug.enabled():
            pprint(string_table)
            pprint(parsed)
    except Exception as e:
        parsed = {
            'logs': [f'parsing failed: {e}'],
            'count_thresholds': {},
            'failure_thresholds': {},
            'error': traceback.format_exc(),
        }

    return parsed


def discover_azurefunctions(section):
    yield Service()


def check_azurefunctions(section):
    try:
        logs = section['logs']
        if section['error']:
            yield Result(
                state=State.UNKNOWN,
                summary=logs,
                details=section['error'],
            )
            return

        count_thresholds = section['count_thresholds']
        failure_thresholds = section['failure_thresholds']
        count_wl = count_thresholds.get('warn_lower', None) or -1
        count_wu = count_thresholds.get('warn_upper', None) or float('inf')
        count_cl = count_thresholds.get('crit_lower', None) or -1
        count_cu = count_thresholds.get('crit_upper', None) or float('inf')
        failure_wl = failure_thresholds.get('warn_lower', None) or -1
        failure_wu = failure_thresholds.get('warn_upper', None) or float('inf')
        failure_cl = failure_thresholds.get('crit_lower', None) or -1
        failure_cu = failure_thresholds.get('crit_upper', None) or float('inf')

        invocs = len(logs)
        dictlogs = [json.loads(log) for log in logs]
        failures = len([
            log for log in dictlogs if log.get('success') != 'True'
            or log.get('resultCode') not in ['0', '200']
        ])

        logs_summary = f"{invocs} invocations with {failures} failures"

        log_str = '\n'.join(logs) if logs else None

        if invocs >= count_cu or invocs <= count_cl:
            state = State.CRIT
        elif failures >= failure_cu or failures <= failure_cl:
            state = State.CRIT
        elif invocs >= count_wu or invocs <= count_wl:
            state = State.WARN
        elif failures >= failure_wu or failures <= failure_wl:
            state = State.WARN
        else:
            state = State.OK

        yield Result(state=state, summary=logs_summary, details=log_str)
    except Exception as e:
        yield Result(
            state=State.UNKNOWN,
            summary=f'Check crash: {e}',
            details=traceback.format_exc(),
        )


agent_section_azurefunctions = AgentSection(
    name="azurefunctions",
    parse_function=parse_azurefunctions,
)

check_plugin_myhostgroups = CheckPlugin(
    name="azurefunctions",
    service_name="Azure Function invocations and failures",
    discovery_function=discover_azurefunctions,
    check_function=check_azurefunctions,
)
