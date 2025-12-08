from prometheus_client import Counter, Gauge, Histogram, REGISTRY, start_http_server

from steward.metrics.base import Labels, MetricsEngine

class PrometheusMetricsEngine(MetricsEngine):
    def __init__(self):
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

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

