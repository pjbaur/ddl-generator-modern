#!/usr/bin/env python
"""
URL validation and safe fetching utilities for SSRF prevention.

This module provides URL validation to prevent Server-Side Request Forgery (SSRF)
attacks and adds request hardening (timeouts, size limits) when fetching data
from URLs.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from requests import Response

# Try to import requests, but don't fail if not available
try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

# Constants for URL validation
ALLOWED_SCHEMES = {'http', 'https'}
MAX_RESPONSE_SIZE = 50 * 1024 * 1024  # 50 MB
DEFAULT_TIMEOUT = 30  # seconds
MAX_REDIRECTS = 5

# Private IP ranges for SSRF prevention
PRIVATE_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),      # RFC 1918
    ipaddress.ip_network('172.16.0.0/12'),   # RFC 1918
    ipaddress.ip_network('192.168.0.0/16'),  # RFC 1918
    ipaddress.ip_network('127.0.0.0/8'),     # Loopback
    ipaddress.ip_network('169.254.0.0/16'),  # Link-local
    ipaddress.ip_network('0.0.0.0/8'),       # Current network
    ipaddress.ip_network('::1/128'),         # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),        # IPv6 unique local
    ipaddress.ip_network('fe80::/10'),       # IPv6 link-local
]


class URLValidationError(ValueError):
    """Raised when a URL fails validation."""
    pass


class SSRFError(URLValidationError):
    """Raised when a URL points to a blocked private IP address."""
    pass


class ResponseTooLargeError(URLValidationError):
    """Raised when a response exceeds the size limit."""
    pass


def is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is in a private/blocked range.

    Args:
        ip_str: String representation of an IP address

    Returns:
        True if the IP is in a private/blocked range, False otherwise
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in PRIVATE_IP_RANGES:
            if ip in network:
                return True
        return False
    except ValueError:
        # Not a valid IP address
        return False


def resolve_host_ips(hostname: str) -> list[str]:
    """
    Resolve a hostname to every address it answers with.

    Args:
        hostname: The hostname to resolve

    Returns:
        Sorted list of unique address strings

    Raises:
        URLValidationError: If the hostname cannot be resolved
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        # Fail closed: a host we cannot resolve is a host we cannot vet.
        raise URLValidationError(
            f"Could not resolve hostname '{hostname}': {e}") from e
    # sockaddr is a 2-tuple for IPv4 and a 4-tuple for IPv6; the address is
    # first in both, but the declared element type is str | int.
    return sorted({str(info[4][0]) for info in infos})


def validate_url_scheme(url: str) -> None:
    """
    Validate that the URL uses an allowed scheme (http or https).

    Args:
        url: The URL string to validate

    Raises:
        URLValidationError: If the scheme is not allowed
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise URLValidationError(
            f"URL scheme '{parsed.scheme}' is not allowed. "
            f"Allowed schemes: {', '.join(ALLOWED_SCHEMES)}"
        )


def validate_url_host(url: str) -> None:
    """
    Validate that the URL host is not a private/blocked IP address.

    This prevents SSRF attacks by blocking requests to internal network
    resources. Literal addresses are checked directly; hostnames are
    resolved and every address they answer with is checked.

    The check and the request that follows resolve the name separately, so
    a name that changes its answer in between (DNS rebinding) is not
    covered. Closing that gap means pinning the validated address into the
    connection itself, which requests does not expose.

    Args:
        url: The URL string to validate

    Raises:
        SSRFError: If the host is, or resolves to, a private IP address
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        raise URLValidationError("URL has no hostname")

    # Check if hostname is an IP address directly
    if is_private_ip(hostname):
        raise SSRFError(
            f"URL hostname '{hostname}' is a private/internal IP address. "
            "Requests to private IPs are blocked for security reasons."
        )

    # Check for localhost variations
    if hostname.lower() in ('localhost', 'localhost.localdomain'):
        raise SSRFError(
            "URL hostname 'localhost' is blocked for security reasons."
        )

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass  # A name, not a literal address -- it has to be resolved.
    else:
        return  # A literal address was already checked above.

    # Blocking only literal addresses leaves the obvious bypass open: point a
    # public name at 127.0.0.1 or the metadata address. Check what it answers
    # with, and reject if any address is private -- round-robin DNS can mix
    # public and internal records.
    for ip in resolve_host_ips(hostname):
        if is_private_ip(ip):
            raise SSRFError(
                f"URL hostname '{hostname}' resolves to {ip}, a private/internal "
                "IP address. Requests to private IPs are blocked for security "
                "reasons."
            )


