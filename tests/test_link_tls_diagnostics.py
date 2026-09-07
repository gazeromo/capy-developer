import ssl
import urllib.error

import pytest

from capy_developer.desktop.transport import Transport
from capy_developer.errors import DeveloperError


@pytest.mark.parametrize('operation', ['guide', 'post'])
@pytest.mark.parametrize('wrapped', [False, True])
def test_certificate_rejection_is_specific_and_never_retried(monkeypatch, operation, wrapped):
    transport = Transport()
    certificate = ssl.SSLCertVerificationError('private diagnostic must not be echoed')
    failure = urllib.error.URLError(certificate) if wrapped else certificate
    calls = []
    def reject(*args, **kwargs):
        calls.append(args)
        raise failure
    monkeypatch.setattr(transport.opener, 'open', reject)
    with pytest.raises(DeveloperError) as caught:
        if operation == 'guide':
            transport.connection_info('https://capy.test')
        else:
            transport.post('https://capy.test', '/api/developer-link/pair/poll', {}, 'synthetic-secret')
    assert caught.value.code == 'LINK_TLS_UNTRUSTED'
    assert 'private diagnostic' not in str(caught.value)
    assert 'synthetic-secret' not in str(caught.value)
    assert len(calls) == 1


def test_network_outage_still_reports_offline(monkeypatch):
    transport = Transport()
    def reject(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError())
    monkeypatch.setattr(transport.opener, 'open', reject)
    with pytest.raises(DeveloperError) as caught:
        transport.post('https://capy.test', '/api/developer-link/pair/poll', {})
    assert caught.value.code == 'LINK_OFFLINE'
