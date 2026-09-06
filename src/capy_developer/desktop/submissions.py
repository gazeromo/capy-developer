"""User-triggered exact immutable candidate disclosure. No development lifecycle calls."""
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
from ..errors import DeveloperError
from ..link_protocol import canonical
from ..submission_protocol import DISCLOSURE, parse_uri, validate_ack, validate_capabilities, validate_grant
from .companion import require
from .submission_transport import SubmissionTransport


def open_candidate(path):
    """Traverse each directory through no-follow descriptors, preventing path swaps."""
    if os.name != 'posix' or not hasattr(os,'O_NOFOLLOW'):
        raise DeveloperError('TRANSFER_PLATFORM_UNSUPPORTED','Protected candidate transfer requires POSIX file descriptors')
    directory=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory);directory=child
        return os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    finally:
        os.close(directory)


def identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def confirm_native(details):
    if platform.system()!='Darwin':
        raise DeveloperError('TRANSFER_CONFIRMATION_UNAVAILABLE','Local transfer confirmation is qualified on macOS only')
    text=(details['origin']+'\n\nCandidate '+details['candidate_id']+'\nCommit '+details['source_commit']+
          '\n'+str(details['candidate_size_bytes'])+' bytes\n\n'+DISCLOSURE)
    # Values remain a single argument; neither a shell nor application-authored code is invoked.
    script='on run argv\n display dialog (item 1 of argv) with title "Send this exact Capy version?" buttons {"Cancel", "Send this version"} default button "Cancel" cancel button "Cancel"\n return "confirmed"\nend run'
    try:
        result=subprocess.run(['/usr/bin/osascript','-e',script,text],capture_output=True,text=True,timeout=180,check=False)
    except (OSError,subprocess.TimeoutExpired):
        return False
    return result.returncode==0 and result.stdout.strip()=='confirmed'


