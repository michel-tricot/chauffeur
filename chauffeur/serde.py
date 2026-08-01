"""JSON <-> dataclass conversion for command params and results.

Deliberately small: supports the types that survive a JSON round trip
(primitives, datetime as ISO-8601, lists, string-keyed dicts, Optional, and
nested dataclasses). Anything else is rejected at registration time so schema
mistakes surface when the handler is decorated, not when the first message
arrives.
"""

from __future__ import annotations

import dataclasses
import functools
import types
import typing
from datetime import datetime
from typing import Any


class SerdeError(ValueError):
    """A wire value does not match the declared schema."""


class SchemaError(TypeError):
    """A declared type cannot be represented on the JSON wire."""


@functools.cache
def _field_types(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def _optional_arg(tp: Any) -> Any:
    """The single non-None arm of an Optional, or raise for wider unions."""
    args = [a for a in typing.get_args(tp) if a is not type(None)]
    if len(args) != 1:
        raise SchemaError(f"only Optional[...] unions are supported: {tp!r}")
    return args[0]


def validate_schema(tp: Any) -> None:
    if tp is Any or tp is None or tp is type(None):
        return
    if tp in (str, int, float, bool, datetime, dict, list):
        return
    if dataclasses.is_dataclass(tp):
        for field_type in _field_types(tp).values():
            validate_schema(field_type)
        return
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        validate_schema(_optional_arg(tp))
        return
    if origin is list:
        validate_schema(typing.get_args(tp)[0])
        return
    if origin is dict:
        key_type, value_type = typing.get_args(tp)
        if key_type is not str:
            raise SchemaError(f"dict keys must be str on the wire: {tp!r}")
        validate_schema(value_type)
        return
    raise SchemaError(f"unsupported wire type: {tp!r}")


def from_wire(tp: Any, value: Any, *, strict: bool = False) -> Any:
    if tp is Any:
        return value
    if tp is None or tp is type(None):
        if value is not None:
            raise SerdeError(f"expected null, got {value!r}")
        return None
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        if value is None:
            return None
        return from_wire(_optional_arg(tp), value, strict=strict)
    if dataclasses.is_dataclass(tp):
        return _dataclass_from_wire(tp, value, strict)
    if origin is list or tp is list:
        if not isinstance(value, list):
            raise SerdeError(f"expected list, got {type(value).__name__}")
        args = typing.get_args(tp)
        item_type = args[0] if args else Any
        return [from_wire(item_type, item, strict=strict) for item in value]
    if origin is dict or tp is dict:
        if not isinstance(value, dict):
            raise SerdeError(f"expected object, got {type(value).__name__}")
        args = typing.get_args(tp)
        value_type = args[1] if args else Any
        return {key: from_wire(value_type, item, strict=strict) for key, item in value.items()}
    if tp is datetime:
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise SerdeError(f"expected ISO-8601 datetime string, got {value!r}") from None
    if tp is bool:
        if not isinstance(value, bool):
            raise SerdeError(f"expected bool, got {type(value).__name__}")
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SerdeError(f"expected int, got {type(value).__name__}")
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SerdeError(f"expected number, got {type(value).__name__}")
        return float(value)
    if tp is str:
        if not isinstance(value, str):
            raise SerdeError(f"expected string, got {type(value).__name__}")
        return value
    raise SchemaError(f"unsupported wire type: {tp!r}")


def _dataclass_from_wire(tp: Any, value: Any, strict: bool) -> Any:
    if not isinstance(value, dict):
        raise SerdeError(f"expected object for {tp.__name__}, got {type(value).__name__}")
    hints = _field_types(tp)
    fields = dataclasses.fields(tp)
    if strict:
        extra = set(value) - {f.name for f in fields}
        if extra:
            raise SerdeError(f"unexpected fields for {tp.__name__}: {sorted(extra)}")
    kwargs = {}
    for field in fields:
        if field.name in value:
            kwargs[field.name] = from_wire(hints[field.name], value[field.name], strict=strict)
        elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            raise SerdeError(f"missing field {field.name!r} for {tp.__name__}")
    return tp(**kwargs)


def to_wire(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_wire(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [to_wire(item) for item in value]
    if isinstance(value, dict):
        return {key: to_wire(item) for key, item in value.items()}
    return value
