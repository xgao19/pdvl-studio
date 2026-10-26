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
    with TestClient(app) as c:
        yield c
