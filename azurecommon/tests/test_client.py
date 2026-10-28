import io
import json
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from http.client import IncompleteRead
from threading import Barrier
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from azurecommon.azurecommon.lib import client as module
from azurecommon.azurecommon.lib.client import AzureClient, AzureError


class AzureClientTests(unittest.TestCase):
    def setUp(self):
        self.azure = AzureClient("tenant", "client", "secret")

    def response(self, payload):
        response = MagicMock()
        body = json.dumps(payload).encode()
        response.__enter__.return_value.read.return_value = body
        response.__enter__.return_value.read1.side_effect = [body, b""]
        response.__enter__.return_value.getheader.return_value = None
        return response

    def http_error(self, status, payload, retry_after=None):
        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        return urllib.error.HTTPError(
            "https://api.loganalytics.io/v1/query", status, "error",
            headers, io.BytesIO(json.dumps(payload).encode()),
        )

    def authenticated_opener(self, scope):
        self.azure._tokens[scope] = ("cached-token", time.monotonic() + 3600)
        opener = Mock()
        self.azure._http.opener = opener
        return opener

    def test_service_urls_scopes_and_web_version(self):
        with patch.object(self.azure, "_request", return_value={}) as request:
            self.azure.web.get(
                "/subscriptions/sub/providers/Microsoft.Web/sites?existing=yes",
                params={"api-version": "wrong", "$filter": "kind eq 'functionapp'"},
            )
            args, kwargs = request.call_args
            url = urlsplit(args[1])
            self.assertEqual(args[0], "GET")
            self.assertEqual(url.netloc, "management.azure.com")
            self.assertEqual(parse_qs(url.query), {
                "existing": ["yes"],
                "api-version": ["2023-12-01"],
                "$filter": ["kind eq 'functionapp'"],
            })
            self.assertEqual(kwargs["scope"], "https://management.azure.com/.default")

            payload = {"query": "requests", "timespan": "PT3600S"}
            self.azure.logs.post("/v1/resource/query", payload=payload)
            args, kwargs = request.call_args
            self.assertEqual(args, ("POST", "https://api.loganalytics.io/v1/resource/query"))
            self.assertEqual(kwargs["scope"], "https://api.loganalytics.io/.default")
            self.assertEqual(json.loads(kwargs["body"]), payload)

            self.azure.appinsights.get("/v1/apps/app/query", params={"query": "requests"})
            args, kwargs = request.call_args
            self.assertEqual(urlsplit(args[1]).netloc, "api.applicationinsights.io")
            self.assertEqual(
                kwargs["scope"], "https://api.applicationinsights.io/.default",
            )

    def test_pagination_preserves_continuation_query_and_version(self):
        pages = [
            {"value": [{"name": "first"}],
             "nextLink": "https://management.azure.com/sites?$skiptoken=a%2Bb"},
            {"value": [{"name": "second"}], "@odata.nextLink": "?$skiptoken=last"},
            {"value": []},
        ]
        with patch.object(self.azure, "_request", side_effect=pages) as request:
            rows = list(self.azure.web.get_paged("/sites", params={"initial": "only"}))
        self.assertEqual(rows, [{"name": "first"}, {"name": "second"}])
        queries = [parse_qs(urlsplit(call.args[1]).query) for call in request.call_args_list]
        self.assertEqual(queries, [
            {"initial": ["only"], "api-version": ["2023-12-01"]},
            {"$skiptoken": ["a+b"], "api-version": ["2023-12-01"]},
            {"$skiptoken": ["last"], "api-version": ["2023-12-01"]},
        ])

    def test_invalid_pagination_is_not_an_empty_discovery(self):
        for page in ({}, {"value": {}}, {"value": [None]},
                     {"value": [], "nextLink": False}):
            with self.subTest(page=page):
                with patch.object(self.azure.web, "get", return_value=page):
                    with self.assertRaises(AzureError):
                        list(self.azure.web.get_paged("/sites"))

    def test_rejects_cross_origin_paths_and_continuations(self):
        with patch.object(self.azure, "_request") as request:
            for path in ("https://other.example/sites", "//other.example/sites",
                         "http://management.azure.com/sites"):
                with self.subTest(path=path), self.assertRaises(AzureError):
                    self.azure.web.get(path)
            request.assert_not_called()
            request.return_value = {
                "value": [], "nextLink": "https://other.example/sites",
            }
            with self.assertRaises(AzureError):
                list(self.azure.web.get_paged("/sites"))
            self.assertEqual(request.call_count, 1)

    def test_rejects_pagination_cycles(self):
        with patch.object(self.azure.web, "get", return_value={
            "value": [], "nextLink": "/sites",
        }) as get:
            with self.assertRaises(AzureError):
                list(self.azure.web.get_paged("/sites"))
            self.assertEqual(get.call_count, 1)

    def test_token_acquisition_is_synchronized_and_cached_per_scope(self):
        with patch.object(self.azure, "_request", return_value={
            "access_token": "token", "expires_in": 3600,
        }) as request:
            with ThreadPoolExecutor(max_workers=8) as pool:
                tokens = list(pool.map(self.azure._token, ["scope"] * 20))
            self.assertEqual(tokens, ["token"] * 20)
            request.assert_called_once()
            self.azure._token("another-scope")
            self.assertEqual(request.call_count, 2)
            self.azure._tokens["scope"] = ("expired", time.monotonic() - 1)
            self.azure._token("scope")
            self.assertEqual(request.call_count, 3)

    def test_invalid_token_responses_raise(self):
        for payload in ({}, {"access_token": "token"}, {
            "access_token": "token", "expires_in": "nan",
        }):
            with self.subTest(payload=payload):
                with patch.object(self.azure, "_request", return_value=payload):
                    with self.assertRaises(AzureError):
                        self.azure._token("scope")

    def test_http_openers_are_thread_local(self):
        barrier = Barrier(2)

        def opener(_):
            result = self.azure._opener()
            barrier.wait(timeout=5)
            self.assertIs(result, self.azure._opener())
            return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(opener, range(2))
        self.assertIsNot(first, second)

    def test_proxy_is_used_for_each_thread_opener(self):
        azure = AzureClient("tenant", "client", "secret", proxy="http://proxy:8080")
        with patch.object(module.urllib.request, "ProxyHandler") as handler, \
                patch.object(module.urllib.request, "build_opener") as build:
            self.assertIs(azure._opener(), build.return_value)
            self.assertIs(build.call_args.args[1], handler.return_value)
        handler.assert_called_once_with({
            "http": "http://proxy:8080", "https": "http://proxy:8080",
        })

    def test_redirects_do_not_replay_credentials(self):
        handler = module._NoRedirect()
        self.assertIsNone(handler.redirect_request(
            None, None, 302, "Found", Message(), "https://other.example",
        ))

    def test_transport_sends_bearer_token_and_json(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.return_value = self.response({"tables": []})
        result = self.azure.logs.post("/query", payload={"query": "test"})
        self.assertEqual(result, {"tables": []})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer cached-token")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"query": "test"})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 60)

    def test_retries_throttling(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.side_effect = [
            self.http_error(429, {"error": {"code": "Throttled"}}, "3"),
            self.response({"tables": []}),
        ]
        with patch.object(self.azure._cancelled, "wait", return_value=False) as sleep:
            self.assertEqual(self.azure.logs.get("/query"), {"tables": []})
            sleep.assert_called_once_with(3.0)
        self.assertEqual(opener.open.call_count, 2)

    def test_retry_after_http_date(self):
        error = self.http_error(503, {}, "Thu, 01 Jan 1970 00:01:40 GMT")
        with patch.object(module.time, "time", return_value=90):
            self.assertEqual(self.azure._retry_delay(error, 0), 10)
        error.close()
        error = self.http_error(503, {}, "invalid")
        self.assertEqual(self.azure._retry_delay(error, 2), 4)
        error.close()

    def test_exhausted_http_retry_exposes_error_details(self):
        self.azure = AzureClient("tenant", "client", "secret", max_retries=0)
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        payload = {"error": {"code": "Forbidden", "message": "denied"}}
        opener.open.side_effect = self.http_error(403, payload)
        with self.assertRaises(AzureError) as raised:
            self.azure.logs.get("/query")
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.code, "Forbidden")
        self.assertEqual(raised.exception.details, payload)
        self.assertEqual(opener.open.call_count, 1)

    def test_connection_retries_are_bounded(self):
        self.azure = AzureClient("tenant", "client", "secret", max_retries=1)
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.side_effect = TimeoutError("timed out")
        with patch.object(self.azure._cancelled, "wait", return_value=False) as sleep:
            with self.assertRaises(AzureError):
                self.azure.logs.get("/query")
            sleep.assert_called_once_with(1.0)
        self.assertEqual(opener.open.call_count, 2)

    def test_unauthorized_refreshes_only_once(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.side_effect = [
            self.http_error(401, {"error": {"code": "Unauthorized"}}),
            self.response({"access_token": "fresh", "expires_in": 3600}),
            self.http_error(401, {"error": {"code": "Unauthorized"}}),
        ]
        with self.assertRaises(AzureError) as raised:
            self.azure.logs.get("/query")
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(opener.open.call_count, 3)
        request = opener.open.call_args_list[-1].args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer fresh")

    def test_invalid_json_and_non_objects_raise(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        for raw in (b"not json", b"[]", b"null"):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = raw
            opener.open.return_value = response
            with self.subTest(raw=raw), self.assertRaises(AzureError):
                self.azure.logs.get("/query")

    def test_empty_response_returns_empty_object(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b""
        opener.open.return_value = response
        self.assertEqual(self.azure.logs.get("/query"), {})

    def test_invalid_configuration_raises(self):
        for kwargs in ({"timeout": 0}, {"timeout": float("inf")},
                       {"max_retries": -1}, {"max_retries": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AzureClient("tenant", "client", "secret", **kwargs)
        with self.assertRaises(ValueError):
            AzureClient("", "client", "secret")

    def test_query_errors_are_left_for_the_plugin(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        payload = {"tables": [], "error": {"code": "PartialError"}}
        opener.open.return_value = self.response(payload)
        self.assertEqual(self.azure.logs.get("/query"), payload)

    def test_no_domain_helpers_or_concurrency_api(self):
        for name in ("map_concurrent", "discover_functions", "logs_query",
                     "appinsights_query", "arm_get", "arm_list"):
            self.assertFalse(hasattr(self.azure, name), name)

    def test_truncated_response_is_retried_and_closed(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        truncated = MagicMock()
        truncated.__enter__.return_value.read.side_effect = IncompleteRead(b"partial", 10)
        opener.open.side_effect = [truncated, self.response({"tables": []})]
        with patch.object(self.azure._cancelled, "wait", return_value=False) as backoff:
            self.assertEqual(self.azure.logs.get("/query"), {"tables": []})
        self.assertEqual(opener.open.call_count, 2)
        truncated.__exit__.assert_called_once()
        backoff.assert_called_once_with(1.0)

    def test_exhausted_truncated_response_is_an_azure_error(self):
        self.azure = AzureClient("tenant", "client", "secret", max_retries=0)
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        truncated = MagicMock()
        error = IncompleteRead(b"partial", 10)
        truncated.__enter__.return_value.read.side_effect = error
        opener.open.return_value = truncated
        with self.assertRaises(AzureError) as raised:
            self.azure.logs.get("/query")
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(opener.open.call_count, 1)

    def test_deadline_limits_socket_timeout(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.return_value = self.response({})
        self.azure._deadline = 100
        with patch.object(module.time, "monotonic", return_value=90):
            self.azure.logs.get("/query")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)

    def test_expired_deadline_prevents_http_and_token_acquisition(self):
        self.azure._deadline = 100
        with patch.object(module.time, "monotonic", return_value=100), \
                patch.object(self.azure, "_opener") as opener, \
                patch.object(self.azure._credential, "get_token") as token:
            with self.assertRaisesRegex(AzureError, "deadline"):
                self.azure.logs.get("/query")
        opener.assert_not_called()
        token.assert_not_called()

    def test_retry_after_cannot_exceed_overall_budget(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.side_effect = self.http_error(429, {}, "3600")
        self.azure._deadline = 100
        with patch.object(module.time, "monotonic", return_value=90), \
                patch.object(self.azure._cancelled, "wait") as backoff:
            with self.assertRaisesRegex(AzureError, "budget"):
                self.azure.logs.get("/query")
        backoff.assert_not_called()
        self.assertEqual(opener.open.call_count, 1)

    def test_successful_response_after_deadline_is_not_returned(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")

        def late_read():
            self.azure._deadline = time.monotonic() - 1
            return b'{"tables": []}'

        response = MagicMock()
        response.__enter__.return_value.read.side_effect = late_read
        opener.open.return_value = response
        with self.assertRaisesRegex(AzureError, "deadline"):
            self.azure.logs.get("/query")

    def test_pagination_shares_deadline_across_pages(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.return_value = self.response({"value": [{}], "nextLink": "/page2"})
        pages = self.azure.logs.get_paged("/page1")
        self.assertEqual(next(pages), {})
        self.azure._deadline = time.monotonic() - 1
        with self.assertRaisesRegex(AzureError, "deadline"):
            next(pages)
        self.assertEqual(opener.open.call_count, 1)

    def test_deadline_is_checked_between_response_chunks(self):
        self.azure._deadline = time.monotonic() + 60
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        response = self.response({})

        def partial_read(size):
            self.azure._deadline = time.monotonic() - 1
            return b'{"partial":'

        response.__enter__.return_value.read1.side_effect = partial_read
        opener.open.return_value = response
        with self.assertRaisesRegex(AzureError, "deadline"):
            self.azure.logs.get("/query")
        response.__enter__.return_value.read1.assert_called_once()

    def test_truncated_chunked_read_retries_within_deadline(self):
        self.azure._deadline = time.monotonic() + 60
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        truncated = self.response({})
        truncated.__enter__.return_value.getheader.side_effect = (
            lambda name: "30" if name == "Content-Length" else None
        )
        truncated.__enter__.return_value.read1.side_effect = [b"{}", b""]
        opener.open.side_effect = [truncated, self.response({})]
        with patch.object(self.azure._cancelled, "wait", return_value=False):
            self.assertEqual(self.azure.logs.get("/query"), {})
        self.assertEqual(opener.open.call_count, 2)

    def test_token_lock_wait_is_bounded(self):
        self.azure._deadline = 100
        with patch.object(module.time, "monotonic", return_value=90), \
                patch.object(self.azure, "_token_lock") as lock:
            lock.acquire.return_value = False
            with self.assertRaisesRegex(AzureError, "deadline"):
                self.azure._token("scope")
            lock.acquire.assert_called_once_with(timeout=10)
            lock.release.assert_not_called()

    def test_cancel_prevents_further_calls(self):
        self.azure.cancel()
        with patch.object(self.azure, "_opener") as opener:
            with self.assertRaisesRegex(AzureError, "cancelled"):
                self.azure.logs.get("/query")
        opener.assert_not_called()

    def test_cancel_interrupts_retry_backoff(self):
        opener = self.authenticated_opener("https://api.loganalytics.io/.default")
        opener.open.side_effect = self.http_error(429, {}, "3")
        with patch.object(self.azure._cancelled, "wait", return_value=True):
            with self.assertRaisesRegex(AzureError, "cancelled"):
                self.azure.logs.get("/query")
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
