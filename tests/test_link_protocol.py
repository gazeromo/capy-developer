import copy
import unittest
from capy_developer.link_protocol import *

class LinkProtocolTests(unittest.TestCase):
    def request(self):
        r={'schema':'capy.developer-link-request/v0','site_id':'site_'+'a'*32,'handoff_id':'hof_'+'b'*32,
           'device_id':'dev_'+'c'*32,'principal_id':'principal-1','authority_id':'authority-1',
           'workspace_kind':'personal','workspace_id':'workspace-1','membership_id':'membership-1',
           'intent':'NEW','parent_handoff_id':None,'release_candidate_id':None,'created_at':1,
           'expires_at':100,'launch_generation':1}
        r['request_digest']=digest({k:v for k,v in r.items() if k!='launch_generation'})
        return r
    def snapshot(self):
        s={k:None for k in SNAPSHOT_FIELDS};s.update(milestone='PREPARING',dirty=False,source_fresh=False);return s
    def test_exact_uri_and_attack_inputs(self):
        uri=make_uri('site_'+'a'*32,'hof_'+'b'*32,1)
        self.assertEqual(parse_uri(uri)['launch_generation'],1)
        for bad in [uri+'#x',uri+'&x=1',uri.replace('launch=1','launch=01'),uri.replace('launch=1','launch=2147483648'),
                    uri.replace('handoff/','handoff/%2e%2e/'),uri.replace('capy-dev:','CAPY-DEV:'),uri+'\n',
                    uri.replace('?site=','?site=%00'),uri.replace('handoff/','user@handoff/'),uri+';echo pwn']:
            with self.assertRaises(ProtocolError):parse_uri(bad)
    def test_origin_and_strict_json(self):
        self.assertEqual(origin('https://example.invalid:443'),'https://example.invalid:443')
        for bad in ['http://example.invalid','https://user:secret@example.invalid','https://example.invalid/path',
                    'https://example.invalid?x=1','https://example.invalid#x','https://example.invalid\\evil']:
            with self.assertRaises(ProtocolError):origin(bad)
        for bad in [b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'"\xff"']:
            with self.assertRaises(ProtocolError):decode_json(bad)
        with self.assertRaises(ProtocolError):decode_json(b'{}',1)
    def test_request_immutable_intent_and_launch_generation(self):
        r=self.request();validate_request(r)
        validate_request({**r,'launch_generation':2})
        for key,value in [('principal_id','other'),('intent','CONTINUE'),('source_path','/synthetic'),('expires_at',False)]:
            bad={**r,key:value}
            with self.assertRaises(ProtocolError):validate_request(bad)
    def test_event_no_false_status_or_path_fields(self):
        e={'schema':'capy.developer-link-event/v0','site_id':'site_'+'a'*32,'handoff_id':'hof_'+'b'*32,
           'device_id':'dev_'+'c'*32,'sequence':1,'snapshot':self.snapshot()}
        e['digest']=digest(e);validate_event(e)
        for field,value in [('milestone',[]),('source_fresh',True),('milestone','ACCEPTED'),('source_path','/synthetic'),('dirty',1),('candidate_id','rc_'+'d'*32)]:
            bad=copy.deepcopy(e);bad['snapshot'][field]=value;bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ProtocolError):validate_event(bad)
    def test_existing_project_v1_is_digest_bound_without_relaxing_v0(self):
        old=self.request();before=canonical(old)
        r={**old,'schema':'capy.developer-link-request/v1','intent':'EXISTING','project_id':'prj_'+'f'*32}
        r['request_digest']=digest({k:v for k,v in r.items() if k not in ('request_digest','launch_generation')})
        validate_request(r)
        validate_request(old);self.assertEqual(canonical(old),before)
        for changes in ({'schema':'capy.developer-link-request/v0'},{'intent':'NEW'},
                        {'project_id':'prj_'+'e'*32},{'project_id':'/some/repository'},
                        {'parent_handoff_id':'hof_'+'1'*32}):
            with self.assertRaises(ProtocolError):validate_request({**r,**changes})
    def test_failed_new_checks_preserve_old_candidate_but_never_promote_it(self):
        s=self.snapshot();s.update(milestone='CHECKS_FAILED',project_id='prj_'+'1'*32,session_id='ses_'+'2'*32,
            verification_id='ver_new',verification_commit='6'*40,verification_status='FAILED',candidate_id='rc_'+'3'*32,
            candidate_verification_id='ver_old',candidate_sha256='4'*64,candidate_commit='5'*40,candidate_size=100,
            source_commit='6'*40)
        validate_snapshot(s)
        with self.assertRaises(ProtocolError):validate_snapshot({**s,'milestone':'CANDIDATE_PREPARED'})
        with self.assertRaises(ProtocolError):validate_snapshot({**s,'source_fresh':True})

if __name__=='__main__':unittest.main()
