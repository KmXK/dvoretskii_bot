import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Pattern, Union


_TYPE_CONVERTERS: dict[str, Callable[[str], Any]] = {
    "int": int,
    "float": float,
    "str": lambda s: s,
    "rest": lambda s: s,
}

_PARAM_RE = re.compile(r"^<(?P<name>[A-Za-z_]\w*):(?P<spec>[^>]+)>$")
_LITERAL_RE = re.compile(r"^[\w\-]+$", re.UNICODE)


@dataclass
class _Literal:
    value: str


@dataclass
class _Param:
    name: str
    type_name: str
    converter: Callable[[str], Any]
    rest: bool = False
    options: tuple[str, ...] | None = None


type _Token = Union[_Literal, _Param]


@dataclass
class _PatternSpec:
    tokens: tuple[_Token, ...]
    raw: str

    @property
    def has_rest(self) -> bool:
        return any(isinstance(t, _Param) and t.rest for t in self.tokens)

    @property
    def literal_count(self) -> int:
        return sum(1 for t in self.tokens if isinstance(t, _Literal))

    @property
    def typed_count(self) -> int:
        return sum(1 for t in self.tokens if isinstance(t, _Param) and not t.rest)

    @property
    def specificity(self) -> tuple[int, int, int]:
        return (self.literal_count, self.typed_count, -1 if self.has_rest else 0)


@dataclass
class Subcommand:
    spec: _PatternSpec | None
    regex: Pattern[str] | None
    func: Callable[..., Awaitable[Any]]
    description: str = ""
    admin: bool = False
    catchall: bool = False
    then_wizard: str | None = None
    raw: str = ""

    def matches(self, args: str) -> tuple[bool, dict[str, Any]]:
        if self.regex is not None:
            m = self.regex.fullmatch(args.strip())
            if m is None:
                return False, {}
            return True, {k: v for k, v in m.groupdict().items() if v is not None}
        assert self.spec is not None
        return _match_spec(self.spec, args)

    @property
    def specificity_key(self) -> tuple[int, int, int, int]:
        if self.regex is not None:
            return (99, 0, 0, 0)
        s = self.spec.specificity
        catchall = -10 if self.catchall else 0
        return (s[0], s[1], s[2], catchall)


def _match_spec(spec: _PatternSpec, raw: str) -> tuple[bool, dict[str, Any]]:
    raw = raw.strip()
    tokens = spec.tokens
    if not tokens:
        return (raw == ""), {}

    words = raw.split()
    parsed: dict[str, Any] = {}
    word_idx = 0

    for i, tok in enumerate(tokens):
        if isinstance(tok, _Literal):
            if word_idx >= len(words) or words[word_idx] != tok.value:
                return False, {}
            word_idx += 1
        else:
            if tok.rest:
                rest_words = words[word_idx:]
                rest_str = " ".join(rest_words)
                if rest_str == "":
                    return False, {}
                if tok.options is not None and rest_str not in tok.options:
                    return False, {}
                parsed[tok.name] = tok.converter(rest_str)
                word_idx = len(words)
            else:
                if word_idx >= len(words):
                    return False, {}
                value = words[word_idx]
                try:
                    parsed[tok.name] = tok.converter(value)
                except (ValueError, TypeError):
                    return False, {}
                if tok.options is not None and value not in tok.options:
                    return False, {}
                word_idx += 1

    if word_idx != len(words):
        return False, {}
    return True, parsed


def _parse_param_token(token: str) -> _Param:
    m = _PARAM_RE.match(token)
    if not m:
        raise ValueError(f"Invalid subcommand param: {token!r}")
    name = m.group("name")
    spec = m.group("spec").strip()
    if spec.startswith("literal[") and spec.endswith("]"):
        inner = spec[len("literal[") : -1]
        options = tuple(opt.strip() for opt in inner.split("|") if opt.strip())
        if not options:
            raise ValueError(f"Empty literal options in {token!r}")
        return _Param(
            name=name,
            type_name="literal",
            converter=lambda s: s,
            rest=False,
            options=options,
        )
    if spec not in _TYPE_CONVERTERS:
        raise ValueError(f"Unknown subcommand type {spec!r} in {token!r}")
    return _Param(
        name=name,
        type_name=spec,
        converter=_TYPE_CONVERTERS[spec],
        rest=(spec == "rest"),
    )


def parse_pattern(pattern: str) -> _PatternSpec:
    pattern = (pattern or "").strip()
    if pattern == "":
        return _PatternSpec(tokens=(), raw=pattern)
    raw_tokens = pattern.split()
    tokens: list[_Token] = []
    rest_seen = False
    for raw in raw_tokens:
        is_param = raw.startswith("<") and raw.endswith(">")
        if is_param:
            if rest_seen:
                raise ValueError(f"Token after :rest is not allowed: {pattern!r}")
            param = _parse_param_token(raw)
            if param.rest:
                rest_seen = True
            tokens.append(param)
        else:
            if rest_seen:
                raise ValueError(f"Literal {raw!r} after :rest in {pattern!r}")
            if not _LITERAL_RE.match(raw):
                raise ValueError(f"Invalid literal token {raw!r} in {pattern!r}")
            tokens.append(_Literal(value=raw))
    return _PatternSpec(tokens=tuple(tokens), raw=pattern)


def subcommand(
    pattern: "str | Pattern[str]" = "",
    *,
    description: str = "",
    admin: bool = False,
    catchall: bool = False,
    then_wizard: str | None = None,
):
    def decorator(func):
        existing = getattr(func, "_feature_subcommands", None)
        if existing is None:
            existing = []
            setattr(func, "_feature_subcommands", existing)

        if isinstance(pattern, re.Pattern):
            sub = Subcommand(
                spec=None,
                regex=pattern,
                func=func,
                description=description,
                admin=admin,
                catchall=catchall,
                then_wizard=then_wizard,
                raw=pattern.pattern,
            )
        else:
            spec = parse_pattern(pattern)
            sub = Subcommand(
                spec=spec,
                regex=None,
                func=func,
                description=description,
                admin=admin,
                catchall=catchall,
                then_wizard=then_wizard,
                raw=pattern,
            )

        existing.append(sub)
        setattr(func, "_feature_marker", "subcommand")
        return func

    return decorator


def sort_subcommands(subs: list[Subcommand]) -> list[Subcommand]:
    return sorted(subs, key=lambda s: s.specificity_key, reverse=True)
