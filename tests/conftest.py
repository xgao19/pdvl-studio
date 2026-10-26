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


@pytest.fixture()
def pdf_factory():
    """Real PDF text streams with known page contents; no network or rendering dependency."""
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    def make(*texts):
        writer = PdfWriter()
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        for body in texts:
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
                                            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            escaped = body.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream.set_data(('BT /F1 12 Tf 72 720 Td (' + escaped + ') Tj ET').encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
        target = io.BytesIO();writer.write(target)
        return target.getvalue()
    return make
