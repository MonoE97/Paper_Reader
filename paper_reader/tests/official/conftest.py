"""Synthetic fixtures only; no live Zotero or LLM calls."""
import importlib
import importlib.util
from types import SimpleNamespace

import pytest


@pytest.fixture
def api():
    # An assertion gives a useful RED before these new packages exist.
    for package in ("official", "analysis", "operations", "ingest"):
        assert importlib.util.find_spec(f"paper_reader.{package}") is not None, f"missing v3 {package}"
    return SimpleNamespace(**{
        name: importlib.import_module(f"paper_reader.{path}")
        for name, path in {
            "official": "official.models", "analysis": "analysis.contracts",
            "operations": "operations.contracts", "ingest": "ingest.contracts",
            "store": "operations.store",
        }.items()
    })


@pytest.fixture
def context_data():
    return dict(base_url="http://127.0.0.1:23119/api/", server_id="synthetic-instance",
                api_version=3, library_type="users", library_id=0)


@pytest.fixture
def event_data():
    return dict(schema_version="paper_reader.zotero-event.v3", operation_id="op_1",
                stage="create", seq=1, previous_digest=None, state="started",
                attempt_id="attempt_1", request_id="request_1",
                created_at="2026-10-06T00:00:00Z", readback=None)


@pytest.fixture
def store(api, tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    return api.store.FileRunStore(root, coordination_root=tmp_path / "coordination")
