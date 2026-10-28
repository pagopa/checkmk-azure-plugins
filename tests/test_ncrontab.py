from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from azurefunctions.azurefunctions.lib import ncrontab


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class NcrontabTests(unittest.TestCase):
    def test_previous_occurrences(self):
        cases = (
            ("0 */5 * * * *", "2026-10-28T10:35:27", "2026-10-28T10:35:00"),
            ("*/5 * * * *", "2026-10-28T10:35:27", "2026-10-28T10:35:00"),
            ("*/10 * * * * *", "2026-10-28T10:35:27", "2026-10-28T10:35:20"),
            ("0 */5 * * * *", "2026-10-28T10:35:00", "2026-10-28T10:30:00"),
            ("0 */5 * * * *", "2026-10-28T10:35:00.000001", "2026-10-28T10:35:00"),
            ("* * * * * *", "2026-01-01T00:00:00", "2025-12-31T23:59:59"),
            ("0 0 0 * * *", "2026-03-01T00:00:00", "2026-02-28T00:00:00"),
            ("0 0 0 * * *", "2024-03-01T00:00:00", "2024-02-29T00:00:00"),
            ("0 0 0 31 * *", "2026-03-01T00:00:00", "2026-01-31T00:00:00"),
            ("0 0 0 29 2 *", "2026-10-28T10:35:27", "2024-02-29T00:00:00"),
            ("0 0 0 29 2 *", "2104-02-29T00:00:00", "2096-02-29T00:00:00"),
            ("0 0 0 29 2 *", "2000-03-01T00:00:00", "2000-02-29T00:00:00"),
            ("0 0 0 1 1 *", "2026-01-01T00:00:00", "2025-01-01T00:00:00"),
            ("0 30 9 * * 1-5", "2026-10-26T09:00:00", "2026-10-23T09:30:00"),
            ("0 0 0 * * 0", "2026-10-28T10:35:27", "2026-10-25T00:00:00"),
            ("0 0 0 * * SuNdAy", "2026-10-28T10:35:27", "2026-10-25T00:00:00"),
            ("0 30 9 * Jan Mon", "2026-02-01T00:00:00", "2026-01-26T09:30:00"),
            ("0 30 9 * JANUARY Monday", "2026-02-01T00:00:00", "2026-01-26T09:30:00"),
            ("0 0 0 1 * Mon", "2026-10-28T10:35:27", "2026-06-01T00:00:00"),
            ("5,20,45 0 12 * * *", "2026-10-28T12:00:40", "2026-10-28T12:00:20"),
            ("0 10-20/5 9-17/2 * * *", "2026-10-28T12:00:00", "2026-10-28T11:20:00"),
            ("0 5/15 * * * *", "2026-10-28T10:40:00", "2026-10-28T10:35:00"),
            ("0 0 9 * Jan,Mar-May/2 *", "2026-06-01T00:00:00", "2026-05-31T09:00:00"),
            ("  0  0  9 * * *  ", "2026-10-28T10:00:00", "2026-10-28T09:00:00"),
        )
        for expression, before, expected in cases:
            with self.subTest(expression=expression, before=before):
                result = ncrontab.previous_occurrence(expression, utc(before))
                self.assertEqual(result, utc(expected))
                self.assertIs(result.tzinfo, timezone.utc)
                self.assertLess(result, utc(before))

    def test_input_is_converted_to_utc(self):
        before = datetime(2026, 10, 28, 12, 35, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(
            ncrontab.previous_occurrence("0 */5 * * * *", before),
            utc("2026-10-28T10:30:00"),
        )

    def test_invalid_or_unsupported_expressions(self):
        expressions = (
            None, 123, "", "* * * *", "* * * * * * *",
            "%MyTimerSchedule%", "00:05:00",
            "60 * * * * *", "0 60 * * * *", "0 0 24 * * *",
            "0 0 0 0 * *", "0 0 0 32 * *", "0 0 0 * 0 *",
            "0 0 0 * 13 *", "0 0 0 * * 7", "-1 * * * * *",
            "0 */0 * * * *", "0 */-1 * * * *", "0 */x * * * *",
            "0 */2/3 * * * *", "0 10-5 * * * *", "0 1-2-3 * * * *",
            "0 0, * * * *", "0 ,0 * * * *", "0 0,,5 * * * *",
            "0 0 0 L * *", "0 0 0 1W * *", "0 0 0 * * Mon#2",
            "0 0 0 * * ?", "@daily", "0 0 0 * Unknown Mon",
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    ncrontab.previous_occurrence(expression, utc("2026-10-28T10:35:27"))

    def test_impossible_dates_terminate_with_error(self):
        for expression in ("0 0 0 31 2 *", "0 0 0 31 Apr,Jun,Sep,Nov *"):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(ValueError, "400-year"):
                    ncrontab.previous_occurrence(expression, utc("2026-10-28T10:35:27"))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ncrontab.previous_occurrence("* * * * * *", datetime(2026, 10, 28))

    def test_datetime_lower_bound(self):
        with self.assertRaises(ValueError):
            ncrontab.previous_occurrence("* * * * * *", datetime.min.replace(tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            ncrontab.previous_occurrence("0 0 0 29 2 *", utc("0001-01-02T00:00:00"))


class TimerCheckTests(unittest.TestCase):
    def setUp(self):
        names = (
            "cmk", "cmk.agent_based", "cmk.agent_based.v2", "cmk.utils",
            "cmk_addons", "cmk_addons.plugins", "cmk_addons.plugins.azurefunctions",
            "cmk_addons.plugins.azurefunctions.lib",
        )
        modules = {name: ModuleType(name) for name in names}
        api = modules["cmk.agent_based.v2"]
        api.AgentSection = Mock()
        api.CheckPlugin = Mock()
        api.Service = Mock()
        api.Result = lambda **kwargs: SimpleNamespace(**kwargs)
        api.State = SimpleNamespace(OK=0, WARN=1, CRIT=2, UNKNOWN=3)
        api.check_levels = Mock(return_value=())
        modules["cmk.utils"].debug = SimpleNamespace(enabled=lambda: False)
        modules["cmk_addons.plugins.azurefunctions.lib.ncrontab"] = ncrontab
        path = (
            Path(__file__).resolve().parents[1]
            / "azurefunctions/azurefunctions/agent_based/azurefunctions.py"
        )
        with patch.dict(sys.modules, modules):
            self.check = runpy.run_path(str(path))["_check_scheduled_invocations"]
        self.clock = Mock(wraps=datetime)
        self.clock.now.return_value = utc("2026-10-28T10:35:27")

    def check_results(self, schedule, logs):
        with patch.dict(self.check.__globals__, {"datetime": self.clock}):
            return list(self.check({"schedule": schedule}, logs))

    def test_successful_scheduled_invocation(self):
        results = self.check_results("0 */5 * * * *", [{
            "timestamp": "2026-10-28T10:35:05+00:00",
            "success": "True", "resultCode": "0", "duration": "100",
        }])
        self.assertEqual([result.state for result in results], [0, 0])
        self.assertIn("2026-10-28 10:35:00+00:00", results[0].details)

    def test_missed_invocation_preserves_existing_states(self):
        results = self.check_results("0 */5 * * * *", [])
        self.assertEqual([result.state for result in results], [1, 2])
        self.clock.now.return_value = utc("2026-10-28T10:39:27")
        results = self.check_results("0 */5 * * * *", [])
        self.assertEqual([result.state for result in results], [2, 2])

    def test_bad_schedules_are_explicitly_unknown(self):
        for schedule in ("%setting%", "00:05:00", "0 0 0 31 2 *", None):
            with self.subTest(schedule=schedule):
                results = self.check_results(schedule, [])
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].state, 3)
                self.assertEqual(results[0].summary, "Invalid or unsupported timer schedule")
                self.assertIn(repr(schedule), results[0].details)


if __name__ == "__main__":
    unittest.main()
