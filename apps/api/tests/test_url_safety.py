import pytest

from myfood.domain.url_safety import UnsafeUrlError, ensure_public_http_url


def test_rejects_non_http_schemes():
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("ftp://example.com/recipe")
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("file:///etc/passwd")


def test_rejects_url_without_host():
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("http://")


def test_rejects_loopback_and_private_hosts():
    for host in ("http://localhost/x", "http://127.0.0.1/x", "http://[::1]/x"):
        with pytest.raises(UnsafeUrlError):
            ensure_public_http_url(host)
    for host in (
        "http://10.0.0.1/x",
        "http://172.22.0.5/x",
        "http://192.168.1.1/x",
    ):
        with pytest.raises(UnsafeUrlError):
            ensure_public_http_url(host)


def test_rejects_cloud_metadata_link_local_address():
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("http://169.254.169.254/latest/meta-data/")


def test_rejects_unresolvable_hostname():
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("http://this-domain-should-not-exist-myfood-test.invalid/x")


def test_allows_a_real_public_host():
    # 8.8.8.8 (Google DNS) resuelve siempre igual, sin depender de qué
    # dominios de recetas existan o respondan en el momento del test.
    ensure_public_http_url("http://8.8.8.8/x")
