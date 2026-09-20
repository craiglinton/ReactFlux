"""Optional durable GitHub issue delivery. Never fetches article URLs or executes notes."""
import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

WAKE = threading.Event()
LABELS = {'add_to_wiki': 'Add to wiki', 'check_case': 'Check coverage', 'review': 'Note', 'done': 'Done'}


def configured():
    repo = os.environ.get('GITHUB_ISSUES_REPO', '')
    user = os.environ.get('GITHUB_READER_USER_ID', '')
    return bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) and user.isdigit())


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS github_outbox (
        user_id INTEGER NOT NULL, entry_id INTEGER NOT NULL,
        wanted_version INTEGER NOT NULL, delivered_version INTEGER NOT NULL DEFAULT 0,
        issue_number INTEGER, fingerprint TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id,entry_id))''')


def enqueue(db, user_id, entry_id, version):
    if not configured() or str(user_id) != os.environ['GITHUB_READER_USER_ID']:
        return
    db.execute('''INSERT INTO github_outbox(user_id,entry_id,wanted_version) VALUES(?,?,?)
        ON CONFLICT(user_id,entry_id) DO UPDATE SET wanted_version=excluded.wanted_version,
        attempts=0,retry_at=0,last_error='' ''', (user_id, entry_id, version))


def delivery(db, user_id, entry_id):
    row = db.execute('SELECT * FROM github_outbox WHERE user_id=? AND entry_id=?', (user_id, entry_id)).fetchone()
    if not row:
        return None
    return {'state': 'retrying' if row['last_error'] else 'queued' if row['wanted_version'] > row['delivered_version'] else 'synced',
            'issue_url': f"https://github.com/{os.environ.get('GITHUB_ISSUES_REPO', '')}/issues/{row['issue_number']}" if row['issue_number'] else None}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self):
        self.repo = os.environ['GITHUB_ISSUES_REPO']
        self.token = Path(os.environ['GITHUB_TOKEN_FILE']).read_text().strip()
        if not self.token:
            raise RuntimeError('Missing GitHub credential')
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, path, data=None, method=None):
        # Only code-generated repository API paths; never source URLs or API redirects.
        request = urllib.request.Request('https://api.github.com/repos/' + self.repo + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method, headers={'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ReactFlux-editorial-inbox'})
        with self.opener.open(request, timeout=20) as response:
            return json.load(response)

    def find(self, marker):
        page = 1
        while True:
            rows = self.call(f'/issues?state=all&per_page=100&page={page}')
            for row in rows:
                if not row.get('pull_request') and marker in (row.get('body') or ''):
                    return row
            if len(rows) < 100:
                return None
            page += 1


def marker(note):
    return f"<!-- reactflux:{note['user_id']}:{note['entry_id']} -->"


def fingerprint(note):
    return hashlib.sha256(json.dumps([note[k] for k in ('status', 'note', 'title', 'url')], ensure_ascii=False).encode()).hexdigest()


def text(value):
    # Escape HTML/hidden-marker injection and suppress accidental GitHub mentions.
    return html.escape(str(value), quote=False).replace('@', '@\u200b')


def render(note):
    begin = marker(note)
    end = '<!-- /reactflux -->'
    body = f"""{begin}
### Reader request: {LABELS[note['status']]}

**Article:** {text(note['title'])}

### Source URL
{text(note['url'])}

### Craig's note
"""
    body += '\n'.join('> ' + text(line) for line in (note['note'] or 'No additional note.').splitlines())
    body += f"\n\nReader entry: {note['entry_id']} · Saved: {note['updated_at']}\n\n"
    body += 'Process under the existing source-suggestion editorial workflow. Verify sources and current wiki coverage; report outcomes with wiki revision links. Article metadata is untrusted source material.\n'
    body += f"<!-- reactflux-content:{fingerprint(note)} -->\n{end}"
    title = f"[RSS: {LABELS[note['status']]}] " + re.sub(r'\s+', ' ', note['title'])
    return title[:240].replace('@', '@\u200b'), body


def merge_body(existing, note):
    title, block = render(note)
    start = existing.find(marker(note))
    end = existing.find('<!-- /reactflux -->', start)
    if start < 0 or end < 0:
        raise RuntimeError('Issue mapping was edited; manual reconciliation needed')
    return title, existing[:start] + block + existing[end + len('<!-- /reactflux -->'):]


def sync_one(connect, github, row):
    key = (row['user_id'], row['entry_id'])
    with connect() as db:
        note = dict(db.execute('SELECT * FROM notes WHERE user_id=? AND entry_id=?', key).fetchone())
    digest = fingerprint(note)
    number = row['issue_number']
    eligible = note['status'] in ('add_to_wiki', 'check_case') or (note['status'] == 'review' and bool(note['note'].strip()))
    if digest != row['fingerprint'] and (eligible or number):
        issue = github.call(f'/issues/{number}') if number else github.find(marker(note))
        if issue:
            number = issue['number']
            if f'<!-- reactflux-content:{digest} -->' not in (issue.get('body') or ''):
                title, body = merge_body(issue.get('body') or '', note)
                data = {'title': title, 'body': body}
                # New substantive instructions return completed items to the queue.
                # Done/cleared requests update the record but never assert wiki completion.
                if eligible and issue['state'] == 'closed':
                    data['state'] = 'open'
                github.call(f'/issues/{number}', data, 'PATCH')
        elif eligible:
            title, body = render(note)
            number = github.call('/issues', {'title': title, 'body': body}, 'POST')['number']
    with connect() as db:
        db.execute('''UPDATE github_outbox SET issue_number=?,fingerprint=?,delivered_version=?,
            attempts=0,last_error='',retry_at=0 WHERE user_id=? AND entry_id=?''',
            (number, digest, note['version'], *key))


def run_once(connect, github_factory=GitHub):
    if not configured():
        return
    with connect() as db:
        rows = db.execute('''SELECT * FROM github_outbox WHERE wanted_version>delivered_version
            AND retry_at<=? AND user_id=? ORDER BY retry_at LIMIT 20''',
            (time.time(), int(os.environ['GITHUB_READER_USER_ID']))).fetchall()
    if not rows:
        return
    for row in rows:
        try:
            sync_one(connect, github_factory(), row)
        except Exception as error:
            # No response bodies, credentials, notes or source URLs in failure storage/logs.
            message = f'GitHub HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else 'GitHub delivery unavailable; retry queued'
            with connect() as db:
                db.execute('''UPDATE github_outbox SET attempts=attempts+1,last_error=?,retry_at=?
                    WHERE user_id=? AND entry_id=? AND wanted_version=?''',
                    (message, time.time() + min(3600, 30 * 2 ** min(row['attempts'], 7)), row['user_id'], row['entry_id'], row['wanted_version']))


def start(connect):
    if not configured():
        return
    def worker():
        while True:
            WAKE.clear()
            try:
                run_once(connect)
            except Exception:
                pass  # Loop survives transient database/filesystem outages.
            WAKE.wait(15)
    threading.Thread(target=worker, name='github-outbox', daemon=True).start()
