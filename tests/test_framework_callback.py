import pytest

from steward.framework.callback_route import (
    CallbackFactory,
    on_callback,
    parse_schema,
)


def test_parse_simple_schema():
    s = parse_schema("todo:done", "<id:int>")
    assert s.field_names == ("id",)


def test_serialize_and_parse_int():
    s = parse_schema("todo:done", "<id:int>")
    raw = s.serialize(id=5)
    assert raw == "todo:done|5"
    parsed = s.parse(raw)
    assert parsed == {"id": 5}


def test_serialize_multifield():
    s = parse_schema("todo:reward", "<answer:literal[yes|no]>|<todo_id:int>|<initiator:int>")
    raw = s.serialize(answer="yes", todo_id=3, initiator=42)
    assert raw == "todo:reward|yes|3|42"
    parsed = s.parse(raw)
    assert parsed == {"answer": "yes", "todo_id": 3, "initiator": 42}


def test_parse_rejects_wrong_prefix():
    s = parse_schema("todo:done", "<id:int>")
    assert s.parse("other:thing|5") is None


def test_parse_rejects_wrong_field_count():
    s = parse_schema("todo:done", "<id:int>")
    assert s.parse("todo:done|5|extra") is None


def test_parse_rejects_invalid_int():
    s = parse_schema("todo:done", "<id:int>")
    assert s.parse("todo:done|abc") is None


def test_serialize_literal_validates():
    s = parse_schema("todo:reward", "<a:literal[yes|no]>")
    s.serialize(a="yes")
    with pytest.raises(ValueError):
        s.serialize(a="maybe")


def test_serialize_rejects_pipe_in_str():
    s = parse_schema("x:y", "<name:str>")
    with pytest.raises(ValueError):
        s.serialize(name="a|b")


def test_serialize_str_field():
    s = parse_schema("x:y", "<name:str>")
    raw = s.serialize(name="alice")
    assert raw == "x:y|alice"
    assert s.parse(raw) == {"name": "alice"}


def test_callback_factory_button():
    s = parse_schema("todo:done", "<id:int>")
    factory = CallbackFactory(s)
    btn = factory.button("Done", id=5)
    assert btn.text == "Done"
    assert btn.callback_data == "todo:done|5"


def test_invalid_name_rejected():
    with pytest.raises(ValueError):
        parse_schema("invalid_no_colon", "<x:int>")


def test_decorator_collects_route():
    @on_callback("todo:reward", schema="<a:int>", only_initiator=True, initiator_field="a")
    async def fn(self, ctx, a):
        return None

    routes = fn._feature_callbacks
    assert len(routes) == 1
    assert routes[0].schema.name == "todo:reward"
    assert routes[0].only_initiator is True
    assert routes[0].initiator_field == "a"
