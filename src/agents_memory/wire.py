from __future__ import annotations

import json
import math
from typing import Any

from .domain import TypedModel


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode_json(raw: bytes) -> dict:
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
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def validate_wire[Model: TypedModel](model: type[Model], value: object) -> Model:
    return model.model_validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False), strict=True)
