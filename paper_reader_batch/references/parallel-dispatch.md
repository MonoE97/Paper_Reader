# Reading dispatch — 3.0

The agent may delegate independent reading tasks to `$paper_reader` within the user's scope and available agent capacity. Core owns Chinese-first analysis, PDF/figure evidence, secondary capture and finding-anchor assessment. Use one fresh run per paper and return immutable plan references. Do not let reading workers approve or apply plans before the user's precise preview confirmation.

Batch CLI supplies no worker claims, leases or scheduler in 3.0. Agent-level reading may be parallel; all approved library writing is serial through the existing core executor. Never introduce another write queue or use task completion as business approval. If delegation is unavailable, process papers sequentially using the same core workflow.

For multiple PDFs, inspect each source and handle ambiguous identity/parent/classification separately. Exclusions must preserve dependencies. An ordinary local-only analysis request is not import authorization; use the explicitly retained 2.2 workflow if that outcome is needed. Report blockers without inventing metadata.
