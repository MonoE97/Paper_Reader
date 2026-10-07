# Explicit PDF import — 3.0

A local PDF or directory path is not automatically a request to import. Ask which outcome is intended if ambiguous. Pure local-only note publication remains available in a retained 2.2 installation and is not exposed by 3.0. The offline `maintenance extract-pdf` diagnostic can inspect text without Zotero.

For explicit PDF import, use `$paper_reader` from its installed skill root. Create a fresh run root using the layout in [the Zotero workflow](zotero-workflow.md); all plans use the one stable installation coordination root. Do not move, rename or overwrite source files. Keep the original filename for the stored attachment; new item title is the article's original title, never the filename.

```bash
uv run paper_reader ingest inspect <pdf-or-directory> --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official
uv run paper_reader zotero collections
```

Inspection is read-only for Zotero and returns per-file source fingerprints, page text, DOI candidates and an immutable evidence_ref. Classify each source separately. Create a fresh `paper_reader.identification-proposal.v3` JSON using the exported schema in `references/official-schemas/`; save it in the run root. The proposal binds the exact source and evidence reference. Supply original title, item type, authors/year/identifiers only when supported. Each field needs a page:N locator, exact quote and explanation. A DOI in references is not the article DOI: identifier evidence must explicitly bind the value and its self/citation/unresolved relation. Unknown/conflicting data stays unresolved, not guessed.

Select an existing collection using its full path, key and reason. Do not create a collection or overwrite old memberships. Imported papers may join the approved union of collections. An explicit selected_parent must carry its current full ZoteroSelection; a matching title alone is not a confirmed duplicate. The planner combines stable identifiers, metadata and PDF hashes; preprints/versions/conflicts may need user resolution. External metadata evidence must be tied to this PDF with URL/text/pdf_comparison; it cannot replace PDF title evidence. If the original filename is unsafe, propose a specific attachment_filename and show it for new approval.

```bash
uv run paper_reader plan import --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --source <absolute-pdf-path> --proposal <proposal-relative-path>
uv run paper_reader plan preview --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path>
```

The full preview must cover metadata, selected parent, existing collection paths/keys/reasons, original filename or proposed replacement, duplicate evidence, source fingerprint, all operations/dependencies and blockers. Wait for explicit human confirmation of the exact content and selected operations, then use `plan approve` and `plan apply` as in the Zotero workflow. Native app authorization does not substitute for business approval.

The core executes parent creation, collection union, attachment creation/upload/registration and readback as separate journaled stages. Previously completed stages are not resent. After uncertain outcomes use `plan reconcile`; zero-match retry needs separate explicit confirmation. Do not directly touch Zotero storage, synthesize another key or delete partially created records. Preserve local source bytes and report local verification separately from user-managed synchronization. Directory input is inspected per file; multiple approved plans may be dispatched through `$paper_reader_batch`.
