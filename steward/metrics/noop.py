from steward.metrics.base import (
    Labels,
    MetricQueryError,
    MetricSample,
    MetricSeries,
    MetricsEngine,
)


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

    async def query_range(
        self,
        promql: str,
        start: float,
        end: float,
        step: float,
        *,
        strict: bool = False,
    ) -> list[MetricSeries]:
        if strict:
            raise MetricQueryError("Metrics query requested while metrics engine is disabled")
        return []
