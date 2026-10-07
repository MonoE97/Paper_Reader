import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_reader.contracts import V2_SCHEMA_MODELS

EXPECTED_SCHEMAS = {
    f"paper_reader.{name}.v3" for name in (
        "run", "summary", "review", "review-package", "candidate", "identification-proposal",
        "zotero-plan", "zotero-approval", "zotero-event", "zotero-result",
        "command-result", "duplicate-report",
    )
}


@pytest.mark.parametrize("version", [None, "paper_reader.run.v2", "paper_reader.run.v99", 3])
def test_v2_unknown_schema_rejected_before_side_effects(api, store, tmp_path, monkeypatch, version):
    from paper_reader.contracts import ArtifactRef
    from hashlib import sha256
    import socket

    payload = {} if version is None else {"schema_version": version}
    raw = json.dumps(payload).encode()
    (store.root / "input.json").write_bytes(raw)
    ref = ArtifactRef(role="source", path="input.json", sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("unsupported schema reached a lock, publication, or network")

    monkeypatch.setattr(api.store.fcntl, "flock", forbidden)
    monkeypatch.setattr(api.store, "publish_bytes_no_replace", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    with pytest.raises(api.operations.WorkflowError) as exc:
        store.load(ref)
    assert exc.value.code == "unsupported_artifact_schema"
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.root.rglob("*") if p.is_file()} == before
    assert not (tmp_path / "coordination").exists()
    old = V2_SCHEMA_MODELS["paper_reader.command-result.v2"](
        schema_version="paper_reader.command-result.v2", command="route", ok=True,
        code="ok", created_at="2026-10-06T00:00:00Z", data={})
    with pytest.raises(api.operations.WorkflowError, match="unsupported_artifact_schema"):
        store.publish(old)


def test_strict_unknown_fields_and_types_rejected(api, context_data, event_data):
    for change in ({"api_version": "3"}, {"library_id": True}, {"token": "not-a-real-secret"}):
        with pytest.raises(ValidationError):
            api.official.LibraryContext(**(context_data | change))
    for change in ({"seq": "1"}, {"seq": True}, {"stage": "delete"}, {"upload_key": "not-real"}):
        with pytest.raises(ValidationError):
            api.operations.OperationEvent(**(event_data | change))
    with pytest.raises(ValidationError):
        api.operations.OperationEvent(**(event_data | {"operation_id": "../escape"}))
    for model in api.operations.V3_SCHEMA_MODELS.values():
        assert model.model_config["strict"] and model.model_config["extra"] == "forbid"
        with pytest.raises(ValidationError) as exc:
            model.model_validate({})
        assert ("schema_version",) in {e["loc"] for e in exc.value.errors()}


def test_schema_export_matches_models(api, tmp_path):
    root = Path(__file__).parents[2]
    result = subprocess.run([sys.executable, "scripts/export-v3-schemas.py", "--output-dir", str(tmp_path)],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert set(api.operations.V3_SCHEMA_MODELS) == EXPECTED_SCHEMAS
    expected_files = {f"{v}.schema.json" for v in EXPECTED_SCHEMAS}
    assert {p.name for p in tmp_path.iterdir()} == expected_files
    checked = root / "references" / "official-schemas"
    assert {p.name for p in checked.iterdir()} == expected_files
    for version, model in api.operations.V3_SCHEMA_MODELS.items():
        name = f"{version}.schema.json"
        generated = json.loads((tmp_path / name).read_text())
        assert generated == model.model_json_schema(mode="validation")
        assert generated == json.loads((checked / name).read_text())
        assert generated["properties"]["schema_version"]["const"] == version


def test_shared_analysis_contract_preserves_v2_fields_and_validation(api):
    from paper_reader.contracts import PaperReaderSummary, PaperReaderReview
    for old, new in ((PaperReaderSummary, api.analysis.Summary), (PaperReaderReview, api.analysis.Review)):
        old_schema, new_schema = old.model_json_schema(), new.model_json_schema()
        old_schema.pop("title")
        new_schema.pop("title")
        old_schema["properties"].pop("schema_version")
        new_schema["properties"].pop("schema_version")
        assert old_schema == new_schema


def test_operation_payload_is_typed_and_no_http_passthrough(api, context_data):
    from pydantic import TypeAdapter
    adapter = TypeAdapter(api.operations.ChangeOperation)
    payload = dict(type="create_note", operation_id="op_1", subject_id="paper_1", subject_title="Paper", depends_on=(),
                   target_key="ABCD2345", reason="已完成阅读审核", blockers=(), before=None,
                   payload={"parent_key": "BCDE2345", "title": "A note", "html": "<h1>A note</h1>",
                            "tags": ("read",), "content_sha256": "a" * 64})
    operation = adapter.validate_python(payload)
    assert operation.payload.parent_key == "BCDE2345"
    for change in ({"url": "http://example.invalid"}, {"method": "DELETE"}, {"reason": ""}, {"type": "delete"}):
        with pytest.raises(ValidationError):
            adapter.validate_python(payload | change)
    with pytest.raises(ValidationError):
        adapter.validate_python(payload | {"payload": payload["payload"] | {"token": "not-real"}})
    for root in (Path("relative"), Path("../run")):
        with pytest.raises(ValidationError):
            api.operations.BoundArtifactRef(run_root=root, run_id="run_1",
                artifact=dict(role="note", path="note/a", sha256="a" * 64, size_bytes=1))


@pytest.mark.parametrize("value", [3.0, "3", True])
def test_api_version_rejects_noninteger_literals(api, context_data, value):
    for validate in (
        lambda data: api.official.LibraryContext.model_validate(data),
        lambda data: api.official.LibraryContext.model_validate_json(json.dumps(data)),
    ):
        with pytest.raises(ValidationError):
            validate(context_data | {"api_version": value})


def test_upload_and_collection_patch_can_bind_a_created_predecessor(api):
    from pydantic import TypeAdapter
    adapter = TypeAdapter(api.operations.ChangeOperation)
    common = dict(operation_id="op_next", subject_id="paper_1", subject_title="Paper", depends_on=("op_create",),
                  target_key="ABCD2345", reason="完成已批准的入库", blockers=(),
                  before={"kind": "predecessor", "operation_id": "op_create"})
    upload = common | dict(type="upload_attachment", payload={"filename": "论文.pdf", "source": {
        "resolved_path": "/synthetic/paper.pdf", "sha256": "a" * 64, "size_bytes": 10, "device": 1, "inode": 2}})
    patch = common | dict(type="add_to_collections", payload={"collections": ("BCDE2345",)})
    for data in (upload, patch):
        operation = adapter.validate_python(data)
        assert operation.before.operation_id == "op_create"
        with pytest.raises(ValidationError):
            adapter.validate_python(data | {"depends_on": ()})
