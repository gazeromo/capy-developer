"""Synthetic exact-transfer controls; never loads owner candidate data."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from capy_developer.config import Config
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.desktop.submissions import Submissions
from capy_developer.desktop.submission_transport import SubmissionTransport
from capy_developer.desktop_cli import run
from capy_developer.errors import DeveloperError
from capy_developer.link_protocol import ProtocolError,canonical
from capy_developer.submission_protocol import parse_uri,validate_grant

SITE='site_'+'1'*32
DEVICE='dev_'+'2'*32
HANDOFF='hof_'+'3'*32
SUB='sub_'+'4'*32
PROJECT='prj_'+'5'*32
SESSION='ses_'+'6'*32
VER='ver_'+'7'*32
CAND='rc_'+'8'*32
URI=f'capy-dev://submission/{SUB}?site={SITE}&send=1'
NOW=1800000000

@unittest.skipUnless(os.name == 'posix', 'Protected file transfer is POSIX-only; protocol tests remain portable')
class TransferTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name).resolve()
  config=Config(root/'data',root/'cache',root/'repo',root/'worktrees',root/'temp');config.ensure()
  self.payload=b'synthetic immutable candidate bytes';digest=hashlib.sha256(self.payload).hexdigest()
  self.path=config.release_candidates_root/digest/'candidate.capyrc';self.path.parent.mkdir();self.path.write_bytes(self.payload)
  self.selection=dict(handoff_id=HANDOFF,project_id=PROJECT,application_id='apps.fixture',session_id=SESSION,verification_id=VER,source_commit='a'*40,candidate_id=CAND,candidate_sha256=digest,candidate_size_bytes=len(self.payload))
  candidate=dict(ok=True,format_schema='capy.application-release-candidate/v1',release_candidate_id=CAND,project_id=PROJECT,application_id='apps.fixture',session_id=SESSION,verification_id=VER,source={'commit':'a'*40},bundle={'sha256':digest,'size_bytes':len(self.payload)})
  self.core=SimpleNamespace(config=config,inspect_release_candidate=Mock(return_value=candidate))
  self.companion=Companion(self.core,credential_store=FileCredentials(test_owned=True),clock=lambda:NOW)
  self.grant=dict(schema='capy.candidate-transfer-grant/v0',submission_id=SUB,site_id=SITE,device_id=DEVICE,generation=1,expires_at=NOW+300,consent_revision='source-package-v0',installation_id='b'*32,principal_id='principal-1',authority_id='authority-1',selection=self.selection)
  with self.companion.state.connect() as db:
   db.execute('INSERT INTO pairs VALUES (?,?,?,?,?,?,?,?,?,?)',(SITE,'https://fixture.example','b'*32,'synthetic-secret',None,DEVICE,'principal-1',NOW+300,'APPROVED','Fixture'))
   request=canonical(dict(device_id=DEVICE,principal_id='principal-1',authority_id='authority-1')).decode()
   db.execute('INSERT INTO handoffs(handoff_id,site_id,request,session_id,project_id,pair_installation_id) VALUES (?,?,?,?,?,?)',(HANDOFF,SITE,request,SESSION,PROJECT,'b'*32))
  self.transport=Mock(); self.transport.post.side_effect=lambda site,endpoint,body,pair: dict(schema='capy.candidate-capabilities/v0',site_id=SITE,device_id=DEVICE,supported=True,max_candidate_bytes=32000000) if endpoint=='capabilities' else copy.deepcopy(self.grant)
  self.ack=dict(schema='capy.candidate-custody/v0',submission_id=SUB,candidate_id=CAND,candidate_sha256=digest,candidate_size_bytes=len(self.payload),status='RECEIVED')
  self.uploads=[]
  def upload(site,grant,pair,stream):
   self.uploads.append(stream.read()); return copy.deepcopy(self.ack)
  self.transport.upload.side_effect=upload
  self.confirm=Mock(return_value=True)
  self.service=Submissions(self.companion,transport=self.transport,confirm=self.confirm)
 def test_exact_transfer_replay_and_unchanged_handoff(self):
  with self.companion.state.connect() as db: before=[tuple(x) for x in db.execute('SELECT * FROM handoffs')]
  self.assertEqual(self.service.send(URI),self.ack)
  self.assertEqual(self.service.send(URI),self.ack)
  self.assertEqual(self.uploads,[self.payload]);self.confirm.assert_called_once()
  with self.companion.state.connect() as db: self.assertEqual(before,[tuple(x) for x in db.execute('SELECT * FROM handoffs')])
  self.assertEqual(self.service.history()[0]['state'],'RECEIVED')
 def test_lost_ack_retries_same_archive_without_reconfirmation(self):
  self.transport.upload.side_effect=DeveloperError('TRANSFER_OFFLINE','synthetic')
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.assertEqual(self.service.history()[0]['state'],'RETRYABLE_FAILURE')
  self.transport.upload.side_effect=lambda *args:copy.deepcopy(self.ack)
  self.service=Submissions(self.companion,transport=self.transport,confirm=self.confirm)
  self.assertEqual(self.service.send(URI),self.ack);self.confirm.assert_called_once()
 def test_authority_and_selection_negative_controls(self):
  changes=[('installation_id','c'*32),('principal_id','other'),('authority_id','other'),('device_id','dev_'+'f'*32),('site_id','site_'+'f'*32),('expires_at',NOW),('generation',2)]
  for key,value in changes:
   with self.subTest(key=key):
    old=self.grant[key];self.grant[key]=value
    with self.assertRaises((DeveloperError,ProtocolError)):self.service.send(URI)
    self.grant[key]=old
  for key,value in [('project_id','prj_'+'f'*32),('session_id','ses_'+'f'*32),('candidate_id','rc_'+'f'*32),('source_commit','f'*40),('candidate_sha256','f'*64),('candidate_size_bytes',1)]:
   with self.subTest(key=key):
    old=self.selection[key];self.selection[key]=value
    with self.assertRaises((DeveloperError,ProtocolError)):self.service.send(URI)
    self.selection[key]=old
  self.transport.upload.assert_not_called();self.confirm.assert_not_called()
 def test_cancel_does_not_send(self):
  self.confirm.return_value=False
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.transport.upload.assert_not_called()
 def test_symlink_and_changed_bytes_refused(self):
  self.path.write_bytes(b'x'*len(self.payload))
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.path.unlink();target=self.path.parent/'other';target.write_bytes(self.payload);self.path.symlink_to(target)
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.transport.upload.assert_not_called()
 def test_stale_pair_and_reselected_candidate_cannot_replay(self):
  self.service.send(URI)
  self.grant['selection']={**self.selection,'source_commit':'f'*40}
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.assertEqual(len(self.uploads),1)
 def test_malformed_ack_retains_failure(self):
  self.ack['candidate_sha256']='f'*64
  with self.assertRaises(ProtocolError):self.service.send(URI)
  self.assertEqual(self.service.history()[0]['state'],'RETRYABLE_FAILURE')
 def test_parent_symlink_refused(self):
  original=self.path.parent; moved=original.with_name('moved');original.rename(moved);original.symlink_to(moved,target_is_directory=True)
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.transport.upload.assert_not_called()
 def test_revocation_during_local_confirmation_refused(self):
  def revoke(details):
   with self.companion.state.connect() as db: db.execute("UPDATE pairs SET state='REVOKED'")
   return True
  self.service.confirm=revoke
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.transport.upload.assert_not_called()
 def test_new_generation_requires_distinct_confirmation(self):
  self.service.send(URI);self.grant['generation']=2
  self.service.send(URI.replace('send=1','send=2'))
  self.assertEqual(self.confirm.call_count,2)
 def test_closed_grant_fields(self):
  self.grant['upload_url']='https://other.example'
  with self.assertRaises(ProtocolError):self.service.send(URI)
  self.confirm.assert_not_called()
 def test_old_server_never_gets_upload(self):
  self.transport.post.side_effect=DeveloperError('TRANSFER_UPGRADE_REQUIRED','unsupported')
  with self.assertRaises(DeveloperError):self.service.send(URI)
  self.transport.upload.assert_not_called();self.confirm.assert_not_called()

class ProtocolTests(unittest.TestCase):
 def test_strict_uri_before_core_init(self):
  for uri in [URI+'&x=1',URI.replace('&send=1','&send=01'),URI+'#fragment',URI.replace('?site=','/?site='),URI.replace('send=1','send=2147483648'),URI.replace('submission','%73ubmission')]:
   with self.subTest(uri=uri),patch('capy_developer.desktop_cli.DeveloperCore') as core,patch('sys.stdout',new_callable=io.StringIO):
    self.assertEqual(run(['handoff','open','--uri',uri]),1);core.assert_not_called()
 def test_old_handler_submission_dispatch(self):
  companion=Mock();companion.prepared_for_launch=False
  with patch('capy_developer.desktop_cli.preflight_open') as preflight,patch('capy_developer.desktop_cli.DeveloperCore'),patch('capy_developer.desktop_cli.Companion',return_value=companion),patch('capy_developer.desktop.submissions.Submissions') as service,patch('sys.stdout',new_callable=io.StringIO):
   service.return_value.send.return_value={'status':'RECEIVED'}
   self.assertEqual(run(['handoff','open','--uri',URI]),0)
   preflight.assert_called_once();service.return_value.send.assert_called_once_with(URI);companion.open_uri.assert_not_called()
 def test_transport_redirect_is_not_followed(self):
  response=Mock(status=302)
  connection=Mock();connection.getresponse.return_value=response
  with patch('http.client.HTTPSConnection',return_value=connection):
   with self.assertRaises(DeveloperError) as error:SubmissionTransport().post('https://fixture.example','capabilities',{},dict(secret='fixture'))
  self.assertEqual(error.exception.code,'TRANSFER_REDIRECT_REFUSED');self.assertEqual(connection.putrequest.call_count,1)
 def test_transport_binary_has_finite_length(self):
  raw=b'fixture';result=canonical({'ok':True});response=Mock(status=200);response.read1.side_effect=[result,b'']
  connection=Mock();connection.getresponse.return_value=response
  grant={'submission_id':SUB,'generation':1,'selection':{'candidate_size_bytes':len(raw),'candidate_sha256':hashlib.sha256(raw).hexdigest()}}
  with patch('http.client.HTTPSConnection',return_value=connection):
   self.assertEqual(SubmissionTransport().upload('https://fixture.example',grant,dict(secret='fixture',device_id=DEVICE),io.BytesIO(raw)),{'ok':True})
  connection.putheader.assert_any_call('Content-Length','7');connection.putheader.assert_any_call('Content-Type','application/octet-stream')
  connection.send.assert_called_once_with(raw)
