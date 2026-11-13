FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY site_exporter ./site_exporter

RUN useradd --create-home --uid 10001 exporter
USER exporter

EXPOSE 9877
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9877/metrics', timeout=2)"

ENTRYPOINT ["python", "-m", "site_exporter", "--listen", "0.0.0.0", "--port", "9877"]
CMD ["--config", "/etc/site-exporter/targets.yml"]
