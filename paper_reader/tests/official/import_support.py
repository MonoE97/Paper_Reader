"""Synthetic HTTP boundary for real import planning/execution/recovery tests."""
import hashlib
import json
from urllib.parse import parse_qs, unquote, urlsplit

from paper_reader.official.models import HttpResponse


class ImportTransport:
    def __init__(self, case, plan):
        self.context = case.gateway.context
        self.version = case.gateway.version
        self.items = {i.key: i.raw_json for i in case.gateway.inventory}
        self.collections = case.gateway.collections
        self.files = {}
        self.permits = {}
        self.calls = []
        self.faults = {}
        self.plan, self.store = plan, case.store
        self.root = case.path.parent
        self.hook = None

    def response(self, status=200, data=None, **headers):
        return HttpResponse(status=status, headers={'Zotero-Server-ID': self.context.server_id,
            'Zotero-API-Version': '3', 'Last-Modified-Version': str(self.version), **headers},
            body=data if isinstance(data, bytes) else json.dumps(data).encode())

    def save(self, key, data):
        self.version += 1
        self.items[key] = {'key': key, 'version': self.version,
            'data': {**data, 'key': key, 'version': self.version}}

    def request(self, method, url, *, headers, body):
        path = urlsplit(url).path.removeprefix('/api/users/0/')
        query = parse_qs(urlsplit(url).query)
        if method == 'GET':
            if path == 'collections':
                rows = [{'key': c.key, 'version': c.version, 'data': {'name': c.name,
                    'parentCollection': c.parent_key or False}} for c in self.collections]
            elif path in ('items', 'items/top'):
                rows = list(self.items.values())
                if path == 'items/top':
                    rows = [r for r in rows if not r['data'].get('parentItem')]
                if 'itemKey' in query:
                    rows = [r for r in rows if r['key'] == query['itemKey'][0]]
            elif path.endswith('/children'):
                parent = path.split('/')[1]
                rows = [r for r in self.items.values() if r['data'].get('parentItem') == parent]
            elif path.endswith('/file/view/url'):
                key = path.split('/')[1]
                return self.response(data=self.files[key].as_uri().encode()) if key in self.files else self.response(404)
            else:
                key = path.split('/')[1]
                return self.response(data=self.items[key]) if key in self.items else self.response(404)
            start, limit = int(query.get('start', ['0'])[0]), int(query.get('limit', ['100'])[0])
            return self.response(data=rows[start:start + limit], **{'Total-Results': str(len(rows))})
        if method == 'POST' and path == 'items':
            data, = json.loads(body)
            stage, key = 'create', data['key']
            operation = next(o for o in self.plan.operations if o.target_key == key and o.type.startswith('create_'))
        elif method == 'PATCH':
            stage, key = 'patch', path.split('/')[1]
            operation = next(o for o in self.plan.operations if o.type == 'add_to_collections' and o.target_key == key)
        elif path.startswith('/api/local/uploads/'):
            stage = 'upload_transfer'
            token = path.rsplit('/', 1)[1]
            key = self.permits[token]['key']
            operation = next(o for o in self.plan.operations if o.type == 'upload_attachment' and o.target_key == key)
        else:
            values = parse_qs(body.decode())
            stage = 'upload_register' if 'upload' in values else 'upload_authorize'
            key = path.split('/')[1]
            operation = next(o for o in self.plan.operations if o.type == 'upload_attachment' and o.target_key == key)
        events = self.store.events(operation.operation_id)
        assert events[-1].state == 'started' and events[-1].stage == stage
        self.calls.append((stage, key, headers.copy(), body))
        if self.hook:
            self.hook(stage, key)
        fault = self.faults.pop(stage, None)
        if fault == 'before':
            raise TimeoutError('SECRET-MUST-NOT-LEAK')
        if isinstance(fault, int):
            return self.response(fault)
        if stage == 'create':
            assert int(headers['If-Unmodified-Since-Version']) == self.version
            self.save(key, data)
            result = self.response(data={'successful': {'0': self.items[key]}, 'unchanged': {}, 'failed': {}})
        elif stage == 'patch':
            assert int(headers['If-Unmodified-Since-Version']) == self.items[key]['version']
            self.save(key, {**self.items[key]['data'], **json.loads(body)})
            result = self.response(204)
        elif stage == 'upload_authorize':
            assert headers['If-None-Match'] == '*'
            if key in self.files:
                return self.response(data={'exists': 1})
            token = 'temporary' + str(len(self.permits))
            self.permits[token] = {'key': key, **{k: v[0] for k, v in values.items()}}
            result = self.response(data={'url': self.context.base_url + 'local/uploads/' + token,
                'uploadKey': token, 'contentType': 'application/pdf', 'prefix': '', 'suffix': ''})
        elif stage == 'upload_transfer':
            assert 'Zotero-API-Key' not in headers and 'Zotero-Server-ID' not in headers
            assert hashlib.md5(body).hexdigest() == self.permits[token]['md5']
            self.permits[token]['bytes'] = body
            result = self.response(201)
        else:
            assert headers['If-None-Match'] == '*'
            permit = self.permits[values['upload'][0]]
            target = self.root / ('stored-' + key + '.pdf')
            target.write_bytes(permit['bytes'])
            self.files[key] = target
            self.save(key, {**self.items[key]['data'], 'md5': permit['md5'], 'filename': permit['filename'],
                'mtime': int(permit['mtime'])})
            result = self.response(204)
        if fault == 'after':
            raise TimeoutError('SECRET-MUST-NOT-LEAK')
        return result
