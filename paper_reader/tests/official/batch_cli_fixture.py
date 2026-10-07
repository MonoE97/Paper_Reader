"""Subprocess test adapter: real CLI/executor/storage, synthetic external service."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from conftest import FakeGateway, WriteGateway, Credentials
from paper_reader import official_cli
from paper_reader.official.models import ItemSnapshot
from paper_reader.operations.store import FileRunStore

path = Path(os.environ['PAPER_READER_BATCH_FIXTURE'])
cases = json.loads(path.read_text())


def live(plan):
    case = next(case for case in cases if case['run_id'] == plan.run_id)
    store = FileRunStore(Path(case['run_root']), coordination_root=Path(sys.argv[sys.argv.index('--coordination-root') + 1]))
    parent = ItemSnapshot.model_validate_json(json.dumps(case['parent']))
    children = tuple(ItemSnapshot.model_validate_json(json.dumps(c)) for c in case['children'])
    gateway = FakeGateway(plan.context, parent, children, Path(case['pdf_path']))
    class PersistentGateway(WriteGateway):
        def create_items(self, *args, **kwargs):
            try:
                return super().create_items(*args, **kwargs)
            finally:
                case['sent'] += 1
                case['children'] = [c.model_dump(mode='json') for c in self.children]
                path.write_text(json.dumps(cases))
    gateway = PersistentGateway(gateway, store)
    gateway.operation_id = plan.operations[0].operation_id
    gateway.mode = 'lost_without_write' if case['name'] == 'C' else 'success'
    return gateway


official_cli.live = live
official_cli.NativeCredentialProvider = Credentials
official_cli.app()
