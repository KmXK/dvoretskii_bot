from datetime import datetime as dt

import pymorphy3

t = dt.now()
morph = pymorphy3.MorphAnalyzer()

cache = {}


def make_agree_with_number(word: str, number: int):
    if cache.get(word) is None:
        cache[word] = morph.parse(word)[0]

    return "{} {}".format(number, cache[word].make_agree_with_number(number).word)
