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


def _check_duration(duration_avg):

    def _fmt_duration(millis):
        if millis > 2000:
            secs = millis / 1000
            return "%.3f s" % secs
        return "%d ms" % int(millis)

    yield from check_levels(
        duration_avg,
        label="Duration",
        metric_name="duration",
        render_func=_fmt_duration,
    )


def _check_http_invocations(funcspec, funclogs):
    failures = 0
    duration_accu = 0
    for log in funclogs:
        if log.get('success') != 'True' \
           or int(log.get('resultCode')) > 399:
            failures += 1
        duration_accu += float(log.get('duration', 0))

    yield from check_levels(
        failures,
        label="Failures",
        metric_name="failures",
        levels_upper=("fixed", (1, 2)),
        render_func=lambda v: "%d" % int(v),
    )

    ninvocs = len(funclogs)
    duration_avg = duration_accu / ninvocs if ninvocs > 0 else 0
    yield from _check_duration(duration_avg)


def _check_scheduled_invocations(funcspec, funclogs):
    clock_skew_secs = 60
    delay_warn_secs = 120  # TODO config
    delay_crit_secs = 240  # TODO config

    funccron = funcspec['schedule']
    now = datetime.now(timezone.utc)
    itr = croniter(funccron, now, second_at_beginning=True)
    schedule = itr.get_prev(datetime)

    duration_accu = 0
    nfailures = 0
    matching_log = None
    success_log = None
    for log in funclogs:
        success = log.get('success') == 'True' and log.get('resultCode') == '0'
        if not success:
            nfailures += 1
        duration_accu += float(log.get('duration', 0))
        timestamp = datetime.fromisoformat(log['timestamp'])
        diff_secs = (timestamp - schedule).total_seconds()

        if diff_secs + clock_skew_secs > 0:
            # execution log is after expected schedule (considering clock skew)
            if diff_secs < delay_crit_secs:
                # execution log is considered matching the expected schedule
                matching_log = log
            if success:
                # there is a successful invocation after schedule: we
                # consider schedule in sync.  this can be different
                # from the log that matched the schedule, e.g. if
                # schedule execution failed and then the function was
                # ran manually
                success_log = log

    if matching_log:
        yield Result(
            state=State.OK,
            summary="Scheduled invocation fired",
            details="Invoked at %s, expected at %s (CRON: %s)" %
            (matching_log['timestamp'], schedule, funccron),
        )
    else:
        warn = (now - schedule).total_seconds() < delay_warn_secs
        yield Result(
            state=State.WARN if warn else State.CRIT,
            summary="Missed scheduled invocation",
            details="Invocation expected at %s (CRON: %s)" %
            (schedule, funccron),
        )

    if success_log:
        yield Result(
            state=State.OK,
            summary="Schedule in sync",
            details=f"Schedule is in sync with {nfailures} previous failures",
        )
    else:
        yield Result(
            state=State.CRIT,
            summary="Schedule out of sync",
            details=f"Schedule out of sync with {nfailures} current failures",
        )

    ninvocs = len(funclogs)
    duration_avg = duration_accu / ninvocs if ninvocs > 0 else 0
    yield from _check_duration(duration_avg)


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
            log for log in logs if log['cloud_RoleName'] == appname
            and log['operation_Name'] == funcname
        ]

        if func['type'] == "timerTrigger":
            yield from _check_scheduled_invocations(func, funclogs)
        elif func['type'] == "httpTrigger":
            yield from _check_http_invocations(func, funclogs)
        else:
            yield Result(
                state=State.UNKNOWN,
                summary=f"Unsupported function trigger: {func['type']}",
                details=traceback.format_exc(),
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
