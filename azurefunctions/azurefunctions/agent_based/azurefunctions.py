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
from datetime import datetime, timezone

from croniter import croniter


def parse_azurefunctions(string_table):
    # string_table is a list of lists, each inner list is one line of
    # the stdout in ../libexec/agent_azurefunctions

    try:
        # flatten the list because it has every element wrapped in another list
        input_list = list(chain.from_iterable(string_table))

        apps = input_list[0]
        logs = input_list[1:]
        dictlogs = [json.loads(log) for log in logs]

        parsed = {
            'apps': json.loads(apps),
            'logs': dictlogs,
            'error': None,
        }

        if debug.enabled():
            pprint(string_table)
            pprint(parsed)
    except Exception as e:
        parsed = {
            'apps': {},
            'logs': [f'parsing failed: {e}'],
            'error': traceback.format_exc(),
        }

    return parsed


def discover_azurefunctions(section):
    # yeld one service per function in each function app
    for appname, funcs in section.get('apps').items():
        for func in funcs:
            yield Service(item=f"{appname} - {func['name']}")


def _check_failures_and_duration(funcspec, funclogs):
    ninvocs = len(funclogs)

    failures = 0
    duration_accu = 0
    for log in funclogs:
        if log.get('success') != 'True' \
           or log.get('resultCode') not in ['0', '200']:
            failures += 1
        duration_accu += float(log.get('duration', 0))

    duration_avg = duration_accu / ninvocs if ninvocs > 0 else 0

    def _fmt_duration(millis):
        if millis > 2000:
            secs = millis / 1000
            return "%.3f s" % secs
        return "%d ms" % int(millis)

    yield from check_levels(
        failures,
        label="Failures",
        metric_name="failures",
        levels_upper=("fixed", (1, 2)),
        render_func=lambda v: "%d" % int(v),
    )

    yield from check_levels(
        duration_avg,
        label="Duration",
        metric_name="duration",
        render_func=_fmt_duration,
    )


def _check_scheduled_invocations(funcspec, funclogs):
    if funcspec['type'] != "timerTrigger":
        # this check applies only to timer trigger funcs
        return

    clock_skew_crit_secs = 120  # TODO config
    clock_skew_warn_secs = 60  # TODO config

    def _match_timestamp(log, expected_timestamp, skew_secs):
        timestamp = datetime.fromisoformat(log['timestamp'])
        diff = expected_timestamp - timestamp
        return abs(diff.total_seconds()) < skew_secs

    funccron = funcspec['schedule']
    base = datetime.now(timezone.utc)
    itr = croniter(funccron, base, second_at_beginning=True)
    expected = itr.get_prev(datetime)

    matching_log = None
    for log in funclogs:
        if _match_timestamp(log, expected, clock_skew_crit_secs):
            matching_log = log
            break

    if not matching_log:
        # outside crit level skew tolerance
        yield Result(
            state=State.CRIT,
            summary="Missed scheduled invocation",
            details="Invocation expected at %s (CRON: %s)" %
            (expected, funccron),
        )
    elif _match_timestamp(matching_log, expected, clock_skew_warn_secs):
        # within tolerance
        yield Result(
            state=State.OK,
            summary="Scheduled invocation fired",
            details="Invoked at %s, expected at %s (CRON: %s)" %
            (matching_log['timestamp'], expected, funccron),
        )
    else:
        # outside warn level skew tolerance
        yield Result(
            state=State.WARN,
            summary="Skew in scheduled invocation",
            details="Invoked at %s, expected at %s (CRON: %s)" %
            (matching_log['timestamp'], expected, funccron),
        )


def check_azurefunctions(item, section):
    try:
        logs = section.get('logs')
        if section['error']:
            # these are errors in parsing phase
            yield Result(
                state=State.UNKNOWN,
                summary=logs,
                details=section['error'],
            )
            return

        [appname, funcname] = item.split(" - ")

        funcs = section.get('apps', {}).get(appname)
        func = [func for func in funcs if func['name'] == funcname][0]

        funclogs = [
            log for log in logs
            if log['cloud_RoleName'] == appname
            and log['operation_Name'] == funcname
        ]

        yield from _check_failures_and_duration(func, funclogs)
        yield from _check_scheduled_invocations(func, funclogs)
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
