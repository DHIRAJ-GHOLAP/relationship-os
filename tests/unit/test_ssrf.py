"""Unit tests for SSRF (Server-Side Request Forgery) protection."""

import pytest
from packages.shared.src.ssrf import validate_destination_url


def test_ssrf_rejects_disallowed_schemes():
    safe, reason = validate_destination_url("ftp://example.com/webhook")
    assert safe is False
    assert "Unsupported scheme" in reason

    safe, reason = validate_destination_url("file:///etc/passwd")
    assert safe is False


def test_ssrf_rejects_loopback():
    safe, _ = validate_destination_url("http://127.0.0.1:8080/webhook")
    assert safe is False

    safe, _ = validate_destination_url("http://localhost:8080/webhook")
    assert safe is False


def test_ssrf_rejects_cloud_metadata():
    safe, _ = validate_destination_url("http://169.254.169.254/latest/meta-data/")
    assert safe is False


def test_ssrf_rejects_private_rfcs():
    safe, _ = validate_destination_url("http://10.0.0.5:8000/webhook")
    assert safe is False

    safe, _ = validate_destination_url("http://192.168.1.100/webhook")
    assert safe is False

    safe, _ = validate_destination_url("http://172.20.0.1/webhook")
    assert safe is False


def test_ssrf_allows_localhost_when_explicitly_permitted():
    safe, _ = validate_destination_url("http://127.0.0.1:8080/webhook", allow_localhost=True)
    assert safe is True

    safe, _ = validate_destination_url("http://localhost:8080/webhook", allow_localhost=True)
    assert safe is True


def test_ssrf_accepts_valid_public_domain():
    safe, _ = validate_destination_url("https://httpbin.org/post")
    assert safe is True
