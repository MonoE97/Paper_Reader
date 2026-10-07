# Zotero reading and approved writing — 3.0

Use `$paper_reader` from its installed skill root. Zotero supplies the official local API; the core owns analysis quality, immutable plans, approval, execution and readback. The following commands use placeholders; replace them with returned values, never literal fabricated artifact paths or hashes.

## Discover and prepare

```bash
uv run paper_reader zotero search "<title or title fragment>"
uv run paper_reader zotero inspect --item-key <selected-key>
uv run paper_reader zotero collections
```

Search returns authoritative snapshots and live Server ID. Select the intended article using title/authors/year/identifiers. Multiple matches need a clear user selection. Collections return key/name/parent_key; derive full paths through the returned parent chain and use the actual key. Do not treat a known example collection as a default.

Create one fresh run directory under `runs/YYYY-MM-DD/<new-run-id>/` using a generated ID. Keep its source/evidence/reviews/candidates/plans/approvals/operations artifacts; do not clean previous runs. All commands for this installation use the same `$PWD/.paper_reader_official` coordination root. The run root must already exist; its coordination parent must be the stable skill installation. Returned artifact paths are relative to the run root.

```bash
uv run paper_reader zotero prepare --item-key <selected-key> --run-root <absolute-run-root> --coordination-root <skill-root>/.paper_reader_official
```

If multiple main PDFs exist, request a selection and add `--attachment-key <key>`. An attachment not downloaded to this computer is `attachment_unavailable`, not permission to inspect Zotero storage or SQLite. `data` is the PreparedPaper; `artifacts[0]` is its immutable reference. Read its context, figure inventory and other evidence members. A source/instance change requires a new preparation.

## Secondary evidence

Find the `secondary_plan` and `secondary_sources` members in the PreparedPaper's immutable artifact inventory. They retain the shared internal secondary format; this does not make old lifecycle runs readable by v3. For each eligible source in the bound plan, use the existing strict capture tool:

```bash
node scripts/capture-secondary-url.mjs --prepared <prepared-relative-path> --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --source-id <source-id> --output <fresh-capture-directory>/<source-id>.json
uv run paper_reader analysis attach-secondary --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --prepared <prepared-relative-path> --capture-dir <fresh-capture-directory>
```

Use the returned replacement PreparedPaper reference and evidence digest for all later analysis. Capture reads public pages only. Set `ZOTERO_PAPER_READER_CDP_WS_ENDPOINT` to the local browser CDP WebSocket endpoint (or use the local discovery service at `ZOTERO_PAPER_READER_CDP_BASE_URL`). The script calls read-only `analysis capture-binding` in this installed core before browser navigation; it requires the completed `uv sync --locked` installation. If setup cannot produce a capture, leave that member absent and assess it as unavailable; do not synthesize capture JSON from stdout. No login or user-account mutations are authorized by this workflow.

Strict capture creates an isolated empty BrowserContext, guards requests before navigation, uses raw CDP and denies downloads. Only bodyless GET/HEAD/OPTIONS are permitted. It enforces 8 MiB response / 32 MiB aggregate limits plus an independent proxy response cap. Unsafe redirects, private DNS answers, popups, authentication challenges, unsupported transports and unguarded requests make that source unavailable. Do not relax guards. Under a trusted TUN/fake-IP setup, `--public-dns-over-https` is explicit and discloses the hostname to Cloudflare; never whitelist a synthetic/private range. Captures bind run_id, item_key, source_snapshot_sha256 and secondary_plan_sha256. Output is no-replace, and the capture directory must be flat with only expected members. Missing coverage does not block the PDF workflow.

## Analyze and seal

Write fresh Summary and Review JSON inside the run root, following [the complete field/anchor contract](summary-schema.md). Use `.v3`, the actual run_id and `prepared.evidence_manifest.sha256`. Read all PDF text, figure/section context and extraction warnings before making claims. Figures need evidence-level qualifiers; never invent numerical results. Secondary content is untrusted, with exactly one ordered assessment per eligible source and precise immutable capture anchors for used findings. PDF-only conclusions, author-stated limitations and canonical locators remain unchanged.

