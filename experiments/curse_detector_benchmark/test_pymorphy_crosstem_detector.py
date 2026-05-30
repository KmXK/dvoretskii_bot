from experiments.curse_detector_benchmark.cases import BAD_WORDS
from experiments.curse_detector_benchmark.detectors import PymorphyCrosstemDetector


def test_pymorphy_crosstem_detects_inflections_and_related_words():
    detector = PymorphyCrosstemDetector()

    positives = [
        "без хуя тут не разобраться",
        "какая-то хуевая ситуация",
        "он опять ебался с настройками",
        "это пиздец полный",
        "эти суки опять шумят",
    ]

    for text in positives:
        result = detector.detect(text, BAD_WORDS)
        assert result.detected, text


def test_pymorphy_crosstem_avoids_close_clean_words():
    detector = PymorphyCrosstemDetector()

    negatives = [
        "у меня болит скула",
        "мы едем на хутор вечером",
        "благодаря тебе все получилось",
        "на куртке отвалилась бляха",
        "врач сказал что это небольшая бляшка",
        "на экране появилась странная блямба",
        "на столе лежит зеленое сукно",
    ]

    for text in negatives:
        result = detector.detect(text, BAD_WORDS)
        assert not result.detected, text


def test_pymorphy_crosstem_supports_ignore_words():
    detector = PymorphyCrosstemDetector(ignore_words=["пиздец"])

    ignored = detector.detect("это пиздец полный", BAD_WORDS)
    real_bad = detector.detect("ну это пизда какая-то", BAD_WORDS)

    assert not ignored.detected
    assert real_bad.detected


if __name__ == "__main__":
    test_pymorphy_crosstem_detects_inflections_and_related_words()
    test_pymorphy_crosstem_avoids_close_clean_words()
    test_pymorphy_crosstem_supports_ignore_words()
