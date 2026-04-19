import re

_AMOUNT_RE = re.compile(r"[\d\s]+[,.]?\d*")


def parse_amount(s: str) -> float:
    s = s.strip().replace("\u00a0", " ").replace(",", ".")
    m = _AMOUNT_RE.search(s)
    if not m:
        raise ValueError(f"Неверная сумма: {s}")
    raw = m.group(0).replace(" ", "").strip()
    value = float(raw)
    if "-" in s[: m.start()]:
        value = -value
    return value


def md_escape(s: str) -> str:
    for c in "_*`[":
        s = s.replace(c, "\\" + c)
    return s


def escape_md_block(text: str) -> str:
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()
