from steward.handlers.handler import Handler


def init_handlers(
    handlers: list[Handler | type[Handler]],
) -> list[Handler]:
    def init_handler(handler: Handler | type[Handler]):
        if not isinstance(handler, type):
            return handler

        return handler()

    return [init_handler(handler) for handler in handlers]
