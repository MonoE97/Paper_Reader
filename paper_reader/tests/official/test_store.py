from dataclasses import replace
from hashlib import sha256
import json
import os

import pytest

from paper_reader.contracts import ArtifactRef
from paper_reader.storage import canonical_json_bytes


def test_immutable_artifacts_and_raw_bytes_survive_restart(api, store, event_data):
    # Use a result rather than an event: only append_event may commit journal truth.
    result = api.operations.CommandResult(schema_version="paper_reader.command-result.v3",
        command="plan.status", ok=True, code="ok", created_at="2026-10-06T00:00:00Z", artifacts=())
    ref = store.publish(result)
    before = (store.root / ref.path).stat().st_mtime_ns
    assert store.publish(result) == ref
    assert (store.root / ref.path).stat().st_mtime_ns == before
    raw_ref = store.publish_bytes(b"raw PDF or JSON bytes\x00", role="source")
    restarted = api.store.FileRunStore(store.root, coordination_root=store.coordination_root)
    assert restarted.load(ref) == result
    assert restarted.read_bytes(raw_ref) == b"raw PDF or JSON bytes\x00"
    with pytest.raises(api.operations.WorkflowError, match="unsupported_artifact_schema"):
        restarted.load(raw_ref)
    assert not store.coordination_root.exists()
    (store.root / raw_ref.path).write_bytes(b"changed")
    with pytest.raises(api.operations.WorkflowError, match="source_changed"):
        restarted.read_bytes(raw_ref)


def test_event_replay_hash_gap_blocks_mutation(api, store, event_data):
    first = api.operations.OperationEvent(**event_data)
    first_ref = store.append_event(first, expected_head=None)
    second = api.operations.OperationEvent(**(event_data | dict(seq=2, previous_digest=first_ref.sha256,
        state="uncertain", request_id="request_2")))
    second_ref = store.append_event(second, expected_head=first_ref.sha256)
    restarted = api.store.FileRunStore(store.root, coordination_root=store.coordination_root)
    assert restarted.events("op_1") == (first, second)
    assert restarted.append_event(first, expected_head=None) == first_ref
    assert restarted.append_event(second, expected_head=first_ref.sha256) == second_ref
    assert len(list(store.root.rglob("*.json"))) == 2
    third = api.operations.OperationEvent(**(event_data | dict(seq=3, previous_digest=second_ref.sha256,
        state="verified", request_id="request_3")))
    with pytest.raises(api.operations.WorkflowError, match="journal_corrupt"):
        restarted.append_event(third, expected_head=first_ref.sha256)
    # Change valid JSON while keeping the next link bound to the original bytes.
    (store.root / first_ref.path).write_bytes(canonical_json_bytes(first.model_dump(mode="json") | {"state": "blocked"}))
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with pytest.raises(api.operations.WorkflowError, match="journal_corrupt"):
        restarted.append_event(third, expected_head=second_ref.sha256)
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


def test_missing_sequence_and_duplicate_send_identity_rejected(api, store, event_data):
    first = api.operations.OperationEvent(**event_data)
    ref = store.append_event(first, expected_head=None)
    duplicate = api.operations.OperationEvent(**(event_data | dict(seq=2, previous_digest=ref.sha256, request_id="request_2")))
    with pytest.raises(api.operations.WorkflowError, match="journal_corrupt"):
        store.append_event(duplicate, expected_head=ref.sha256)
    # Rename simulates a lost prefix, without deleting test inputs.
    (store.root / ref.path).rename(store.root / ref.path.replace("00000000000000000001", "00000000000000000002"))
    with pytest.raises(api.operations.WorkflowError, match="journal_corrupt"):
        store.events("op_1")


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "root_replaced", "parent_replaced"])
def test_no_replace_and_path_replacement_fail_closed(api, store, tmp_path, attack):
    original = b"original"
    ref = store.publish_bytes(original, role="note")
    target = store.root / ref.path
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim"
    victim.write_bytes(b"untouched")
    if attack in ("symlink", "hardlink"):
        target.rename(target.with_suffix(".saved"))
        if attack == "symlink":
            target.symlink_to(victim)
        else:
            os.link(victim, target)
    elif attack == "root_replaced":
        store.root.rename(tmp_path / "old-run")
        store.root.mkdir()
    else:
        target.parent.rename(target.parent.with_name("old-notes"))
        target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        store.publish_bytes(original, role="note")
    assert victim.read_bytes() == b"untouched"
    assert set(p.name for p in outside.iterdir()) == {"victim"}


