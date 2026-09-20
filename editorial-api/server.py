"""Private article notes; authenticates every request against a fixed Miniflux server."""
import github_sync
import datetime
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB = os.environ.get('EDITORIAL_DB', '/data/editorial.sqlite3')
BASE = os.environ.get('MINIFLUX_API', 'http://miniflux:8080/miniflux/v1').rstrip('/')
ORIGIN = os.environ.get('READER_ORIGIN', 'https://feeds.ailawwiki.com')
STATUSES = {'review', 'add_to_wiki', 'check_case', 'done'}

class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

OPENER = urllib.request.build_opener(NoRedirect())

def miniflux(path, headers):
    auth = {k: headers[k] for k in ('Authorization', 'X-Auth-Token') if headers.get(k)}
    if not auth:
        raise ApiError(401, 'Sign in to read private notes.')
    try:
        with OPENER.open(urllib.request.Request(BASE + path, headers=auth), timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ApiError(401, 'Your reader session has expired.') from None
        if error.code == 404:
            raise ApiError(404, 'Article not found.') from None
        raise ApiError(502, 'The reader could not verify this request.') from None
    except (OSError, ValueError):
        raise ApiError(503, 'The reader is temporarily unavailable.') from None

def connect():
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection

def initialize():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS notes (
            user_id INTEGER NOT NULL, entry_id INTEGER NOT NULL,
            note TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
            title TEXT NOT NULL, url TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, entry_id))''')
        github_sync.initialize(db)
    os.chmod(DB, 0o600)

def read_note(user_id, entry_id):
    with connect() as db:
        row = db.execute('SELECT * FROM notes WHERE user_id=? AND entry_id=?', (user_id, entry_id)).fetchone()
    result = dict(row) if row else {'entry_id': entry_id, 'note': '', 'status': 'review', 'version': 0}
    with connect() as db:
        result['github'] = github_sync.delivery(db, user_id, entry_id)
    return result

def save_note(user_id, entry_id, payload, article):
    note, status, version = payload.get('note'), payload.get('status'), payload.get('version')
    if not isinstance(note, str) or len(note) > 10000 or status not in STATUSES or type(version) is not int or version < 0:
        raise ApiError(400, 'Check the note, review status and version.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version FROM notes WHERE user_id=? AND entry_id=?', (user_id, entry_id)).fetchone()
        current = row['version'] if row else 0
        if version != current:
            raise ApiError(409, 'This note changed elsewhere. Reload the saved note before trying again.')
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        db.execute('''INSERT INTO notes VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,entry_id) DO UPDATE SET note=excluded.note,
            status=excluded.status, version=excluded.version, title=excluded.title,
            url=excluded.url, updated_at=excluded.updated_at''',
            (user_id, entry_id, note, status, version + 1, article['title'], article['url'], now))
        github_sync.enqueue(db, user_id, entry_id, version + 1)
    github_sync.WAKE.set()
    return read_note(user_id, entry_id)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log credentials, note bodies or article URLs.

    def send_json(self, code, value):
        content = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def handle_api(self, write=False):
        try:
            if self.headers.get('Origin') not in (None, ORIGIN):
                raise ApiError(403, 'Origin not allowed.')
            user = miniflux('/me', self.headers)
            user_id = int(user['id'])
            if not write and self.path == '/editorial/notes':
                with connect() as db:
                    rows = db.execute("SELECT * FROM notes WHERE user_id=? AND (note<>'' OR status<>'review') ORDER BY updated_at DESC LIMIT 1000", (user_id,)).fetchall()
                self.send_json(200, {'notes': [dict(row) for row in rows]})
                return
            match = re.fullmatch(r'/editorial/entries/([1-9][0-9]{0,15})', self.path)
            if not match:
                raise ApiError(404, 'Not found.')
            entry_id = int(match[1])
            article = miniflux('/entries/' + str(entry_id), self.headers)
            if int(article['user_id']) != user_id:
                raise ApiError(404, 'Article not found.')
            if write:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ApiError(415, 'Send JSON.')
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise ApiError(400, 'Invalid request length.') from None
                if not 0 < size <= 65536:
                    raise ApiError(413, 'Note is too large.')
                try:
                    payload = json.loads(self.rfile.read(size))
                except (ValueError, UnicodeError):
                    raise ApiError(400, 'Invalid JSON.') from None
                if not isinstance(payload, dict):
                    raise ApiError(400, 'Invalid note.')
                result = save_note(user_id, entry_id, payload, article)
            else:
                result = read_note(user_id, entry_id)
            self.send_json(200, result)
        except ApiError as error:
            self.send_json(error.status, {'error': error.message})
        except Exception:
            self.send_json(500, {'error': 'Unable to save or load this note.'})

    def do_GET(self):
        self.handle_api()

    def do_PUT(self):
        self.handle_api(write=True)

if __name__ == '__main__':
    initialize()
    github_sync.start(connect)
    ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
