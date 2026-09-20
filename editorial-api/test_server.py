import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import server

class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(server, 'DB', str(Path(self.temp.name) / 'notes.db'))
        self.db_patch.start()
        server.initialize()
        def fake_miniflux(path, headers):
            token = headers.get('X-Auth-Token')
            if token not in ('user-one', 'user-two'):
                raise server.ApiError(401, 'Unauthorized')
            owner = 1 if token == 'user-one' else 2
            if path == '/me':
                return {'id': owner}
            if path == '/entries/9':
                return {'id': 9, 'user_id': 1, 'title': 'Test article', 'url': 'https://example.org/story'}
            raise server.ApiError(404, 'Not found')
        self.auth_patch = patch.object(server, 'miniflux', fake_miniflux)
        self.auth_patch.start()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:' + str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.auth_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def call(self, path='/editorial/entries/9', token='user-one', data=None, origin=server.ORIGIN):
        headers = {'Content-Type': 'application/json', 'Origin': origin}
        if token:
            headers['X-Auth-Token'] = token
        request = urllib.request.Request(self.base + path, headers=headers,
            method='PUT' if data is not None else 'GET',
            data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_private_roundtrip_and_stale_write(self):
        payload = {'note': '<script>still plain text</script>', 'status': 'check_case', 'version': 0}
        self.assertEqual(self.call(data=payload)[0], 200)
        status, saved = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(saved['note'], payload['note'])
        self.assertEqual(saved['version'], 1)
        self.assertEqual(self.call(data=payload)[0], 409)
        self.assertEqual(self.call()[1]['version'], 1)
        self.assertEqual(len(self.call('/editorial/notes')[1]['notes']), 1)
        self.assertEqual(self.call('/editorial/notes', token='user-two')[1]['notes'], [])

    def test_authentication_and_article_ownership(self):
        self.assertEqual(self.call(token=None)[0], 401)
        self.assertEqual(self.call(token='user-two')[0], 404)
        self.assertEqual(self.call(token='user-two', data={'note':'x','status':'review','version':0})[0], 404)
        self.assertEqual(self.call(origin='https://other.example')[0], 403)
        self.assertEqual(self.call('/editorial/entries/0')[0], 404)

    def test_validation(self):
        for data in [{'note':'x','status':'unknown','version':0},
                     {'note':'x','status':'review','version':True},
                     {'note':'x'*10001,'status':'review','version':0}, []]:
            self.assertEqual(self.call(data=data)[0], 400)

if __name__ == '__main__':
    unittest.main()
