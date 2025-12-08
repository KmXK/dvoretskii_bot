from steward.metrics.base import Labels, MetricsEngine

class NoopMetricsEngine(MetricsEngine):
    def inc(self, name: str, labels: Labels, value: float = 1) -> None:
        pass

    def set(self, name: str, labels: Labels, value: float) -> None:
        pass

    def observe(self, name: str, labels: Labels, value: float) -> None:
        pass

    def start_server(self, port: int) -> None:
        pass

