"""Запуск экспортера: python -m site_exporter --config targets.yml --port 9877"""

import argparse
import asyncio
import logging
import signal

from prometheus_client import REGISTRY, start_http_server

from site_exporter.config import load_config
from site_exporter.metrics import SiteMetrics

log = logging.getLogger("site_exporter")


async def run(config_path: str, port: int, listen: str) -> None:
    config = load_config(config_path)
    metrics = SiteMetrics(REGISTRY)
    start_http_server(port, addr=listen)
    log.info(
        "Экспортер слушает %s:%d, целей: %d, интервал %d с",
        listen,
        port,
        len(config.targets),
        config.interval_seconds,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)  # корректная остановка по docker stop

    while not stop.is_set():
        await metrics.check_all(config)
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.interval_seconds)
        except TimeoutError:
            pass
    log.info("Остановлен")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prometheus-экспортер доступности сайтов")
    parser.add_argument("--config", default="targets.yml")
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--listen", default="127.0.0.1", help="в контейнере: --listen 0.0.0.0")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # не логировать каждый запрос
    asyncio.run(run(args.config, args.port, args.listen))


if __name__ == "__main__":
    main()
