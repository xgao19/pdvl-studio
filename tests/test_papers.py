"""Literature ingestion uses real PDFs and the same archive/evidence/revision chain."""
import asyncio
import hashlib
import io
import json

import httpx
import pytest
from pypdf import PdfWriter
from pdvl import papers
from pdvl.db import init_db
from pdvl.research import project_snapshot
from pdvl.tools import execute_research_tool, tools_for_mode


def project(client, title='Literature'):
    return client.post('/api/projects', json={'title': title}).json()['id']


def upload(client, pid, body, title='Paper A'):
    return client.post(f'/api/projects/{pid}/papers/pdf', params={'title': title},
                       content=body, headers={'Content-Type': 'application/pdf'})


def test_pdf_pages_search_continuation_and_evidence_revision(client, pdf_factory):
    pid = project(client)
    original = pdf_factory('Abstract only.', 'Definition: C is constant.', 'Result: ' + 'x' * 9000 + ' END')
    response = upload(client, pid, original)
    assert response.status_code == 201
    paper = response.json();aid = paper['id']
    assert paper['page_count'] == 3
    assert paper['pdf_sha256'] == hashlib.sha256(original).hexdigest()
    assert client.get('/api/artifacts/' + paper['pdf_artifact_id']).content == original
    base = f'/api/projects/{pid}'
    assert upload(client, pid, original).json()['id'] == aid
    assert len(client.get(base + '/papers').json()) == 1
    assert client.get(base + '/runs').json() == []  # An import is not a Codex execution.
    source = base + '/artifacts/' + aid + '/text'
    page = client.get(source, params={'page': 2}).json()
    assert page['text'] == 'Definition: C is constant.'
    assert page['citation'] == f'[原文 p.2](/api/artifacts/{aid}#page=2)'
    found = client.get(source, params={'query': 'END'}).json()['matches']
    assert len(found) == 1 and found[0]['page'] == 3 and found[0]['offset'] > 7000
    first = client.get(source, params={'page': 3}).json()
    second = client.get(source, params={'page': 3, 'offset': first['next_offset']}).json()
    assert first['truncated'] and not second['truncated']
    assert first['text'] + second['text'] == 'Result: ' + 'x' * 9000 + ' END'
    assert project_snapshot(pid)['papers'][0]['id'] == aid
    assert client.get(base + '/evidence').json() == []
    claim = client.post(base + '/claims', json={'title': 'Scope', 'statement': 'C is constant under these assumptions'}).json()
    payload = {'claim_id': claim['id'], 'artifact_id': aid, 'kind': 'literature',
               'verdict': 'supporting', 'description': 'Definition on PDF page 2.',
               'provenance': {'pages': [2], 'paper_source': {'pdf_sha256': 'forged'}}}
    evidence = client.post(base + '/evidence', json=payload).json()
    provenance = json.loads(evidence['provenance'])
    assert provenance['paper_source']['pages'] == [2]
    assert provenance['paper_source']['pdf_sha256'] == paper['pdf_sha256']
    assert provenance['artifact']['sha256'] == paper['sha256']
    document = client.post(base + '/documents', json={'title': 'Argument', 'text': f"Conditional result [evidence:{evidence['id']}]"}).json()
    init_db()
    saved = client.get('/api/documents/' + document['document']['id']).json()
    resolved = saved['revisions'][0]['sources'][0]
    assert resolved['artifact_id'] == aid and resolved['run_id'] == paper['run_id']
    assert resolved['claim_status'] == 'idea'
    assert client.get(source, params={'page': 2}).json()['text'] == page['text']
    payload['provenance']['pages'] = [4]
    assert client.post(base + '/evidence', json=payload).status_code == 422
    assert len(client.get(base + '/evidence').json()) == 1


