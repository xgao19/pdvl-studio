"""Fixed, independently inspectable retrieval and citation acceptance corpus."""
import asyncio
import json
from pathlib import Path

from pdvl import api
from pdvl.db import connection, init_db
from pdvl.papers import read_artifact
from pdvl.research import validate_chat_citations
from pdvl.tools import execute_research_tool

CORPUS = json.loads((Path(__file__).parent / 'fixtures/discuss_acceptance.json').read_text())


def test_fixed_corpus_retrieval_to_reading_and_citation(client, pdf_factory):
    pid = client.post('/api/projects', json={'title': 'Fixed retrieval acceptance'}).json()['id']
    other = client.post('/api/projects', json={'title': 'Isolated'}).json()['id']
    papers = [client.post(f'/api/projects/{pid}/papers/pdf', params={'title': p['title']},
                         content=pdf_factory(*p['pages'])).json() for p in CORPUS['papers']]
    for case in CORPUS['queries']:
        expected = papers[case['paper']]
        result = client.get(f'/api/projects/{pid}/papers/fulltext', params={'query': case['query']}).json()
        assert result['results'][0]['artifact_id'] == expected['id'], case['question']
        assert result['results'][0]['page'] == case['page']
        tool = asyncio.run(execute_research_tool('search_project_papers', {'query': case['query']}, pid))
        assert tool == result
        source = read_artifact(pid, expected['id'], case['page'])
        assert case['contains'] in source['text']
        # Finding an excerpt never authorizes a page citation.
        invalid, checks = validate_chat_citations(pid, source['citation'], [])
        assert not checks[0]['valid'] and invalid == source['citation']
        read = {'artifact_id': source['id'], 'page': source['page'], 'sha256': source['sha256'], 'length': len(source['text'])}
        valid, checks = validate_chat_citations(pid, source['citation'], [read])
        assert checks[0]['valid'] and valid == source['citation']
    assert client.get(f'/api/projects/{other}/papers/fulltext', params={'query': 'epsilon'}).json()['results'] == []
    assert client.get(f'/api/projects/{pid}/papers/fulltext', params={'query': CORPUS['absent_query']}).json()['results'] == []
    for query in ('" OR NOT * )', 'epsilon" OR project_id:other', "epsilon'; DROP TABLE projects; --"):
        assert client.get(f'/api/projects/{pid}/papers/fulltext', params={'query': query}).status_code == 200
    assert client.get(f'/api/projects/{pid}/papers/fulltext', params={'query': '   '}).status_code == 422
    # Index is derived, backfilled for older archives, idempotent and transactional.
    with connection() as con:
        con.execute('DELETE FROM paper_fts')
    init_db();init_db()
    with connection() as con:
        assert con.execute('SELECT count(*) FROM paper_fts').fetchone()[0] == 7
    assert client.get(f'/api/projects/{pid}/papers/fulltext', params={'query': 'CASCADE'}).json()['results'][0]['page'] == 3
    assert client.get(f'/api/projects/{pid}/evidence').json() == []
    assert client.get(f'/api/projects/{pid}/claims').json() == []


