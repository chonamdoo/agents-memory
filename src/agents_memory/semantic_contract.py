from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, create_model

from .domain import (
    ClaimDraft,
    SmallText,
    TypedModel,
)

GeneratedAssertion = create_model(
    "GeneratedAssertion",
    __base__=TypedModel,
    assertion_id=(str, Field(..., pattern=r"^a[0-9]{4}$")),
    assertion_span_id=(str, Field(..., min_length=1, max_length=16)),
    **{
        name: (field.rebuild_annotation(), ...)
        for name, field in ClaimDraft.model_fields.items()
        if name not in {"evidence", "conditions", "exceptions", "valid_from", "valid_until"}
    },
)


class AnchoredQualification(TypedModel):
    kind: Literal["condition", "exception", "context"]
    phrase: SmallText
    evidence_span_id: str | None = Field(max_length=16)


class IndividualQualification(AnchoredQualification):
    assertion_id: str = Field(pattern=r"^a[0-9]{4}$")


class SharedQualification(AnchoredQualification):
    assertion_ids: tuple[str, ...] = Field(min_length=2, max_length=32)


class GeneratedValidity(TypedModel):
    valid_from: datetime | None
    valid_until: datetime | None
    evidence_span_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    assertion_ids: tuple[str, ...] = Field(min_length=1, max_length=32)


class GeneratedExtraction(TypedModel):
    claims: tuple[GeneratedAssertion, ...] = Field(max_length=32)
    individual_qualifications: tuple[IndividualQualification, ...] = Field(max_length=64)
    shared_qualifications: tuple[SharedQualification, ...] = Field(max_length=64)
    validities: tuple[GeneratedValidity, ...] = Field(max_length=32)
    unused_span_ids: tuple[str, ...] = Field(max_length=128)

