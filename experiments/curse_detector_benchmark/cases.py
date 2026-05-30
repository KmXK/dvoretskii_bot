from dataclasses import dataclass


@dataclass(frozen=True)
class CurseCase:
    name: str
    text: str
    expected: bool
    note: str


BAD_WORDS = [
    "хуй",
    "пизда",
    "ебать",
    "блядь",
    "сука",
]


CASES = [
    CurseCase(
        name="direct_nominative",
        text="хуй",
        expected=True,
        note="Exact dictionary form should be detected.",
    ),
    CurseCase(
        name="direct_in_sentence",
        text="ну это пизда какая-то",
        expected=True,
        note="Exact bad word inside sentence.",
    ),
    CurseCase(
        name="case_insensitive",
        text="БЛЯДЬ, опять сломалось",
        expected=True,
        note="Uppercase token with punctuation.",
    ),
    CurseCase(
        name="inflected_genitive",
        text="без хуя тут не разобраться",
        expected=True,
        note="Inflected noun form should match base lemma.",
    ),
    CurseCase(
        name="inflected_plural",
        text="эти суки опять шумят",
        expected=True,
        note="Plural inflection should match singular lemma.",
    ),
    CurseCase(
        name="verb_inflection",
        text="он опять ебался с настройками",
        expected=True,
        note="Verb form should match configured verb lemma.",
    ),
    CurseCase(
        name="derived_adjective",
        text="какая-то хуевая ситуация",
        expected=True,
        note="Derived adjective is useful to compare; pure lemmatizers may miss it.",
    ),
    CurseCase(
        name="compound_word",
        text="это пиздец полный",
        expected=True,
        note="Derived/compound profanity; configurable detectors may need extra dictionary entry.",
    ),
    CurseCase(
        name="normal_word_suka_sound",
        text="у меня болит скула",
        expected=False,
        note="Looks somewhat close to 'сука' but is normal.",
    ),
    CurseCase(
        name="normal_word_hutor",
        text="мы едем на хутор вечером",
        expected=False,
        note="Starts similarly to a bad root but is normal.",
    ),
    CurseCase(
        name="normal_word_blago",
        text="благодаря тебе всё получилось",
        expected=False,
        note="Starts similarly to a profanity prefix but is normal.",
    ),
    CurseCase(
        name="normal_word_blyaha",
        text="на куртке отвалилась бляха",
        expected=False,
        note="Normal word that is visually close to a profanity root.",
    ),
    CurseCase(
        name="normal_word_blyashka",
        text="врач сказал что это небольшая бляшка",
        expected=False,
        note="Normal word that is visually close to a profanity root.",
    ),
    CurseCase(
        name="normal_word_blyamba",
        text="на экране появилась странная блямба",
        expected=False,
        note="Normal word that is visually close to a profanity root.",
    ),
    CurseCase(
        name="normal_word_sukno",
        text="на столе лежит зеленое сукно",
        expected=False,
        note="Normal word that shares a prefix with 'сука'.",
    ),
    CurseCase(
        name="command_should_be_ignored_by_backend_policy",
        text="/curse word_list add хуй",
        expected=False,
        note="Matches current bot policy: commands are not auto-counted.",
    ),
    CurseCase(
        name="clean_sentence",
        text="сегодня хороший день и вкусный кофе",
        expected=False,
        note="Plain clean sentence.",
    ),
]