def validate_url(url: str) -> None:
    """
    Validate a URL for security (scheme and SSRF prevention).

    Args:
        url: The URL string to validate

    Raises:
        URLValidationError: If the URL fails validation
        SSRFError: If the URL points to a blocked address
    """
    validate_url_scheme(url)
    validate_url_host(url)


def is_url(data: object) -> bool:
    """
    Check if a string appears to be a URL.

    Args:
        data: The string to check

    Returns:
        True if the string appears to be a URL, False otherwise
    """
    if not isinstance(data, str):
        return False
    try:
        parsed = urlparse(data)
        return parsed.scheme.lower() in ALLOWED_SCHEMES and bool(parsed.netloc)
    except (ValueError, TypeError):
        return False


def safe_fetch(url: str, timeout: int = DEFAULT_TIMEOUT, max_size: int = MAX_RESPONSE_SIZE) -> Response:
    """
    Safely fetch content from a URL with validation, timeout, and size limits.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds (default: 30)
        max_size: Maximum response size in bytes (default: 50MB)

    Returns:
        Response object from requests library

    Raises:
        URLValidationError: If the URL fails validation
        SSRFError: If the URL points to a blocked address
        ResponseTooLargeError: If the response exceeds the size limit
        requests.RequestException: If the request fails

    Redirects are followed manually, up to MAX_REDIRECTS, and each target is
    validated before it is requested.
    """
    if requests is None:
        raise ImportError("The 'requests' library is required for URL fetching. "
                          "Install it with: pip install requests")

    # Validate URL before fetching
    validate_url(url)

    # Follow redirects by hand so every hop is validated. requests would
    # follow them internally, and only the URL passed in was ever checked --
    # a public URL answering 302 -> http://169.254.169.254/ would otherwise
    # reach the metadata service.
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        logging.info(f"Fetching URL: {current_url}")
        response = requests.get(current_url, timeout=timeout, stream=True,
                                allow_redirects=False)
        # is_redirect is False without a Location header, leaving nothing to
        # follow; that response is the answer.
        if not response.is_redirect:
            break
        response.close()
        current_url = urljoin(current_url, response.headers['location'])
        validate_url(current_url)
    else:
        raise URLValidationError(
            f"Exceeded {MAX_REDIRECTS} redirects starting from {url}")

    response.raise_for_status()

    # Check content length if available
    content_length = response.headers.get('content-length')
    if content_length and int(content_length) > max_size:
        raise ResponseTooLargeError(
            f"Response size ({int(content_length)} bytes) exceeds "
            f"maximum allowed size ({max_size} bytes)"
        )

    # Read content with size limit
    content = b''
    for chunk in response.iter_content(chunk_size=8192):
        content += chunk
        if len(content) > max_size:
            raise ResponseTooLargeError(
                f"Response exceeded maximum allowed size ({max_size} bytes)"
            )

    # Replace the content so it can be accessed normally
    response._content = content
    return response


def safe_fetch_text(url: str, timeout: int = DEFAULT_TIMEOUT, max_size: int = MAX_RESPONSE_SIZE) -> str:
    """
    Safely fetch text content from a URL.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        max_size: Maximum response size in bytes

    Returns:
        Text content of the response

    Raises:
        Same exceptions as safe_fetch()
    """
    response = safe_fetch(url, timeout=timeout, max_size=max_size)
    return response.text


def safe_fetch_content(url: str, timeout: int = DEFAULT_TIMEOUT, max_size: int = MAX_RESPONSE_SIZE) -> bytes:
    """
    Safely fetch binary content from a URL.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        max_size: Maximum response size in bytes

    Returns:
        Binary content of the response

    Raises:
        Same exceptions as safe_fetch()
    """
    response = safe_fetch(url, timeout=timeout, max_size=max_size)
    return response.content
