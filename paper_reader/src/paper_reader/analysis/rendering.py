from paper_reader.candidate_integrity import LocalPublicationError
from collections.abc import Iterable

from paper_reader.note import next_same_day_version_suffix, validate_note
from paper_reader.zotero_live import _parse_headings


def build_note_title(paper_title: str, generated_date: str, existing_note_html: Iterable[str]) -> str:
    """Freeze the same-day suffix from the analysis source snapshot."""
    titles = [_parse_headings(html)[0] for html in existing_note_html]
    suffix = next_same_day_version_suffix(titles, paper_title=paper_title, generated_date=generated_date)
    return f'[Codex Summary] {paper_title} - {generated_date}{suffix}'


def _rewrite_markdown_h1(note_bytes: bytes, note_title: str) -> bytes:
    try:
        note = note_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalPublicationError("invalid_sealed_review", "sealed note.md is not UTF-8") from exc
    lines = note.splitlines(keepends=True)
    if not lines or not lines[0].startswith("# "):
        raise LocalPublicationError("invalid_sealed_review", "sealed note.md is missing its H1")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n" if lines[0].endswith("\n") else ""
    lines[0] = f"# {_markdown_literal_note_title(note_title)}{newline}"
    rewritten = "".join(lines)
    errors = validate_note(rewritten)
    if errors:
        raise LocalPublicationError(
            "invalid_sealed_review",
            "; ".join(errors),
        )
    return rewritten.encode("utf-8")


def _markdown_literal_note_title(note_title: str) -> str:
    """Keep the fixed summary prefix readable while neutralizing inline Markdown in the exact title."""

    prefix = "[Codex Summary] "
    fixed_prefix = prefix if note_title.startswith(prefix) else ""
    remainder = note_title[len(fixed_prefix) :]
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">", "&"):
        remainder = remainder.replace(character, f"\\{character}")
    return f"{fixed_prefix}{remainder}"
