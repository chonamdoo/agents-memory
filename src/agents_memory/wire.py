from __future__ import annotations

import json
import math
from typing import Any, overload

from pydantic import BaseModel, TypeAdapter

# Count the maximum escaped request ID and stamp wrapper; quoted text is measured separately.
RESULT_ENVELOPE_BYTES = len(json.dumps({
    "jsonrpc": "2.0", "id": "\x01" * 256,
    "result": {"content": [{"type": "text", "text": ""}], "isError": False,
               "_meta": {"agents-memory/stamp": {}}},
}, separators=(",", ":")).encode("ascii")) - 2


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode_json_value(raw: bytes) -> Any:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except RecursionError:
        raise ValueError("nested input exceeds limit") from None

    def validate(item, depth: int) -> None:
        if depth > 24:
            raise ValueError("nested input exceeds limit")
        if isinstance(item, str):
            item.encode("utf-8")
            if "\x00" in item:
                raise ValueError("NUL is not text")
        elif isinstance(item, dict):
            for key, child in item.items():
                validate(key, depth + 1)
                validate(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                validate(child, depth + 1)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite JSON number")

    validate(value, 0)
    return value


def decode_json(raw: bytes) -> dict:
    value = decode_json_value(raw)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


@overload
def validate_wire[Model: BaseModel](model: type[Model], value: object) -> Model: ...


@overload
def validate_wire[Value](model: TypeAdapter[Value], value: object) -> Value: ...


def validate_wire(model: type[BaseModel] | TypeAdapter[Any], value: object) -> Any:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(model, TypeAdapter):
        return model.validate_json(raw, strict=True)
    return model.model_validate_json(raw, strict=True)


def tool_result_bytes(value: dict) -> int:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return len(json.dumps(text).encode("ascii")) + RESULT_ENVELOPE_BYTES


