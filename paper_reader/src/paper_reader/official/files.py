"""Official file URL decoding and independent, stable PDF fingerprints."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from paper_reader.analysis.contracts import PdfSource
from paper_reader.operations.contracts import WorkflowError
from paper_reader.resource_policy import V2_RESOURCE_POLICY
from paper_reader.storage import fingerprint_resolved_source


def file_url_to_path(url: str) -> Path:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost')
                or parsed.query or parsed.fragment or re.search(r'%(?![0-9a-fA-F]{2})', parsed.path)):
            raise ValueError('invalid local file URL')
        path = Path(unquote(parsed.path, errors='strict'))
        if not path.is_absolute() or not path.is_file():
            raise ValueError('attachment is not a local file')
        return path.resolve(strict=True)
    except (OSError, ValueError, UnicodeError):
        raise WorkflowError('attachment_unavailable', 'attachment file is unavailable locally') from None


def fingerprint_pdf(path: Path) -> PdfSource:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise OSError('not a regular file')
        if resolved.stat().st_size > V2_RESOURCE_POLICY.local_pdf_max_bytes:
            raise WorkflowError('resource_limit', 'PDF exceeds byte limit')
        value = fingerprint_resolved_source(resolved)
    except (OSError, ValueError) as exc:
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError('attachment_unavailable', 'PDF is unavailable or changed while reading') from None
    return PdfSource(resolved_path=value.resolved_path, size_bytes=value.size_bytes,
                     sha256=value.sha256, device=value.device, inode=value.inode)
