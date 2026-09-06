"""Fixed-origin bounded HTTPS submission transport with a total request deadline."""
import hashlib
import http.client
import re
import time
from urllib.parse import urlsplit
from ..errors import DeveloperError
from ..link_protocol import canonical, decode_json, origin
from ..submission_protocol import PREFIX, MAX_BYTES

class SubmissionTransport:
    def __init__(self, timeout=30):
        self.timeout=min(timeout,30)

    def _request(self, site, endpoint, pair, payload, size, *, binary=False, generation=None):
        origin(site)
        if re.fullmatch(r'(capabilities|pending-v0|sub_[0-9a-f]{32}/(grant|bytes))',endpoint) is None:
            raise DeveloperError('TRANSFER_DESTINATION_INVALID','Invalid fixed transfer endpoint')
        parsed=urlsplit(site); path=PREFIX+endpoint
        headers={'Authorization':'Bearer '+pair['secret'],'Accept':'application/json','Content-Length':str(size),
                 'Content-Type':'application/octet-stream' if binary else 'application/json'}
        if binary: headers.update({'X-Capy-Device':pair['device_id'],'X-Capy-Generation':str(generation)})
        connection=http.client.HTTPSConnection(parsed.hostname,parsed.port,timeout=self.timeout)
        deadline=time.monotonic()+self.timeout
        def remaining():
            left=deadline-time.monotonic()
            if left<=0: raise TimeoutError()
            if connection.sock: connection.sock.settimeout(left)
        try:
            connection.putrequest('POST',path)
            for key,value in headers.items(): connection.putheader(key,value)
            connection.endheaders(); sent=0; digest=hashlib.sha256()
            while sent<size:
                remaining(); chunk=payload.read(min(65536,size-sent))
                if not chunk: raise DeveloperError('TRANSFER_BYTES_CHANGED','Candidate bytes changed during transfer')
                connection.send(chunk); sent+=len(chunk); digest.update(chunk)
            if binary and digest.hexdigest()!=pair['_candidate_sha256']:
                raise DeveloperError('TRANSFER_BYTES_CHANGED','Candidate bytes changed during transfer')
            remaining(); response=connection.getresponse()
            if response.status==404 and endpoint=='capabilities':
                raise DeveloperError('TRANSFER_UPGRADE_REQUIRED','The paired site does not support candidate transfer')
            if not 200<=response.status<300:
                code='TRANSFER_REDIRECT_REFUSED' if 300<=response.status<400 else 'TRANSFER_REMOTE_REJECTED'
                raise DeveloperError(code,'The paired site rejected this transfer operation')
            result=bytearray()
            while len(result)<=262144:
                remaining(); chunk=response.read1(min(65536,262145-len(result)))
                if not chunk: break
                result.extend(chunk)
            return decode_json(bytes(result),max_bytes=262144)
        except (OSError,http.client.HTTPException):
            raise DeveloperError('TRANSFER_OFFLINE','The paired site could not complete this transfer') from None
        finally: connection.close()

    def post(self,site,endpoint,body,pair):
        import io
        raw=canonical(body)
        if len(raw)>262144: raise DeveloperError('TRANSFER_REQUEST_TOO_LARGE','Transfer JSON exceeds its bound')
        return self._request(site,endpoint,pair,io.BytesIO(raw),len(raw))

    def upload(self,site,grant,pair,stream):
        size=grant['selection']['candidate_size_bytes']
        if type(size) is not int or not 0<size<=MAX_BYTES: raise DeveloperError('TRANSFER_REQUEST_TOO_LARGE','Candidate exceeds transfer bound')
        return self._request(site,grant['submission_id']+'/bytes',{**pair,'_candidate_sha256':grant['selection']['candidate_sha256']},stream,size,binary=True,generation=grant['generation'])
