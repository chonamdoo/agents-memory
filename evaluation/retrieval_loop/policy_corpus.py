"""Real-document holdout, read from a local directory and never committed.

Set AM_LOOP_POLICY_DIR to a policy-spec folder containing `wiki/**/*.md` documents with
`### POLICY-NNN — title` sections and a `**Rule**:` line, plus dated
`*업데이트 요약 YYYY-MM-DD.md` summaries whose bullets start with `- [[wiki/<path>|<stem>]] — `.

Claims: each rule's text prefixed by its document title and section heading (one claim per
policy, carrying its document title, feature ID and POLICY ID as entities) and each dated summary bullet (one claim per change note).
Queries are built mechanically, without hand-written labels:
  PT  policy title alone, and document title plus policy title -> that rule
  PI  feature ID plus POLICY ID -> that rule
  G6  document title plus "변경 이력", for documents changed on two or more dates
      -> every dated change note of that document (old and new versions together)
Like the synthetic holdout this set is reported only in aggregate, is never used for
tuning, and blocks promotion when it regresses.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from corpus import Claim, Corpus

_SECTION = re.compile(r"^### (POLICY-\d+)\s*[—-]\s*(.+?)\n(.*?)(?=^### |\Z)", re.M | re.S)
_RULE = re.compile(r"\*\*Rule\*\*:\s*(.+)")
_FIELD = re.compile(r"^(title|feature_id):\s*(.+)$", re.M)
_BULLET = re.compile(r"^- \[\[wiki/([^|\]]+)\|[^\]]*\]\]\s*[—-]\s*(.+)$", re.M)
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md$")
_MAX_HISTORY = 6


def _one_sentence(text: str, limit: int = 600) -> str:
    """Flatten markdown and inner sentence ends so the body is one source span."""
    text = re.sub(r"\*\*|`|\[\[[^|\]]*\||\[\[|\]\]", "", text).replace("MUST ", "")
    text = re.sub(r"([.!?。！？])\s+(?=\S)", r"\1; ", " ".join(text.split()))
    text = text[:limit].rstrip(" ;")
    return text if text.endswith((".", "!", "?")) else text + "."


def policy() -> Corpus | None:
    root = os.environ.get("AM_LOOP_POLICY_DIR")
    if not root:
        return None
    corpus = Corpus("policy")
    titles: dict[str, str] = {}
    by_title: dict[str, list[str]] = {}
    headings: list[tuple[str, str]] = []
    for path in sorted(Path(root, "wiki").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields = dict(_FIELD.findall(text))
        doc_title = fields.get("title", path.stem).strip()[:120]
        feature = fields.get("feature_id", "").strip()
        relative = path.relative_to(Path(root, "wiki")).as_posix()
        titles[relative] = doc_title
        for policy_id, title, body in _SECTION.findall(text):
            rule = _RULE.search(body)
            if rule is None:
                continue
            key = f"{path.stem}-{policy_id}"
            title = title.strip()
            entities = tuple(item for item in (doc_title, feature, policy_id) if item)
            # A captured section carries its heading, so its identifiers are grounded in the original.
            heading = " ".join(item for item in (feature, policy_id, title) if item)
            corpus.claims.append(Claim(key, _one_sentence(f"{doc_title} {heading}: {rule.group(1)}"), doc_title,
                                       "requires", title[:120], entities))
            by_title.setdefault(title, []).append(key)
            headings.append((doc_title, title))
            if feature:
                corpus.ask("PI", "fragment", f"{feature} {policy_id}", key)
    for doc_title, title in dict.fromkeys(headings):
        gold = tuple(by_title[title])
        corpus.ask("PT", "fragment", title, *gold)
        corpus.ask("PT", "keyword", f"{doc_title} {title}", *gold)
    history: dict[str, list[str]] = {}
    for summary in sorted(Path(root).glob("*요약*.md")):
        date = _DATE.search(summary.name)
        if date is None:
            continue
        for index, (relative, change) in enumerate(_BULLET.findall(summary.read_text(encoding="utf-8"))):
            doc_title = titles.get(relative)
            if doc_title is None:
                continue
            key = f"change-{date.group(1)}-{index:02d}"
            corpus.claims.append(Claim(key, _one_sentence(f"{date.group(1)} {doc_title} 정책 변경: {change}"),
                                       doc_title, "changed", date.group(1), (doc_title,)))
            history.setdefault(doc_title, []).append(key)
    for doc_title, keys in history.items():
        if len(keys) >= 2:
            corpus.ask("G6", "keyword", f"{doc_title} 변경 이력", *keys[-_MAX_HISTORY:])
    return corpus
