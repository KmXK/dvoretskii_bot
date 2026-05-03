import re

import pytest

from steward.framework.subcommand import (
    Subcommand,
    parse_pattern,
    sort_subcommands,
    subcommand,
)


def make(pattern, **kw):
    @subcommand(pattern, **kw)
    async def fn(self, ctx):
        return None
    return fn._feature_subcommands[-1]


def test_parse_empty_pattern():
    spec = parse_pattern("")
    assert spec.tokens == ()


def test_parse_literal_only():
    spec = parse_pattern("list")
    assert spec.literal_count == 1
    assert spec.typed_count == 0


def test_parse_multi_word_literal():
    spec = parse_pattern("punishment today")
    assert spec.literal_count == 2


def test_parse_typed_param():
    spec = parse_pattern("done <id:int>")
    assert spec.literal_count == 1
    assert spec.typed_count == 1


def test_parse_rest_param():
    spec = parse_pattern("word_list add <words:rest>")
    assert spec.literal_count == 2
    assert spec.has_rest


def test_parse_literal_options():
    spec = parse_pattern("set <kind:literal[public|private]>")
    from steward.framework.subcommand import _Param
    param = next(t for t in spec.tokens if isinstance(t, _Param))
    assert param.options == ("public", "private")


def test_parse_allows_literal_after_param():
    spec = parse_pattern("<id:int> priority <p:int>")
    assert spec.literal_count == 1
    assert spec.typed_count == 2


def test_parse_rejects_token_after_rest():
    with pytest.raises(ValueError):
        parse_pattern("<text:rest> <n:int>")
    with pytest.raises(ValueError):
        parse_pattern("<text:rest> later")


def test_parse_rejects_unknown_type():
    with pytest.raises(ValueError):
        parse_pattern("<x:bogus>")


def test_match_empty_to_empty():
    sub = make("")
    ok, parsed = sub.matches("")
    assert ok and parsed == {}


def test_match_empty_does_not_match_text():
    sub = make("")
    ok, _ = sub.matches("list")
    assert not ok


def test_match_literal():
    sub = make("list")
    ok, parsed = sub.matches("list")
    assert ok and parsed == {}


def test_match_literal_with_extra_fails():
    sub = make("list")
    ok, _ = sub.matches("list extra")
    assert not ok


def test_match_typed_int():
    sub = make("done <id:int>")
    ok, parsed = sub.matches("done 5")
    assert ok and parsed == {"id": 5}


def test_match_typed_int_rejects_non_int():
    sub = make("done <id:int>")
    ok, _ = sub.matches("done abc")
    assert not ok


def test_match_int_only():
    sub = make("<n:int>")
    ok, parsed = sub.matches("42")
    assert ok and parsed == {"n": 42}


def test_match_int_only_rejects_text():
    sub = make("<n:int>")
    ok, _ = sub.matches("hello")
    assert not ok


def test_match_rest_captures_remainder():
    sub = make("word_list add <words:rest>")
    ok, parsed = sub.matches("word_list add плохо хорошо")
    assert ok
    assert parsed == {"words": "плохо хорошо"}


def test_match_rest_requires_some_text():
    sub = make("word_list add <words:rest>")
    ok, _ = sub.matches("word_list add")
    assert not ok


def test_match_catchall_text():
    sub = make("<text:rest>", catchall=True)
    ok, parsed = sub.matches("купить молоко")
    assert ok and parsed == {"text": "купить молоко"}


def test_match_two_typed_params():
    sub = make("punishment add <coeff:int> <title:rest>")
    ok, parsed = sub.matches("punishment add 5 отжимания утром")
    assert ok
    assert parsed == {"coeff": 5, "title": "отжимания утром"}


def test_match_literal_path_takes_precedence():
    longer = make("punishment today")
    shorter = make("punishment <id:int>")
    sorted_subs = sort_subcommands([shorter, longer])
    assert sorted_subs[0].raw == "punishment today"


def test_match_typed_before_catchall():
    typed = make("<n:int>")
    catch = make("<text:rest>", catchall=True)
    sorted_subs = sort_subcommands([catch, typed])
    assert sorted_subs[0].raw == "<n:int>"


def test_match_done_with_id_vs_done_alone():
    done_alone = make("done")
    done_with_id = make("done <id:int>")
    sorted_subs = sort_subcommands([done_alone, done_with_id])
    assert sorted_subs[0].raw == "done <id:int>"
    ok_5, p_5 = sorted_subs[0].matches("done 5")
    assert ok_5 and p_5 == {"id": 5}
    ok_alone, _ = sorted_subs[1].matches("done")
    assert ok_alone


def test_match_literal_with_options():
    sub = make("kind <k:literal[public|private]>")
    ok_pub, parsed_pub = sub.matches("kind public")
    assert ok_pub and parsed_pub == {"k": "public"}
    ok_x, _ = sub.matches("kind other")
    assert not ok_x


def test_match_regex_escape_hatch():
    @subcommand(re.compile(r"^foo (?P<x>\d+)$"))
    async def fn(self, ctx):
        return None
    sub = fn._feature_subcommands[-1]
    ok, parsed = sub.matches("foo 42")
    assert ok and parsed == {"x": "42"}


def test_admin_flag():
    sub = make("add <id:int>", admin=True)
    assert sub.admin is True


def test_description_propagates():
    sub = make("list", description="Список")
    assert sub.description == "Список"


def test_match_curse_n():
    sub = make("<n:int>")
    ok, parsed = sub.matches("5")
    assert ok and parsed == {"n": 5}


def test_match_curse_done_and_done_id():
    done_alone = make("done")
    done_id = make("done <id:int>")
    subs = sort_subcommands([done_alone, done_id])
    ok_just, _ = subs[1].matches("done")
    assert ok_just
    ok_with, p = subs[0].matches("done 7")
    assert ok_with and p == {"id": 7}
