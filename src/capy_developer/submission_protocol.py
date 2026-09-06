"""Additive closed candidate transfer protocol; never changes Developer Link V0."""
import re
from .link_protocol import ProtocolError

MAX_BYTES = 32_000_000
PREFIX = '/api/candidate-submissions/'
DISCLOSURE = ('Sending shares packaged application source, contracts, packaged tests/fixtures, '
              'and verification evidence with this Capy release service. It does not share Git '
              'history, Codex conversations, other projects, or unrelated files. It will not install the app.')

def check(value, code='TRANSFER_PROTOCOL_INVALID'):
    if not value:
        raise ProtocolError(code)

def identifier(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'_[0-9a-f]{32}', value) is not None

def integer(value):
    return type(value) is int and 1 <= value <= 2147483647

def parse_uri(value):
    check(isinstance(value, str) and len(value) <= 256)
    match = re.fullmatch(r'capy-dev://submission/(sub_[0-9a-f]{32})\?site=(site_[0-9a-f]{32})&send=([1-9][0-9]{0,9})', value)
    check(match is not None and integer(int(match[3])))
    return dict(submission_id=match[1], site_id=match[2], generation=int(match[3]))

def validate_capabilities(value, pair):
    check(isinstance(value, dict) and set(value) == {'schema','site_id','device_id','supported','max_candidate_bytes'})
    check(value['schema']=='capy.candidate-capabilities/v0' and value['site_id']==pair['site_id'] and value['device_id']==pair['device_id'])
    check(value['supported'] is True and type(value['max_candidate_bytes']) is int and value['max_candidate_bytes']==MAX_BYTES, 'TRANSFER_UPGRADE_REQUIRED')
    return value

def validate_grant(value):
    check(isinstance(value,dict) and set(value)==set('schema submission_id site_id device_id generation expires_at consent_revision installation_id principal_id authority_id selection'.split()))
    check(value['schema']=='capy.candidate-transfer-grant/v0' and value['consent_revision']=='source-package-v0')
    for key,prefix in [('submission_id','sub'),('site_id','site'),('device_id','dev')]:
        check(identifier(value[key],prefix))
    check(integer(value['generation']) and type(value['expires_at']) is int and value['expires_at']>0)
    check(isinstance(value['installation_id'],str) and re.fullmatch('[0-9a-f]{32}',value['installation_id']) is not None)
    for key in ('principal_id','authority_id'):
        check(isinstance(value[key],str) and 0<len(value[key])<=128 and re.fullmatch(r'[A-Za-z0-9_.:\-]+',value[key]) is not None)
    selection=value['selection']
    check(isinstance(selection,dict) and set(selection)==set('handoff_id project_id application_id session_id verification_id source_commit candidate_id candidate_sha256 candidate_size_bytes'.split()))
    for key,prefix in [('handoff_id','hof'),('project_id','prj'),('session_id','ses'),('verification_id','ver'),('candidate_id','rc')]:
        check(identifier(selection[key],prefix))
    check(isinstance(selection['application_id'],str) and len(selection['application_id'])<=128 and re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+',selection['application_id']) is not None)
    for key,size in [('source_commit',40),('candidate_sha256',64)]:
        check(isinstance(selection[key],str) and re.fullmatch('[0-9a-f]{'+str(size)+'}',selection[key]) is not None)
    check(type(selection['candidate_size_bytes']) is int and 0<selection['candidate_size_bytes']<=MAX_BYTES)
    return value

def validate_ack(value, grant):
    check(isinstance(value,dict) and set(value)==set('schema submission_id candidate_id candidate_sha256 candidate_size_bytes status'.split()))
    check(value['schema']=='capy.candidate-custody/v0' and value['status']=='RECEIVED' and value['submission_id']==grant['submission_id'])
    check(all(value[k]==grant['selection'][k] for k in ('candidate_id','candidate_sha256','candidate_size_bytes')) and type(value['candidate_size_bytes']) is int)
    return value