def test_conflicting_immutable_target_is_not_overwritten(api, store):
    ref = store.publish_bytes(b"original", role="note")
    target = store.root / ref.path
    target.write_bytes(b"occupied")
    with pytest.raises(api.operations.WorkflowError, match="source_changed"):
        store.publish_bytes(b"original", role="note")
    assert target.read_bytes() == b"occupied"


def test_resource_limits_checked_before_publication(api, store, monkeypatch, event_data):
    monkeypatch.setattr(api.store, "RESOURCE_POLICY", replace(api.store.RESOURCE_POLICY,
        structured_artifact_max_bytes=32, run_max_bytes=64, artifact_tree_max_members=8))
    with pytest.raises(api.operations.WorkflowError, match="resource_limit"):
        store.publish_bytes(b"x" * 33, role="source")
    with pytest.raises(api.operations.WorkflowError, match="resource_limit"):
        store.append_event(api.operations.OperationEvent(**event_data), expected_head=None)
    assert list(store.root.iterdir()) == []
    store.publish_bytes(b"x" * 32, role="source")
    store.publish_bytes(b"y" * 32, role="source")
    before = list(store.root.rglob("*"))
    with pytest.raises(api.operations.WorkflowError, match="resource_limit"):
        store.publish_bytes(b"z", role="source")
    assert list(store.root.rglob("*")) == before


def test_partial_event_is_not_recovered_or_promoted(api, store, event_data):
    first = api.operations.OperationEvent(**event_data)
    ref = store.append_event(first, expected_head=None)
    (store.root / ref.path).with_suffix(".writing").write_bytes(b'{"schema_version":')
    assert store.events("op_1") == (first,)
    assert (store.root / ref.path).with_suffix(".writing").read_bytes() == b'{"schema_version":'


def test_library_lock_serializes_installation_and_partitions_contexts(api, store, context_data):
    import multiprocessing
    ctx = multiprocessing.get_context("spawn")
    context = api.official.LibraryContext(**context_data)
    with store.library_lock(context):
        ready = ctx.Event()
        acquired = ctx.Event()
        process = ctx.Process(target=_take_lock, args=(store.root, store.coordination_root, context_data, ready, acquired))
        process.start()
        assert ready.wait(5)
        assert not acquired.wait(0.2)
        other_data = context_data | {"server_id": "another-instance"}
        other_ready, other_acquired = ctx.Event(), ctx.Event()
        other = ctx.Process(target=_take_lock, args=(store.root, store.coordination_root, other_data, other_ready, other_acquired))
        other.start()
        assert other_ready.wait(5)
        assert not other_acquired.wait(0.2)
    assert other_acquired.wait(5)
    other.join(5)
    assert other.exitcode == 0
    assert acquired.wait(5)
    process.join(5)
    assert process.exitcode == 0
    assert "synthetic-instance" not in str(list(store.coordination_root.rglob("*")))
    assert len(list(store.coordination_root.glob("*/*"))) == 2


def _take_lock(root, coordination_root, context_data, ready, acquired):
    from paper_reader.operations.store import FileRunStore
    from paper_reader.official.models import LibraryContext
    ready.set()
    with FileRunStore(root, coordination_root=coordination_root).library_lock(LibraryContext(**context_data)):
        acquired.set()


@pytest.mark.parametrize("replaced", ["library", "coordination"])
def test_replacing_lock_directory_cannot_split_same_library_critical_section(api, store, context_data, replaced):
    import multiprocessing
    from paper_reader.storage import UnsafeStoragePathError
    ctx = multiprocessing.get_context("spawn")
    ready, acquired = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_take_lock, args=(store.root, store.coordination_root, context_data, ready, acquired))
    entered_early = False
    try:
        with pytest.raises(UnsafeStoragePathError):
            with store.library_lock(api.official.LibraryContext(**context_data)):
                directory = store.coordination_root
                if replaced == "library":
                    directory = next(p for p in directory.glob("*/*") if p.is_dir())
                directory.rename(directory.with_name(directory.name + "-retired"))
                process.start()
                assert ready.wait(5)
                entered_early = acquired.wait(0.3)
        assert acquired.wait(5)
    finally:
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert not entered_early, "a second critical section entered while the first still held its lock"
    assert process.exitcode == 0
