"""Pure, conservative duplicate assessment over explicit metadata candidates."""
import re
import unicodedata

from paper_reader.analysis.contracts import PaperIdentifier, PdfSource
from paper_reader.ingest.contracts import (
    AttachmentEvidence, DuplicateAssessment, DuplicateCandidate, IdentificationProposal,
)
from paper_reader.official.models import ItemSnapshot
from paper_reader.workflow import format_creators


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


def match_duplicates(proposal: IdentificationProposal, source: PdfSource,
                     inventory: tuple[ItemSnapshot, ...], *,
                     attachments: tuple[AttachmentEvidence, ...] = ()) -> DuplicateAssessment:
    wanted = {normalized_identifier(i) for i in proposal.identifiers}
    matches = []
    strong_conflict = False
    for item in inventory:
        if item.data.item_type in ('note', 'attachment') or item.raw_json['data'].get('deleted'):
            continue
        identifiers = {normalized_identifier(i) for i in item_identifiers(item)}
        shared = wanted & identifiers
        same_title = bool(proposal.title and normalized_text(proposal.title) == normalized_text(item.data.title))
        exact = tuple(a.attachment_key for a in attachments if a.parent_key == item.key and a.source is not None
                      and (a.source.sha256, a.source.size_bytes) == (source.sha256, source.size_bytes))
        # arXiv version variants remain candidates, never strong identifier matches.
        same_arxiv = any(k == other_k == 'arxiv' and re.sub(r'v\d+$', '', v) == re.sub(r'v\d+$', '', other_v)
                         for k, v in wanted for other_k, other_v in identifiers)
        if not (shared or same_title or exact or same_arxiv):
            continue
        conflicts, reasons = [], []
        if not same_title:
            conflicts.append('title')
        data = item.raw_json['data']
        creators = [c for c in data.get('creators', []) if c.get('creatorType', 'author') == 'author']
        authors = {normalized_text(format_creators([c])) for c in creators}
        if proposal.authors and authors and {normalized_text(a) for a in proposal.authors} != authors:
            conflicts.append('authors')
        year = re.search(r'\b([12]\d{3})\b', str(data.get('date', '')))
        if proposal.year is not None and year and proposal.year != int(year[1]):
            conflicts.append('year')
        if proposal.item_type is not None and proposal.item_type != item.data.item_type:
            conflicts.append('item_type')
        for kind in {k for k, _ in wanted} & {k for k, _ in identifiers}:
            if {v for k, v in wanted if k == kind} != {v for k, v in identifiers if k == kind}:
                conflicts.append('identifiers')
                break
        if exact:
            reasons.append('本地附件的完整 SHA-256 与大小相同。')
        if shared:
            reasons.append('稳定标识符相同；仍需同时核对元数据。')
        if same_title:
            reasons.append('规范化题名相同，仅作为候选证据。')
        if same_arxiv and not shared:
            reasons.append('arXiv 基础编号相同，版本不同。')
        relation = 'exact_attachment' if exact else 'compatible_identifier' if shared and not conflicts else 'possible'
        strong_conflict = strong_conflict or bool(conflicts and (exact or shared))
        matches.append(DuplicateCandidate(parent_key=item.key, relationship=relation, attachment_keys=exact,
                                           reasons=tuple(reasons), conflicting_fields=tuple(conflicts)))
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
