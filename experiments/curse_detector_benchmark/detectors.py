from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass
from typing import Protocol


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+", re.UNICODE)


@dataclass(frozen=True)
class DetectionResult:
    detected: bool
    matched: tuple[str, ...] = ()
    skipped_reason: str | None = None


class CurseDetector(Protocol):
    name: str

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        pass


def _tokens(text: str) -> list[str]:
    if text.startswith("/"):
        return []
    return [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]


def _normalize_words(words: list[str]) -> set[str]:
    return {word.lower().replace("ё", "е") for word in words}


class ExactTokenDetector:
    name = "exact-token-baseline"

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        bad = _normalize_words(bad_words)
        matched = tuple(token for token in _tokens(text) if token in bad)
        return DetectionResult(detected=bool(matched), matched=matched)


class PymorphyDetector:
    name = "pymorphy3-custom-dict"

    def __init__(self) -> None:
        pymorphy3 = importlib.import_module("pymorphy3")
        self._morph = pymorphy3.MorphAnalyzer()

    def _forms(self, word: str) -> set[str]:
        forms = {word}
        for parsed in self._morph.parse(word):
            forms.add(parsed.normal_form.replace("ё", "е"))
        return forms

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        bad_forms: set[str] = set()
        for word in _normalize_words(bad_words):
            bad_forms.update(self._forms(word))

        matched: list[str] = []
        for token in _tokens(text):
            if self._forms(token) & bad_forms:
                matched.append(token)
        return DetectionResult(detected=bool(matched), matched=tuple(matched))


class PymorphyCrosstemDetector:
    name = "pymorphy3-crosstem-custom-dict"

    def __init__(self, ignore_words: list[str] | None = None) -> None:
        pymorphy3 = importlib.import_module("pymorphy3")
        crosstem = importlib.import_module("crosstem")
        self._morph = pymorphy3.MorphAnalyzer()
        self._stemmer = crosstem.DerivationalStemmer("rus")
        self._ignore_words = ignore_words or []

    def _pymorphy_forms(self, word: str) -> set[str]:
        forms = {word}
        for parsed in self._morph.parse(word):
            forms.add(parsed.normal_form)
        return {form.lower().replace("ё", "е") for form in forms}

    def _all_forms(self, word: str) -> set[str]:
        forms = self._pymorphy_forms(word)
        stems = set()
        for form in forms:
            try:
                stems.add(self._stemmer.stem(form).lower().replace("ё", "е"))
            except Exception:
                pass
        return forms | stems

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        bad_forms: set[str] = set()
        for word in _normalize_words(bad_words):
            bad_forms.update(self._all_forms(word))

        ignored_forms: set[str] = set()
        for word in _normalize_words(self._ignore_words):
            ignored_forms.update(self._pymorphy_forms(word))

        matched: list[str] = []
        for token in _tokens(text):
            forms = self._all_forms(token)
            if forms & ignored_forms:
                continue
            if forms & bad_forms:
                matched.append(token)
        return DetectionResult(detected=bool(matched), matched=tuple(matched))


class GlinProfanityDetector:
    name = "glin-profanity"

    def __init__(self) -> None:
        self._module = importlib.import_module("glin_profanity")

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        if hasattr(self._module, "Filter"):
            detector = self._module.Filter(
                {
                    "languages": [],
                    "custom_words": bad_words,
                    "normalize_unicode": False,
                }
            )
            result = detector.check_profanity(text)
            matched = tuple(result.get("profane_words") or ())
            return DetectionResult(
                detected=bool(result.get("contains_profanity")),
                matched=matched,
            )

        for name in ("contains_profanity", "check"):
            if not hasattr(self._module, name):
                continue
            func = getattr(self._module, name)
            signature = inspect.signature(func)
            kwargs = {}
            if "custom_words" in signature.parameters:
                kwargs["custom_words"] = bad_words
            return DetectionResult(detected=bool(func(text, **kwargs)))

        return DetectionResult(
            detected=False,
            skipped_reason="Unsupported glin_profanity API shape",
        )


class BetterProfanityDetector:
    name = "better-profanity"

    def __init__(self) -> None:
        module = importlib.import_module("better_profanity")
        self._profanity = module.profanity

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        self._profanity.load_censor_words(custom_words=bad_words)
        detected = bool(self._profanity.contains_profanity(text))
        return DetectionResult(detected=detected)


class ProfanityFilterDetector:
    name = "profanity-filter"

    def __init__(self) -> None:
        module = importlib.import_module("profanity_filter")
        self._class = module.ProfanityFilter

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        detector = self._class(custom_profane_word_dictionaries={"ru": bad_words})
        detected = bool(detector.is_profane(text))
        return DetectionResult(detected=detected)


class _SkippedDetector:
    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self._reason = reason

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        return DetectionResult(
            detected=False,
            skipped_reason=self._reason,
        )


def build_detectors() -> list[CurseDetector]:
    detectors: list[CurseDetector] = [
        ExactTokenDetector(),
        PymorphyDetector(),
        PymorphyCrosstemDetector(),
    ]

    optional_classes = [
        GlinProfanityDetector,
        BetterProfanityDetector,
        ProfanityFilterDetector,
    ]
    for cls in optional_classes:
        try:
            detectors.append(cls())
        except Exception as error:
            detectors.append(_SkippedDetector(cls.name, str(error)))
    return detectors
