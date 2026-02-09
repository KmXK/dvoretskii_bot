from steward.metrics.base import Labels, MetricSample, MetricsEngine


class NoopMetricsEngine(MetricsEngine):
    def inc(self, name: str, labels: Labels, value: float = 1) -> None:
        pass

    def set(self, name: str, labels: Labels, value: float) -> None:
        pass

    def observe(self, name: str, labels: Labels, value: float) -> None:
        pass

    def start_server(self, port: int) -> None:
        pass

    async def query(self, promql: str) -> list[MetricSample]:
        return []

