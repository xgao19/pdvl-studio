"""Private onboarding and packaging boundaries; no real provider calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pdvl.config import codex_environment, codex_runtime, home, model_settings
from pdvl.desktop import apply_settings, desktop_lock, save_settings, settings_path, validate_settings
from pdvl import worker
from scripts.build_macos import copy_sources, audit_bundle


SETTINGS = {'api_key': 'fake-desktop-secret', 'base_url': 'https://example.test/v1/', 'model': 'test-model'}


def test_private_settings_generate_both_adapters_without_copying_the_secret(client, monkeypatch):
    before = {key: os.getenv(key) for key in ('CODEX_HOME', 'CODEX_SQLITE_HOME')}
    save_settings(SETTINGS)
    stored = json.loads(settings_path().read_text())
    assert settings_path().stat().st_mode & 0o777 == 0o600
    assert home().stat().st_mode & 0o777 == 0o700
    for name in ('CUSTOM_API_KEY', 'CUSTOM_API_BASE', 'CUSTOM_MODEL', 'PDVL_MODELS_FILE', 'PDVL_CODEX_ENABLED'):
        monkeypatch.setenv(name, '')
    apply_settings(stored)
    registry = model_settings()
    assert set(registry[m] for m in ('discuss', 'investigate', 'verify', 'write')) == {'configured-api'}
    assert registry['models'][0]['model'] == codex_runtime()['model'] == 'test-model'
    assert codex_runtime()['base_url'] == 'https://example.test/v1'
    env = codex_environment(codex_runtime())
    assert env['CUSTOM_API_KEY'] == SETTINGS['api_key']
    assert env['CODEX_HOME'] == env['CODEX_SQLITE_HOME'] == str(home() / 'codex')
    for path in [home() / 'models.json', home() / 'codex/config.toml']:
        assert SETTINGS['api_key'] not in path.read_text()
    assert before == {key: os.getenv(key) for key in before}


@pytest.mark.parametrize('change', [
    {'base_url': 'http://remote.example/v1'}, {'base_url': 'https://user:password@example.test/v1'},
    {'base_url': 'https://example.test/v1?key=secret'}, {'model': ''}, {'api_key': 'key\nexport BAD=1'},
])
def test_invalid_settings_never_replace_existing_credentials(client, change):
    save_settings(SETTINGS)
    original = settings_path().read_bytes()
    with pytest.raises(ValueError):
        save_settings({**SETTINGS, **change})
    assert settings_path().read_bytes() == original
    assert list(home().glob('tmp*')) == []


def test_local_http_and_running_instance_lock(client):
    assert validate_settings({**SETTINGS, 'base_url': 'http://localhost:11434/v1'})
    save_settings(SETTINGS)
    with desktop_lock():
        with pytest.raises(BlockingIOError):
            save_settings({**SETTINGS, 'api_key': 'different-fake-key'})
    assert json.loads(settings_path().read_text())['api_key'] == SETTINGS['api_key']


def test_configure_reads_key_only_from_stdin_and_reports_no_secret(client):
    result = subprocess.run([sys.executable, '-m', 'pdvl.desktop', '--configure'],
                            input=json.dumps(SETTINGS), text=True, capture_output=True)
    assert result.returncode == 0 and SETTINGS['api_key'] not in result.stdout + result.stderr
    assert json.loads(settings_path().read_text())['api_key'] == SETTINGS['api_key']


def test_source_allowlist_excludes_local_state_and_credentials(tmp_path):
    target = tmp_path / 'source'
    target.mkdir()
    copy_sources(target)
    files = {str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()}
    assert {'pdvl/api.py', 'web/app.js', 'configs/desktop.json', 'worker/codex/package-lock.json'} <= files
    assert not any('.local' in p or '.env' in p or 'node_modules' in p or 'test_' in p for p in files)
    audit_bundle(target)
    (target / 'settings.json').write_text('{}')
    with pytest.raises(ValueError, match='Private state'):
        audit_bundle(target)
    (target / 'settings.json').unlink()
    (target / 'external').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='External bundle symlink'):
        audit_bundle(target)


def test_changed_api_destination_never_receives_a_queued_tasks_key(client, monkeypatch):
    monkeypatch.setenv('PDVL_CODEX_ENABLED', '1')
    pid = client.post('/api/projects', json={'title': 'API configuration change'}).json()['id']
    run = client.post(f'/api/projects/{pid}/runs', json={'question': 'Queued under original provider'}).json()
    config = home() / 'codex/config.toml'
    config.write_text(config.read_text().replace('localhost:9999', 'localhost:9998'))
    def fail(*args, **kwargs):
        raise AssertionError('No subprocess should send a key to the old endpoint')
    monkeypatch.setattr(worker.subprocess, 'Popen', fail)
    result = worker.process_one()
    assert result['id'] == run['id'] and result['state'] == 'failed'
    assert 'credential destination changed' in result['error']


def test_build_rejects_a_key_accidentally_put_in_the_default_preset(tmp_path, monkeypatch):
    from scripts import build_macos
    source = tmp_path / 'source'
    (source / 'configs').mkdir(parents=True)
    (source / 'configs/desktop.json').write_text(json.dumps(SETTINGS))
    monkeypatch.setattr(build_macos, 'ROOT', source)
    target = tmp_path / 'release'
    target.mkdir()
    with pytest.raises(ValueError, match='empty API key'):
        copy_sources(target)
    assert list(target.iterdir()) == []
