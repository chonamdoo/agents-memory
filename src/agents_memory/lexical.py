from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[^\W_]+(?:[_＿][^\W_]+)*", re.UNICODE)
_CODE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:[.:/\\-][A-Za-z0-9_$]+)*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")
_HANGUL = re.compile(r"[가-힣]+")


def tokens(text: str) -> list[str]:
    result: dict[str, None] = {}

    def add(value: str) -> None:
        for candidate in (value, value.casefold()):
            if candidate and len(result) < 2048 and len(candidate.encode("utf-8")) <= 1024:
                result[candidate] = None

    for view in (text, unicodedata.normalize("NFKC", text)):
        for match in _WORD.finditer(view):
            add(match.group())
        for match in _CODE.finditer(view):
            value = match.group()
            add(value)
            for part in re.split(r"[_.:/\\$-]+", value):
                add(part)
                for component in _CAMEL.findall(part):
                    add(component)
        for match in _HANGUL.finditer(view):
            value = match.group()
            add(value)
            for position in range(len(value) - 1):
                add(value[position : position + 2])
    return list(result)
