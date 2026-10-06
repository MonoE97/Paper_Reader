from paper_reader.candidate_integrity import LocalPublicationError
from paper_reader.note import validate_note


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
