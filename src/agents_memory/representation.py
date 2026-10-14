from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from .domain import DomainError


def serialized_json_bytes(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii"))


def stored_record_window(value: dict, start: int, max_bytes: int, representation_bytes: int, *,
                         measure_json: Callable[[dict], int] = serialized_json_bytes) -> dict:
    stored = {key: item for key, item in value.items() if key != "epoch"}
    raw = json.dumps(stored, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if type(start) is not int or not 0 <= start < len(raw) or type(max_bytes) is not int or not 1 <= max_bytes <= 4096:
        raise DomainError("CLAIM_WINDOW_INVALID", "Choose a bounded inspection JSON byte window")
    try:
        text = raw[start:min(len(raw), start + max_bytes)].decode("utf-8")
    except UnicodeDecodeError as error:
        if error.start == 0 and error.reason != "unexpected end of data":
            raise DomainError("CLAIM_WINDOW_INVALID", "The inspection cursor must align to UTF-8") from None
        text = raw[start:start + error.start].decode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    metadata = {key: value[key] for key in ("id", "kind", "epoch", "state", "revision") if key in value}

    def window(length: int) -> dict:
        body = text[:length]
        stop = start + len(body.encode("utf-8"))
        return {**metadata, "partial": True, "draft_window": {
            "encoding": "utf-8-json", "scope": "stored_record", "live_fields": ["epoch"],
            "digest": digest, "body": body,
            "byte_start": start, "byte_end": stop, "total_bytes": len(raw),
            "next_byte": stop if stop < len(raw) else None,
        }}

    def fits(candidate: dict) -> bool:
        # Reserve the whole bigint clock width, not the current epoch's digit count.
        if "epoch" in candidate:
            candidate = {**candidate, "epoch": 9223372036854775807}
        return measure_json(candidate) <= representation_bytes

    result = window(len(text))
    if text and fits(result):
        return result
    low, high = 0, len(text)
    while high - low > 1:
        middle = (low + high) // 2
        if fits(window(middle)):
            low = middle
        else:
            high = middle
    if low == 0:
        raise DomainError("CLAIM_WINDOW_TOO_LARGE", "An inspection JSON character exceeds the byte budget", status=413)
    return window(low)
