import re
from functools import cached_property, lru_cache

import crosstem
import pymorphy3


_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+", re.UNICODE)


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


class CurseDetector:
    @cached_property
    def _morph(self):
        return pymorphy3.MorphAnalyzer()

    @cached_property
    def _stemmer(self):
        return crosstem.DerivationalStemmer("rus")

    def count(
        self,
        text: str,
        bad_words: set[str],
        ignore_words: set[str] | None = None,
    ) -> int:
        if not text or text.startswith("/") or not bad_words:
            return 0

        bad_forms = self._bad_forms(frozenset(_norm(w) for w in bad_words))
        ignore_forms = self._ignore_forms(frozenset(_norm(w) for w in (ignore_words or set())))

        count = 0
        for token in self._tokens(text):
            token_forms = self._all_forms(token)
            if token_forms & ignore_forms:
                continue
            if token_forms & bad_forms:
                count += 1
        return count

    def _tokens(self, text: str) -> list[str]:
        return [_norm(token) for token in _TOKEN_RE.findall(text)]

    @lru_cache(maxsize=4096)
    def _pymorphy_forms(self, word: str) -> frozenset[str]:
        forms = {word}
        for parsed in self._morph.parse(word):
            forms.add(_norm(parsed.normal_form))
        return frozenset(forms)

    @lru_cache(maxsize=4096)
    def _all_forms(self, word: str) -> frozenset[str]:
        forms = set(self._pymorphy_forms(word))
        for form in list(forms):
            try:
                forms.add(_norm(self._stemmer.stem(form)))
            except Exception:
                pass
        return frozenset(forms)

    @lru_cache(maxsize=128)
    def _bad_forms(self, words: frozenset[str]) -> frozenset[str]:
        forms: set[str] = set()
        for word in words:
            forms.update(self._all_forms(word))
        return frozenset(forms)

    @lru_cache(maxsize=128)
    def _ignore_forms(self, words: frozenset[str]) -> frozenset[str]:
        forms: set[str] = set()
        for word in words:
            forms.update(self._pymorphy_forms(word))
        return frozenset(forms)
