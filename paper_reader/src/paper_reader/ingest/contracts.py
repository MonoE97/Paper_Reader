from __future__ import annotations

from typing import Literal

from paper_reader.analysis.contracts import PaperIdentifier, PdfSource
from paper_reader.contracts import ArtifactRef, NonNegativeInt, PortableIdentifier, Rfc3339Utc, StrictContractModel
from paper_reader.official.models import ItemKey, Text


class FieldEvidence(StrictContractModel):
    field: Literal["title", "authors", "year", "identifiers", "collections"]
    source: ArtifactRef
    locator: Text
    explanation: Text


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
