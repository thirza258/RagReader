"""SSRF protection of the URL fetcher (PRD §39 "URL security").

No network: `socket.getaddrinfo` is replaced with a fixed table and the
already-checked connection (`open_checked_socket`) with an in-memory socket
that replays a canned HTTP response, so the real requests/urllib3 stack —
including the guarded `_new_conn` — runs end to end.
"""
import io
import os
import socket
from unittest import mock

from django.test import SimpleTestCase, override_settings

from common.errors import PipelineError
from utils.insert_file import DataLoader
from workspace.services import url_fetch
from workspace.services.url_fetch import UrlNotAllowed, fetch_url, is_public_address, validate_url

PUBLIC_IP = "93.184.216.34"


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = b""

    def sendall(self, data):
        self.sent += bytes(data)

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.response)

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        pass

    def close(self):
        pass


def http_response(status=200, reason="OK", headers=None, body=b""):
    headers = {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)), **(headers or {})}
    head = f"HTTP/1.1 {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items() if v is not None) + "\r\n"
    return head.encode("latin-1") + body


class FakeNetwork:
    """DNS table plus canned responses keyed by the address connected to."""

    def __init__(self, dns, responses):
        self.dns = dns
        self.responses = responses
        self.connections = []
        self.lookups = []

    def getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        self.lookups.append(host)
        if host not in self.dns:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        infos = []
        for address in self.dns[host]:
            if ":" in address:
                infos.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0)))
            else:
                infos.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)))
        return infos

    def open_socket(self, family, socktype, proto, sockaddr, timeout, socket_options, source_address):
        self.connections.append(sockaddr)
        sock = FakeSocket(self.responses[sockaddr[0]])
        self.last_socket = sock
        return sock

    def __enter__(self):
        self._patches = [
            mock.patch("socket.getaddrinfo", side_effect=self.getaddrinfo),
            mock.patch.object(url_fetch, "open_checked_socket", side_effect=self.open_socket),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()


class ValidateUrlTests(SimpleTestCase):
    def test_refused_without_any_network_access(self):
        refused = [
            "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/", "javascript:alert(1)",
            "http://localhost/", "http://LOCALHOST./", "http://api.localhost/", "http://127.0.0.1/",
            "http://127.1/", "http://2130706433/", "http://0x7f000001/", "http://0.0.0.0/", "http://10.1.2.3/",
            "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
            "http://100.64.0.1/", "http://224.0.0.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
            "http://[fe80::1]/", "http://[fc00::1]/", "http://[64:ff9b::7f00:1]/", "http://[2002:7f00:1::1]/",
            "http://user@example.com/", "http://user:pass@example.com/", "http://example.com:22/",
            "http://example.com:6379/", "http://example.com:0/", "http://", "", "not a url", "http://exa mple.com/",
            "https://example.com/" + "a" * 2100,
        ]
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("validate_url must not resolve")):
            for url in refused:
                with self.subTest(url=url), self.assertRaises(UrlNotAllowed) as raised:
                    validate_url(url)
                self.assertEqual((raised.exception.code, raised.exception.http_status), ("url_not_allowed", 400))

    def test_public_urls_pass(self):
        for url in ("https://example.com/a?b=c", "http://example.com:8080/x", "https://example.com:8443/",
                    f"http://{PUBLIC_IP}/", "https://[2606:2800:220:1:248:1893:25c8:1946]/"):
            with self.subTest(url=url):
                validate_url(url)

    def test_address_classification(self):
        for address in ("127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1",
                        "fe80::1%eth0", "224.0.0.1", "0.0.0.0", "64:ff9b::a00:1", "not-an-ip"):
            with self.subTest(address=address):
                self.assertFalse(is_public_address(address))
        self.assertTrue(is_public_address(PUBLIC_IP))
        self.assertTrue(is_public_address("2606:2800:220:1:248:1893:25c8:1946"))


