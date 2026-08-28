#!/usr/bin/env python
"""
Tests for ddlgenerator.url_utils module.

Tests URL validation, SSRF prevention, and safe fetching functionality.
Migrated from test_ddlgenerator.py as part of Phase 5 test consolidation.
"""

import socket
from unittest.mock import patch

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from ddlgenerator import url_utils

PUBLIC_IP = '93.184.216.34'


def addrinfo(*ips):
    """Shape a getaddrinfo() return value for the given addresses."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 80)) for ip in ips]


@pytest.fixture(autouse=True)
def stub_dns():
    """
    Keep DNS out of these unit tests.

    validate_url_host resolves hostnames, so without this every test using
    example.com would depend on the network. Tests that care about what a
    name resolves to patch socket.getaddrinfo themselves; a decorator patch
    activates after fixture setup, so it wins over this one.
    """
    with patch('socket.getaddrinfo', return_value=addrinfo(PUBLIC_IP)):
        yield


class FakeResponse:
    """Stand-in for requests.Response covering what safe_fetch touches."""

    def __init__(self, status_code=200, headers=None, chunks=(b'data',)):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
        self.chunks = chunks
        self.closed = False
        self._content = None

    @property
    def is_redirect(self):
        return 'location' in self.headers and self.status_code in (
            301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size=8192):
        yield from self.chunks

    def close(self):
        self.closed = True

    @property
    def text(self):
        return self._content.decode()

    @property
    def content(self):
        return self._content


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------
class TestURLValidation:
    """Tests for url_utils URL validation (P1-2)"""

    def test_valid_http_url(self):
        """Valid HTTP URLs should pass validation"""
        # Should not raise
        url_utils.validate_url('http://example.com/data.yaml')

    def test_valid_https_url(self):
        """Valid HTTPS URLs should pass validation"""
        # Should not raise
        url_utils.validate_url('https://example.com/data.json')

    def test_invalid_scheme_ftp(self):
        """FTP URLs should be rejected"""
        with pytest.raises(url_utils.URLValidationError):
            url_utils.validate_url('ftp://example.com/file')

    def test_invalid_scheme_file(self):
        """file:// URLs should be rejected"""
        with pytest.raises(url_utils.URLValidationError):
            url_utils.validate_url('file:///etc/passwd')

    def test_invalid_scheme_javascript(self):
        """javascript: URLs should be rejected"""
        with pytest.raises(url_utils.URLValidationError):
            url_utils.validate_url('javascript:alert(1)')

    def test_no_hostname(self):
        """URL with no hostname should be rejected"""
        with pytest.raises(url_utils.URLValidationError):
            url_utils.validate_url('http://')


