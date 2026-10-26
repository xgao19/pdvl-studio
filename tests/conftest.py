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


@pytest.fixture()
def model_stream(monkeypatch):
    """Real HTTP/SSE boundary with deterministic model replies, including tool fragments."""
    import json
    from copy import deepcopy
    import httpx
    from pdvl import providers
    def install(replies, web=None):
        replies = iter(replies)
        sent = []
        def handle(request):
            if request.url.host == 'ollama.com' and request.url.path.startswith('/api/'):
                assert web is not None, 'Unexpected web service request'
                return web(request)
            payload = json.loads(request.content)
            sent.append((str(request.url), deepcopy(payload)))
            reply = next(replies)
            assert payload['stream'] is True
            if request.url.path.endswith('/responses'):
                events = []
                for item in reply.get('output', []):
                    if item.get('type') == 'message':
                        for piece in item.get('content', []):
                            body = piece.get('text', '')
                            events.extend({'type': 'response.output_text.delta', 'delta': c} for c in (body[:3], body[3:]) if c)
                events.append({'type': 'response.completed', 'response': {'status': 'completed', **reply}})
            else:
                result = reply['choices'][0]['message']
                events = []
                body = result.get('content') or ''
                for chunk in (body[:3], body[3:]):
                    if chunk:
                        events.append({'choices': [{'delta': {'content': chunk}}]})
                for i, call in enumerate(result.get('tool_calls') or []):
                    function = call['function']
                    events.extend([
                        {'choices': [{'delta': {'tool_calls': [{'index': i, 'id': call['id'], 'function': {'name': function['name'], 'arguments': function['arguments'][:4]}}]}}]},
                        {'choices': [{'delta': {'tool_calls': [{'index': i, 'function': {'arguments': function['arguments'][4:]}}]}}]},
                    ])
                events.append({'model': reply.get('model', payload['model']), 'usage': reply.get('usage', {}),
                               'choices': [{'delta': {}, 'finish_reason': 'tool_calls' if result.get('tool_calls') else 'stop'}]})
            body = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n' for e in events) + 'data: [DONE]\n\n'
            return httpx.Response(200, text=body, headers={'Content-Type': 'text/event-stream'})
        real_client = httpx.AsyncClient
        monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
        return sent
    return install
