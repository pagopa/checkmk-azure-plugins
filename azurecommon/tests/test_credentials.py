import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from azurecommon.azurecommon.lib import credentials as module
from azurecommon.azurecommon.lib.client import AzureClient, AzureError
from azurecommon.azurecommon.lib.credentials import (
    AccessToken, AutoProvider, AzureCliProvider, ServicePrincipalProvider,
)


class CredentialTests(unittest.TestCase):
    def test_service_principal_uses_client_transport(self):
        request = Mock(return_value={"access_token": "token", "expires_in": "3600"})
        provider = ServicePrincipalProvider("tenant", "client", "secret")
        self.assertEqual(provider.get_token("scope", request), AccessToken("token", 3600))
        request.assert_called_once_with(
            "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            {"grant_type": "client_credentials", "client_id": "client",
             "client_secret": "secret", "scope": "scope"},
        )

    def test_explicit_cli_requires_executable(self):
        with patch.object(module.shutil, "which", return_value=None):
            with self.assertRaisesRegex(AzureError, "not found"):
                AzureCliProvider().get_token("scope", Mock())

    def test_cli_token_scope_lifetime_and_proxy(self):
        result = Mock(stdout=json.dumps({
            "accessToken": "cli-token", "expires_on": 4600,
        }))
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.subprocess, "run", return_value=result) as run, \
                patch.object(module.time, "time", return_value=1000):
            token = AzureCliProvider(proxy="http://proxy:8080").get_token("scope", Mock())
        self.assertEqual(token, AccessToken("cli-token", 3600))
        self.assertEqual(run.call_args.args[0], [
            "/bin/az", "account", "get-access-token", "--scope", "scope",
            "--output", "json",
        ])
        self.assertEqual(run.call_args.kwargs["env"]["HTTPS_PROXY"], "http://proxy:8080")
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_cli_supports_legacy_expiration(self):
        result = Mock(stdout=json.dumps({
            "accessToken": "cli-token", "expiresOn": "1970-01-01 01:00:00+00:00",
        }))
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.subprocess, "run", return_value=result), \
                patch.object(module.time, "time", return_value=0):
            self.assertEqual(
                AzureCliProvider().get_token("scope", Mock()),
                AccessToken("cli-token", 3600),
            )

    def test_cli_failures_are_explicit(self):
        for error in (
            subprocess.CalledProcessError(1, ["az"], stderr="run az login"),
            subprocess.TimeoutExpired(["az"], 60),
            FileNotFoundError("az disappeared"),
        ):
            with self.subTest(error=error):
                with patch.object(module.shutil, "which", return_value="/bin/az"), \
                        patch.object(module.subprocess, "run", side_effect=error):
                    with self.assertRaises(AzureError):
                        AzureCliProvider().get_token("scope", Mock())

    def test_invalid_cli_responses_are_rejected(self):
        for stdout in (
            "invalid", "[]", "{}",
            json.dumps({"accessToken": "token", "expires_on": "bad"}),
            json.dumps({"accessToken": "token", "expires_on": 0}),
        ):
            with self.subTest(stdout=stdout):
                with patch.object(module.shutil, "which", return_value="/bin/az"), \
                        patch.object(module.subprocess, "run", return_value=Mock(stdout=stdout)):
                    with self.assertRaises(AzureError):
                        AzureCliProvider().get_token("scope", Mock())

    def test_auto_selects_cli_without_service_principal_credentials(self):
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.AzureCliProvider, "get_token",
                             return_value=AccessToken("cli", 3600)) as cli:
            provider = AutoProvider()
            self.assertEqual(provider.get_token("scope", Mock()).token, "cli")
            cli.assert_called_once()

    def test_auto_selects_service_principal_when_cli_is_absent(self):
        request = Mock(return_value={"access_token": "sp", "expires_in": 3600})
        with patch.object(module.shutil, "which", return_value=None):
            provider = AutoProvider("tenant", "client", "secret")
            self.assertEqual(provider.get_token("scope", request).token, "sp")
            with self.assertRaises(ValueError):
                AutoProvider()

    def test_auto_does_not_fall_back_after_cli_authentication_error(self):
        request = Mock()
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.AzureCliProvider, "get_token",
                             side_effect=AzureError("not logged in")):
            provider = AutoProvider("tenant", "client", "secret")
            with self.assertRaisesRegex(AzureError, "not logged in"):
                provider.get_token("scope", request)
        request.assert_not_called()

    def test_auto_does_not_switch_if_cli_disappears(self):
        request = Mock()
        with patch.object(module.shutil, "which", side_effect=["/bin/az", None]):
            provider = AutoProvider("tenant", "client", "secret")
            with self.assertRaises(AzureError):
                provider.get_token("scope", request)
        request.assert_not_called()

    def test_explicit_provider_uses_shared_client_cache(self):
        provider = Mock()
        provider.get_token.return_value = AccessToken("token", 3600)
        azure = AzureClient(credential=provider)
        self.assertEqual(azure._token("scope"), "token")
        self.assertEqual(azure._token("scope"), "token")
        provider.get_token.assert_called_once()
        with self.assertRaises(ValueError):
            AzureClient("tenant", "client", "secret", credential=provider)

    def test_cli_process_uses_remaining_budget(self):
        result = Mock(stdout=json.dumps({"accessToken": "token", "expires_on": 4600}))
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.subprocess, "run", return_value=result) as run, \
                patch.object(module.time, "time", return_value=1000), \
                patch.object(module.time, "monotonic", return_value=90):
            AzureCliProvider().get_token("scope", Mock(), deadline=100)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_expired_deadline_prevents_cli_execution(self):
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.subprocess, "run") as run, \
                patch.object(module.time, "monotonic", return_value=100):
            with self.assertRaisesRegex(AzureError, "deadline"):
                AzureCliProvider().get_token("scope", Mock(), deadline=100)
        run.assert_not_called()

    def test_auto_forwards_deadline(self):
        with patch.object(module.shutil, "which", return_value="/bin/az"), \
                patch.object(module.AzureCliProvider, "get_token",
                             return_value=AccessToken("token", 3600)) as get_token:
            request = Mock()
            AutoProvider().get_token("scope", request, deadline=100)
        get_token.assert_called_once_with("scope", request, deadline=100)


if __name__ == "__main__":
    unittest.main()
