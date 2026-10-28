"""Azure credential providers using only the Python standard library."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote

from .errors import AzureError

TokenRequest = Callable[[str, Mapping[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class AccessToken:
    """Access token and remaining lifetime in seconds."""

    token: str
    expires_in: float

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not self.token:
            raise AzureError("Invalid authentication response: missing access token")
        if not math.isfinite(self.expires_in) or self.expires_in <= 0:
            raise AzureError("Invalid authentication response: token lifetime must be positive")


class TokenProvider(Protocol):
    def get_token(
        self, scope: str, request: TokenRequest, *, deadline: float | None = None,
    ) -> AccessToken:
        """Acquire a token; request performs a form POST using the client transport."""
        ...


class ServicePrincipalProvider:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        if not tenant_id or not client_id or not client_secret:
            raise ValueError("tenant_id, client_id and client_secret are required")
        self._url = (
            f"https://login.microsoftonline.com/{quote(tenant_id, safe='')}"
            "/oauth2/v2.0/token"
        )
        self._client_id = client_id
        self._client_secret = client_secret

    def get_token(
        self, scope: str, request: TokenRequest, *, deadline: float | None = None,
    ) -> AccessToken:
        payload = request(self._url, {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": scope,
        })
        try:
            lifetime = float(payload["expires_in"])
        except (KeyError, ValueError, TypeError) as exc:
            raise AzureError("Invalid OAuth response: invalid expires_in") from exc
        token = payload.get("access_token")
        if not isinstance(token, str):
            raise AzureError("Invalid OAuth response: missing access_token")
        return AccessToken(token, lifetime)


class AzureCliProvider:
    def __init__(
        self, *, proxy: str | None = None, timeout: float = 60,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Azure CLI timeout must be finite and positive")
        self._proxy = proxy
        self._timeout = timeout

    def get_token(
        self, scope: str, request: TokenRequest, *, deadline: float | None = None,
    ) -> AccessToken:
        executable = shutil.which("az")
        if executable is None:
            raise AzureError("Azure CLI executable 'az' was not found in PATH")
        env = os.environ.copy()
        if self._proxy:
            env["HTTP_PROXY"] = self._proxy
            env["HTTPS_PROXY"] = self._proxy
        timeout = self._timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AzureError("Azure operation deadline exceeded before CLI authentication")
            timeout = min(timeout, remaining)
        try:
            result = subprocess.run(
                [executable, "account", "get-access-token", "--scope", scope,
                 "--output", "json"],
                capture_output=True, text=True, check=True,
                timeout=timeout, env=env,
            )
        except subprocess.CalledProcessError as exc:
            raise AzureError(
                f"Azure CLI authentication failed: {exc.stderr.strip()}",
            ) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AzureError(f"Cannot acquire an Azure CLI token: {exc}") from exc
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise AzureError("Azure CLI returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AzureError("Azure CLI returned an invalid token response")
        try:
            expires_at = (
                float(payload["expires_on"]) if "expires_on" in payload
                else datetime.fromisoformat(payload["expiresOn"]).timestamp()
            )
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise AzureError("Azure CLI returned an invalid token expiration") from exc
        token = payload.get("accessToken")
        if not isinstance(token, str):
            raise AzureError("Azure CLI returned no access token")
        return AccessToken(token, expires_at - time.time())


class AutoProvider:
    """Select CLI if installed, otherwise service principal, once at construction.

    Authentication failures never trigger a fallback to a different identity.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        proxy: str | None = None,
        timeout: float = 60,
    ) -> None:
        self._provider: TokenProvider
        if shutil.which("az") is not None:
            self._provider = AzureCliProvider(proxy=proxy, timeout=timeout)
        else:
            if not tenant_id or not client_id or not client_secret:
                raise ValueError(
                    "Azure CLI is not installed: service-principal credentials are required",
                )
            self._provider = ServicePrincipalProvider(tenant_id, client_id, client_secret)

    def get_token(
        self, scope: str, request: TokenRequest, *, deadline: float | None = None,
    ) -> AccessToken:
        return self._provider.get_token(scope, request, deadline=deadline)
