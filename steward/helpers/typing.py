from typing import Any, Type, TypeGuard, TypeVar

_T = TypeVar("_T")


def is_list_of(val: list[Any], type: Type[_T]) -> TypeGuard[list[_T]]:
    return isinstance(val[0], type)


def is_list_of_safe(val: list[Any], type: Type[_T]) -> TypeGuard[list[_T]]:
    return all(isinstance(element, type) for element in val)
