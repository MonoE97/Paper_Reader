# Core handoff references — 3.0

`$paper_reader` owns the immutable plan, Chinese-first sealed analysis, complete note and secondary evidence/anchor semantics. Batch does not import those models or revalidate their schema. A candidate alone is not an executable plan.

A reading task returns the absolute run_root, run_id and the complete plan ArtifactRef from the core command result. Batch forms a BoundArtifactRef from those fields and records it in its v3 manifest. Preserve role/path/sha256/size_bytes/media_type exactly. Reference paths remain relative to the core run. The selected core installation is explicit and may be non-sibling.

The batch preview includes the core's complete presentation fields. Business approval returns BoundApprovalRef with the same run identity, the approval artifact and the bound plan ArtifactRef. It grants no authority beyond the core approval. Never translate this envelope into raw API or MCP write instructions. Only the core executor writes and verifies; state/report remain derived summaries.

Missing results and lost responses remain uncertain. Keep exact request identity and receipts; do not fabricate success or auto-dispatch a second execution. Retained v2 worker-result/lease contracts are historical and are not accepted by the current public CLI.
