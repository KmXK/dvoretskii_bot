import inspect

from steward.data.repository import Repository
from steward.handlers.handler import Handler


def init_handlers(
    repository: Repository,
    handlers: list[Handler | type[Handler]],
) -> list[Handler]:
    def init_handler(handler: Handler | type[Handler]):
        if not isinstance(handler, type):
            return handler

        sig = inspect.signature(handler.__init__)
        params = sig.parameters
        if params.get("repository") is None:
            return handler()

        return handler(repository)  # type: ignore

    return [init_handler(handler) for handler in handlers]