class Submissions:
    def __init__(self, companion, *, transport=None, confirm=None):
        self.companion=companion; self.core=companion.core; self.state=companion.state
        self.transport=transport or SubmissionTransport(); self.confirm=confirm or confirm_native
        # Separate store preserves compatibility with old link schema and completed sessions.
        with self.state.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS candidate_transfers (
              submission_id TEXT NOT NULL,generation INTEGER NOT NULL,site_id TEXT NOT NULL,
              binding TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,
              ack TEXT,error_code TEXT,PRIMARY KEY(submission_id,generation))''')

    def history(self):
        with self.state.connect() as db:
            return [dict(row) for row in db.execute('SELECT submission_id,generation,site_id,state,error_code FROM candidate_transfers ORDER BY rowid')]

    def send(self,uri):
        parsed=parse_uri(uri)
        with self.companion._lock():
            pair=self.companion._approved(parsed['site_id'])
            caps=self.transport.post(pair['origin'],'capabilities',{'schema':'capy.candidate-capabilities/v0','site_id':pair['site_id'],'device_id':pair['device_id']},pair)
            validate_capabilities(caps,pair)
            grant=validate_grant(self.transport.post(pair['origin'],parsed['submission_id']+'/grant',{'schema':'capy.candidate-grant-request/v0','site_id':pair['site_id'],'device_id':pair['device_id'],'generation':parsed['generation']},pair))
            require(all(grant[k]==parsed[k] for k in parsed) and all(grant[k]==pair[k] for k in ('site_id','device_id','installation_id','principal_id')) and self.companion.clock()<grant['expires_at'], 'TRANSFER_AUTHORITY_MISMATCH','Transfer grant does not match this active local connection')
            selected=grant['selection']; handoff=self.state.handoff(selected['handoff_id'])
            self.companion._pair_for_handoff(handoff)
            request=json.loads(handoff['request'])
            require(handoff['site_id']==pair['site_id'] and handoff['project_id']==selected['project_id'] and handoff['session_id']==selected['session_id'] and request['authority_id']==grant['authority_id'], 'TRANSFER_HANDOFF_MISMATCH','Selected version does not belong to this local handoff')
            candidate=self.core.inspect_release_candidate(selected['candidate_id'])
            require(candidate['ok'] and candidate.get('format_schema')=='capy.application-release-candidate/v1' and all(candidate[k]==selected[k] for k in ('project_id','application_id','session_id','verification_id')) and candidate['release_candidate_id']==selected['candidate_id'] and candidate['source']['commit']==selected['source_commit'] and candidate['bundle']['sha256']==selected['candidate_sha256'] and candidate['bundle']['size_bytes']==selected['candidate_size_bytes'], 'TRANSFER_CANDIDATE_MISMATCH','The exact approved candidate is not available')
            binding=canonical({k:v for k,v in grant.items() if k!='expires_at'}).decode()
            with self.state.connect() as db:
                old=db.execute('SELECT * FROM candidate_transfers WHERE submission_id=? AND generation=?',(parsed['submission_id'],parsed['generation'])).fetchone()
                require(old is None or old['binding']==binding,'TRANSFER_CONFLICT','This transfer generation has a different immutable selection')
                if old is not None and old['state']=='RECEIVED': return json.loads(old['ack'])
                db.execute('INSERT OR IGNORE INTO candidate_transfers(submission_id,generation,site_id,binding,state) VALUES (?,?,?,?,?)',(parsed['submission_id'],parsed['generation'],parsed['site_id'],binding,'AWAITING_CONFIRMATION'))
            if old is None or not old['confirmed']:
                require(self.confirm({'origin':pair['origin'],**selected}) is True,'TRANSFER_CANCELLED','Source transfer was not confirmed locally')
                with self.state.connect() as db:
                    db.execute('UPDATE candidate_transfers SET confirmed=1,state=? WHERE submission_id=? AND generation=?',('CONFIRMED',parsed['submission_id'],parsed['generation']))
            require(self.companion.clock()<grant['expires_at'],'TRANSFER_EXPIRED','The transfer grant expired before sending')
            self.companion._pair_for_handoff(handoff)
            root=self.core.config.release_candidates_root.expanduser().absolute()
            path=root/selected['candidate_sha256']/'candidate.capyrc'
            try:
                try:
                    descriptor=open_candidate(path)
                except OSError:
                    raise DeveloperError('TRANSFER_BYTES_UNSAFE','Candidate path is not a protected regular file') from None
                with os.fdopen(descriptor,'rb') as stream:
                    before=os.fstat(stream.fileno())
                    require(stat.S_ISREG(before.st_mode) and before.st_size==selected['candidate_size_bytes'],'TRANSFER_BYTES_UNSAFE','Candidate is not the approved regular file')
                    digest=hashlib.sha256()
                    remaining=selected['candidate_size_bytes']
                    while remaining:
                        chunk=stream.read(min(65536,remaining))
                        require(bool(chunk),'TRANSFER_BYTES_CHANGED','Candidate was truncated before disclosure')
                        digest.update(chunk); remaining-=len(chunk)
                    require(stream.read(1)==b'','TRANSFER_BYTES_CHANGED','Candidate grew before disclosure')
                    require(digest.hexdigest()==selected['candidate_sha256'] and identity(os.fstat(stream.fileno()))==identity(before),'TRANSFER_BYTES_CHANGED','Candidate bytes changed before disclosure')
                    stream.seek(0)
                    with self.state.connect() as db: db.execute('UPDATE candidate_transfers SET state=?,error_code=NULL WHERE submission_id=? AND generation=?',('SENDING',parsed['submission_id'],parsed['generation']))
                    ack=validate_ack(self.transport.upload(pair['origin'],grant,pair,stream),grant)
                    require(identity(os.fstat(stream.fileno()))==identity(before),'TRANSFER_BYTES_CHANGED','Candidate changed while sending')
                with self.state.connect() as db: db.execute('UPDATE candidate_transfers SET state=?,ack=? WHERE submission_id=? AND generation=?',('RECEIVED',canonical(ack).decode(),parsed['submission_id'],parsed['generation']))
                return ack
            except Exception as exc:
                with self.state.connect() as db: db.execute('UPDATE candidate_transfers SET state=?,error_code=? WHERE submission_id=? AND generation=?',('RETRYABLE_FAILURE',exc.code if isinstance(exc,DeveloperError) else 'TRANSFER_FAILED',parsed['submission_id'],parsed['generation']))
                raise
