"""Reusable 3.0 services; the public CLI and batch delegate to these owners."""
from paper_reader.official.client import connect
from paper_reader.official.sync_report import scan_duplicates, observe_remote, build_sync_report
from paper_reader.analysis.prepare import prepare_pdf, prepare_zotero
from paper_reader.analysis.review import seal_analysis
from paper_reader.analysis.secondary import attach_secondary_captures
from paper_reader.operations.planner import plan_note
from paper_reader.operations.preview import preview_plan, approve_plan
from paper_reader.operations.executor import apply_plan, retry_operation, plan_status
from paper_reader.operations.reconcile import reconcile_plan
from paper_reader.ingest.identify import inspect_pdf, inspect_inputs
from paper_reader.ingest.duplicates import match_duplicates
from paper_reader.ingest.planner import plan_import, validate_import_plan

__all__ = ['connect', 'prepare_pdf', 'prepare_zotero', 'seal_analysis', 'attach_secondary_captures',
           'plan_note', 'preview_plan', 'approve_plan', 'apply_plan', 'retry_operation',
           'plan_status', 'reconcile_plan', 'inspect_pdf', 'inspect_inputs', 'match_duplicates',
           'plan_import', 'validate_import_plan', 'scan_duplicates', 'observe_remote', 'build_sync_report']
