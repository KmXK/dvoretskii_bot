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

