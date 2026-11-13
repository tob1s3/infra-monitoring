"""Проверки одного сайта: HTTP-ответ и срок действия TLS-сертификата."""

import asyncio
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from site_exporter.config import Target


@dataclass
class CheckResult:
    up: bool
    status_code: int | None  # None — ответа не было вовсе (таймаут, DNS, отказ соединения)
    response_seconds: float
    error: str | None = None


async def check_http(client: httpx.AsyncClient, target: Target) -> CheckResult:
    started = time.perf_counter()
    try:
        response = await client.get(str(target.url), timeout=target.timeout_seconds)
    except httpx.HTTPError as exc:
        return CheckResult(
            up=False,
            status_code=None,
            response_seconds=time.perf_counter() - started,
            error=type(exc).__name__,
        )
    elapsed = time.perf_counter() - started
    return CheckResult(
        up=response.status_code in target.expected_status,
        status_code=response.status_code,
        response_seconds=elapsed,
    )


def days_until(not_after: str, now: datetime) -> float:
    """Сколько дней осталось до даты из поля notAfter сертификата ('Jun  1 12:00:00 2027 GMT')."""
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=UTC)
    return (expires - now).total_seconds() / 86400


async def tls_days_left(target: Target, ssl_context: ssl.SSLContext | None = None) -> float | None:
    """Дни до окончания сертификата или None, если проверить не удалось.

    Сертификат проверяется по-настоящему (цепочка и имя хоста): просроченный или
    чужой сертификат даст None, а алерт сработает на site_up по HTTPS-ошибке.
    """
    parsed = urlparse(str(target.url))
    host, port = parsed.hostname, parsed.port or 443
    context = ssl_context or ssl.create_default_context()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            timeout=target.timeout_seconds,
        )
    except (OSError, TimeoutError, ssl.SSLError):
        return None
    try:
        cert = writer.get_extra_info("peercert")
        if not cert or "notAfter" not in cert:
            return None
        return days_until(cert["notAfter"], datetime.now(UTC))
    finally:
        writer.close()
