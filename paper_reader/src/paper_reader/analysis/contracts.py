from __future__ import annotations

from typing import Literal

from paper_reader.contracts import (
    AbsolutePath, ArtifactRef, GateState, NonNegativeInt, PortableIdentifier,
    ReviewFields, Rfc3339Utc, Sha256, StrictContractModel, SummaryFields,
)
from paper_reader.official.models import Text, ZoteroSelection


class PdfSource(StrictContractModel):
    resolved_path: AbsolutePath
    size_bytes: NonNegativeInt
    sha256: Sha256
    device: NonNegativeInt
    inode: NonNegativeInt


class PaperIdentifier(StrictContractModel):
    kind: Literal["doi", "arxiv", "isbn", "pmid"]
    value: Text


class PaperMetadata(StrictContractModel):
    title: Text
    authors: tuple[Text, ...]
    year: NonNegativeInt | None
    identifiers: tuple[PaperIdentifier, ...]


class PreparedPaper(StrictContractModel):
    schema_version: Literal["paper_reader.run.v3"]
    run_id: PortableIdentifier
    created_at: Rfc3339Utc
    source: PdfSource
    metadata: PaperMetadata
    selection: ZoteroSelection | None
    source_snapshots: tuple[ArtifactRef, ...]
    evidence_manifest: ArtifactRef
    context: ArtifactRef
    figure_inventory: tuple[ArtifactRef, ...]
    artifacts: tuple[ArtifactRef, ...]


class Summary(SummaryFields):
    schema_version: Literal["paper_reader.summary.v3"]


class Review(ReviewFields):
    schema_version: Literal["paper_reader.review.v3"]


class ReviewPackage(StrictContractModel):
    schema_version: Literal["paper_reader.review-package.v3"]
    review_package_id: PortableIdentifier
    run_id: PortableIdentifier
    created_at: Rfc3339Utc
    summary: ArtifactRef
    review: ArtifactRef
    evidence_manifest: ArtifactRef
    summary_sha256: Sha256
    review_sha256: Sha256
    evidence_digest: Sha256
    artifacts: tuple[ArtifactRef, ...]
    gate: GateState


class NoteCandidate(StrictContractModel):
    schema_version: Literal["paper_reader.candidate.v3"]
    candidate_id: PortableIdentifier
    run_id: PortableIdentifier
    created_at: Rfc3339Utc
    source: PdfSource
    run_snapshot: ArtifactRef
    target: ZoteroSelection | None
    evidence_manifest: ArtifactRef
    sealed_review: ArtifactRef
    note_title: Text
    note_markdown: ArtifactRef
    note_html: ArtifactRef
    tags: tuple[str, ...]
    content_sha256: Sha256
    content_length: NonNegativeInt
    artifacts: tuple[ArtifactRef, ...]
    gate: GateState
