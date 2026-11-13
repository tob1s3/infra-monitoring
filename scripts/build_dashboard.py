"""Генерирует grafana/dashboards/overview.json.

JSON дашборда Grafana большой и плохо читается в ревью, поэтому он собирается из
этого описания: здесь видно, какие панели есть и какие запросы PromQL за ними стоят.

    python scripts/build_dashboard.py
"""

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
OUT = Path(__file__).resolve().parent.parent / "grafana" / "dashboards" / "overview.json"

_next_id = 0
# Не считаем loopback и виртуальные интерфейсы Docker
NET_FILTER = 'device!~"lo|veth.*|br-.*|docker.*"'


def panel(kind, title, exprs, x, y, w, h, unit=None, legend="{{name}}", **extra):
    global _next_id
    _next_id += 1
    targets = [
        {"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": legend}
        for i, e in enumerate(exprs if isinstance(exprs, list) else [exprs])
    ]
    p = {
        "id": _next_id,
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    for key, value in extra.items():
        if key == "defaults":
            p["fieldConfig"]["defaults"].update(value)
        else:
            p["options"][key] = value
    return p


def row(title, y):
    global _next_id
    _next_id += 1
    return {
        "id": _next_id,
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


def thresholds(*steps):
    return {
        "thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}
    }


UP_MAPPING = {
    "mappings": [
        {
            "type": "value",
            "options": {
                "0": {"text": "НЕДОСТУПЕН", "color": "red"},
                "1": {"text": "OK", "color": "green"},
            },
        }
    ],
    **thresholds((None, "red"), (1, "green")),
}

panels = [
    row("Сайты", 0),
    panel(
        "stat",
        "Состояние",
        "site_up",
        0,
        1,
        8,
        6,
        defaults=UP_MAPPING,
        colorMode="background",
        textMode="value_and_name",
    ),
    panel("timeseries", "Время ответа", "site_response_seconds", 8, 1, 10, 6, unit="s"),
    panel(
        "bargauge",
        "Дней до окончания сертификата",
        "site_tls_cert_expiry_days",
        18,
        1,
        6,
        6,
        unit="d",
        displayMode="basic",
        orientation="horizontal",
        defaults={"min": 0, "max": 90, **thresholds((None, "red"), (3, "orange"), (14, "green"))},
    ),
    panel("state-timeline", "История доступности", "site_up", 0, 7, 24, 5, defaults=UP_MAPPING),
    row("Сервер", 12),
    panel(
        "gauge",
        "CPU",
        '100 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100',
        0,
        13,
        4,
        6,
        unit="percent",
        legend="{{instance}}",
        defaults={"min": 0, "max": 100, **thresholds((None, "green"), (70, "orange"), (85, "red"))},
    ),
    panel(
        "gauge",
        "Память",
        "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
        4,
        13,
        4,
        6,
        unit="percent",
        legend="{{instance}}",
        defaults={"min": 0, "max": 100, **thresholds((None, "green"), (80, "orange"), (90, "red"))},
    ),
    panel(
        "bargauge",
        "Заполнение дисков",
        '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}'
        ' / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}) * 100',
        8,
        13,
        6,
        6,
        unit="percent",
        legend="{{mountpoint}}",
        displayMode="basic",
        orientation="horizontal",
        defaults={"min": 0, "max": 100, **thresholds((None, "green"), (80, "orange"), (90, "red"))},
    ),
    panel(
        "timeseries",
        "Сеть",
        [
            f"sum by (instance) (rate(node_network_{d}_bytes_total{{{NET_FILTER}}}[5m]))"
            for d in ("receive", "transmit")
        ],
        14,
        13,
        10,
        6,
        unit="Bps",
        legend="{{instance}}",
    ),
    row("booking-api", 19),
    panel(
        "timeseries",
        "Запросы в секунду по кодам ответа",
        'sum by (status) (rate(http_requests_total{job="booking-api"}[5m]))',
        0,
        20,
        8,
        7,
        unit="reqps",
        legend="{{status}}",
    ),
    panel(
        "timeseries",
        "Время ответа, 95-й перцентиль",
        "histogram_quantile(0.95, sum by (le, handler) "
        '(rate(http_request_duration_seconds_bucket{job="booking-api"}[5m])))',
        8,
        20,
        8,
        7,
        unit="s",
        legend="{{handler}}",
    ),
    panel(
        "stat",
        "Записи за сутки",
        [
            "sum(increase(booking_bookings_created_total[24h]))",
            "sum(increase(booking_bookings_cancelled_total[24h]))",
            "sum(increase(booking_conflicts_total[24h]))",
        ],
        16,
        20,
        8,
        7,
        legend="",
        textMode="value_and_name",
        colorMode="none",
    ),
]
# Подписи для трёх показателей в «Записи за сутки»
for target, name in zip(panels[-1]["targets"], ["создано", "отменено", "конфликтов"], strict=True):
    target["legendFormat"] = name

dashboard = {
    "uid": "infra-overview",
    "title": "Инфраструктура: сайты, сервер, booking-api",
    "tags": ["infra-monitoring"],
    "timezone": "browser",
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "schemaVersion": 39,
    "editable": False,
    "panels": panels,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Записан {OUT.relative_to(OUT.parents[2])}: {len(panels)} панелей")