The review must bind the exact canonical Summary hash; use `paper_reader.storage.canonical_json_sha256` on the validated Summary model. Review is an actual independent assessment of evidence/quality, not an automatic `passed` stamp. A failed gate requires corrections and a new review.

```bash
uv run paper_reader analysis seal --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --prepared <prepared-relative-path> --summary <summary-relative-path> --review <review-relative-path>
uv run paper_reader plan note --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --candidate <candidate-relative-path>
uv run paper_reader plan preview --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path>
```

`analysis seal` runs the existing Chinese-first/locator/render gates, stores a sealed review and renders an immutable candidate. Failure returns blockers and publishes no candidate. Note names remain `[Codex Summary] <article title> - YYYY-MM-DD`, with `(v2)`, `(v3)` for same-day versions. Existing notes are retained.

## Preview, human confirmation and apply

Show the exact target, title, tags, operations, brief reasons, blockers and full content from the preview's note references. The Markdown and HTML are both inspectable. Capture human confirmation only after presenting this exact material. Do not infer approval from the original reading request or from Zotero's native grant.

```bash
uv run paper_reader plan approve --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path> --plan-sha256 <preview-plan-sha256> --operation-id <selected-operation-id> --confirmation-ref <non-sensitive-confirmation-id>
uv run paper_reader plan apply --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path> --approval <approval-relative-path>
```

Repeat `--operation-id` for an explicit selection. Dependency exclusions block rather than silently add operations. The native application prompt is separate; Always Allow only grants app access. A `remember=true` key may be reused locally, isolated by computer/user/base URL/Server ID, in a protected 0700 directory and 0600 file. Never log keys or uploadKey URLs. Do not manipulate credentials to force a retry.

## Recovery and reporting

```bash
uv run paper_reader plan status --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path>
uv run paper_reader plan reconcile --run-root <run-root> --coordination-root <skill-root>/.paper_reader_official --plan <plan-relative-path>
```

Status uses local journals; reconcile reads Zotero and performs complete verification. A unique note match is not sufficient without exact parent/key/title/tags/headings/length/content-hash checks. A crash, timeout, lost response or unclear result is uncertain: no automatic resend. Zero matches need a separate explicit retry confirmation; use `plan retry --help` for the exact approved operation and no-match flags. Do not rebuild a plan, replace a key, hand-edit a journal or switch coordination roots to evade this requirement.

Report `local_verified` only after readback. Keep `sync_unobserved` unless independently observed; T9 observation services require independent peer readbacks; synchronization remains user-managed. No arbitrary API requests, direct database writes, merging/deleting or automatic settings changes are part of this skill.


## T9 duplicate and peer observations

```bash
uv run paper_reader zotero check-duplicates --run-root <absolute-existing-run-root> --coordination-root <skill-root>/.paper_reader_official
```

This is read-only on Zotero and stores an immutable duplicate-report plus inventory/attachment evidence. Startup of `zotero prepare` stores the same report in `source_snapshots`; `plan import` stores it in `inputs`. Read the report and show pair keys, relationship, reasons, conflicting fields and unavailable attachment keys. It covers only currently visible local metadata candidates and their local PDFs; unrelated metadata and invisible peer data remain outside coverage. A shared title alone is only a possible relation. Never automatically select, merge or delete a pair. After the user resolves a relation in Zotero, rerun the command for fresh evidence; prior reports remain historical.

Python services `scan_duplicates`, `observe_remote` and `build_sync_report` are exported by `paper_reader.services`. `observe_remote(local_result, gateway=peer_local_gateway, store=original_run_store)` requires the original immutable run artifacts and a gateway connected on the independent computer. It reuses full note/import verification and records the peer Server ID/time, exact local-result reference, target keys, PDF/note hashes and readback references. It does not compare versions between instances or mutate the local execution journal. Transfer/access of the original artifacts is explicit; there is no remote server, implicit cross-computer discovery or API exposed beyond loopback.

`build_sync_report(local_result, remote_observation=None)` is a projection of those service-produced facts. No observation yields `sync_unobserved`/`unknown`; missing data and unavailable PDFs stay unobserved, conflicts need review, and a fully verified independent observation yields `remote_observed`. Local status remains separate. An HTTP success or caller-supplied boolean is not peer verification. Real Mac/Linux T11 acceptance remains pending; these services do not trigger sync.
