from __future__ import annotations

import re

_CREDENTIALS = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"gh[pousr]_[A-Za-z0-9]{36,255}"
    r"|github_pat_[A-Za-z0-9_]{70,255}"
    r"|sk-ant-[A-Za-z0-9_-]{80,255}"
    r"|sk-(?:proj-|svcacct-)[A-Za-z0-9_-]{40,255}"
    r"|xox[baprs]-[A-Za-z0-9-]{24,255}"
    r")(?![A-Za-z0-9_-])"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?P<kind>(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY)-----"
    r"\s*(?:[A-Za-z0-9+/=]\s*){64,16384}-----END (?P=kind)-----"
)


def contains_source_secret(text: str) -> bool:
    return bool(_CREDENTIALS.search(text) or _PRIVATE_KEY.search(text))
