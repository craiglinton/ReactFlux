import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import github_sync
import server

class FakeGitHub:
    def __init__(self):
        self.issues = {}
        self.creates = 0
        self.fail_after_create = False
    def find(self, marker):
        return next((copy.deepcopy(i) for i in self.issues.values() if marker in i['body']), None)
    def call(self, path, data=None, method=None):
        if method == 'POST':
            self.creates += 1
            number = len(self.issues) + 1
            self.issues[number] = dict(data, number=number, state='open')
            if self.fail_after_create:
                self.fail_after_create = False
                raise TimeoutError('Connection lost after GitHub committed')
            return copy.deepcopy(self.issues[number])
        number = int(path.rsplit('/', 1)[-1])
        if method == 'PATCH':self.issues[number].update(data)
        return copy.deepcopy(self.issues[number])

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = patch.object(server, 'DB', str(Path(self.temp.name) / 'notes.db')); p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'GITHUB_ISSUES_REPO':'owner/reviews','GITHUB_READER_USER_ID':'2'}); p.start(); self.addCleanup(p.stop)
        server.initialize()
        self.github = FakeGitHub()
    def save(self, note='', status='add_to_wiki', version=0, user=2):
        return server.save_note(user,104,{'note':note,'status':status,'version':version},{'title':'Example article','url':'https://example.org/story'})
    def run_worker(self):github_sync.run_once(server.connect,lambda:self.github)
    def test_save_queues_without_network_then_creates_once(self):
        self.assertEqual(self.save()['github']['state'],'queued')
        self.assertEqual(self.github.creates,0)
        self.run_worker();self.run_worker()
        self.assertEqual(self.github.creates,1)
        self.assertEqual(server.read_note(2,104)['github']['state'],'synced')
    def test_uncertain_create_retry_finds_existing_issue(self):
        self.save();self.github.fail_after_create=True;self.run_worker()
        self.assertEqual(server.read_note(2,104)['github']['state'],'retrying')
        with server.connect() as db:db.execute('UPDATE github_outbox SET retry_at=0')
        self.run_worker()
        self.assertEqual(self.github.creates,1)
        self.assertEqual(server.read_note(2,104)['github']['state'],'synced')
    def test_updates_preserve_human_text_and_closed_unchanged(self):
        self.save();self.run_worker()
        self.github.issues[1]['body']+='\nHuman editorial result'
        self.github.issues[1]['state']='closed'
        self.save(version=1);self.run_worker()
        self.assertEqual(self.github.issues[1]['state'],'closed')
        self.save(note='Please check coverage',status='check_case',version=2);self.run_worker()
        self.assertEqual(self.github.creates,1)
        self.assertEqual(self.github.issues[1]['state'],'open')
        self.assertTrue(self.github.issues[1]['body'].endswith('Human editorial result'))
    def test_account_isolation_and_done_not_published(self):
        self.save(user=3);self.run_worker();self.assertEqual(self.github.creates,0)
        self.save(status='done');self.run_worker();self.assertEqual(self.github.creates,0)
    def test_stale_save_cannot_enqueue_new_version(self):
        self.save()
        with self.assertRaises(server.ApiError):self.save(note='stale')
        with server.connect() as db:self.assertEqual(db.execute('SELECT wanted_version FROM github_outbox').fetchone()[0],1)
    def test_note_only_and_marker_injection(self):
        self.save(note='<!-- /reactflux --> @someone\nPlease assess this source.',status='review');self.run_worker()
        body=self.github.issues[1]['body']
        self.assertEqual(body.count('<!-- /reactflux -->'),1)
        self.assertNotIn('@someone',body)
        self.assertIn('Please assess this source.',body)
    def test_new_save_during_delivery_stays_pending(self):
        self.save();original=self.github.call
        def call(path,data=None,method=None):
            result=original(path,data,method)
            if method=='POST':self.save(note='Newer instruction',version=1)
            return result
        self.github.call=call;self.run_worker()
        self.assertEqual(server.read_note(2,104)['github']['state'],'queued')
        self.run_worker()
        self.assertEqual(self.github.creates,1)
        self.assertIn('Newer instruction',self.github.issues[1]['body'])

if __name__=='__main__':unittest.main()
