# Batch workflow — 3.0

`$paper_reader` performs each paper's Chinese-first analysis, secondary evidence/review gates and immutable planning. Batch receives opaque references, never parses core artifacts or writes Zotero. Use separate non-sibling installations if desired, with an explicit absolute core root.

## Input directory and manifest

Create a fresh existing batch directory under `runs/YYYY-MM-DD/<new-batch-id>/`. It owns `manifest.json`, `.batch.lock`, and `requests/<UUID>/{intent.json,approvals/<sequence>.json,result.json}`. The manifest is immutable and all request files are no-replace. Keep the directory for replay/recovery; do not move or edit its contents while running. No worker lease or background scheduler is installed.

`manifest.json` has this shape; replace placeholders with actual core command outputs. A core reference includes all returned ArtifactRef fields, including media_type when present. Obtain run_id from plan data and the plan artifact from its command result.

```json
{
  "schema_version": "paper_reader_batch.manifest.v3",
  "batch_id": "batch_example",
  "paper_reader_root": "/absolute/core/installation/paper_reader",
  "plan_refs": [{
    "run_root": "/absolute/core/installation/paper_reader/runs/YYYY-MM-DD/run-id",
    "run_id": "run-id",
    "artifact": {
      "role": "zotero-plan", "path": "plans/example/plan.json",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size_bytes": 123, "media_type": "application/json"
    }
  }]
}
```

The manifest cannot be hand-guessed from titles or candidate paths. Same library writes use the core installation's one coordination root; do not route the batch through multiple active writers on this computer.

## Preview and selection

```bash
uv run paper_reader_batch preview --manifest <batch-root>/manifest.json --run-root <batch-root>
```

The one JSON response has `data.preview` and `data.preview_sha256`. Save the whole `data` object as a separate fresh preview JSON file; do not pass the outer command-result envelope to approve. Show the entire preview, core note Markdown/HTML content and brief reasons. Read note artifact references through their run root. Obtain human confirmation and explicit subject selection before approval. `subject_id` comes from core preview operations, not a filename.

```bash
uv run paper_reader_batch approve --manifest <batch-root>/manifest.json --run-root <batch-root> --preview <saved-preview-data.json> --expected-preview-sha256 <digest> --confirmation-ref <non-sensitive-confirmation-id> --request-id <fresh-UUID> --subject-id <selected-subject>
```

Repeat `--subject-id` for selected papers. Omitting all subjects returns an empty approval list and excludes everything; it never means select all. Record the returned `data.approval_refs` exactly.

```bash
uv run paper_reader_batch apply --manifest <batch-root>/manifest.json --run-root <batch-root> --request-id <different-fresh-UUID> --approval '<one-complete-BoundApprovalRef-JSON>'
```

Repeat `--approval` for each returned reference. Use structured argument arrays or safe shell quoting, never interpolate untrusted paper text into a shell command. Core validates all referenced approvals/journals before connecting and serially uses its existing executor.

## Recovery and report

The same request UUID must have the exact same arguments. A repeated apply uses core status/read-only reconciliation and cannot issue a second apply. If response is lost, use the same request and original references; do not invent a new request to try writing again. No automatic retry is permitted. `approval_uncertain` means inspect partial receipts and ask about any subsequent approval, not auto-approve again. A core timeout is uncertain until readback resolves it; zero match alone does not prove safe retry. Use core `plan retry` only after separate explicit confirmation.

Results distinguish verified, skipped, blocked and uncertain per paper with reasons/next steps. Report local verification separately from `sync_unobserved`; T9 scans and observations belong to the core. Preserve any returned remote observation reference; batch does not interpret or create remote proof. Partial success does not authorize resending the batch. Existing source PDFs and Zotero notes remain intact; no automatic merge/deletion or synchronization changes.