def test_isolation_invalid_pages_and_failed_imports_are_atomic(client, pdf_factory):
    pid, other = project(client), project(client, 'Other')
    paper = upload(client, pid, pdf_factory('Known source')).json()
    assert client.get(f"/api/projects/{other}/artifacts/{paper['id']}/text").status_code == 404
    result = asyncio.run(execute_research_tool('read_research_artifact', {'artifact_id': paper['id']}, other))
    assert 'error' in result
    source = f"/api/projects/{pid}/artifacts/{paper['id']}/text"
    for params in ({'page': 0}, {'page': 2}, {'offset': -1}, {'offset': 999}, {'query': 'x' * 151}):
        assert client.get(source, params=params).status_code == 422
    writer = PdfWriter();writer.add_blank_page(width=612, height=792)
    blank = io.BytesIO();writer.write(blank)
    encrypted = io.BytesIO();writer.encrypt('password');writer.write(encrypted)
    for body in (b'not a pdf', blank.getvalue(), encrypted.getvalue(), b'%PDF-' + bytes(8*1024*1024)):
        assert upload(client, pid, body).status_code in (413, 422)
    assert len(client.get(f'/api/projects/{pid}/papers').json()) == 1
    assert client.post(f'/api/projects/{other}/chat', json={'paper_ids': [paper['id']], 'message': 'Read'}).status_code == 404
    assert client.post(f'/api/projects/{pid}/chat', json={'paper_ids': [paper['id']] * 3, 'message': 'Read'}).status_code == 422


@pytest.mark.parametrize('value', ['http://127.0.0.1/a.pdf', 'https://arxiv.org.evil/abs/2301.12345',
                                  'https://arxiv.org/abs/2301.12345?key=secret', '../../secret', '2301.12345v0'])
def test_arxiv_inputs_never_become_arbitrary_network_destinations(value):
    with pytest.raises(ValueError):
        papers.arxiv_id(value)


