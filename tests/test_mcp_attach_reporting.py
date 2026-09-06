from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from capy_developer import desktop_cli, mcp
from capy_developer.errors import DeveloperError


def test_fresh_native_attach_restarts_bounded_reporting(monkeypatch):
    start = Mock()
    monkeypatch.setattr(desktop_cli, 'start_sync', start)
    core = SimpleNamespace(config=object(), attach_development=Mock(return_value={'ok': True}))
    assert mcp._call(core, 'capy_development_attach', {'handoff_id': 'synthetic'}) == {'ok': True}
    core.attach_development.assert_called_once_with('synthetic')
    start.assert_called_once_with(core.config)


def test_rejected_attach_does_not_start_reporting(monkeypatch):
    start = Mock()
    monkeypatch.setattr(desktop_cli, 'start_sync', start)
    core = SimpleNamespace(config=object(), attach_development=Mock(side_effect=DeveloperError('REJECTED', 'synthetic')))
    with pytest.raises(DeveloperError):
        mcp._call(core, 'capy_development_attach', {'handoff_id': 'synthetic'})
    start.assert_not_called()
