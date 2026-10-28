"""Dependency-free, synchronous Azure REST clients, shareable between threads."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException, HTTPResponse, IncompleteRead
from threading import Event, Lock, local
from typing import Any, Iterator, Mapping

from .credentials import ServicePrincipalProvider, TokenProvider
from .errors import AzureError

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_WEB_API_VERSION = "2023-12-01"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to a redirected endpoint.
        return None


class AzureServiceClient:
    """Service-bound JSON operations. Constructed by AzureClient."""

    def __init__(
        self,
        client: AzureClient,
        base_url: str,
        scope: str,
        *,
        api_version: str | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._scope = scope
        self._api_version = api_version

    def _url(self, path: str) -> str:
        url = urllib.parse.urljoin(self._base_url + "/", path)
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self._base_url)
        if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            raise AzureError("Request URL must belong to the service origin")
        if parsed.fragment:
            raise AzureError("Request URL must not contain a fragment")
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(self._url(path))
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if params:
            query.extend(urllib.parse.parse_qsl(
                urllib.parse.urlencode(params, doseq=True),
                keep_blank_values=True,
            ))
        if self._api_version is not None:
            query = [(key, value) for key, value in query if key != "api-version"]
            query.append(("api-version", self._api_version))
        url = urllib.parse.urlunsplit(parsed._replace(
            query=urllib.parse.urlencode(query),
        ))
        return self._client._request(method, url, scope=self._scope, body=body)

    def get(
        self, path: str, *, params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET a JSON object. Paths are relative to the service origin."""
        return self._request("GET", path, params=params)

    def post(self, path: str, *, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST a JSON object and return the decoded response object."""
        return self._request("POST", path, body=json.dumps(payload).encode())

    def get_paged(
        self, path: str, *, params: Mapping[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield 'value' objects, following same-origin ARM/OData next links."""
        current_url = self._url(path)
        seen: set[str] = set()
        while True:
            if current_url in seen:
                raise AzureError("Invalid paginated response: repeated nextLink")
            seen.add(current_url)
            page = self.get(current_url, params=params)
            values = page.get("value")
            if not isinstance(values, list) or any(
                not isinstance(item, dict) for item in values
            ):
                raise AzureError(
                    "Invalid paginated response: expected objects in 'value'",
                    details=page,
                )
            yield from values
            next_link = page.get("nextLink")
            if next_link is None or next_link == "":
                next_link = page.get("@odata.nextLink")
            if next_link is None or next_link == "":
                return
            if not isinstance(next_link, str):
                raise AzureError("Invalid paginated response: nextLink must be a string")
            current_url = self._url(urllib.parse.urljoin(current_url, next_link))
            params = None


class AzureClient:
    """Azure client with shared token cache and per-thread HTTP state.

    Public operations are exposed through web, logs and appinsights.
    Parallel execution and interpretation of JSON belong to the caller.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        proxy: str | None = None,
        timeout: float = 60,
        max_retries: int = 4,
        credential: TokenProvider | None = None,
        deadline: float | None = None,
    ) -> None:
        if credential is not None and any((tenant_id, client_id, client_secret)):
            raise ValueError("Pass either a credential provider or service-principal credentials")
        if credential is None:
            if not tenant_id or not client_id or not client_secret:
                raise ValueError("tenant_id, client_id and client_secret are required")
            credential = ServicePrincipalProvider(tenant_id, client_id, client_secret)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if deadline is not None and not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        self._credential = credential
        self._proxy = proxy
        self._timeout = timeout
        self._max_retries = max_retries
        self._deadline = deadline
        self._cancelled = Event()
        self._tokens: dict[str, tuple[str, float]] = {}
        self._token_lock = Lock()
        self._http = local()
        self.web = AzureServiceClient(
            self, "https://management.azure.com",
            "https://management.azure.com/.default", api_version=_WEB_API_VERSION,
        )
        self.logs = AzureServiceClient(
            self, "https://api.loganalytics.io",
            "https://api.loganalytics.io/.default",
        )
        self.appinsights = AzureServiceClient(
            self, "https://api.applicationinsights.io",
            "https://api.applicationinsights.io/.default",
        )

    def _opener(self) -> urllib.request.OpenerDirector:
        if not hasattr(self._http, "opener"):
            handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
            if self._proxy:
                handlers.append(urllib.request.ProxyHandler({
                    "http": self._proxy, "https": self._proxy,
                }))
            self._http.opener = urllib.request.build_opener(*handlers)
        return self._http.opener

    def _token(self, scope: str) -> str:
        remaining = self._remaining()
        acquired = (
            self._token_lock.acquire() if remaining is None
            else self._token_lock.acquire(timeout=remaining)
        )
        if not acquired:
            raise AzureError("Azure operation deadline exceeded while waiting for a token")
        try:
            self._remaining()
            cached = self._tokens.get(scope)
            if cached and cached[1] - 60 > time.monotonic():
                return cached[0]
            acquired_at = time.monotonic()
            token = self._credential.get_token(
                scope, self._request_token, deadline=self._deadline,
            )
            self._remaining()
            self._tokens[scope] = (token.token, acquired_at + token.expires_in)
            return token.token
        finally:
            self._token_lock.release()

    def _remaining(self) -> float | None:
        if self._cancelled.is_set():
            raise AzureError("Azure operation cancelled")
        if self._deadline is None:
            return None
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise AzureError("Azure operation deadline exceeded")
        return remaining

    def cancel(self) -> None:
        """Stop retries and further calls; blocking I/O cannot be forcibly interrupted."""
        self._cancelled.set()

    def _read_response(self, response: HTTPResponse | urllib.error.HTTPError) -> bytes:
        if self._deadline is None:
            return response.read()
        length = response.getheader("Content-Length")
        expected = (
            int(length) if length is not None and length.isdigit()
            and response.getheader("Transfer-Encoding") != "chunked" else None
        )
        chunks = []
        size = 0
        while True:
            self._remaining()
            chunk = response.read1(65536)
            if not chunk:
                if expected is not None and size < expected:
                    raise IncompleteRead(b"".join(chunks), expected - size)
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)

    def _request_token(self, url: str, payload: Mapping[str, str]) -> dict[str, Any]:
        return self._request(
            "POST", url, body=urllib.parse.urlencode(payload).encode(),
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        scope: str | None = None,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        refreshed = False
        attempt = 0
        while True:
            self._remaining()
            headers = {"Accept": "application/json"}
            token = self._token(scope) if scope is not None else None
            if token is not None:
                headers["Authorization"] = "Bearer " + token
            if body is not None:
                headers["Content-Type"] = (
                    "application/json" if scope is not None
                    else "application/x-www-form-urlencoded"
                )
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            remaining = self._remaining()
            timeout = self._timeout if remaining is None else min(self._timeout, remaining)
            try:
                with self._opener().open(request, timeout=timeout) as response:
                    raw = self._read_response(response)
            except urllib.error.HTTPError as exc:
                try:
                    if exc.code == 401 and scope is not None and not refreshed:
                        remaining = self._remaining()
                        acquired = (
                            self._token_lock.acquire() if remaining is None
                            else self._token_lock.acquire(timeout=remaining)
                        )
                        if not acquired:
                            raise AzureError("Azure operation deadline exceeded during token refresh")
                        try:
                            cached = self._tokens.get(scope)
                            if cached and cached[0] == token:
                                del self._tokens[scope]
                        finally:
                            self._token_lock.release()
                        refreshed = True
                        continue
                    if exc.code in _RETRY_STATUS and attempt < self._max_retries:
                        delay = self._retry_delay(exc, attempt)
                    else:
                        raise self._http_error(exc) from exc
                finally:
                    exc.close()
            except (urllib.error.URLError, TimeoutError, ConnectionError, HTTPException) as exc:
                if attempt >= self._max_retries:
                    raise AzureError(
                        f"Connection error for {method} {url}: {exc}",
                    ) from exc
                delay = float(2 ** attempt)
            else:
                self._remaining()
                if not raw:
                    return {}
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise AzureError(
                        f"Invalid JSON response for {method} {url}",
                    ) from exc
                if not isinstance(payload, dict):
                    raise AzureError(
                        f"Expected a JSON object for {method} {url}",
                        details=payload,
                    )
                self._remaining()
                return payload
            remaining = self._remaining()
            if remaining is not None and delay >= remaining:
                raise AzureError("Retry delay exceeds the remaining Azure operation budget")
            if self._cancelled.wait(delay):
                raise AzureError("Azure operation cancelled during retry backoff")
            attempt += 1

    @staticmethod
    def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            if retry_after.isdigit():
                return float(retry_after)
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return max(0.0, date.timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                # An invalid server hint does not prevent the normal backoff.
                pass
        return float(2 ** attempt)

    def _http_error(self, exc: urllib.error.HTTPError) -> AzureError:
        try:
            text = self._read_response(exc).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError, HTTPException) as read_error:
            return AzureError(
                f"HTTP {exc.code}: failed to read error response: {read_error}",
                status=exc.code,
            )
        try:
            details = json.loads(text)
        except ValueError:
            details = text
        error = details.get("error", details) if isinstance(details, dict) else None
        code = error.get("code") if isinstance(error, dict) else error
        return AzureError(
            f"HTTP {exc.code}: {text}",
            status=exc.code,
            code=code if isinstance(code, str) else None,
            details=details,
        )