def test_real_arxiv_metadata_and_pdf_transport_are_shared_by_search_import_and_tools(client, pdf_factory, monkeypatch):
    pid = project(client)
    body = pdf_factory('Original paper.', 'Scoped result on a later page.')
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>http://arxiv.org/abs/2301.12345v2</id><title>A scoped result</title>
      <published>2023-01-01</published><summary>Abstract is not the original result.</summary>
      <author><name>A. Researcher</name></author></entry></feed>'''
    seen = []
    def handle(request):
        seen.append(request)
        assert 'authorization' not in request.headers
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, content=atom)
        assert str(request.url) == 'https://arxiv.org/pdf/2301.12345v2'
        return httpx.Response(200, content=body)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(papers.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(papers, '_arxiv_last', 0)
    search = client.get(f'/api/projects/{pid}/papers/search', params={'query': 'scale identity'}).json()
    assert search['results'][0]['arxiv_id'] == '2301.12345v2'
    assert 'Abstract-only' in search['warning']
    monkeypatch.setattr(papers, '_arxiv_last', 0)
    imported = client.post(f'/api/projects/{pid}/papers', json={'arxiv_id': 'https://arxiv.org/abs/2301.12345v2'}).json()
    assert imported['page_count'] == 2 and imported['title'] == 'A scoped result'
    reused = asyncio.run(execute_research_tool('import_arxiv_paper', {'arxiv_id': '2301.12345v2'}, pid))
    assert reused['id'] == imported['id'] and len(seen) == 3
    monkeypatch.setattr(papers, '_arxiv_last', 0)
    mismatch = client.post(f'/api/projects/{pid}/papers', json={'arxiv_id': '2301.12345v1'})
    assert mismatch.status_code == 422 and 'different version' in mismatch.json()['detail']
    assert len(client.get(f'/api/projects/{pid}/papers').json()) == 1
    assert client.get(f'/api/projects/{pid}/evidence').json() == []


def test_discuss_ollama_loop_reads_both_originals_and_records_page_provenance(client, pdf_factory, monkeypatch, tmp_path, model_stream):
    pid = project(client)
    original_a = 'C is constant; derivative is zero. ' + '"\\' * 2600
    a = upload(client, pid, pdf_factory('A abstract', original_a), 'Study A').json()
    b = upload(client, pid, pdf_factory('B abstract', 'C depends on mu; derivative is c1.'), 'Study B').json()
    registry = {mode: 'ollama' for mode in ('discuss', 'investigate', 'verify', 'write')}
    registry['models'] = [{'id': 'ollama', 'model': 'deepseek-v4.1-flash:1017', 'provider': 'custom', 'api': 'chat_completions'}]
    path = tmp_path / 'models.json';path.write_text(json.dumps(registry))
    monkeypatch.setenv('PDVL_MODELS_FILE', str(path));monkeypatch.setenv('CUSTOM_API_KEY', 'test-ollama')
    monkeypatch.setenv('CUSTOM_API_BASE', 'https://ollama.com/v1')
    final = f"The assumptions differ [原文 p.2](/api/artifacts/{a['id']}#page=2) [原文 p.2](/api/artifacts/{b['id']}#page=2)"
    replies = iter([
        {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': str(n), 'type': 'function', 'function': {'name': 'read_research_artifact',
             'arguments': json.dumps({'artifact_id': p['id'], 'page': 2})}} for n, p in enumerate((a, b))]}}]},
        {'model': 'deepseek-v4.1-flash:1017', 'choices': [{'message': {'content': final}}]}])
    sent = model_stream(replies)
    result = client.post(f'/api/projects/{pid}/chat', json={'message': 'Compare the definitions', 'paper_ids': [a['id'], b['id']]}).text.splitlines()[-1]
    result = json.loads(result)
    assert result['answer'] == final
    assert sent[0][0] == 'https://ollama.com/v1/chat/completions'
    assert a['id'] in sent[0][1]['messages'][0]['content'] and b['id'] in sent[0][1]['messages'][0]['content']
    assert 'run_named_physics_check' not in [t['function']['name'] for t in sent[0][1]['tools']]
    outputs = [json.loads(m['content']) for m in sent[1][1]['messages'] if m['role'] == 'tool']
    assert [o['text'] for o in outputs] == [original_a, 'C depends on mu; derivative is c1.']
    assert [t['source']['artifact_id'] for t in result['meta']['tools']] == [a['id'], b['id']]
    stored = client.get(f'/api/projects/{pid}/messages').json()
    assert json.loads(stored[0]['meta_json'])['paper_ids'] == [a['id'], b['id']]
    assert json.loads(stored[1]['meta_json'])['tools'][1]['source']['page'] == 2
    assert client.get(f'/api/projects/{pid}/evidence').json() == []


def test_combined_archive_limit_rolls_back_the_whole_import(client, pdf_factory, monkeypatch):
    from pdvl import db
    pid = project(client)
    original = pdf_factory('Source text')
    # PDF fits, but PDF plus metadata/text does not. No orphan run or PDF may survive.
    monkeypatch.setattr(db, 'ARCHIVE_LIMIT', len(original) + 10)
    result = upload(client, pid, original)
    assert result.status_code == 422 and 'archive limit' in result.json()['detail']
    assert db.rows('SELECT id FROM runs WHERE project_id=?', (pid,)) == []
    assert db.rows('SELECT id FROM artifacts') == []


def test_cancelling_pdf_parse_cannot_archive_after_the_chat_has_stopped(client, monkeypatch):
    import threading
    pid = project(client)
    entered, release = threading.Event(), threading.Event()
    def blocked_parse(_content):
        entered.set();assert release.wait(3)
        return ['Parsing finished after cancellation']
    monkeypatch.setattr(papers, 'extract_pdf', blocked_parse)
    async def run():
        task = asyncio.create_task(papers.archive_pdf(pid, b'%PDF-placeholder', 'Cancelled import'))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):await task
        finally:
            release.set()
    asyncio.run(run())
    assert client.get(f'/api/projects/{pid}/papers').json() == []
    from pdvl.db import rows
    assert rows('SELECT artifact_id FROM paper_fts') == []
    assert rows('SELECT id FROM runs WHERE project_id=?', (pid,)) == []
