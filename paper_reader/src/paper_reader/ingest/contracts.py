from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator

from paper_reader.analysis.contracts import PaperIdentifier, PdfSource
from paper_reader.contracts import ArtifactRef, NonNegativeInt, PositiveInt, PortableIdentifier, Rfc3339Utc, StrictContractModel
from paper_reader.official.models import ImportItemType, ItemKey, Text, ZoteroSelection


class FieldEvidence(StrictContractModel):
    field: Literal["title", "authors", "year", "identifiers", "collections", "item_type"]
    source: ArtifactRef
    locator: Text
    explanation: Text
    quote: str = ""
    identifier: PaperIdentifier | None = None
    identifier_relation: Literal["self", "citation", "unresolved"] = "unresolved"


class CollectionChoice(StrictContractModel):
    key: ItemKey
    full_path: Text
    reason: Text


class IdentificationProposal(StrictContractModel):
    schema_version: Literal["paper_reader.identification-proposal.v3"]
    proposal_id: PortableIdentifier
    run_id: PortableIdentifier
    created_at: Rfc3339Utc
    source: PdfSource
    title: Text | None
    authors: tuple[Text, ...]
    year: NonNegativeInt | None
    identifiers: tuple[PaperIdentifier, ...]
    evidence: tuple[FieldEvidence, ...]
    collections: tuple[CollectionChoice, ...]
    missing_fields: tuple[Text, ...]
    conflicts: tuple[Text, ...]
    item_type: ImportItemType | None = None
    selected_parent: ZoteroSelection | None = None
    attachment_filename: Text | None = None


class ExternalMetadataEvidence(StrictContractModel):
    pdf_source: PdfSource
    url: Text
    text: Text
    pdf_comparison: Text

    @field_validator('url')
    @classmethod
    def require_source_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('external evidence requires a credential-free source URL')
        return value


class EvidencePage(StrictContractModel):
    page: PositiveInt
    text: str


class FieldCandidate(StrictContractModel):
    field: Literal["title", "identifiers"]
    value: Text
    page: PositiveInt
    start: NonNegativeInt
    end: PositiveInt
    region: Literal["body", "references"]


class IdentificationEvidence(StrictContractModel):
    source: PdfSource
    pages: tuple[EvidencePage, ...]
    candidates: tuple[FieldCandidate, ...]
    warnings: tuple[str, ...]


class InspectionEntry(StrictContractModel):
    subject_id: PortableIdentifier
    path: Text
    status: Literal["inspected", "skipped", "blocked"]
    reason: str | None
    evidence: IdentificationEvidence | None
    evidence_ref: ArtifactRef | None = None


class InspectionReport(StrictContractModel):
    entries: tuple[InspectionEntry, ...]


class AttachmentEvidence(StrictContractModel):
    attachment_key: ItemKey
    parent_key: ItemKey
    source: PdfSource | None  # None means not available locally, never absent in Zotero.


class DuplicateCandidate(StrictContractModel):
    parent_key: ItemKey
    relationship: Literal["exact_attachment", "compatible_identifier", "possible"]
    attachment_keys: tuple[ItemKey, ...]
    reasons: tuple[Text, ...]
    conflicting_fields: tuple[Text, ...]


class DuplicateAssessment(StrictContractModel):
    relationship: Literal["exact_attachment", "compatible_identifier", "possible", "none", "ambiguous"]
    parent_key: ItemKey | None
    matches: tuple[DuplicateCandidate, ...]
    unavailable_attachment_keys: tuple[ItemKey, ...]
    scope: Literal["metadata_candidates"] = "metadata_candidates"
    coverage_note: Text = "仅核对题名/标识符候选及其本地附件；未扫描元数据完全不同的全库 PDF，未观察另一端。"


class ImportDetails(StrictContractModel):
    proposal: ArtifactRef
    source: PdfSource
    filename: Text
    suggested_filename: str | None
    status: Literal["ready", "blocked", "skipped"]
    blockers: tuple[Text, ...]
    collections: tuple[CollectionChoice, ...]
    duplicates: DuplicateAssessment
    selected_parent_key: ItemKey | None = None
    collection_snapshot: ArtifactRef
    inventory_snapshot: ArtifactRef
    attachment_snapshot: ArtifactRef
