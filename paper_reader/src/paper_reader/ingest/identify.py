"""Read PDF evidence, never infer bibliographic metadata or dispatch an LLM."""
from pathlib import Path
import re

from paper_reader.evidence_bundle import _verified_pdf_snapshot, EvidenceBundleError
from paper_reader.ingest.contracts import (
    EvidencePage, FieldCandidate, IdentificationEvidence, InspectionEntry, InspectionReport,
)
from paper_reader.official.files import fingerprint_pdf
from paper_reader.operations.contracts import WorkflowError
from paper_reader.pdf_extract import extract_pdf, PdfPageLimitError, ExtractedTextLimitError
from paper_reader.resource_policy import V2_RESOURCE_POLICY as LIMITS
from paper_reader.storage import new_random_id

DOI_PATTERN = re.compile(r'10\.\d{4,9}/[^\s<>"\u201c\u201d]+', re.IGNORECASE)
REFERENCE_HEADING = re.compile(r'^\s*(?:\d+[.\s]+)?(?:references|bibliography|参考文献)\s*$', re.I | re.M)


def inspect_pdf(path: Path) -> IdentificationEvidence:
    source = fingerprint_pdf(path)
    try:
        with _verified_pdf_snapshot(source, run_id='ingest-inspect') as verified:
            extraction = extract_pdf(Path(source.resolved_path), _verified_pdf_path=verified,
                hard_max_pages=LIMITS.pdf_max_pages, max_chars=LIMITS.extracted_text_max_chars)
    except (PdfPageLimitError, ExtractedTextLimitError):
        raise WorkflowError('resource_limit', 'PDF extraction exceeds limits') from None
    except EvidenceBundleError:
        raise WorkflowError('source_changed', 'PDF changed during extraction') from None
    except (OSError, ValueError, RuntimeError):
        raise WorkflowError('metadata_unresolved', 'PDF could not be extracted') from None
    if fingerprint_pdf(path) != source:
        raise WorkflowError('source_changed', 'PDF changed during extraction')
    pages = tuple(EvidencePage(page=p['page'], text=p['text']) for p in extraction['pages'])
    candidates = []
    in_references = False
    for page in pages:
        heading = REFERENCE_HEADING.search(page.text)
        for match in DOI_PATTERN.finditer(page.text):
            value = match.group().rstrip('.,;)]}')
            region = 'references' if in_references or (heading and match.start() >= heading.start()) else 'body'
            candidates.append(FieldCandidate(field='identifiers', value=value, page=page.page,
                start=match.start(), end=match.start() + len(value), region=region))
        in_references = in_references or heading is not None
    # Full page text is the title/author evidence; choosing a heading is the proposer's job.
    return IdentificationEvidence(source=source, pages=pages, candidates=tuple(candidates),
                                  warnings=tuple(extraction['warnings']))


def inspect_inputs(path: Path) -> InspectionReport:
    """One-level directory inspection; failures are local to each input."""
    path = path.expanduser().absolute()
    paths = []
    if path.is_dir():
        for entry in path.iterdir():
            if len(paths) >= LIMITS.artifact_tree_max_members:
                raise WorkflowError('resource_limit', 'input directory exceeds member limit')
            paths.append(entry)
        paths.sort()
    else:
        paths.append(path)
    entries, seen = [], set()
    for entry in paths:
        status, reason, evidence = 'skipped', 'not_pdf', None
        if entry.suffix.lower() == '.pdf' and not entry.is_dir():
            try:
                source = fingerprint_pdf(entry)
                identity = (source.device, source.inode)
                if identity in seen:
                    reason = 'duplicate_path'
                else:
                    evidence = inspect_pdf(entry)
                    seen.add(identity)
                    status, reason = 'inspected', None
            except WorkflowError as exc:
                status, reason = 'blocked', exc.code
        entries.append(InspectionEntry(subject_id=new_random_id('subject'), path=str(entry), status=status,
                                       reason=reason, evidence=evidence))
    return InspectionReport(entries=tuple(entries))
