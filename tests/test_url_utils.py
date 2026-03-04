#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for ddlgenerator.url_utils module.

Tests URL validation, SSRF prevention, and safe fetching functionality.
Migrated from test_ddlgenerator.py as part of Phase 5 test consolidation.
"""

import pytest

from ddlgenerator import url_utils


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
