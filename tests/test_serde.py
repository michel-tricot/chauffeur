from dataclasses import dataclass, field
from datetime import datetime

import pytest

from chauffeur import serde


@dataclass
class Inner:
    n: int


@dataclass
class Payload:
    url: str
    count: int = 0
    ratio: float = 1.0
    tags: list[str] = field(default_factory=list)
    inner: Inner | None = None
    when: datetime | None = None


def test_from_wire_basic_and_defaults():
    got = serde.from_wire(Payload, {"url": "https://x"})
    assert got == Payload(url="https://x")


def test_from_wire_nested_and_list():
    got = serde.from_wire(Payload, {"url": "u", "tags": ["a", "b"], "inner": {"n": 3}})
    assert got.tags == ["a", "b"]
    assert got.inner == Inner(n=3)


def test_from_wire_datetime_roundtrip():
    when = datetime(2026, 7, 31, 12, 0, 0)
    got = serde.from_wire(Payload, {"url": "u", "when": when.isoformat()})
    assert got.when == when
    assert serde.to_wire(got)["when"] == when.isoformat()


def test_missing_required_field():
    with pytest.raises(serde.SerdeError, match="missing field 'url'"):
        serde.from_wire(Payload, {})


def test_type_mismatch():
    with pytest.raises(serde.SerdeError, match="expected int"):
        serde.from_wire(Payload, {"url": "u", "count": "nope"})


def test_bool_is_not_int():
    with pytest.raises(serde.SerdeError):
        serde.from_wire(Payload, {"url": "u", "count": True})


def test_strict_rejects_extra_fields():
    with pytest.raises(serde.SerdeError, match="unexpected fields"):
        serde.from_wire(Payload, {"url": "u", "surprise": 1}, strict=True)


def test_lenient_ignores_extra_fields():
    got = serde.from_wire(Payload, {"url": "u", "surprise": 1})
    assert got == Payload(url="u")


def test_validate_schema_rejects_unsupported_type():
    @dataclass
    class HasBytes:
        p: bytes

    with pytest.raises(serde.SchemaError):
        serde.validate_schema(HasBytes)


def test_validate_schema_rejects_non_str_dict_key():
    @dataclass
    class Bad:
        m: dict[int, str]

    with pytest.raises(serde.SchemaError, match="dict keys"):
        serde.validate_schema(Bad)


def test_to_wire_dataclass():
    assert serde.to_wire(Inner(n=5)) == {"n": 5}
