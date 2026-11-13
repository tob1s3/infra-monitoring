"""Метрики Prometheus и цикл проверок."""

import asyncio
import logging
import time

import httpx
from prometheus_client import CollectorRegistry, Counter, Gauge

from site_exporter.checks import check_http, tls_days_left
from site_exporter.config import Config, Target

log = logging.getLogger(__name__)
LABELS = ["name", "url"]


class SiteMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.up = Gauge(
            "site_up", "1 — сайт ответил ожидаемым кодом, 0 — нет", LABELS, registry=registry
        )
        self.status_code = Gauge(
            "site_http_status_code",
            "Код ответа HTTP (0 — ответа не было)",
            LABELS,
            registry=registry,
        )
        self.response_seconds = Gauge(
            "site_response_seconds", "Время ответа в секундах", LABELS, registry=registry
        )
        self.tls_days = Gauge(
            "site_tls_cert_expiry_days",
            "Дней до окончания TLS-сертификата",
            LABELS,
            registry=registry,
        )
        self.last_check = Gauge(
            "site_last_check_timestamp_seconds",
            "Время последней проверки (unix)",
            LABELS,
            registry=registry,
        )
        self.checks = Counter(
            "site_checks", "Число проверок по результату", [*LABELS, "result"], registry=registry
        )
        self._tls_known: set[tuple[str, str]] = set()

    async def check_one(self, client: httpx.AsyncClient, target: Target) -> None:
        labels = {"name": target.name, "url": str(target.url)}
        result = await check_http(client, target)

        self.up.labels(**labels).set(1 if result.up else 0)
        self.status_code.labels(**labels).set(result.status_code or 0)
        self.response_seconds.labels(**labels).set(result.response_seconds)
        self.last_check.labels(**labels).set(time.time())
        self.checks.labels(**labels, result="ok" if result.up else "fail").inc()

        if target.is_https:
            days = await tls_days_left(target)
            key = (target.name, str(target.url))
            if days is not None:
                self.tls_days.labels(**labels).set(days)
                self._tls_known.add(key)
            elif key in self._tls_known:
                # Проверить не удалось — убираем значение, чтобы не висела устаревшая цифра
                self.tls_days.remove(*key)
                self._tls_known.discard(key)

        if not result.up:
            log.warning(
                "%s недоступен: код=%s ошибка=%s", target.name, result.status_code, result.error
            )

    async def check_all(self, config: Config) -> None:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await asyncio.gather(*(self.check_one(client, t) for t in config.targets))
