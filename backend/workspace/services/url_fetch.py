"""SSRF-safe URL fetching (PRD §10, §39 "URL security").

Validating a URL's hostname before the request is not enough: DNS can answer
differently at connect time (rebinding), a public page can redirect to
http://169.254.169.254/, and an `HTTP_PROXY` in the worker's environment can
route the request somewhere else entirely. So:

* every socket is opened by `_GuardedConnectionMixin._new_conn`, which
  resolves the host itself, refuses the whole host if *any* address is not
  globally routable, and connects to the exact address it checked — there is
  no second lookup to race;
* redirects are followed by hand (at most MAX_REDIRECTS) and each hop's URL
  is re-validated before its connection is opened;
* the session ignores the environment (`trust_env=False`) and refuses proxies;
* ports, content types, body size and total time are capped.

Written against urllib3 2.8 (pinned via requests in requirements.txt):
`HTTPConnection._new_conn` is the single place both HTTP and HTTPS
connections create their TCP socket; HTTPS wraps the returned socket in TLS
for the original hostname, so certificate checks are unaffected.
"""
import ipaddress
import logging
import socket
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.connection import _set_socket_options
from urllib3.util.timeout import _DEFAULT_TIMEOUT

from common.errors import PipelineError

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_REDIRECTS = 5
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
# A per-read timeout alone lets a server drip one byte every 14 seconds forever.
TOTAL_TIMEOUT = 45
MAX_URL_LENGTH = 2048
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CONTENT_TYPES = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "text",
    "text/markdown": "text",
    "text/x-markdown": "text",
    "application/pdf": "pdf",
}
USER_AGENT = "RAGReader/1.0 (+https://rag.nevatal.id; document ingestion)"
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
# NAT64 well-known prefix: the low 32 bits are an IPv4 address the gateway reaches.
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
NOT_ALLOWED_MESSAGE = "This URL cannot be fetched. Use a public http(s) address."


class UrlNotAllowed(PipelineError):
    def __init__(self, message=NOT_ALLOWED_MESSAGE):
        super().__init__("url_not_allowed", message, retryable=False, http_status=400)


