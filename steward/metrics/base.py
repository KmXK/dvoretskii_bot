from abc import ABC, abstractmethod

Labels = dict[str, str]

class MetricsEngine(ABC):
    @abstractmethod
    def inc(self, name: str, labels: Labels, value: float = 1) -> None: ...

    @abstractmethod
    def set(self, name: str, labels: Labels, value: float) -> None: ...

    @abstractmethod
    def observe(self, name: str, labels: Labels, value: float) -> None: ...

    @abstractmethod
    def start_server(self, port: int) -> None: ...

