#!/usr/bin/env python3

from cmk.agent_based.v2 import AgentSection
from cmk.agent_based.v2 import CheckPlugin
from cmk.agent_based.v2 import Service
from cmk.agent_based.v2 import Result
from cmk.agent_based.v2 import State
from cmk.utils import debug
from pprint import pprint
import traceback
from itertools import chain


def parse_azuremonitor(string_table):
    # string_table is a list of lists, each inner list is one line of
    # the stdout in ../libexec/agent_azuremonitor

    def _safe_parse_int(s, default=0):
        try:
            return int(s)
        except Exception:
            return default

    try:
        # flatten the list because it has every element wrapped in another list
        input_list = list(chain.from_iterable(string_table))

        count_warn_str = input_list[0]
        count_crit_str = input_list[1]
        logs = input_list[2:]

        parsed = {
            'logs': logs,
            'count_warn': _safe_parse_int(count_warn_str, 1),
            'count_crit': _safe_parse_int(count_crit_str, 1),
            'error': None,
        }

        if debug.enabled():
            pprint(string_table)
            pprint(parsed)
    except Exception as e:
        parsed = {
            'logs': [f'parsing failed: {e}'],
            'count_warn': 0,
            'count_crit': 0,
            'error': traceback.format_exc(),
        }

    return parsed


def discover_azuremonitor(section):
    yield Service()


def check_azuremonitor(section):
    try:
        logs = section['logs']
        count_warn = section['count_warn']
        count_crit = section['count_crit']

        numlogs = len(logs)
        logs_summary = f"Query retrieved {numlogs} logs"

        if section['error']:
            yield Result(
                state=State.UNKNOWN,
                summary=logs,
                details=section['error'],
            )
            return

        log_str = '\n'.join(logs) if logs else None

        if numlogs >= count_crit:
            state = State.CRIT
        elif numlogs >= count_warn:
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


agent_section_azuremonitor = AgentSection(
    name="azuremonitor",
    parse_function=parse_azuremonitor,
)

check_plugin_myhostgroups = CheckPlugin(
    name="azuremonitor",
    service_name="Azure Monitor logs and metrics",
    discovery_function=discover_azuremonitor,
    check_function=check_azuremonitor,
)
