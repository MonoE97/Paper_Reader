# Paper Reader

[中文说明](README.zh-CN.md)

Paper Reader **3.0.0** provides two independently installable skills for Zotero reading notes and explicit PDF import through Zotero 10's official local API. This repository is a maintenance workspace; the runtime projects are `paper_reader/` and `paper_reader_batch/`.

This is the 3.0 source/install contract. T10 local package validation is separate from T11 real-device acceptance and public release. T9 provides read-only local duplicate scanning and independent peer observation services; real Mac/Linux sync acceptance remains pending. Synchronization remains user-managed; program output stays `sync_unobserved` without independent remote evidence. Import-time duplicate checks and complete local readback remain enforced.

## Workflows

| Skill | Responsibility |
| --- | --- |
| `$paper_reader` | Discover/select Zotero papers, read PDF evidence, preserve Chinese-first analysis and review, preview an immutable note/import plan, execute only explicitly approved operations, verify local results. |
| `$paper_reader_batch` | Gather existing core plans, show complete previews, record explicit paper selection, serially call the core and summarize per-paper outcomes. |

PDF import preserves the source path, original filename and bytes, uses the article's original title and existing collections, and never silently overwrites memberships. A PDF path alone is not permission to import. Independent local-only note publication remains in a separately retained **2.2** installation; 3.0 does not automatically route to it. Existing notes and old runs stay intact. New public commands do not read/migrate old lifecycle artifacts or expose the old MCP writer.

## Requirements

Use a POSIX runtime: Linux or macOS, Python >=3.13, and uv. Native Windows is not supported by the current descriptor/flock implementation. Zotero 10 must run locally with the official API available at `http://127.0.0.1:23119/api/`, API version 3, personal library `/users/0`. No third-party Zotero MCP plugin, direct SQLite access or central service is required. Linux and Mac each access their own instance; do not expose the API remotely or compare their local versions.

Application authorization and content approval are separate. Always Allow does not approve a batch's content. Only native `remember=true` grants are persisted in a protected local user directory, isolated by machine/user/URL/Server ID. Keys never belong in runs, logs, Git or prompts. The agent must show full note content, targets, operations, reasons and blockers and wait for explicit human confirmation before `plan approve`/`plan apply`. All mutation remains inside the core executor. Uncertain outcomes require read-only reconciliation; no automatic retry, merge, deletion or sync-setting change.

## Clean installation from one commit

Export only tracked files from one exact commit. Do not recursively copy the working tree, `.venv`, caches, `docs`, credentials or runs. The stage layout below is disposable test-installation space with `core/paper_reader`, non-sibling `batch/skills/paper_reader_batch`, and `logs`; retain it until explicitly cleaned. Check it before creating environments:

```bash
revision="$(git rev-parse --verify HEAD^{commit})"
stage="$(mktemp -d /tmp/paper-reader-3.0.XXXXXXXX)"
chmod 700 "$stage"
mkdir -p "$stage/core" "$stage/batch/skills" "$stage/logs"
git archive "$revision" paper_reader | tar -x -C "$stage/core"
git archive "$revision" paper_reader_batch | tar -x -C "$stage/batch/skills"
uv run --project paper_reader --no-sync python "$stage/core/paper_reader/scripts/validate-skill.py" "$stage/core/paper_reader" --release-bundle
uv run --project paper_reader_batch --no-sync python "$stage/batch/skills/paper_reader_batch/scripts/validate-skill.py" "$stage/batch/skills/paper_reader_batch" --release-bundle
```

`--release-bundle` is a standard-library-only validator and may also be run directly with an already available Python >=3.13. It rejects runtime/private files, symlinks, special files, stale versions/entrypoints and unsupported active schemas. The old `references/schemas/` files remain historical; active v3 exports live in `references/official-schemas/`. The single duplicate-report schema is active in T9.

Then validate both independent installations:

```bash
cd "$stage/core/paper_reader"
uv sync --locked
uv run pytest
uv run paper_reader --version
uv run paper_reader --help
uv run paper_reader maintenance extract-pdf tests/fixtures/minimal.pdf
uv run python scripts/validate-skill.py .

cd "$stage/batch/skills/paper_reader_batch"
uv sync --locked
PAPER_READER_TEST_ROOT="$stage/core/paper_reader" uv run pytest
uv run paper_reader_batch --version
uv run paper_reader_batch --help
uv run python scripts/validate-skill.py .
```

The root helper `scripts/validate-committed-release-bundles.sh <exact-commit> /tmp` automates this stricter full-suite gate and retains logs. Existing batch v2 recovery defects were deferred by explicit user choice; all old tests remain enabled. Report any such failures separately from 3.0 checks; a failing full suite is never described as fully green. The helper can therefore return nonzero even when the current v3 workflow passes. Do not weaken it, skip tests or infer remote CI success from local evidence.

Only after staging checks, install the exported tracked bundle into a **new, absent** skill directory named `paper_reader` or `paper_reader_batch` under the chosen Codex/Claude skills root. Keep the old 2.2 installation separately if required; never overwrite it or copy environments/runs into the new installation. Before enabling 3.0 writing, stop using the old writer on that computer. Independent installations do not share locks; one active core writer per computer is required. Carry both skill roots explicitly; batch accepts a `paper_reader_root` in its manifest and the tests use `PAPER_READER_TEST_ROOT` for non-sibling layouts.

## Public commands and contracts

From each installed skill root, run `uv sync --locked` and `uv run <skill> --help`.

- Core: `zotero search|inspect|collections|prepare|check-duplicates`, `analysis capture-binding|attach-secondary|seal`, `ingest inspect`, `plan note|import|preview|approve|apply|status|reconcile|retry`, `maintenance extract-pdf`.
- Batch: `preview`, `approve`, `apply`; existing core plans and exact request UUIDs are required. No runtime LLM worker/lease scheduler is added.
- Operational stdout is one strict `.command-result.v3` JSON; help/version are human-readable. Historical/unknown lifecycle inputs fail without migration or fallback.
- Reusable Python services live in `paper_reader.services`; CLI adapters reuse analysis and the single executor. Batch consumes command envelopes and opaque core references, not core schema implementations.

Read [core instructions](paper_reader/SKILL.md), [Zotero reading](paper_reader/references/zotero-workflow.md), [explicit import](paper_reader/references/pdf-path-workflow.md), [analysis fields and anchors](paper_reader/references/summary-schema.md), and [batch instructions](paper_reader_batch/SKILL.md).

Secondary pages remain untrusted cross-check material. Their exact immutable capture anchors do not replace canonical PDF evidence or prove scientific correctness. Chinese-first prose, PDF-only conclusions, full review and the existing note template remain the quality baseline. Local verification, real API acceptance, Mac/Linux runtime acceptance, user-confirmed sync, remote CI and publication are separate claims. T11 real-device acceptance requires a separately approved concrete sample; no current installation step grants real write authority.