class GuardedFetchTests(SimpleTestCase):
    def test_public_address_is_fetched_through_a_checked_connection(self):
        network = FakeNetwork({"public.example": [PUBLIC_IP]}, {PUBLIC_IP: http_response(body=b"<html><body><p>Alpha</p></body></html>")})
        with network:
            result = fetch_url("http://public.example/article?id=1")
        self.assertEqual(network.connections, [(PUBLIC_IP, 80)])
        self.assertIn(b"GET /article?id=1 HTTP/1.1", network.last_socket.sent)
        self.assertIn(b"Host: public.example", network.last_socket.sent)
        self.assertEqual((result.kind, result.content_type, result.charset), ("html", "text/html", "utf-8"))
        self.assertEqual((result.final_url, result.body), ("http://public.example/article?id=1", b"<html><body><p>Alpha</p></body></html>"))

    def test_names_that_resolve_inward_are_refused_before_connecting(self):
        for answers in (["10.0.0.7"], [PUBLIC_IP, "127.0.0.1"], ["100.64.3.4"], ["169.254.169.254"],
                        ["::ffff:10.0.0.1"], ["::1"], ["fd00::1"]):
            with self.subTest(answers=answers):
                network = FakeNetwork({"sneaky.example": answers}, {})
                with network, self.assertRaises(UrlNotAllowed):
                    fetch_url("http://sneaky.example/")
                self.assertEqual(network.connections, [])

    def test_redirect_to_a_private_name_is_refused(self):
        network = FakeNetwork(
            {"public.example": [PUBLIC_IP], "internal.example": ["10.1.2.3"]},
            {PUBLIC_IP: http_response(302, "Found", {"Location": "http://internal.example/admin", "Content-Length": "0"})},
        )
        with network, self.assertRaises(UrlNotAllowed):
            fetch_url("http://public.example/")
        self.assertEqual(network.connections, [(PUBLIC_IP, 80)])
        self.assertEqual(network.lookups, ["public.example", "internal.example"])

    def test_redirect_to_a_literal_private_address_or_bad_scheme_is_refused(self):
        for location in ("http://127.0.0.1/", "http://169.254.169.254/latest/", "file:///etc/passwd", "http://localhost:8080/"):
            with self.subTest(location=location):
                network = FakeNetwork(
                    {"public.example": [PUBLIC_IP]},
                    {PUBLIC_IP: http_response(301, "Moved", {"Location": location, "Content-Length": "0"})},
                )
                with network, self.assertRaises(UrlNotAllowed):
                    fetch_url("http://public.example/")
                self.assertEqual(len(network.connections), 1)

    def test_redirects_are_followed_up_to_the_limit(self):
        hosts = [f"hop{i}.example" for i in range(8)]
        addresses = [f"93.184.216.{10 + i}" for i in range(8)]
        responses = {
            address: http_response(302, "Found", {"Location": f"http://{hosts[i + 1]}/", "Content-Length": "0"})
            for i, address in enumerate(addresses[:-1])
        }
        network = FakeNetwork({host: [address] for host, address in zip(hosts, addresses)}, responses)
        with network, self.assertRaises(UrlNotAllowed) as raised:
            fetch_url(f"http://{hosts[0]}/")
        self.assertIn("redirected too many times", str(raised.exception))
        self.assertEqual(len(network.connections), url_fetch.MAX_REDIRECTS + 1)

        responses[addresses[2]] = http_response(body=b"<p>Gamma</p>")
        network = FakeNetwork({host: [address] for host, address in zip(hosts, addresses)}, responses)
        with network:
            result = fetch_url(f"http://{hosts[0]}/")
        self.assertEqual(result.final_url, f"http://{hosts[2]}/")
        self.assertEqual(result.redirects, [f"http://{hosts[1]}/", f"http://{hosts[2]}/"])

    def test_environment_proxies_are_ignored(self):
        network = FakeNetwork({"public.example": [PUBLIC_IP], "proxy.internal": ["10.9.9.9"]},
                              {PUBLIC_IP: http_response(body=b"<p>Alpha</p>")})
        proxies = {"HTTP_PROXY": "http://proxy.internal:3128", "http_proxy": "http://proxy.internal:3128",
                   "ALL_PROXY": "http://proxy.internal:3128", "NO_PROXY": ""}
        with network, mock.patch.dict(os.environ, proxies):
            fetch_url("http://public.example/")
        self.assertEqual(network.connections, [(PUBLIC_IP, 80)])
        self.assertNotIn("proxy.internal", network.lookups)

    def test_size_type_and_status_limits(self):
        cases = [
            (http_response(body=b"x" * 64), "file_too_large"),
            (http_response(headers={"Content-Length": None}, body=b"x" * 64), "file_too_large"),
            (http_response(headers={"Content-Length": "999999999"}, body=b""), "file_too_large"),
            (http_response(headers={"Content-Type": "image/png"}, body=b"\x89PNG"), "unsupported_file_type"),
            (http_response(404, "Not Found", body=b"missing"), "url_fetch_failed"),
            (http_response(503, "Unavailable", body=b"later"), "url_fetch_failed"),
        ]
        for response, code in cases:
            with self.subTest(code=code, response=response[:40]):
                network = FakeNetwork({"public.example": [PUBLIC_IP]}, {PUBLIC_IP: response})
                with network, self.assertRaises(PipelineError) as raised:
                    fetch_url("http://public.example/", max_bytes=32)
                self.assertEqual(raised.exception.code, code)

    def test_pdf_and_untyped_html_are_recognised(self):
        for headers, body, kind in (({"Content-Type": "application/pdf"}, b"%PDF-1.4 ...", "pdf"),
                                    ({"Content-Type": None}, b"<!DOCTYPE html><html><p>Alpha</p></html>", "html"),
                                    ({"Content-Type": "text/markdown"}, b"# Alpha", "text")):
            with self.subTest(kind=kind):
                network = FakeNetwork({"public.example": [PUBLIC_IP]}, {PUBLIC_IP: http_response(headers=headers, body=body)})
                with network:
                    self.assertEqual(fetch_url("http://public.example/").kind, kind)

    def test_unresolvable_names_are_a_retryable_fetch_failure(self):
        with FakeNetwork({}, {}), self.assertRaises(PipelineError) as raised:
            fetch_url("http://nowhere.example/")
        self.assertEqual((raised.exception.code, raised.exception.retryable), ("url_fetch_failed", True))

    @override_settings(RAG_MAX_URL_BYTES=16)
    def test_the_default_cap_comes_from_settings(self):
        network = FakeNetwork({"public.example": [PUBLIC_IP]}, {PUBLIC_IP: http_response(body=b"y" * 17)})
        with network, self.assertRaises(PipelineError) as raised:
            fetch_url("http://public.example/")
        self.assertEqual(raised.exception.code, "file_too_large")

    def test_legacy_url_insert_uses_the_same_guard(self):
        network = FakeNetwork({"sneaky.example": ["192.168.0.10"]}, {})
        with network:
            for url in ("http://localhost:8000/admin", "http://sneaky.example/"):
                with self.subTest(url=url), self.assertRaises(UrlNotAllowed):
                    DataLoader._fetch_url(url)
        self.assertEqual(network.connections, [])
