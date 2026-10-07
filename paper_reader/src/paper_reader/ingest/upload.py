"""Three upload stages within the executor's lock and immutable approval."""
from paper_reader.official.uploads import UploadError
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.execution_state import record
from paper_reader.ingest.execution import expected_before, fresh_import


def upload_attachment(plan, op, approval, *, gateway, credentials, store):
    """Never persist permits, and never resend a stage in the same attempt."""
    before = expected_before(plan, op, store)
    expected_md5 = before.raw_json['data'].get('md5') or None
    permit = None
    for stage in ('upload_authorize', 'upload_transfer', 'upload_register'):
        key = None
        if stage != 'upload_transfer':
            try:
                key = credentials.get_key(plan.context)
            except WorkflowError as exc:
                record(plan, op.operation_id, approval, store, state='blocked', stage=stage, error_code=exc.code)
                return exc.code
        # A native dialog or source change may happen between any two requests.
        fresh_import(plan, op, gateway, store)
        record(plan, op.operation_id, approval, store, state='started', stage=stage)
        try:
            if stage == 'upload_authorize':
                permit = gateway.request_upload(op.target_key, op.payload.source, filename=op.payload.filename,
                    expected_file_md5=expected_md5, credentials=key)
                if permit.upload_key is None:
                    return None  # exists=1 still requires full file readback
            elif stage == 'upload_transfer':
                receipt = gateway.send_upload(permit, op.payload.source)
                if (receipt.attachment_key != op.target_key or receipt.md5 != permit.md5
                        or receipt.size_bytes != op.payload.source.size_bytes):
                    raise UploadError('write_uncertain', uncertain=True)
            else:
                result = gateway.register_upload(permit, expected_file_md5=expected_md5, credentials=key)
                if result.state != 'succeeded' or result.key != op.target_key:
                    raise UploadError(result.error_code or 'write_uncertain', uncertain=result.state != 'failed')
        except UploadError as exc:
            state = 'uncertain' if exc.uncertain else 'blocked'
            record(plan, op.operation_id, approval, store, state=state, stage=stage, error_code=exc.code)
            if exc.code == 'auth_required' and stage != 'upload_transfer':
                credentials.invalidate(plan.context)
            return exc.code
        except Exception:
            record(plan, op.operation_id, approval, store, state='uncertain', stage=stage, error_code='write_uncertain')
            return 'write_uncertain'
        finally:
            del key
    return None
