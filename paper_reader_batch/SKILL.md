---
name: paper_reader_batch
description: Use when the user requests multiple Zotero reading notes or explicit PDF imports; delegate analysis to paper_reader, then preview, select and serially execute its approved core plans.
---

# paper_reader_batch

Paper Reader Batch 3.0 coordinates existing core plans. `$paper_reader` owns discovery, Chinese-first analysis, secondary evidence, plans, approval, all writes and readback. This package never imports the core Python package, interprets its lifecycle schemas, dispatches an LLM internally, or sends a raw API/MCP write.

## Setup and scope

From the installed skill root, run `uv sync --locked`, `uv run paper_reader_batch --version` and `uv run paper_reader_batch --help`. Install core separately and pass its explicit absolute `paper_reader_root` in the manifest. A non-sibling installation is supported; do not guess a sibling root. Use one writing core installation per computer. Pure local-only analysis/publication stays in a retained 2.2 installation; explicit PDF import must be requested.

## Workflow

1. Resolve the requested papers/PDFs and use `$paper_reader` to produce one immutable plan per run. Reading workers may be delegated only within the user's requested scope and available agent support. The CLI does not introduce a worker/lease scheduler. Follow [dispatch guidance](references/parallel-dispatch.md) and [core result references](references/worker-result-contract.md).
2. Create a fresh batch directory at `runs/YYYY-MM-DD/<new-batch-id>/`. Save a `paper_reader_batch.manifest.v3` with an explicit core root and returned run/plan references; see [batch workflow](references/batch-workflow.md). Do not copy core schemas, generate fake references or migrate a v2 manifest.
3. Run `preview`; show each paper's operations, targets, full content, reasons, duplicates and blockers. Read core note references so the complete Markdown/HTML are inspectable. Save the returned preview `data` intact for approval.
4. STOP for human confirmation of this exact preview and selection. Run `approve` with selected subject IDs, preview digest, a non-sensitive confirmation reference and a fresh `--request-id` UUID. Excluded parent/dependent operations are never silently restored. All excluded means no approval and no writing.
5. Run `apply` with returned approval references and its own fresh `--request-id`. Core execution is serial and shares one credential provider per process. Always Allow grants application access only; it is not batch content approval.
6. Report verified/skipped/blocked/uncertain per paper. `sync_unobserved` is not sync failure or proof of remote visibility. T9 remote observation and synchronization-related duplicate detection are deferred to user management.

There is no automatic retry. Reuse the same request id only with exactly the same arguments. Repeating an already-started apply request queries/reconciles core outcomes without issuing another apply. An approval request that started but lost its response is `approval_uncertain`; inspect receipts rather than approving again automatically. Any new content/target/source requires an affected plan to be previewed and confirmed again. Only the core can authorize an explicit zero-match retry. Never hand-edit receipts/journals, synthesize another key or create a new request to force a resend.

## Active contract

Public commands are `uv run paper_reader_batch preview`, `approve`, and `apply`. Active batch schemas are manifest/state/event/report/command-result `.v3`, exported under `references/official-schemas/`. State and report summarize core results; they do not own write truth. Strict unknown/historical artifacts fail; there is no automatic migration or old command fallback. Retained v2 files/tests are historical, including separately tracked recovery defects. Full legacy tests are run and reported separately from the v3 workflow validation.
