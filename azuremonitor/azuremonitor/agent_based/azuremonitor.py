#!/usr/bin/env python3

from cmk.agent_based.v2 import AgentSection
from cmk.agent_based.v2 import CheckPlugin
from cmk.agent_based.v2 import Service
from cmk.agent_based.v2 import Result
from cmk.agent_based.v2 import State
import json
import traceback


def parse_azuremonitor(string_table):
    # string_table with sep(0) contains only 1 json row
    # [['{"count_warn": 1, "count_crit": 2, ...}']]
    try:
        if not string_table or not string_table[0]:
            raise ValueError("No data from agent")

        raw_json = string_table[0][0]
        data = json.loads(raw_json)

        parsed = {
            'logs': data.get('logs', []),
            'count_warn': int(data.get('count_warn', 1)),
            'count_crit': int(data.get('count_crit', 1)),
            'custom_summary': data.get('custom_summary', ''),
            'error': None,
        }

    except Exception as e:
        parsed = {
            'logs': [f'parsing failed: {e}'],
            'count_warn': 0,
            'count_crit': 0,
            'custom_summary': 'Internal parsing error',
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
        custom_summary = section['custom_summary']

        numlogs = len(logs)
        logs_summary = custom_summary.replace('{numlogs}', str(numlogs))

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

check_plugin_azuremonitor = CheckPlugin(
    name="azuremonitor",
    service_name="Azure Monitor logs and metrics",
    discovery_function=discover_azuremonitor,
    check_function=check_azuremonitor,
)
