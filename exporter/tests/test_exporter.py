import asyncio
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from prometheus_client import CollectorRegistry
from pydantic import ValidationError

from site_exporter.checks import check_http, days_until, tls_days_left
from site_exporter.config import Config, Target, load_config
from site_exporter.metrics import SiteMetrics

SITE = Target(name="shop", url="https://shop.example/health")


def client_returning(status: int | None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status is None:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- конфигурация ---------------------------------------------------------------


def test_load_config(tmp_path):
    path = tmp_path / "targets.yml"
    path.write_text(
        "interval_seconds: 15\n"
        "targets:\n"
        "  - name: api\n"
        "    url: http://booking-api:8000/health\n"
        "  - name: site\n"
        "    url: https://example.com\n"
        "    expected_status: [200, 301]\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.interval_seconds == 15
    assert [t.name for t in config.targets] == ["api", "site"]
    assert not config.targets[0].is_https and config.targets[1].is_https


def test_duplicate_names_are_rejected():
    with pytest.raises(ValidationError, match="уникальными"):
        Config(targets=[SITE, SITE])


def test_bad_url_is_rejected():
    with pytest.raises(ValidationError):
        Target(name="x", url="not-a-url")


# --- HTTP-проверка -------------------------------------------------------------


async def test_expected_status_means_up():
    async with client_returning(200) as client:
        result = await check_http(client, SITE)
    assert result.up and result.status_code == 200 and result.error is None


async def test_server_error_means_down():
    async with client_returning(503) as client:
        result = await check_http(client, SITE)
    assert not result.up and result.status_code == 503


async def test_custom_expected_status():
    target = Target(name="redirect", url="https://example.com", expected_status=[301])
    async with client_returning(301) as client:
        assert (await check_http(client, target)).up


async def test_connection_error_means_down_without_status():
    async with client_returning(None) as client:
        result = await check_http(client, SITE)
    assert not result.up and result.status_code is None and result.error == "ConnectError"


# --- TLS-сертификат --------------------------------------------------------------


def test_days_until():
    now = datetime(2027, 5, 22, 12, 0, tzinfo=UTC)
    assert days_until("Jun  1 12:00:00 2027 GMT", now) == pytest.approx(10)


@pytest.fixture
def tls_server(tmp_path):
    """Локальный HTTPS-сервер с самоподписанным сертификатом на 10 дней."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=10))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(cert_path, key_path)
    client_ctx = ssl.create_default_context(cafile=str(cert_path))
    return server_ctx, client_ctx


async def test_tls_days_left_reads_real_certificate(tls_server):
    server_ctx, client_ctx = tls_server

    async def handle(reader, writer):
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        target = Target(name="local", url=f"https://localhost:{port}/")
        days = await tls_days_left(target, ssl_context=client_ctx)
    finally:
        server.close()
        await server.wait_closed()
    assert days == pytest.approx(10, abs=0.01)


async def test_untrusted_certificate_gives_none(tls_server):
    server_ctx, _ = tls_server

    async def handle(reader, writer):
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        # Системный контекст не доверяет самоподписанному сертификату
        target = Target(name="local", url=f"https://localhost:{port}/")
        assert await tls_days_left(target) is None
    finally:
        server.close()
        await server.wait_closed()


async def test_unreachable_host_gives_none():
    target = Target(name="closed", url="https://127.0.0.1:1/", timeout_seconds=1)
    assert await tls_days_left(target) is None


# --- метрики ---------------------------------------------------------------------


async def test_metrics_are_exported():
    registry = CollectorRegistry()
    metrics = SiteMetrics(registry)
    target = Target(name="api", url="http://booking-api:8000/health")
    labels = {"name": "api", "url": "http://booking-api:8000/health"}

    async with client_returning(200) as client:
        await metrics.check_one(client, target)
    assert registry.get_sample_value("site_up", labels) == 1
    assert registry.get_sample_value("site_http_status_code", labels) == 200
    assert registry.get_sample_value("site_checks_total", {**labels, "result": "ok"}) == 1

    async with client_returning(None) as client:
        await metrics.check_one(client, target)
    assert registry.get_sample_value("site_up", labels) == 0
    assert registry.get_sample_value("site_http_status_code", labels) == 0
    assert registry.get_sample_value("site_checks_total", {**labels, "result": "fail"}) == 1
