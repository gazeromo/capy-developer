from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.mcp import handle

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='cc-', dir='/tmp' if Path('/tmp').is_dir() else None)
        self.root=Path(self.tmp.name)
        self.core=DeveloperCore(Config(*(self.root/n for n in ('data','cache','repos','work','temp'))))
    def tearDown(self): self.tmp.cleanup()
    def candidate(self):
        s=self.core.start_development({'idempotency_key':'new','request':'Synthetic fixture',
                                     'new':{'name':'Continuation Fixture','application_id':'apps.continuation'}})
        w=Path(s['workspace']['native_path'])
        run_git(['config','user.name','Fixture'],cwd=w);run_git(['config','user.email','fixture@localhost'],cwd=w)
        (w/'retained_behavior.py').write_text('VALUE = 42\n')
        run_git(['add','retained_behavior.py'],cwd=w);run_git(['commit','-m','Add retained behavior'],cwd=w)
        head=run_git(['rev-parse','HEAD'],cwd=w)
        v=self.core.verify_development({'session_id':s['session_id'],'application_id':'apps.continuation',
                                      'candidate_commit':head,'idempotency_key':'verify'})
        self.assertEqual(v['status'],'PASSED',json.dumps(v))
        c=self.core.create_release_candidate(v['verification_id']);self.assertTrue(c['ok'],c)
        self.core.finish_development(s['session_id'],'COMPLETED')
        return s,w,c
    def payload(self,c): return {'release_candidate_id':c['release_candidate_id'],'request':'Continue fixture','idempotency_key':'continue'}
    def test_exact_candidate_with_older_main_restart_and_dirty_child_replay(self):
        s,w,c=self.candidate();payload=self.payload(c)
        before=self.core.inspect_development(s['session_id'])['terminal']
        new=self.core.continue_development(payload)
        self.assertEqual(new['project']['project_id'],s['project']['project_id'])
        self.assertNotEqual(new['session_id'],s['session_id'])
        self.assertEqual(new['exact_base_commit'],c['source']['commit'])
        target=Path(new['workspace']['native_path'])
        self.assertEqual((target/'retained_behavior.py').read_text(),'VALUE = 42\n')
        self.assertEqual(run_git(['rev-parse','main'],cwd=w),s['exact_base_commit'])
        self.assertEqual(self.core.inspect_development(s['session_id'])['terminal'],before)
        (target/'new-unverified.txt').write_text('keep me')
        restarted=DeveloperCore(self.core.config)
        replay=handle(restarted,{'id':1,'method':'tools/call','params':{'name':'capy_development_continue','arguments':payload}})
        self.assertFalse(replay['result']['isError'])
        self.assertEqual(replay['result']['structuredContent']['session_id'],new['session_id'])
        self.assertEqual((target/'new-unverified.txt').read_text(),'keep me')
        with self.assertRaises(DeveloperError) as error:
            restarted.continue_development({**payload,'request':'different'})
        self.assertEqual(error.exception.code,'IDEMPOTENCY_CONFLICT')
    def test_unverified_parent_and_missing_object_do_not_allocate(self):
        s,w,c=self.candidate();payload=self.payload(c)
        with self.core.db.connect() as db: count=db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        (w/'dirty.txt').write_text('preserve')
        with self.assertRaises(DeveloperError) as error:self.core.continue_development(payload)
        self.assertEqual(error.exception.code,'CONTINUATION_UNVERIFIED_CHANGES')
        self.assertEqual((w/'dirty.txt').read_text(),'preserve')
        run_git(['add','dirty.txt'],cwd=w);run_git(['commit','-m','New unverified change'],cwd=w)
        with self.assertRaises(DeveloperError) as error:self.core.continue_development(payload)
        self.assertEqual(error.exception.code,'CONTINUATION_UNVERIFIED_CHANGES')
        with self.core.db.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],count)
    def test_preparation_crash_retries_same_session(self):
        s,w,c=self.candidate();payload=self.payload(c)
        with patch.object(self.core,'_complete_workspace',side_effect=OSError('synthetic environment failure')):
            with self.assertRaises(OSError):self.core.continue_development(payload)
        with self.core.db.connect() as db:
            pending=db.execute("SELECT session_id FROM sessions WHERE idempotency_key='continue'").fetchone()[0]
        self.assertEqual(self.core.continue_development(payload)['session_id'],pending)

if __name__=='__main__': unittest.main()
