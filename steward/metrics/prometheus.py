import logging

import aiohttp
from prometheus_client import Counter, Gauge, Histogram, REGISTRY, start_http_server

from steward.metrics.base import Labels, MetricSample, MetricsEngine

logger = logging.getLogger(__name__)


class PrometheusMetricsEngine(MetricsEngine):
    def __init__(self, vm_url: str | None = None):
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._vm_url = vm_url

    def _get_counter(self, name: str, labels: Labels) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, name, list(labels.keys()), registry=REGISTRY)
        return self._counters[name]

    def _get_gauge(self, name: str, labels: Labels) -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, name, list(labels.keys()), registry=REGISTRY)
        return self._gauges[name]

    def _get_histogram(self, name: str, labels: Labels) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, name, list(labels.keys()), registry=REGISTRY)
        return self._histograms[name]

    def inc(self, name: str, labels: Labels, value: float = 1) -> None:
        self._get_counter(name, labels).labels(**labels).inc(value)

    def set(self, name: str, labels: Labels, value: float) -> None:
        self._get_gauge(name, labels).labels(**labels).set(value)

    def observe(self, name: str, labels: Labels, value: float) -> None:
        self._get_histogram(name, labels).labels(**labels).observe(value)

    def start_server(self, port: int) -> None:
        start_http_server(port, registry=REGISTRY)

    async def query(self, promql: str) -> list[MetricSample]:
        if not self._vm_url:
            return []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._vm_url}/api/v1/query",
                    params={"query": promql},
                ) as resp:
                    data = await resp.json()
                    if data.get("status") != "success":
                        logger.warning("VM query failed: %s", data)
                        return []
                    results = []
                    for item in data.get("data", {}).get("result", []):
                        labels = item.get("metric", {})
                        value = float(item.get("value", [0, "0"])[1])
                        results.append(MetricSample(labels=labels, value=value))
                    return results
        except Exception as e:
            logger.exception("VM query error: %s", e)
            return []

