from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _BaseExtraModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Metadata(_BaseExtraModel):
    origin_file: str | None = None
    processing_version: str | None = None
    parser_version: str | None = None
    normalizer_version: str | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    was_sanitized: bool | None = None
    sanitization_reason: str | None = None


class StructuredData(_BaseExtraModel):
    act_number: str | None = None
    act_year: int | None = None
    signer: str | None = None


class Reference(_BaseExtraModel):
    type: str
    target: str


class NormativeReference(_BaseExtraModel):
    reference_type: str | None = None
    reference_number: str | None = None
    reference_text: str | None = None
    reference_full: str | None = None
    reference_year: int | None = None
    reference_date: str | None = None
    issuing_body: str | None = None
    is_revocation: bool | None = None
    is_amendment: bool | None = None


class ProcedureReference(_BaseExtraModel):
    procedure_type: str | None = None
    procedure_identifier: str | None = None
    procedure_year: int | None = None
    procedure_body: str | None = None


class Signature(_BaseExtraModel):
    person_name: str | None = None
    role_title: str | None = None
    sequence: int | None = None
    person_name_normalized: str | None = None
    role_title_normalized: str | None = None
    is_placeholder: bool | None = None
    extraction_source: str | None = None


class DouDocument(_BaseExtraModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(alias="_id")
    source_id: str
    source_zip: str | None = None
    source_type: str | None = None
    pub_date: datetime
    section: str
    edition: str | None = None
    page: int | None = None
    art_type: str | None = None
    art_category: str | None = None
    orgao: str | None = None
    issuing_organ: str | None = None
    identifica: str | None = None
    ementa: str | None = None
    texto: str = ""
    data_text: str | None = None
    content_html: str | None = None
    structured: StructuredData | None = None
    references: list[Reference] = Field(default_factory=list)
    normative_references: list[NormativeReference] = Field(default_factory=list)
    procedure_references: list[ProcedureReference] = Field(default_factory=list)
    signatures: list[Signature] = Field(default_factory=list)
    affected_entities: list[str] = Field(default_factory=list)
    metadata: Metadata | None = None
