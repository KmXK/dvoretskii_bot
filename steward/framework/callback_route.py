import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from steward.framework.keyboard import Button


_TYPE_CONVERTERS: dict[str, Callable[[str], Any]] = {
    "int": int,
    "float": float,
    "str": lambda s: s,
}

_FIELD_RE = re.compile(r"^<(?P<name>[A-Za-z_]\w*):(?P<spec>[^>]+)>$")
_NAME_RE = re.compile(r"^[A-Za-z_][\w]*(?::[A-Za-z_][\w]*)+$")


@dataclass
class _SchemaField:
    name: str
    type_name: str
    converter: Callable[[str], Any]
    options: tuple[str, ...] | None = None

    def serialize(self, value: Any) -> str:
        if self.options is not None:
            sval = str(value)
            if sval not in self.options:
                raise ValueError(
                    f"Field {self.name!r} value {value!r} not in {self.options}"
                )
            return sval
        if self.type_name == "int":
            return str(int(value))
        if self.type_name == "float":
            return str(float(value))
        sval = str(value)
        if "|" in sval:
            raise ValueError(f"Field {self.name!r} value contains delimiter '|': {sval!r}")
        return sval

    def parse(self, raw: str) -> Any:
        if self.options is not None:
            if raw not in self.options:
                raise ValueError(
                    f"Field {self.name!r} value {raw!r} not in {self.options}"
                )
            return raw
        return self.converter(raw)


@dataclass
class CallbackSchema:
    name: str
    fields: tuple[_SchemaField, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def serialize(self, **values: Any) -> str:
        if set(values.keys()) != set(self.field_names):
            missing = set(self.field_names) - set(values.keys())
            extra = set(values.keys()) - set(self.field_names)
            raise ValueError(
                f"Callback {self.name!r} expects {self.field_names}, "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        parts = [self.name]
        for f in self.fields:
            parts.append(f.serialize(values[f.name]))
        return "|".join(parts)

    def parse(self, raw: str) -> dict[str, Any] | None:
        parts = raw.split("|")
        if not parts or parts[0] != self.name:
            return None
        if len(parts) - 1 != len(self.fields):
            return None
        result: dict[str, Any] = {}
        for f, value in zip(self.fields, parts[1:]):
            try:
                result[f.name] = f.parse(value)
            except (ValueError, TypeError):
                return None
        return result


def parse_schema(name: str, schema: str) -> CallbackSchema:
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid callback name {name!r} (expected feature:action)")
    parts = [s.strip() for s in _split_schema(schema) if s.strip()]
    fields: list[_SchemaField] = []
    for part in parts:
        m = _FIELD_RE.match(part)
        if not m:
            raise ValueError(f"Invalid schema field {part!r} in callback {name!r}")
        fname = m.group("name")
        spec = m.group("spec").strip()
        if spec.startswith("literal[") and spec.endswith("]"):
            inner = spec[len("literal[") : -1]
            options = tuple(opt.strip() for opt in inner.split("|") if opt.strip())
            if not options:
                raise ValueError(f"Empty literal options in {part!r}")
            fields.append(
                _SchemaField(
                    name=fname,
                    type_name="literal",
                    converter=lambda s: s,
                    options=options,
                )
            )
        else:
            if spec not in _TYPE_CONVERTERS:
                raise ValueError(f"Unknown callback field type {spec!r} in {part!r}")
            fields.append(
                _SchemaField(
                    name=fname,
                    type_name=spec,
                    converter=_TYPE_CONVERTERS[spec],
                )
            )
    return CallbackSchema(name=name, fields=tuple(fields))


def _split_schema(schema: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in schema:
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


@dataclass
class CallbackRoute:
    schema: CallbackSchema
    func: Callable[..., Awaitable[Any]]
    only_initiator: bool = False
    initiator_field: str = "initiator"


def on_callback(
    name: str,
    *,
    schema: str = "",
    only_initiator: bool = False,
    initiator_field: str = "initiator",
):
    parsed_schema = parse_schema(name, schema)

    def decorator(func):
        existing = getattr(func, "_feature_callbacks", None)
        if existing is None:
            existing = []
            setattr(func, "_feature_callbacks", existing)
        existing.append(
            CallbackRoute(
                schema=parsed_schema,
                func=func,
                only_initiator=only_initiator,
                initiator_field=initiator_field,
            )
        )
        setattr(func, "_feature_marker", "callback")
        return func

    return decorator


class CallbackFactory:
    def __init__(self, schema: CallbackSchema):
        self._schema = schema

    def __call__(self, **values: Any) -> str:
        return self._schema.serialize(**values)

    def button(self, text: str, **values: Any) -> Button:
        return Button(text=text, callback_data=self.__call__(**values))