# ---------------------------------------------------------------------------
# SSRF Prevention
# ---------------------------------------------------------------------------
class TestSSRFPrevention:
    """Tests for SSRF (Server-Side Request Forgery) prevention"""

    def test_ssrf_localhost(self):
        """localhost should be blocked for SSRF prevention"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://localhost/admin')

    def test_ssrf_loopback_127(self):
        """127.x.x.x should be blocked for SSRF prevention"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://127.0.0.1/admin')

    def test_ssrf_private_10(self):
        """10.x.x.x should be blocked for SSRF prevention"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://10.0.0.1/internal')

    def test_ssrf_private_192_168(self):
        """192.168.x.x should be blocked for SSRF prevention"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://192.168.1.1/router')

    def test_ssrf_private_172_16(self):
        """172.16-31.x.x should be blocked for SSRF prevention"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://172.16.0.1/internal')

    def test_ssrf_zero_ip(self):
        """0.0.0.0 should be blocked"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://0.0.0.0/admin')

    def test_ssrf_link_local(self):
        """169.254.x.x (link-local) should be blocked"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://169.254.169.254/metadata')

    def test_ssrf_ipv6_loopback(self):
        """IPv6 loopback ::1 should be blocked"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://[::1]/admin')

    def test_ssrf_172_31(self):
        """172.31.x.x (upper end of 172.16/12 range) should be blocked"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('http://172.31.255.255/internal')


# ---------------------------------------------------------------------------
# is_url helper
# ---------------------------------------------------------------------------
class TestIsURL:
    """Tests for is_url helper function"""

    def test_is_url_with_http(self):
        """is_url should return True for HTTP URLs"""
        assert url_utils.is_url('http://example.com') is True

    def test_is_url_with_https(self):
        """is_url should return True for HTTPS URLs"""
        assert url_utils.is_url('https://example.com') is True

    def test_is_url_with_file_path(self):
        """is_url should return False for file paths"""
        assert url_utils.is_url('/path/to/file.yaml') is False

    def test_is_url_with_non_string(self):
        """is_url should return False for non-string inputs"""
        assert url_utils.is_url(['list']) is False
        assert url_utils.is_url({'dict': 'value'}) is False
        assert url_utils.is_url(None) is False


# ---------------------------------------------------------------------------
# safe_fetch
# ---------------------------------------------------------------------------
class TestSafeFetch:
    """Tests for safe_fetch function"""

    def test_safe_fetch_validates_url(self):
        """safe_fetch should reject private IPs before making a request"""
        with pytest.raises(url_utils.SSRFError):
            url_utils.safe_fetch('http://192.168.1.1/secret')

    def test_safe_fetch_rejects_bad_scheme(self):
        """safe_fetch should reject non-http(s) schemes"""
        with pytest.raises(url_utils.URLValidationError):
            url_utils.safe_fetch('ftp://example.com/file')


# ---------------------------------------------------------------------------
# is_private_ip helper
# ---------------------------------------------------------------------------
class TestIsPrivateIP:
    """Tests for is_private_ip helper function"""

    def test_is_private_ip_public(self):
        """Public IPs should not be flagged as private"""
        assert url_utils.is_private_ip('8.8.8.8') is False
        assert url_utils.is_private_ip('93.184.216.34') is False

    def test_is_private_ip_invalid(self):
        """Invalid IP strings should return False"""
        assert url_utils.is_private_ip('not-an-ip') is False
        assert url_utils.is_private_ip('') is False


# ---------------------------------------------------------------------------
# DNS-based SSRF prevention
# ---------------------------------------------------------------------------
class TestHostnameResolution:
    """
    A hostname that is not literally a private IP can still point at one.
    Blocking only literal addresses leaves the obvious bypass open: register
    a public name, point it at 127.0.0.1 or the cloud metadata address.
    """

    @patch('socket.getaddrinfo')
    def test_hostname_resolving_to_loopback_is_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = addrinfo('127.0.0.1')
        with pytest.raises(url_utils.SSRFError, match='127.0.0.1'):
            url_utils.validate_url('http://localtest.example.com/data.json')

    @patch('socket.getaddrinfo')
    def test_hostname_resolving_to_metadata_endpoint_is_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = addrinfo('169.254.169.254')
        with pytest.raises(url_utils.SSRFError):
            url_utils.validate_url('https://metadata.example.com/latest/meta-data/')

    @patch('socket.getaddrinfo')
    def test_blocks_when_any_resolved_address_is_private(self, mock_getaddrinfo):
        """Round-robin DNS can mix public and internal addresses."""
        mock_getaddrinfo.return_value = addrinfo(PUBLIC_IP, '10.0.0.5')
        with pytest.raises(url_utils.SSRFError, match='10.0.0.5'):
            url_utils.validate_url('https://mixed.example.com/data.json')

    @patch('socket.getaddrinfo')
    def test_public_hostname_passes(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = addrinfo(PUBLIC_IP)
        url_utils.validate_url('https://example.com/data.json')

    @patch('socket.getaddrinfo')
    def test_unresolvable_hostname_is_rejected(self, mock_getaddrinfo):
        """Fail closed: an unverifiable host is not a safe host."""
        mock_getaddrinfo.side_effect = socket.gaierror('Name or service not known')
        with pytest.raises(url_utils.URLValidationError):
            url_utils.validate_url('https://nx.example.com/data.json')

    @patch('socket.getaddrinfo')
    def test_literal_public_ip_skips_resolution(self, mock_getaddrinfo):
        """A literal address was already checked; no lookup needed."""
        url_utils.validate_url(f'https://{PUBLIC_IP}/data.json')
        mock_getaddrinfo.assert_not_called()


# ---------------------------------------------------------------------------
# Redirect validation
# ---------------------------------------------------------------------------
class TestRedirectValidation:
    """
    Validating only the URL handed in leaves redirects unchecked: a public
    URL that answers 302 -> http://169.254.169.254/ reaches the metadata
    service, because the guard never sees the second request.
    """

    @patch('ddlgenerator.url_utils.requests')
    def test_redirect_to_private_ip_is_blocked(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(
            302, {'location': 'http://169.254.169.254/latest/meta-data/'})
        with pytest.raises(url_utils.SSRFError):
            url_utils.safe_fetch('https://example.com/data.json')

    @patch('ddlgenerator.url_utils.requests')
    def test_redirect_to_public_url_is_followed(self, mock_requests):
        mock_requests.get.side_effect = [
            FakeResponse(302, {'location': 'https://elsewhere.example.com/real.json'}),
            FakeResponse(200, chunks=(b'{"a": 1}',)),
        ]
        response = url_utils.safe_fetch('https://example.com/data.json')
        assert response.content == b'{"a": 1}'
        assert mock_requests.get.call_count == 2

    @patch('ddlgenerator.url_utils.requests')
    def test_relative_redirect_is_resolved_against_current_url(self, mock_requests):
        mock_requests.get.side_effect = [
            FakeResponse(302, {'location': '/moved/data.json'}),
            FakeResponse(200, chunks=(b'ok',)),
        ]
        url_utils.safe_fetch('https://example.com/data.json')
        assert mock_requests.get.call_args_list[1][0][0] == (
            'https://example.com/moved/data.json')

    @patch('ddlgenerator.url_utils.requests')
    def test_redirect_chain_is_capped(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(
            302, {'location': 'https://example.com/loop'})
        with pytest.raises(url_utils.URLValidationError, match='redirect'):
            url_utils.safe_fetch('https://example.com/data.json')

    @patch('ddlgenerator.url_utils.requests')
    def test_requests_is_told_not_to_follow_redirects(self, mock_requests):
        """
        Per-hop validation only works if requests hands the redirect back
        rather than following it itself. Leave allow_redirects on and the
        loop never sees a hop, making every check inside it dead code --
        with no other test able to tell the difference.
        """
        mock_requests.get.return_value = FakeResponse(200, chunks=(b'ok',))
        url_utils.safe_fetch('https://example.com/data.json')
        assert mock_requests.get.call_args.kwargs['allow_redirects'] is False

    @patch('ddlgenerator.url_utils.requests')
    def test_redirect_without_location_is_returned_as_is(self, mock_requests):
        """A 302 with no Location cannot be followed; treat it as the answer."""
        mock_requests.get.return_value = FakeResponse(302, chunks=(b'body',))
        response = url_utils.safe_fetch('https://example.com/data.json')
        assert response.content == b'body'


# ---------------------------------------------------------------------------
# Size limits and fetch wrappers
# ---------------------------------------------------------------------------
class TestFetchLimits:
    """
    The size caps are the module's DoS guard, and nothing exercised them.
    These pin behavior that already worked, so a later edit cannot quietly
    drop a limit.
    """

    @patch('ddlgenerator.url_utils.requests')
    def test_declared_content_length_over_limit_is_rejected(self, mock_requests):
        """A content-length header over the cap is refused before the body."""
        mock_requests.get.return_value = FakeResponse(
            200, {'content-length': '999999'})
        with pytest.raises(url_utils.ResponseTooLargeError, match='exceeds'):
            url_utils.safe_fetch('https://example.com/big.json', max_size=100)

    @patch('ddlgenerator.url_utils.requests')
    def test_streamed_body_over_limit_is_rejected(self, mock_requests):
        """
        content-length is attacker-controlled and optional, so the streaming
        cap is the guard that actually holds.
        """
        mock_requests.get.return_value = FakeResponse(
            200, chunks=(b'x' * 60, b'x' * 60))
        with pytest.raises(url_utils.ResponseTooLargeError, match='exceeded'):
            url_utils.safe_fetch('https://example.com/big.json', max_size=100)

    @patch('ddlgenerator.url_utils.requests')
    def test_body_within_limit_is_returned_whole(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(
            200, chunks=(b'{"a": ', b'1}'))
        response = url_utils.safe_fetch('https://example.com/data.json',
                                        max_size=100)
        assert response.content == b'{"a": 1}'

    @patch('ddlgenerator.url_utils.requests')
    def test_http_error_status_propagates(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(404)
        with pytest.raises(requests.HTTPError):
            url_utils.safe_fetch('https://example.com/missing.json')

    @patch('ddlgenerator.url_utils.requests')
    def test_safe_fetch_text_returns_decoded_body(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(200, chunks=(b'hello',))
        assert url_utils.safe_fetch_text('https://example.com/a.txt') == 'hello'

    @patch('ddlgenerator.url_utils.requests')
    def test_safe_fetch_content_returns_bytes(self, mock_requests):
        mock_requests.get.return_value = FakeResponse(200, chunks=(b'\x00\x01',))
        assert url_utils.safe_fetch_content(
            'https://example.com/a.bin') == b'\x00\x01'

    @patch('ddlgenerator.url_utils.requests', None)
    def test_missing_requests_library_is_reported(self):
        with pytest.raises(ImportError, match='requests'):
            url_utils.safe_fetch('https://example.com/data.json')

    def test_is_url_handles_unparseable_input(self):
        """urlparse raises on a malformed IPv6 literal; is_url must not."""
        assert url_utils.is_url('http://[::1') is False
