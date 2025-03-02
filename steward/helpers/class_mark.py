from dataclasses import field
from typing import Any

marks: dict[str, Any] = {}


def try_get_class_by_mark(
    mark: str | dict[str, Any],
):
    if isinstance(mark, str) and mark in marks:
        return marks[mark]
    elif isinstance(mark, dict) and mark.get("__class_mark__") in marks:
        return marks[mark["__class_mark__"]]
    return None


def get_class_by_mark(
    mark: str | dict[str, Any],
):
    if result := try_get_class_by_mark(mark):
        return result
    raise Exception()


# marks type decorator
def class_mark(name: str | None = None):
    def wrapper(cls: Any):
        cls.__class_mark__ = field(init=False)
        cls.__annotations__ = {
            **cls.__annotations__,
            "__class_mark__": str,
        }

        post_init = getattr(cls, "__post_init__", None)

        marks[name or type(cls).__name__] = cls

        def new_post_init(self: Any):
            self.__class_mark__ = name or type(self).__name__

            if post_init:
                post_init()

        cls.__post_init__ = new_post_init
        return cls

    return wrapper
