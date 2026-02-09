from abc import ABC, abstractmethod
from dataclasses import dataclass

Labels = dict[str, str]


@dataclass
class MetricSample:
    labels: dict[str, str]
    value: float


class MetricsEngine(ABC):
    @abstractmethod
    def inc(self, name: str, labels: Labels, value: float = 1) -> None: ...

    @abstractmethod
    def set(self, name: str, labels: Labels, value: float) -> None: ...

    @abstractmethod
    def observe(self, name: str, labels: Labels, value: float) -> None: ...

    @abstractmethod
    def start_server(self, port: int) -> None: ...

    @abstractmethod
    async def query(self, promql: str) -> list[MetricSample]: ...


class ContextMetrics:
    def __init__(self, engine: MetricsEngine, labels: Labels):
        self._engine = engine
        self._labels = labels

    def inc(self, name: str, labels: Labels | None = None, value: float = 1) -> None:
        self._engine.inc(name, {**self._labels, **(labels or {})}, value)

    def set(self, name: str, value: float, labels: Labels | None = None) -> None:
        self._engine.set(name, {**self._labels, **(labels or {})}, value)

    def observe(self, name: str, value: float, labels: Labels | None = None) -> None:
        self._engine.observe(name, {**self._labels, **(labels or {})}, value)

    async def query(self, promql: str) -> list[MetricSample]:
        return await self._engine.query(promql)

