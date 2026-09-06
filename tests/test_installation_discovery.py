import hashlib
import json

import pytest

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.desktop.setup import Setup
from capy_developer.errors import DeveloperError
from capy_developer.installation import discover, roots


def config(root):
    return Config(*(root / name for name in ("data", "cache", "repos", "trees", "temp")))


def installed(tmp_path):
    original = config(tmp_path / "custom")
    core = DeveloperCore(original)
    path = tmp_path / "client" / "config.toml"
    path.parent.mkdir()
    path.write_text('model = "unchanged"\n[mcp_servers.unrelated]\ncommand = "never-run"\n')
    Setup(core, config_path=path).install(native=False)
    return original, path


def test_fresh_discovery_does_not_create_any_roots(tmp_path):
    default = config(tmp_path / "new")
    result = discover(default=default, config_path=tmp_path / "absent.toml")
    assert result["status"] == "FRESH_PROPOSAL"
    assert not default.data_root.parent.exists()


def test_exact_custom_roots_reused_without_config_or_catalog_writes(tmp_path):
    original, path = installed(tmp_path)
    before = {p: p.read_bytes() for p in (path, original.database, original.data_root / "desktop/setup.json")}
    default = config(tmp_path / "default")
    for _ in range(2):
        result = discover(default=default, config_path=path)
        assert result["config"] == original
        assert result["source"] == "HISTORICAL_SETUP"
    assert roots(result["config"]) == roots(original)
    assert not default.data_root.exists()
    assert all(p.read_bytes() == payload for p, payload in before.items())


@pytest.mark.parametrize("change", ["receipt", "block", "missing_catalog", "malformed", "unowned"])
def test_recognized_broken_setup_never_falls_back(tmp_path, change):
    original, path = installed(tmp_path)
    if change == "receipt":
        receipt = original.data_root / "desktop/setup.json"
        value = json.loads(receipt.read_text())
        value["python"] = "/foreign/python"
        receipt.write_text(json.dumps(value))
    elif change == "block":
        path.write_text(path.read_text().replace('args = [', 'args = ["unexpected", '))
    elif change == "missing_catalog":
        original.database.unlink()
    elif change == "malformed":
        path.write_text("invalid [ TOML")
    else:
        (original.data_root / "desktop/setup.json").unlink()
    default = config(tmp_path / "default")
    with pytest.raises(DeveloperError) as caught:
        discover(default=default, config_path=path)
    assert caught.value.code == "INSTALLATION_CONFLICT"
    assert not default.data_root.exists()


def test_two_catalogs_require_explicit_selection(tmp_path):
    original, path = installed(tmp_path)
    default = config(tmp_path / "default")
    DeveloperCore(default)
    with pytest.raises(DeveloperError):
        discover(default=default, config_path=path)
    assert discover(default=default, config_path=path, explicit=original)["config"] == original


def test_default_existing_and_partial_installation(tmp_path):
    default = config(tmp_path / "default")
    DeveloperCore(default)
    assert discover(default=default, config_path=tmp_path / "absent")["source"] == "DEFAULT"
    default.database.unlink()
    (default.data_root / "desktop").mkdir()
    with pytest.raises(DeveloperError):
        discover(default=default, config_path=tmp_path / "absent")


def test_symlink_and_unowned_config_are_not_executed(tmp_path):
    original, path = installed(tmp_path)
    target = tmp_path / "target"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(DeveloperError):
        discover(default=config(tmp_path / "default"), config_path=path)


def test_unrelated_settings_preserved_without_capy_entry(tmp_path):
    path = tmp_path / "config.toml"
    content = b'[mcp_servers.other]\ncommand = "never-execute-me"\n'
    path.write_bytes(content)
    assert discover(default=config(tmp_path / "new"), config_path=path)["status"] == "FRESH_PROPOSAL"
    assert path.read_bytes() == content


def test_validated_locator_reuses_exact_roots_and_binds_receipt(tmp_path):
    original, _ = installed(tmp_path)
    receipt = original.data_root / "installation.json"
    raw = json.dumps({"schema": "capy.installation/v0", "roots": roots(original)}).encode()
    receipt.write_bytes(raw)
    locator = tmp_path / "installation.json"
    locator.write_text(json.dumps({"schema": "capy.installation-locator/v0", "receipt": str(receipt),
                                   "sha256": hashlib.sha256(raw).hexdigest()}))
    default = config(tmp_path / "new")
    assert discover(default=default, config_path=tmp_path / "absent", locator=locator)["config"] == original
    receipt.write_bytes(raw + b" ")
    with pytest.raises(DeveloperError):
        discover(default=default, config_path=tmp_path / "absent", locator=locator)
    assert not default.data_root.exists()


def test_pinned_entrypoint_roots_override_different_global_locator(tmp_path, monkeypatch):
    from capy_developer import cli, installation
    original, _ = installed(tmp_path)
    other = config(tmp_path / 'other')
    DeveloperCore(other)
    monkeypatch.setattr(installation, 'located_config', lambda path: other)
    for key, value in roots(original).items():
        monkeypatch.setenv(key, value)
    result = cli.run(['installation','inspect'])
    assert result['source'] == 'EXPLICIT'
    assert result['technical_details']['roots'] == roots(original)