def test_citation_validation_rejects_forged_unread_and_cross_project_sources(client, pdf_factory):
    pid = client.post('/api/projects', json={'title': 'Citation audit'}).json()['id']
    other = client.post('/api/projects', json={'title': 'Other'}).json()['id']
    paper = client.post(f'/api/projects/{pid}/papers/pdf', params={'title': 'Original'}, content=pdf_factory('One', 'Two')).json()
    aid = paper['id']
    source = read_artifact(pid, aid)
    reads = [{'artifact_id': aid, 'page': 1, 'sha256': source['sha256'], 'length': 3}]
    links = [f'[valid](/api/artifacts/{aid}#page=1)', f'[unread](/api/artifacts/{aid}#page=2)',
             f'[bounds](/api/artifacts/{aid}#page=3)', '[missing](/api/artifacts/a_missing#page=1)',
             f'[no page](/api/artifacts/{aid})', f'[external](https://example.com/api/artifacts/{aid}#page=1)',
             '[evidence:e_missing]']
    answer, checks = validate_chat_citations(pid, '\n'.join(links), reads)
    assert len(checks) == 7 and sum(c['valid'] for c in checks) == 1
    assert sum(not c['valid'] for c in checks) == 6
    assert '[未核验 evidence:e_missing]' in answer
    assert not validate_chat_citations(other, links[0], reads)[1][0]['valid']
    assert not validate_chat_citations(pid, links[0], [{**reads[0], 'sha256': 'forged'}])[1][0]['valid']
    # Markdown reference links are checked too, but examples in code are not citations.
    reference = f'[source][ref]\n\n[ref]: /api/artifacts/{aid}#page=2'
    assert not validate_chat_citations(pid, reference, reads)[1][0]['valid']
    assert validate_chat_citations(pid, '`'+links[0]+'`', [])[1] == []
    html = client.post('/api/render', json={'markdown': answer, 'blocked_links': [c['target'] for c in checks if not c['valid']]}).json()['html']
    assert f'href="/api/artifacts/{aid}#page=1"' in html
    assert html.count('href=') == 1
    # Escaped and reference-link spellings are disabled by parsed destination, not string substitution.
    escaped_aid = aid.replace('_', r'\_')
    escaped = f'[unread](/api/artifacts/{escaped_aid}#page=2)'
    for body in (escaped, reference):
        rendered = client.post('/api/render', json={'markdown': body, 'blocked_links': [f'/api/artifacts/{aid}#page=2']}).json()['html']
        assert 'href=' not in rendered


def test_ollama_stream_search_read_answer_and_followup_citations(client, pdf_factory, monkeypatch, model_stream):
    pid = client.post('/api/projects', json={'title': 'Tool loop acceptance'}).json()['id']
    paper = client.post(f'/api/projects/{pid}/papers/pdf', params={'title': 'Original'}, content=pdf_factory('Abstract', 'CASCADE pseudodata; no experimental extraction')).json()
    monkeypatch.setenv('CUSTOM_API_KEY', 'fixture-key');monkeypatch.setenv('CUSTOM_API_BASE', 'https://ollama.com/v1')
    monkeypatch.setattr(api, 'pick_model', lambda *_: {'id': 'ollama', 'provider': 'custom', 'model': 'deepseek-v4.1-flash:1017', 'api': 'chat_completions'})
    def call(name, args):
        return {'choices': [{'message': {'tool_calls': [{'id': name, 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}
    final = f"Only pseudodata [原文 p.2](/api/artifacts/{paper['id']}#page=2)."
    sent = model_stream([call('search_project_papers', {'query': 'CASCADE'}),
                         call('read_research_artifact', {'artifact_id': paper['id'], 'page': 2}),
                         {'choices': [{'message': {'content': final}}]},
                         {'choices': [{'message': {'content': final}}]}])
    events = [json.loads(line) for line in client.post(f'/api/projects/{pid}/chat', json={'message': 'Find the limitation'}).text.splitlines()]
    types = [e['type'] for e in events]
    assert types[0] == 'start' and types[-1] == 'done'
    assert types.count('tool_start') == types.count('tool_end') == 2
    assert types.index('tool_start') < types.index('tool_end') < types.index('delta') < types.index('done')
    assert ''.join(e['text'] for e in events if e['type'] == 'delta') == final
    result = events[-1]
    assert result['meta']['state'] == 'completed' and result['meta']['citations'][0]['valid']
    assert [e['name'] for e in result['meta']['tools']] == ['search_project_papers', 'read_research_artifact']
    assert json.loads(sent[1][1]['messages'][-1]['content'])['results'][0]['page'] == 2
    followup = json.loads(client.post(f'/api/projects/{pid}/chat', json={'message': 'Restate the limitation briefly'}).text.splitlines()[-1])
    assert followup['meta']['citations'][0]['valid']  # Recent real reads survive across turns.
    assert followup['meta']['tools'] == []
    assert client.get(f'/api/projects/{pid}/evidence').json() == []
