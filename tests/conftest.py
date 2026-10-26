import pytest
from fastapi.testclient import TestClient
from pdvl.api import app

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('PDVL_HOME', str(tmp_path))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.delenv('CUSTOM_API_KEY', raising=False)
    monkeypatch.setenv('PDVL_CODEX_ENABLED','0')
    monkeypatch.setenv('PDVL_TEST_TOKEN', 'fake-runtime-token')
    runtime = tmp_path / 'codex'
    runtime.mkdir()
    (runtime / 'config.toml').write_text('''model = "test-model"
model_provider = "test"
[model_providers.test]
name = "Test provider"
base_url = "http://localhost:9999/v1"
env_key = "PDVL_TEST_TOKEN"
wire_api = "responses"
requires_openai_auth = false
''')
    with TestClient(app) as c:
        yield c
