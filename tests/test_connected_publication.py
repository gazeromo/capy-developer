"""Provider-free connected V1 canary through verification and native transfer."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.desktop.submissions import Submissions
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.link_protocol import canonical


class ConnectedPublicationTests(unittest.TestCase):
    evidence_root = None
    def test_connected_canary_exact_native_transfer(self):
        with tempfile.TemporaryDirectory(prefix='cc-' , dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            core = DeveloperCore(Config(root/'data', root/'cache', root/'repos', root/'worktrees', Path('/tmp')/root.name))
            session = core.start_development({'idempotency_key':'canary', 'request':'Create a provider-free connected read application.', 'new':{'name':'Connected read', 'application_id':'test.connected_read'}})
            workspace = Path(session['workspace']['native_path'])
            for name in ('conformance', 'tests'):
                shutil.rmtree(workspace/name)
            shutil.copytree(Path(__file__).parent/'fixtures/connected_read', workspace, dirs_exist_ok=True)
            run_git(['config','user.name','Canary'],cwd=workspace)
            run_git(['config','user.email','canary@localhost'],cwd=workspace)
            run_git(['add','--all'],cwd=workspace)
            run_git(['commit','-m','Provider-free connected canary'],cwd=workspace)
            commit = run_git(['rev-parse','HEAD'],cwd=workspace)
            verification = core.verify_development({'session_id':session['session_id'],'application_id':'test.connected_read','candidate_commit':commit,'idempotency_key':'verify-canary'})
            self.assertEqual(verification['status'],'PASSED',json.dumps(verification))
            candidate = core.create_release_candidate(verification['verification_id'])
            inspected = core.inspect_release_candidate(candidate['release_candidate_id'])
            self.assertEqual(inspected['format_schema'],'capy.application-release-candidate/v1')
            self.assertEqual(inspected['bundle']['sha256'],candidate['bundle']['sha256'])
            site='site_'+'1'*32; device='dev_'+'2'*32; handoff='hof_'+'3'*32; submission='sub_'+'4'*32; now=1800000000
            companion=Companion(core,credential_store=FileCredentials(test_owned=True),clock=lambda:now)
            selection=dict(handoff_id=handoff,project_id=candidate['project_id'],application_id='test.connected_read',session_id=session['session_id'],verification_id=verification['verification_id'],source_commit=commit,candidate_id=candidate['release_candidate_id'],candidate_sha256=candidate['bundle']['sha256'],candidate_size_bytes=candidate['bundle']['size_bytes'])
            with companion.state.connect() as db:
                db.execute('INSERT INTO pairs VALUES (?,?,?,?,?,?,?,?,?,?)',(site,'https://fixture.example','b'*32,'synthetic-secret',None,device,'principal-1',now+300,'APPROVED','Fixture'))
                request=canonical(dict(device_id=device,principal_id='principal-1',authority_id='authority-1')).decode()
                db.execute('INSERT INTO handoffs(handoff_id,site_id,request,session_id,project_id,pair_installation_id) VALUES (?,?,?,?,?,?)',(handoff,site,request,session['session_id'],candidate['project_id'],'b'*32))
            grant=dict(schema='capy.candidate-transfer-grant/v0',submission_id=submission,site_id=site,device_id=device,generation=1,expires_at=now+300,consent_revision='source-package-v0',installation_id='b'*32,principal_id='principal-1',authority_id='authority-1',selection=selection)
            ack=dict(schema='capy.candidate-custody/v0',submission_id=submission,candidate_id=candidate['release_candidate_id'],candidate_sha256=candidate['bundle']['sha256'],candidate_size_bytes=candidate['bundle']['size_bytes'],status='RECEIVED')
            transport=Mock()
            transport.post.side_effect=lambda _site,endpoint,_body,_pair: dict(schema='capy.candidate-capabilities/v0',site_id=site,device_id=device,supported=True,max_candidate_bytes=32000000) if endpoint=='capabilities' else copy.deepcopy(grant)
            uploads=[]
            def upload(_site,_grant,_pair,stream):
                uploads.append(stream.read())
                return copy.deepcopy(ack)
            transport.upload.side_effect=upload
            confirm=Mock(return_value=False)
            service=Submissions(companion,transport=transport,confirm=confirm)
            uri=f'capy-dev://submission/{submission}?site={site}&send=1'
            with self.assertRaises(DeveloperError):
                service.send(uri)
            self.assertEqual(uploads,[])
            confirm.return_value=True
            self.assertEqual(service.send(uri),ack)
            self.assertEqual(uploads,[(core.config.release_candidates_root/candidate['bundle']['sha256']/'candidate.capyrc').read_bytes()])
            self.assertEqual(confirm.call_count,2)
            if self.evidence_root is not None:
                self.evidence_root.mkdir(parents=True, exist_ok=True)
                (self.evidence_root/'candidate.capyrc').write_bytes(uploads[0])
                (self.evidence_root/'verification.json').write_text(json.dumps(verification, indent=2)+'\n')
                (self.evidence_root/'candidate.json').write_text(json.dumps(inspected, indent=2)+'\n')
                (self.evidence_root/'native-send.json').write_text(json.dumps({'ack':ack,'synthetic_transport':True,'synthetic_confirmation':True,'cancelled_upload_count':0,'confirmed_upload_count':len(uploads)}, indent=2)+'\n')
