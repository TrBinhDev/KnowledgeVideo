import ipaddress
import logging
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

logger = logging.getLogger("kv.security")

# The Windows root store on some machines still holds an expired ISRG Root X2 cross-cert that
# OpenSSL picks first (breaks Wikimedia); Mozilla's certifi bundle avoids that.
_TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "ref",
    "ref_src",
    "source",
    "spm",
    "igshid",
    "_ga",
    "ncid",
}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for deduplication.

    - Trims whitespace
    - Lowercases scheme and host
    - Removes standard default ports (80 for http, 443 for https)
    - Strips fragment (#...)
    - Strips trailing slash on non-root paths
    - Removes analytics/tracking query params while keeping meaningful params
    - Sorts query parameters deterministically
    """
    clean = (url or "").strip()
    if not clean:
        return ""

    parsed = urlparse(clean)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Strip default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize path
    path = parsed.path
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Filter and sort query params
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_items = [
        (k, v) for k, v in query_items
        if k.lower() not in _TRACKING_PARAMS
    ]
    filtered_items.sort(key=lambda item: (item[0], item[1]))
    clean_query = urlencode(filtered_items)

    return urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        clean_query,
        "",  # Strip fragment
    ))


def is_safe_ip(ip_str: str) -> bool:
    """Check if an IP address is public and safe to connect to."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False

    # Block AWS / Cloud metadata IPv4
    if ip == ipaddress.IPv4Address("169.254.169.254"):
        return False

    return True


def validate_safe_url(url: str) -> str:
    """Validate that a URL uses http/https and does not point to internal/private networks.

    Raises:
        ValueError: If URL is malformed, uses unsupported scheme, or resolves to a private IP.
    """
    clean_url = url.strip()
    if not clean_url:
        raise ValueError("URL trống")

    parsed = urlparse(clean_url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Chỉ hỗ trợ giao thức HTTP và HTTPS: '{parsed.scheme}'")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError(f"URL không có hostname hợp lệ: '{clean_url}'")

    if hostname in _BLOCKED_HOSTS:
        raise ValueError(f"Truy cập vào '{hostname}' bị từ chối vì lý do an toàn mạng.")

    # Check if hostname is directly an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if not is_safe_ip(str(ip)):
            raise ValueError(f"Địa chỉ IP '{ip}' thuộc dải mạng nội bộ hoặc bị hạn chế.")
    except ValueError as val_err:
        if "Địa chỉ IP" in str(val_err):
            raise
        # Not an IP literal, resolve hostname via DNS
        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            resolved_ips = {item[4][0] for item in addr_info if item[4]}
            if not resolved_ips:
                raise ValueError(f"Không thể phân giải tên miền: '{hostname}'")
            for resolved_ip in resolved_ips:
                if not is_safe_ip(resolved_ip):
                    raise ValueError(f"Tên miền '{hostname}' phân giải về IP bị chặn: '{resolved_ip}'")
        except socket.gaierror as error:
            raise ValueError(f"Lỗi DNS khi phân giải '{hostname}': {error}") from error

    return clean_url


class SafeRedirectHandler(HTTPRedirectHandler):
    """Urllib redirect handler that verifies target URLs before following redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        clean_newurl = newurl.strip()
        try:
            validate_safe_url(clean_newurl)
        except ValueError as exc:
            logger.warning("blocked_unsafe_redirect url=%s reason=%s", clean_newurl, exc)
            raise HTTPError(clean_newurl, 403, f"Redirect bị chặn vì lý do an toàn: {exc}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, clean_newurl)


def build_safe_opener():
    """Build a urllib OpenerDirector equipped with SafeRedirectHandler."""
    return build_opener(SafeRedirectHandler(), HTTPSHandler(context=_TLS_CONTEXT))


def fetch_safe_bytes(url: str, timeout: float = 10.0, user_agent: str = "KnowledgeVideo/0.1") -> bytes:
    """Fetch content from a validated URL with size limit and redirect protection."""
    validate_safe_url(url)
    opener = build_safe_opener()
    request = Request(url, headers={"User-Agent": user_agent})
    with opener.open(request, timeout=timeout) as response:
        content = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ValueError(f"Nội dung vượt quá giới hạn cho phép ({_MAX_RESPONSE_BYTES // (1024*1024)}MB)")
        return content
