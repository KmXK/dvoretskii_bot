from steward.metrics.base import Labels, MetricQueryError, MetricSample, MetricsEngine


class NoopMetricsEngine(MetricsEngine):
    def inc(self, name: str, labels: Labels, value: float = 1) -> None:
        pass

    def set(self, name: str, labels: Labels, value: float) -> None:
        pass

    def observe(self, name: str, labels: Labels, value: float) -> None:
        pass

    def start_server(self, port: int) -> None:
        pass

    async def query(self, promql: str, *, strict: bool = False) -> list[MetricSample]:
        if strict:
            raise MetricQueryError("Metrics query requested while metrics engine is disabled")
        return []
