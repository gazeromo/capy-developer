import copy
import json

import pytest

from capy_developer.core import DeveloperCore
from capy_developer.errors import DeveloperError
from capy_developer.harness_client import HarnessClient
from capy_developer.link_protocol import make_uri
import test_desktop
from test_desktop import SITE, HANDOFF, PROJECT, SESSION, NOW, request


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path.resolve()))
    case = test_desktop.DesktopTests()
    case.setUp()
    yield case
    case.tearDown()


def test_claim_links_same_session_and_replay_without_start(setup):
    case = setup
    case.transport.request = request(schema='capy.developer-link-request/v1', intent='EXISTING', project_id=PROJECT)
    before = copy.deepcopy(case.core.value)
    uri = make_uri(SITE, HANDOFF, 1)
    case.companion.prepare_uri(uri, local_request={'request': 'Resume this app', 'session_id': SESSION})
    case.companion.prepare_uri(uri, local_request={'request': 'Resume this app', 'session_id': SESSION})
    assert case.core.starts == []
    assert case.core.continues == []
    assert case.core.value == before
    assert case.companion.state.handoff(HANDOFF)['session_id'] == SESSION
    assert case.companion.state.handoff(HANDOFF)['project_id'] == PROJECT
    with pytest.raises(DeveloperError, match='existing linked handoff'):
        case.companion.existing_session(SESSION)


def test_session_dirty_terminal_or_wrong_claim_fails(setup):
    case = setup
    case.core.value['workspace']['dirty'] = True
    with pytest.raises(DeveloperError, match='commit or resolve'):
        case.companion.existing_session(SESSION)
    case.core.value['workspace']['dirty'] = False
    case.core.value['status'] = 'COMPLETED'
    with pytest.raises(DeveloperError, match='not ready'):
        case.companion.existing_session(SESSION)
    case.core.value['status'] = 'READY'
    case.transport.request = request(schema='capy.developer-link-request/v1', intent='EXISTING', project_id='prj_'+'9'*32)
    with pytest.raises(DeveloperError, match='claimed project'):
        case.companion.prepare_uri(make_uri(SITE, HANDOFF, 1), local_request={'request': 'Resume', 'session_id': SESSION})
    assert case.core.starts == []
    assert case.companion.state.handoff(HANDOFF)['session_id'] is None


def test_begin_uses_existing_wire_project_without_session_field(setup, monkeypatch):
    case = setup
    harness = HarnessClient(case.core, companion=case.companion)
    client = 'cli_'+'8'*32
    pair = case.companion.state.pair_record(SITE)
    with case.companion.state.connect() as db:
        db.execute('INSERT INTO harness_clients VALUES (?,?,?,?,?,?,NULL)', (SITE, 'codex', pair['installation_id'], client, 'v1', 'MCP_STDIO'))
    case.transport.request = request(schema='capy.developer-link-request/v1', intent='EXISTING', project_id=PROJECT)
    posts = []
    def post(site, operation, value):
        posts.append(value)
        return copy.deepcopy(case.transport.request)
    monkeypatch.setattr(harness, '_post', post)
    from capy_developer import workspace_resume
    monkeypatch.setattr(workspace_resume, 'prepare', lambda *args: {'supported': True})
    result = harness.begin({'client_id': client, 'intent_id': 'a'*32, 'request': 'Resume preserved app', 'session_id': SESSION})
    assert posts == [{'client_id': client, 'intent_id': 'a'*32, 'parent_handoff_id': None, 'project_id': PROJECT}]
    assert result['development']['session_id'] == SESSION
    assert not case.core.starts


def test_v1_projection_does_not_mutate_candidate_or_v0(setup, monkeypatch):
    case = setup
    core = case.core
    v0 = {'schema': 'capy.development-release-candidate-result/v0', 'ok': True}
    assert DeveloperCore._publication_action(core, v0) is v0
    candidate = {'schema': 'capy.development-release-candidate-result/v1', 'ok': True, 'session_id': SESSION}
    assert DeveloperCore._publication_action(core, candidate)['next_action']['action'] == 'LINK_EXISTING_SESSION'
    case.transport.request = request(schema='capy.developer-link-request/v1', intent='EXISTING', project_id=PROJECT)
    case.companion.prepare_uri(make_uri(SITE, HANDOFF, 1), local_request={'request': 'Resume', 'session_id': SESSION})
    monkeypatch.setattr('time.time', lambda: NOW)
    result = DeveloperCore._publication_action(core, candidate)
    assert result['next_action']['handoff_id'] == HANDOFF
    assert result['next_action']['review_url'] == 'https://capy.example/developer/requests/' + HANDOFF
    assert 'next_action' not in candidate
