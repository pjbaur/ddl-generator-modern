#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
URL validation and safe fetching utilities for SSRF prevention.

This module provides URL validation to prevent Server-Side Request Forgery (SSRF)
attacks and adds request hardening (timeouts, size limits) when fetching data
from URLs.
"""

import ipaddress
import logging
from urllib.parse import urlparse

# Try to import requests, but don't fail if not available
try:
    import requests
except ImportError:
    requests = None

# Constants for URL validation
ALLOWED_SCHEMES = {'http', 'https'}
MAX_RESPONSE_SIZE = 50 * 1024 * 1024  # 50 MB
DEFAULT_TIMEOUT = 30  # seconds

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


def is_private_ip(ip_str):
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


def validate_url_scheme(url):
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


def validate_url_host(url):
    """
    Validate that the URL host is not a private/blocked IP address.

    This prevents SSRF attacks by blocking requests to internal network
    resources.

    Args:
        url: The URL string to validate

    Raises:
        SSRFError: If the host resolves to a private IP address
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


def validate_url(url):
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


def is_url(data):
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
    except Exception:
        return False


def safe_fetch(url, timeout=DEFAULT_TIMEOUT, max_size=MAX_RESPONSE_SIZE):
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
    """
    if requests is None:
        raise ImportError("The 'requests' library is required for URL fetching. "
                         "Install it with: pip install requests")

    # Validate URL before fetching
    validate_url(url)

    logging.info(f"Fetching URL: {url}")

    # Make request with timeout and streaming
    response = requests.get(url, timeout=timeout, stream=True)
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


def safe_fetch_text(url, timeout=DEFAULT_TIMEOUT, max_size=MAX_RESPONSE_SIZE):
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


def safe_fetch_content(url, timeout=DEFAULT_TIMEOUT, max_size=MAX_RESPONSE_SIZE):
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
