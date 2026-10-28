import contextlib
import builtins
from concurrent.futures import Future, ThreadPoolExecutor
import io
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from azurecommon.azurecommon.lib import client as client_module
from azurecommon.azurecommon.lib import credentials
from azurecommon.azurecommon.lib.client import AzureError

ROOT = Path(__file__).resolve().parents[1]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.logs.post.return_value = {"tables": []}
        self.client.appinsights.get.return_value = {"tables": []}
        self.client.web.get_paged.side_effect = lambda path: iter([])
        self.modules = {}
        for name in (
            "cmk_addons", "cmk_addons.plugins", "cmk_addons.plugins.azurecommon",
            "cmk_addons.plugins.azurecommon.lib",
        ):
            package = ModuleType(name)
            package.__dict__["__path__"] = []
            self.modules[name] = package
        self.modules["cmk_addons.plugins.azurecommon.lib.client"] = client_module
        self.modules["cmk_addons.plugins.azurecommon.lib.credentials"] = credentials

    def arguments(self, plugin):
        args = ["--tenant-id", "tenant", "--client-id", "client", "--client-secret", "secret"]
        if plugin == "azuremonitor":
            return args + [
                "--resource-id", "/subscriptions/sub/providers/Test/resource",
                "--query", "first___cmk_azuremonitor_newline___second",
                "--timedelta-seconds", "3600",
            ]
        return args + [
            "--subscription-id", "sub", "--resource-group", "group",
            "--appinsights-app-id", "insights", "--timedelta-kql", "1d",
        ]

    def run_agent(self, plugin, stdout, extra=()):
        path = ROOT / plugin / plugin / "libexec" / f"agent_{plugin}"
        with patch.dict(sys.modules, self.modules), \
                patch.object(sys, "argv", [str(path)] + self.arguments(plugin) + list(extra)), \
                patch.object(client_module, "AzureClient", return_value=self.client) as factory, \
                contextlib.redirect_stdout(stdout):
            runpy.run_path(str(path), run_name="__main__")
        return factory

    def test_monitor_output_query_and_proxy(self):
        self.client.logs.post.return_value = {"tables": [{
            "columns": [{"name": "message"}, {"name": "count"}],
            "rows": [["example", 2], [None, 0]],
        }]}
        stdout = io.StringIO()
        factory = self.run_agent("azuremonitor", stdout, (
            "--proxy", "http://proxy:8080", "--count-warn", "3", "--count-crit", "5",
        ))
        lines = stdout.getvalue().splitlines()
        self.assertEqual(lines[:5], [
            "<<<azuremonitor:sep(0)>>>", "3", "<<<azuremonitor:sep(1)>>>", "5",
            "<<<azuremonitor:sep(2)>>>",
        ])
        self.assertEqual([json.loads(line) for line in lines[5:]], [
            {"message": "example", "count": 2}, {"message": None, "count": 0},
        ])
        self.client.logs.post.assert_called_once_with(
            "/v1/subscriptions/sub/providers/Test/resource/query",
            payload={"query": "first\nsecond", "timespan": "PT3600S"},
        )
        self.assertEqual(factory.call_args.kwargs["proxy"], "http://proxy:8080")
        self.assertIsInstance(
            factory.call_args.kwargs["credential"], credentials.ServicePrincipalProvider,
        )

    def test_monitor_empty_results_keep_section_shape(self):
        stdout = io.StringIO()
        self.run_agent("azuremonitor", stdout)
        self.assertEqual(stdout.getvalue().splitlines(), [
            "<<<azuremonitor:sep(0)>>>", "0", "<<<azuremonitor:sep(1)>>>", "1",
            "<<<azuremonitor:sep(2)>>>",
        ])

    def test_functions_discovery_and_invocations(self):
        sites = "/subscriptions/sub/resourceGroups/group/providers/Microsoft.Web/sites"

        def pages(path):
            if path == sites:
                return iter([
                    {"name": "app", "kind": "functionapp,linux"},
                    {"name": "empty", "kind": "functionapp"},
                    {"name": "website", "kind": "app"},
                ])
            if path == f"{sites}/app/functions":
                return iter([{
                    "name": "app/timer",
                    "properties": {"config": {"bindings": [{
                        "type": "timerTrigger", "schedule": "0 */5 * * * *",
                    }]}},
                }])
            if path == f"{sites}/empty/functions":
                return iter([])
            self.fail(f"Unexpected ARM path: {path}")

        self.client.web.get_paged.side_effect = pages
        self.client.appinsights.get.return_value = {"tables": [{
            "columns": [{"name": "operation_Name"}, {"name": "success"}],
            "rows": [["timer", "True"]],
        }]}
        stdout = io.StringIO()
        self.run_agent("azurefunctions", stdout)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(lines[0], "<<<azurefunctions:sep(0)>>>")
        self.assertEqual(json.loads(lines[1]), {
            "app": [{"name": "timer", "type": "timerTrigger", "schedule": "0 */5 * * * *"}],
            "empty": [],
        })
        self.assertEqual(json.loads(lines[2]), {"operation_Name": "timer", "success": "True"})
        args, kwargs = self.client.appinsights.get.call_args
        self.assertEqual(args, ("/v1/apps/insights/query",))
        self.assertIn("ago(1d)", kwargs["params"]["query"])
        self.assertIn('customDimensions["faas.invocation_id"]', kwargs["params"]["query"])

    def test_query_partial_errors_never_print_success_sections(self):
        for plugin, operation in (
            ("azuremonitor", self.client.logs.post),
            ("azurefunctions", self.client.appinsights.get),
        ):
            operation.return_value = {"tables": [], "error": {"code": "PartialError"}}
            stdout = io.StringIO()
            with self.subTest(plugin=plugin), self.assertRaises(AzureError):
                self.run_agent(plugin, stdout)
            self.assertEqual(stdout.getvalue(), "")

    def test_discovery_errors_never_print_partial_results(self):
        self.client.web.get_paged.side_effect = AzureError("ARM failed")
        stdout = io.StringIO()
        with self.assertRaises(AzureError):
            self.run_agent("azurefunctions", stdout)
        self.assertEqual(stdout.getvalue(), "")

    def test_functions_discovery_worker_count(self):
        for workers, extra in (
            (8, ()), (1, ("--max-workers", "1")), (3, ("--max-workers", "3")),
        ):
            with self.subTest(workers=workers):
                with patch(
                    "concurrent.futures.ThreadPoolExecutor", wraps=ThreadPoolExecutor,
                ) as executor:
                    self.run_agent("azurefunctions", io.StringIO(), extra)
                self.assertEqual(executor.call_args_list, [
                    call(max_workers=2), call(max_workers=workers),
                ])

    def test_functions_rejects_invalid_worker_count(self):
        for value in ("0", "-1", "1.5", "invalid"):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with self.subTest(value=value):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        self.run_agent("azurefunctions", stdout, ("--max-workers", value))
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("--max-workers", stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")

    def test_functions_timeout_cancels_pending_work_without_joining(self):
        pending = Future()
        pool = Mock()
        pool.submit.return_value = pending
        stdout = io.StringIO()
        with patch("concurrent.futures.ThreadPoolExecutor", return_value=pool), \
                patch("concurrent.futures.wait", return_value=(set(), {pending})) as wait:
            with self.assertRaisesRegex(AzureError, "deadline"):
                self.run_agent("azurefunctions", stdout)
        self.assertLessEqual(wait.call_args.kwargs["timeout"], 300)
        pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        self.client.cancel.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")

    def test_functions_observes_failure_without_waiting_for_other_task(self):
        pending = Future()
        failed = Future()
        failed.set_exception(AzureError("query failed"))
        pool = Mock()
        pool.submit.side_effect = [pending, failed]
        stdout = io.StringIO()
        with patch("concurrent.futures.ThreadPoolExecutor", return_value=pool):
            with self.assertRaisesRegex(AzureError, "query failed"):
                self.run_agent("azurefunctions", stdout)
        pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        self.client.cancel.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")

    def test_agents_forward_overall_deadline(self):
        for plugin in ("azuremonitor", "azurefunctions"):
            with self.subTest(plugin=plugin):
                with patch("time.monotonic", return_value=100):
                    factory = self.run_agent(
                        plugin, io.StringIO(), ("--total-timeout", "12"),
                    )
                self.assertEqual(factory.call_args.kwargs["deadline"], 112)

    def test_agents_reject_invalid_total_timeout(self):
        for plugin in ("azuremonitor", "azurefunctions"):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(plugin=plugin, value=value):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            self.run_agent(
                                plugin, io.StringIO(), ("--total-timeout", value),
                            )
                    self.assertEqual(raised.exception.code, 2)

    def test_functions_rule_forwards_workers_and_defaults_for_existing_rules(self):
        api = ModuleType("cmk.server_side_calls.v1")
        api.__dict__.update(
            noop_parser=Mock(),
            SpecialAgentConfig=Mock(),
            SpecialAgentCommand=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        modules = {"cmk.server_side_calls.v1": api}
        for name in ("cmk", "cmk.server_side_calls"):
            package = ModuleType(name)
            package.__dict__["__path__"] = []
            modules[name] = package
        path = (
            ROOT / "azurefunctions" / "azurefunctions"
            / "server_side_calls" / "special_agent.py"
        )
        with patch.dict(sys.modules, modules):
            namespace = runpy.run_path(str(path))
        secret = Mock()
        secret.unsafe.return_value = "secret"
        params = {
            "tenant_id": "tenant", "subscription_id": "sub", "resource_group": "group",
            "client_id": "client", "client_secret": secret, "appinsights_app_id": "insights",
            "timedelta_kql": "1d",
        }
        for configured, expected in (({}, "8"), ({"max_workers": 1}, "1"),
                                     ({"max_workers": 3}, "3")):
            with self.subTest(configured=configured):
                commands = list(namespace["_agent_arguments"](params | configured, None))
                args = commands[0].command_arguments
                self.assertEqual(args[args.index("--max-workers") + 1], expected)
                self.assertNotIn("--credential-provider", args)

    def test_legacy_cli_flag_and_explicit_provider(self):
        factory = self.run_agent(
            "azurefunctions", io.StringIO(), ("--use-cli-credentials",),
        )
        self.assertIsInstance(factory.call_args.kwargs["credential"], credentials.AzureCliProvider)
        for plugin in ("azuremonitor", "azurefunctions"):
            with self.subTest(plugin=plugin):
                with patch.object(credentials.shutil, "which", return_value=None):
                    factory = self.run_agent(
                        plugin, io.StringIO(), ("--credential-provider", "auto"),
                    )
                self.assertIsInstance(
                    factory.call_args.kwargs["credential"], credentials.AutoProvider,
                )

    def test_cli_modes_do_not_require_service_principal_secrets(self):
        for plugin in ("azuremonitor", "azurefunctions"):
            args = self.arguments(plugin)[6:] + ["--credential-provider", "auto"]
            with self.subTest(plugin=plugin):
                with patch.object(self, "arguments", return_value=args), \
                        patch.object(credentials.shutil, "which", return_value="/bin/az"):
                    self.run_agent(plugin, io.StringIO())

    def test_missing_dependency_has_actionable_error(self):
        original_import = builtins.__import__

        def import_without_common(name, *args, **kwargs):
            if name.startswith("cmk_addons"):
                raise ModuleNotFoundError("missing common", name="cmk_addons")
            return original_import(name, *args, **kwargs)

        for plugin in ("azuremonitor", "azurefunctions"):
            with self.subTest(plugin=plugin):
                with patch.object(builtins, "__import__", side_effect=import_without_common):
                    with self.assertRaisesRegex(SystemExit, "install or upgrade.*azurecommon"):
                        self.run_agent(plugin, io.StringIO())


if __name__ == "__main__":
    unittest.main()