class _BlockedAddress(Exception):
    """Raised inside urllib3. Deliberately not an OSError, so neither urllib3
    nor requests retries or rewraps it; it surfaces from session.get as-is."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


@dataclass
class FetchResult:
    url: str
    final_url: str
    content_type: str
    kind: str  # "html", "text" or "pdf"
    charset: str | None
    body: bytes
    redirects: list = field(default_factory=list)


# ── Address and URL checks ───────────────────────────────────────────────────

def _embedded_ipv4(ip):
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in NAT64_PREFIX:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_address(value) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return False
    embedded = _embedded_ipv4(ip)
    if embedded is not None and not is_public_address(embedded):
        return False
    # is_global alone admits multicast (224.0.0.0/4) on some Python versions.
    return ip.is_global and not (
        ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_unspecified
    )


def _literal_ip(host):
    """The address a literal host denotes, including inet_aton's short forms
    ("127.1", "0x7f.1", "2130706433") that resolvers also accept."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def validate_url(url):
    """Syntax-level checks; raises UrlNotAllowed. Returns the parsed URL.

    Hostnames are only fully checked at connect time (see module docstring);
    this rejects what is wrong without any network access.
    """
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL_LENGTH:
        raise UrlNotAllowed("Enter a valid http(s) URL.")
    if any(ord(char) < 33 for char in url.strip()):
        raise UrlNotAllowed("Enter a valid http(s) URL.")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise UrlNotAllowed("Enter a valid http(s) URL.")
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowed("Only http and https URLs can be fetched.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UrlNotAllowed("URLs with a username or password are not allowed.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UrlNotAllowed("Enter a valid http(s) URL.")
    if port is not None and port not in ALLOWED_PORTS:
        raise UrlNotAllowed("Only ports 80, 443, 8080 and 8443 are allowed.")
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise UrlNotAllowed()
    literal = _literal_ip(host)
    if literal is not None and not is_public_address(literal):
        raise UrlNotAllowed()
    return parts


def resolve_public_addresses(host, port):
    """getaddrinfo results for host:port, refusing the host if any address is
    not public — a name that also points inward is not worth the risk."""
    host = host.strip("[]")
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos:
        raise socket.gaierror(f"No addresses for {host}")
    for _family, _type, _proto, _canonname, sockaddr in infos:
        if not is_public_address(sockaddr[0]):
            raise _BlockedAddress(f"{host} resolves to a non-public address")
    return infos


def open_checked_socket(family, socktype, proto, sockaddr, timeout, socket_options, source_address):
    """Connect to an already-checked address. A seam for tests."""
    sock = socket.socket(family, socktype, proto)
    try:
        _set_socket_options(sock, socket_options)
        if timeout is not _DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        if source_address:
            sock.bind(source_address)
        sock.connect(sockaddr)
        return sock
    except BaseException:
        sock.close()
        raise


class _GuardedConnectionMixin:
    def _new_conn(self):
        try:
            infos = resolve_public_addresses(self._dns_host, self.port)
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        last_error = None
        for family, socktype, proto, _canonname, sockaddr in infos:
            try:
                sock = open_checked_socket(
                    family, socktype, proto, sockaddr, self.timeout,
                    self.socket_options, self.source_address,
                )
            except socket.timeout as exc:
                raise ConnectTimeoutError(
                    self, f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
                ) from exc
            except OSError as exc:
                last_error = exc
                continue
            sys.audit("http.client.connect", self, self.host, self.port)
            return sock
        raise NewConnectionError(self, f"Failed to establish a new connection: {last_error}")


class _GuardedHTTPConnection(_GuardedConnectionMixin, HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnectionMixin, HTTPSConnection):
    pass


class _GuardedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class GuardedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        # A per-manager copy: the module-level mapping is shared by every
        # other urllib3 user in the process.
        self.poolmanager.pool_classes_by_scheme = {"http": _GuardedHTTPPool, "https": _GuardedHTTPSPool}

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        raise _BlockedAddress("Proxies are not used for document fetching")


def guarded_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    adapter = GuardedAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# ── Fetching ─────────────────────────────────────────────────────────────────

def _content_type(response):
    raw = response.headers.get("Content-Type", "")
    mime, _, params = raw.partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.strip().partition("=")
        if key.lower() == "charset" and value:
            charset = value.strip().strip('"').strip("'") or None
    return mime.strip().lower(), charset


def _sniff(body):
    head = body[:1024].lstrip().lower()
    if body[:1024].find(b"%PDF-") != -1:
        return "application/pdf"
    if head.startswith(b"<!doctype html") or b"<html" in head:
        return "text/html"
    return None


def fetch_url(url, *, max_bytes=None, session=None) -> FetchResult:
    """Fetch `url` under the rules in the module docstring.

    Raises PipelineError: url_not_allowed, file_too_large, unsupported_file_type,
    url_fetch_failed or url_fetch_timeout.
    """
    max_bytes = max_bytes or settings.RAG_MAX_URL_BYTES
    owns_session = session is None
    session = session or guarded_session()
    deadline = time.monotonic() + TOTAL_TIMEOUT
    current, redirects = url, []
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            validate_url(current)
            try:
                response = session.get(
                    current, allow_redirects=False, stream=True,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown,application/pdf;q=0.9,*/*;q=0.1",
                        "Accept-Encoding": "gzip, deflate",
                    },
                )
            except _BlockedAddress:
                raise UrlNotAllowed()
            except requests.Timeout:
                raise PipelineError("url_fetch_timeout", "The page took too long to respond. Try again later.", retryable=True, http_status=504)
            except requests.RequestException:
                raise PipelineError("url_fetch_failed", "The page could not be reached. Check the URL and try again.", retryable=True, http_status=502)
            try:
                if response.status_code in REDIRECT_STATUSES and response.headers.get("Location"):
                    current = urljoin(current, response.headers["Location"])
                    redirects.append(current)
                    continue
                return _read_response(url, current, response, max_bytes, deadline, redirects)
            finally:
                response.close()
        raise UrlNotAllowed("The URL redirected too many times.")
    finally:
        if owns_session:
            session.close()


def _read_response(url, final_url, response, max_bytes, deadline, redirects):
    if response.status_code >= 400:
        retryable = response.status_code >= 500 or response.status_code == 429
        raise PipelineError(
            "url_fetch_failed", f"The page answered with HTTP {response.status_code}.",
            retryable=retryable, http_status=502,
        )
    mime, charset = _content_type(response)
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise PipelineError("file_too_large", "The page is larger than the size limit for web pages.", http_status=413)
    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise PipelineError("file_too_large", "The page is larger than the size limit for web pages.", http_status=413)
            if time.monotonic() > deadline:
                raise PipelineError("url_fetch_timeout", "The page took too long to download. Try again later.", retryable=True, http_status=504)
    except requests.RequestException:
        raise PipelineError("url_fetch_failed", "The page could not be downloaded completely. Try again.", retryable=True, http_status=502)
    body = bytes(body)
    if not mime:
        mime = _sniff(body) or ""
    kind = CONTENT_TYPES.get(mime)
    if kind is None:
        raise PipelineError(
            "unsupported_file_type",
            "The URL does not point to a web page, plain text, Markdown or PDF.",
            http_status=415,
        )
    return FetchResult(url=url, final_url=final_url, content_type=mime, kind=kind, charset=charset, body=body, redirects=redirects)
