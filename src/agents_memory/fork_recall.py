from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from .domain import ContextCommand, DomainError, Handle, RelevanceJudgment, TypedModel
from .private_io import private_read
from .wire import decode_json, validate_wire

RECALL_INPUT_BYTES = 262144
RECALL_REASON_BYTES = 512


class _Candidate(TypedModel):
    claim_id: Handle
    inspection_ref: Handle
    partial: bool
    preview: str | None = None
    polarity: str | None = None
    modality: str | None = None
    arms: tuple[str, ...] = ()
    evidence_role: Literal["unjudged_candidate_not_execution_authority"] | None = None


class _ChildReturn(TypedModel):
    admission_id: Handle
    status: Literal["complete", "partial", "cancelled", "failed"]
    relevance: tuple[RelevanceJudgment, ...] = Field(max_length=20)


def read_recall_document(path: Path, *, project_root: Path) -> dict:
    """Read one bounded JSON object from an owner-only directory outside the project.

    Native write tools cannot promise private file modes, so the per-invocation
    directory carries the privacy boundary; the leaf must be a single-link file.
    """
    path = Path(path)
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise DomainError("PATH_DENIED", "The recall evidence directory is unavailable") from None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise DomainError("PATH_DENIED", "Recall evidence must be in an owner-only (0700) directory")
        located = Path(os.path.realpath(path.parent))
        try:
            named = os.stat(located)
        except OSError:
            named = None
        if named is None or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
            raise DomainError("PATH_DENIED", "The recall evidence directory changed while it was checked")
        if located.is_relative_to(os.path.realpath(project_root)):
            raise DomainError("PATH_DENIED", "Recall evidence must stay outside the project tree")
        # Case-insensitive volumes and firmlinks give one directory several spellings; compare file identity.
        try:
            root = os.stat(project_root)
        except FileNotFoundError:
            root = None
        except OSError:
            raise DomainError("PATH_DENIED", "The project root for recall evidence is unavailable") from None
        for ancestor in (located, *located.parents) if root is not None else ():
            try:
                identity = os.stat(ancestor)
            except OSError:
                continue
            if (identity.st_dev, identity.st_ino) == (root.st_dev, root.st_ino):
                raise DomainError("PATH_DENIED", "Recall evidence must stay outside the project tree")
        return decode_json(private_read(Path(path.name), RECALL_INPUT_BYTES, private=False, directory=directory))
    finally:
        os.close(directory)


def validate_fork_recall(
    request: dict, current_request: dict, candidates: dict, child_return: dict,
    *, task_id: str, current_task_id: str,
) -> dict:
    """Emit second-call arguments only; native inspection and task identity remain parent assertions."""
    if (type(task_id) is not str or not task_id.strip() or len(task_id.encode()) > 512
            or type(current_task_id) is not str or task_id != current_task_id):
        raise DomainError("HOST_RECALL_STALE", "The parent task identity changed or is missing")
    if any(type(value) is not dict for value in (request, current_request, candidates, child_return)):
        raise DomainError("HOST_RECALL_INVALID", "Recall validation requires complete JSON objects")
    try:
        validate_wire(ContextCommand, request)
        validate_wire(ContextCommand, current_request)
        if "admission_id" in request or "relevance" in request:
            raise ValueError("The frozen request must be a first context call")
        if json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
            current_request, sort_keys=True, ensure_ascii=False, allow_nan=False,
        ):
            raise DomainError("HOST_RECALL_STALE", "The entire original context request must remain unchanged")
        manifest = candidates.get("candidate_manifest")
        if type(manifest) is not list or len(manifest) > 20:
            raise ValueError("A complete bounded candidate manifest is required")
        admitted = [validate_wire(_Candidate, item) for item in manifest]
        ids = [item.claim_id for item in admitted]
        if len(set(ids)) != len(ids) or any(item.inspection_ref != item.claim_id for item in admitted):
            raise ValueError("The candidate manifest has duplicate or mismatched inspection identities")
        if type(candidates.get("judgment_required")) is not bool or candidates["judgment_required"] != bool(ids):
            raise ValueError("The first response does not declare a complete judgment manifest")
        result = validate_wire(_ChildReturn, child_return)
        if result.admission_id != candidates.get("admission_id"):
            raise ValueError("The child returned a different admission")
        if result.status != "complete":
            raise DomainError("HOST_RECALL_INCOMPLETE", "Only a completed fork may supply relevance judgments")
        returned_ids = [item.claim_id for item in result.relevance]
        if len(returned_ids) != len(ids) or len(set(returned_ids)) != len(ids) or set(returned_ids) != set(ids):
            raise ValueError("The child must judge every candidate exactly once, with no foreign IDs")
        if any(len(item.reason.encode()) > RECALL_REASON_BYTES for item in result.relevance):
            raise ValueError("Fork relevance reasons must be short and body-free")
        second = {
            **request, "admission_id": result.admission_id,
            "relevance": [item.model_dump(mode="json") for item in result.relevance],
        }
        validate_wire(ContextCommand, second)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        raise DomainError("HOST_RECALL_INVALID", "The fork return or frozen context evidence is invalid") from None
    return second
