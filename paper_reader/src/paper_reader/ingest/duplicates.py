"""Pure, conservative duplicate assessment over explicit metadata candidates."""
import re
import unicodedata
from dataclasses import dataclass

from paper_reader.analysis.contracts import PaperIdentifier, PdfSource
from paper_reader.ingest.contracts import (
    AttachmentEvidence, DuplicateAssessment, DuplicateCandidate, IdentificationProposal,
)
from paper_reader.official.models import ItemSnapshot
from paper_reader.workflow import format_creators


@dataclass(frozen=True)
class DuplicateMetadata:
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    identifiers: tuple[PaperIdentifier, ...]
    item_type: str | None


def item_metadata(item: ItemSnapshot) -> DuplicateMetadata:
    data = item.raw_json['data']
    creators = [c for c in data.get('creators', []) if c.get('creatorType', 'author') == 'author']
    year = re.search(r'\b([12]\d{3})\b', str(data.get('date', '')))
    return DuplicateMetadata(item.data.title, tuple(format_creators([c]) for c in creators),
                             int(year[1]) if year else None, item_identifiers(item), item.data.item_type)


def normalized_text(value: str) -> str:
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def normalized_identifier(identifier: PaperIdentifier) -> tuple[str, str]:
    value = identifier.value.strip().casefold()
    if identifier.kind == 'doi':
        value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value).rstrip('.,;')
    elif identifier.kind == 'arxiv':
        value = re.sub(r'^(?:https?://arxiv\.org/abs/|arxiv:\s*)', '', value)
    elif identifier.kind == 'isbn':
        value = re.sub(r'[\s-]', '', value)
    return identifier.kind, value


def item_identifiers(item: ItemSnapshot) -> tuple[PaperIdentifier, ...]:
    data = item.raw_json['data']
    identifiers = [PaperIdentifier(kind=kind, value=data[field]) for field, kind in
        (('DOI', 'doi'), ('ISBN', 'isbn'), ('archiveID', 'arxiv'))
        if isinstance(data.get(field), str) and data[field].strip()
        and (field != 'archiveID' or str(data.get('archive', '')).casefold() == 'arxiv')]
    for kind, value in re.findall(r'^\s*(DOI|arXiv|PMID|ISBN):\s*(\S+)\s*$', item.data.extra, re.I | re.M):
        identifiers.append(PaperIdentifier(kind=kind.lower(), value=value))
    return tuple(identifiers)


def assess_candidate(metadata: DuplicateMetadata, item: ItemSnapshot, *,
                     exact_attachments: tuple[str, ...] = ()) -> DuplicateCandidate | None:
    """The same conservative comparison for import candidates and library pairs."""
    if item.data.item_type in ('note', 'attachment') or item.raw_json['data'].get('deleted'):
        return None
    other = item_metadata(item)
    wanted = {normalized_identifier(i) for i in metadata.identifiers}
    identifiers = {normalized_identifier(i) for i in other.identifiers}
    shared = wanted & identifiers
    same_title = bool(normalized_text(metadata.title or '') and
                      normalized_text(metadata.title or '') == normalized_text(other.title or ''))
    same_arxiv = any(k == other_k == 'arxiv' and re.sub(r'v\d+$', '', v) == re.sub(r'v\d+$', '', other_v)
                     for k, v in wanted for other_k, other_v in identifiers)
    if not (shared or same_title or exact_attachments or same_arxiv):
        return None
    conflicts, reasons = [], []
    if not same_title:
        conflicts.append('title')
    authors = {normalized_text(a) for a in other.authors}
    if metadata.authors and authors and {normalized_text(a) for a in metadata.authors} != authors:
        conflicts.append('authors')
    if metadata.year is not None and other.year is not None and metadata.year != other.year:
        conflicts.append('year')
    if metadata.item_type is not None and metadata.item_type != other.item_type:
        conflicts.append('item_type')
    for kind in {k for k, _ in wanted} & {k for k, _ in identifiers}:
        if {v for k, v in wanted if k == kind} != {v for k, v in identifiers if k == kind}:
            conflicts.append('identifiers')
            break
    if exact_attachments:
        reasons.append('本地附件的完整 SHA-256 与大小相同。')
    if shared:
        reasons.append('稳定标识符相同；仍需同时核对元数据。')
    if same_title:
        reasons.append('规范化题名相同，仅作为候选证据。')
    if same_arxiv and not shared:
        reasons.append('arXiv 基础编号相同，版本不同。')
    relation = 'exact_attachment' if exact_attachments else 'compatible_identifier' if shared and not conflicts else 'possible'
    return DuplicateCandidate(parent_key=item.key, relationship=relation, attachment_keys=exact_attachments,
                              reasons=tuple(reasons), conflicting_fields=tuple(conflicts))


def match_duplicates(proposal: IdentificationProposal, source: PdfSource,
                     inventory: tuple[ItemSnapshot, ...], *,
                     attachments: tuple[AttachmentEvidence, ...] = ()) -> DuplicateAssessment:
    metadata = DuplicateMetadata(proposal.title, proposal.authors, proposal.year, proposal.identifiers, proposal.item_type)
    matches = []
    wanted = {normalized_identifier(i) for i in proposal.identifiers}
    strong_conflict = False
    for item in inventory:
        exact = tuple(a.attachment_key for a in attachments if a.parent_key == item.key and a.source is not None
                      and (a.source.sha256, a.source.size_bytes) == (source.sha256, source.size_bytes))
        match = assess_candidate(metadata, item, exact_attachments=exact)
        if match is not None:
            matches.append(match)
            shared = wanted & {normalized_identifier(i) for i in item_identifiers(item)}
            strong_conflict = strong_conflict or bool(match.conflicting_fields and (exact or shared))
    keys = {m.parent_key for m in matches}
    unavailable = tuple(a.attachment_key for a in attachments if a.parent_key in keys and a.source is None)
    if not matches:
        relationship, parent_key = 'none', None
    elif len(matches) > 1 or strong_conflict:
        relationship, parent_key = 'ambiguous', None
    else:
        relationship = matches[0].relationship
        parent_key = matches[0].parent_key if relationship in ('exact_attachment', 'compatible_identifier') else None
    return DuplicateAssessment(relationship=relationship, parent_key=parent_key, matches=tuple(matches),
                               unavailable_attachment_keys=unavailable)
