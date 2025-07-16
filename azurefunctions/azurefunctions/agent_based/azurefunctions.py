#!/usr/bin/env python3

from cmk.agent_based.v2 import AgentSection
from cmk.agent_based.v2 import CheckPlugin
from cmk.agent_based.v2 import Service
from cmk.agent_based.v2 import Result
from cmk.agent_based.v2 import State
from cmk.agent_based.v2 import check_levels
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

        name = input_list[0]
        count_thresholds_dict = input_list[1]
        failure_thresholds_dict = input_list[2]
        logs = input_list[3:]

        parsed = {
            'name': name,
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
            'name': 'UNKNOWN',
            'logs': [f'parsing failed: {e}'],
            'count_thresholds': {},
            'failure_thresholds': {},
            'error': traceback.format_exc(),
        }

    return parsed


def discover_azurefunctions(section):
    yield Service(item=section.get('name'))


def check_azurefunctions(item, section):
    try:
        logs = section['logs']
        if section['error']:
            yield Result(
                state=State.UNKNOWN,
                summary=logs,
                details=section['error'],
            )
            return

        invocs = len(logs)

        failures = 0
        duration_accu = 0
        for log in logs:
            dictlog = json.loads(log)
            if dictlog.get('success') != 'True' \
               or dictlog.get('resultCode') not in ['0', '200']:
                failures += 1
            duration_accu += float(dictlog.get('duration', 0))

        duration_avg = duration_accu / invocs if invocs > 0 else 0

        ct = section.get('count_thresholds', {})
        ft = section.get('failure_thresholds', {})

        def _level(warn, crit):
            if not crit:
                return None
            return ("fixed", (warn or crit, crit))

        def _fmt_duration(millis):
            if millis > 2000:
                secs = millis / 1000
                return "%.3f s" % secs
            return "%d ms" % int(millis)

        yield from check_levels(
            invocs,
            label="Invocations",
            metric_name="invocations",
            levels_lower=(_level(ct.get('warn_lower', None),
                                 ct.get('crit_lower', None))),
            levels_upper=(_level(ct.get('warn_upper', None),
                                 ct.get('crit_upper', None))),
            render_func=lambda v: "%d" % int(v),
        )

        yield from check_levels(
            failures,
            label="Failures",
            metric_name="failures",
            levels_upper=(_level(ft.get('warn_upper', None),
                                 ft.get('crit_upper', None))),
            render_func=lambda v: "%d" % int(v),
        )

        yield from check_levels(
            duration_avg,
            label="Duration",
            metric_name="duration",
            render_func=_fmt_duration,
        )


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
    service_name="Azure Function %s",
    discovery_function=discover_azurefunctions,
    check_function=check_azurefunctions,
)
