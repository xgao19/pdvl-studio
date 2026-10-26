"""Offline integration tests: real local worker subprocess, mocked agent/model only."""
import hashlib
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pdvl import api
from pdvl.config import home
from pdvl.db import connection, init_db, one
from pdvl.worker import process_one, collect_artifacts
from pdvl.tools import execute_research_tool


@pytest.fixture()
def bridge(monkeypatch):
    real_popen = subprocess.Popen
    seen = []
    script = '''
import json, sys
from pathlib import Path
task = json.load(sys.stdin)
w = Path(task['workdir'])
(w / 'received.json').write_text(json.dumps(task))
(w / 'findings.md').write_text('An unresolved physical finding.', encoding='utf-8')
(w / 'derivation.md').write_text('Shared gamma cancels; extraction remains open.', encoding='utf-8')
(w / 'check.py').write_text('assert 1 + 1 == 2')
(w / 'result.bin').write_bytes(bytes([0, 255]))
# The archived input must remain the original even if the agent edits its copy.
(w / 'RESEARCH_CONTEXT.json').write_text('{}')
print(json.dumps({'kind':'final','text':'Agent conclusion, not verification.','thread_id':'thread-test'}))
'''
    def launch(command, *args, **kwargs):
        if command[0] == 'node':
            seen.append(command)
            command = [sys.executable, '-c', script]
        return real_popen(command, *args, **kwargs)
    monkeypatch.setattr('pdvl.worker.subprocess.Popen', launch)
    return seen


def project(client, title='Research'):
    pid = client.post('/api/projects', json={'title': title}).json()['id']
    claim = client.post(f'/api/projects/{pid}/claims', json={
        'title': 'Kernel conjecture', 'statement': 'An unproved relation',
        'assumptions': ['Common evolution convention']}).json()
    return pid, claim


def queue(client, monkeypatch, pid):
    monkeypatch.setenv('PDVL_CODEX_ENABLED', '1')
    result = client.post(f'/api/projects/{pid}/runs', json={
        'question': 'Check the relation', 'model_id': 'test-model'})
    assert result.status_code == 202
    return result.json()


def test_context_to_artifact_evidence_and_revision(client, monkeypatch, bridge):
    pid, claim = project(client)
    base = f'/api/projects/{pid}'
    client.post(base + '/decisions', json={'text': 'Keep extraction unresolved'})
    client.post(base + '/documents', json={'title': 'Introduction', 'text': 'Prior manuscript argument'})
    async def generate(model, instructions, messages, **kwargs):
        return 'Prior discussion insight', {}
    monkeypatch.setattr(api, 'generate', generate)
    client.post(base + '/chat', json={'message': 'What assumptions matter?'})
    run = queue(client, monkeypatch, pid)
    frozen = json.loads(run['context_json'])
    assert frozen['claims'][0]['assumptions'] == '["Common evolution convention"]'
    assert frozen['documents'][0]['text'] == 'Prior manuscript argument'
    assert frozen['messages'][-1]['content'] == 'Prior discussion insight'
    client.post(base + '/decisions', json={'text': 'Later decision, not part of task'})
    completed = process_one()
    assert completed['state'] == 'completed'
    assert completed['thread_id'] == 'thread-test'
    assert len(bridge) == 1
    assert process_one() is None  # Already claimed tasks are never silently rerun.
    workdir = home() / 'runs' / run['id'] / 'workspace'
    received = json.loads((workdir / 'received.json').read_text())
    assert 'Keep extraction unresolved' in received['question']
    assert 'Prior manuscript argument' in received['question']
    assert 'Later decision' not in received['question']
    assert 'Common evolution convention' in received['question']
    assert client.get(base + '/evidence').json() == []
    artifacts = {a['name']: a for a in client.get(f"/api/runs/{run['id']}/artifacts").json()}
    assert 'workspace/check.py' in artifacts
    assert '.git' not in ' '.join(artifacts)
    original_context = client.get('/api/artifacts/' + artifacts['input/context.json']['id']).content
    assert original_context == run['context_json'].encode()
    assert client.get('/api/artifacts/' + artifacts['workspace/result.bin']['id']).content == bytes([0, 255])
    artifact = artifacts['workspace/findings.md']
    original = client.get('/api/artifacts/' + artifact['id']).content
    assert hashlib.sha256(original).hexdigest() == artifact['sha256']
    (workdir / 'findings.md').write_text('Changed after execution')
    assert client.get('/api/artifacts/' + artifact['id']).content == original
    evidence = client.post(base + '/evidence', json={
        'claim_id': claim['id'], 'artifact_id': artifact['id'], 'kind': 'derivation',
        'verdict': 'unresolved', 'description': 'The derivation leaves extraction open',
        'provenance': {'artifact': {'sha256': 'forged'}, 'context_sha256': 'forged'}}).json()
    provenance = json.loads(evidence['provenance'])
    assert provenance['artifact']['sha256'] == artifact['sha256']
    assert provenance['context_sha256'] == hashlib.sha256(original_context).hexdigest()
    assert provenance['artifact']['model_id'] == 'test-model'
    assert client.get(base + '/claims').json()[0]['status'] == 'idea'
    marker = f"[evidence:{evidence['id']}]"
    text = f'The extraction remains a conjecture {marker}. Assumptions matter {marker}.'
    saved = client.post(base + '/documents', json={'title': 'Result', 'text': text})
    assert saved.status_code == 201
    saved = saved.json()
    did = saved['document']['id']
    revision = saved['revisions'][0]
    assert json.loads(revision['evidence_refs']) == [evidence['id']]
    source = revision['sources'][0]
    assert source['claim_id'] == claim['id']
    assert source['claim_status'] == 'idea'
    assert source['artifact_id'] == artifact['id']
    assert source['run_id'] == run['id']
    tool_result = asyncio.run(execute_research_tool('read_research_artifact', {'artifact_id': artifact['id']}, pid))
    assert tool_result['text'].encode() == original
    assert tool_result['sha256'] == artifact['sha256']
    binary = asyncio.run(execute_research_tool('read_research_artifact', {'artifact_id': artifacts['workspace/result.bin']['id']}, pid))
    assert 'Binary artifact' in binary['error']
    # Citation removal affects the next revision only.
    next_revision = client.post(base + '/documents', json={
        'document_id': did, 'title': 'Result', 'text': 'Revised without this source'}).json()
    assert next_revision['revisions'][0]['sources'] == []
    assert next_revision['revisions'][1]['sources'][0]['id'] == evidence['id']
    seen = []
    async def capture(model, instructions, messages, **kwargs):
        assert kwargs['allow_tools'] is True
        seen.append(instructions)
        return 'A careful paragraph ' + marker, {}
    monkeypatch.setattr(api, 'generate', capture)
    assert client.post(base + '/chat', json={'mode': 'write', 'message': 'Develop the argument'}).status_code == 200
    assert evidence['id'] in seen[0] and artifact['sha256'] in seen[0]
    assert 'Revised without this source' in seen[0]
    assert 'Agent conclusion, not verification.' in seen[0]
    # Reinitialization / a fresh app lifespan leaves the whole chain intact.
    init_db()
    with TestClient(api.app) as restarted:
        assert restarted.get('/api/documents/' + did).json()['revisions'][1]['sources'][0]['artifact_id'] == artifact['id']
        assert restarted.get('/api/artifacts/' + artifact['id']).content == original


def test_sources_cannot_cross_projects_and_bad_citations_roll_back(client, monkeypatch, bridge):
    pid, claim = project(client)
    other, other_claim = project(client, 'Other project')
    run = queue(client, monkeypatch, pid)
    process_one()
    artifact = client.get(f"/api/runs/{run['id']}/artifacts").json()[0]
    evidence = client.post(f'/api/projects/{pid}/evidence', json={
        'claim_id': claim['id'], 'artifact_id': artifact['id'], 'description': 'Source'}).json()
    assert client.post(f'/api/projects/{other}/evidence', json={
        'claim_id': other_claim['id'], 'artifact_id': artifact['id'], 'description': 'Wrong project'}).status_code == 404
    assert client.post(f'/api/projects/{other}/evidence', json={
        'claim_id': claim['id'], 'description': 'Wrong claim'}).status_code == 404
    assert client.post(f'/api/projects/{pid}/evidence', json={
        'claim_id': claim['id'], 'artifact_id': 'missing', 'description': 'Missing source'}).status_code == 404
    assert client.post(f'/api/projects/{pid}/evidence', json={
        'claim_id': claim['id'], 'artifact_id': '', 'description': 'Empty source'}).status_code == 422
    assert 'error' in asyncio.run(execute_research_tool('read_research_artifact', {'artifact_id': artifact['id']}, other))
    for marker in (f"[evidence:{evidence['id']}]", '[evidence:missing]', '[evidence:bad-id]', '[evidence:]'):
        assert client.post(f'/api/projects/{other}/documents', json={'title': 'Invalid', 'text': marker}).status_code == 422
    assert client.get(f'/api/projects/{other}/documents').json() == []
    valid = client.post(f'/api/projects/{pid}/documents', json={'title': 'Valid', 'text': 'No citation'}).json()
    did = valid['document']['id']
    assert client.post(f'/api/projects/{pid}/documents', json={
        'title': 'Invalid revision', 'document_id': did, 'text': '[evidence:missing]'}).status_code == 422
    assert client.get('/api/documents/' + did).json()['document']['latest_revision'] == 1
    assert client.post(f'/api/projects/{other}/documents', json={
        'title': 'Wrong document', 'document_id': did, 'text': 'Text'}).status_code == 404
    assert client.get('/api/artifacts/missing').status_code == 404
    assert client.get('/api/runs/missing/artifacts').status_code == 404


def test_preparation_failure_is_recorded(client, monkeypatch):
    pid, _ = project(client)
    run = queue(client, monkeypatch, pid)
    def fail(*args, **kwargs):
        raise OSError('git unavailable')
    monkeypatch.setattr('pdvl.worker.subprocess.run', fail)
    result = process_one()
    assert result['state'] == 'failed' and 'git unavailable' in result['error']
    assert result['ended_at']
    assert client.get('/api/runs/' + run['id']).json()['state'] == 'failed'


def test_configured_model_is_frozen_at_queue_time(client, monkeypatch, bridge):
    pid, _ = project(client)
    monkeypatch.setenv('PDVL_CODEX_ENABLED', '1')
    monkeypatch.setenv('PDVL_CODEX_MODEL', 'model-at-queue-time')
    run = client.post(f'/api/projects/{pid}/runs', json={'question': 'Check this'}).json()
    monkeypatch.setenv('PDVL_CODEX_MODEL', 'different-model')
    assert process_one()['state'] == 'completed'
    received = json.loads((home() / 'runs' / run['id'] / 'workspace' / 'received.json').read_text())
    assert received['model'] == run['model_id'] == 'model-at-queue-time'


@pytest.mark.parametrize('mode', ['empty', 'failed', 'timeout'])
def test_runtime_failure_is_not_completed(client, monkeypatch, mode):
    pid, _ = project(client)
    queue(client, monkeypatch, pid)
    real_popen = subprocess.Popen
    script = {'empty': 'pass', 'failed': 'raise SystemExit(1)', 'timeout': 'import time; time.sleep(10)'}[mode]
    def launch(command, *args, **kwargs):
        if command[0] == 'node':
            command = [sys.executable, '-c', script]
        return real_popen(command, *args, **kwargs)
    monkeypatch.setattr('pdvl.worker.subprocess.Popen', launch)
    result = process_one(timeout_seconds=0.1 if mode == 'timeout' else 5)
    assert result['state'] == 'failed' and result['error']


def test_archive_rejects_external_symlinks_and_oversize_files(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    secret = tmp_path / 'outside.txt'
    secret.write_text('Outside research input')
    (workspace / 'link').symlink_to(secret)
    with pytest.raises(ValueError, match='symlinks'):
        collect_artifacts(workspace, {})
    (workspace / 'link').unlink()
    (workspace / 'nested').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        collect_artifacts(workspace, {})
    (workspace / 'nested').unlink()
    with (workspace / 'large').open('wb') as out:
        out.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match='10 MiB'):
        collect_artifacts(workspace, {})


def test_existing_database_migrates_without_losing_records(client):
    pid, claim = project(client)
    client.post(f'/api/projects/{pid}/evidence', json={'claim_id': claim['id'], 'description': 'Old note'})
    # Remove only the new schema to reproduce the previous version on real data.
    with connection() as con:
        con.execute('ALTER TABLE evidence DROP COLUMN artifact_id')
        con.execute('ALTER TABLE runs DROP COLUMN context_json')
        con.execute('DROP TABLE artifacts')
    init_db()
    init_db()
    assert one('SELECT statement FROM claims WHERE id=?', (claim['id'],))['statement'] == 'An unproved relation'
    old = client.get(f'/api/projects/{pid}/evidence').json()[0]
    assert old['description'] == 'Old note' and old['artifact_id'] is None


def test_cited_old_evidence_stays_in_writing_context(client, monkeypatch):
    pid, claim = project(client)
    base = f'/api/projects/{pid}'
    evidence = client.post(base + '/evidence', json={'claim_id': claim['id'], 'description': 'Original source'}).json()
    for _ in range(16):
        client.post(base + '/evidence', json={'claim_id': claim['id'], 'description': 'Later note'})
    client.post(base + '/documents', json={'title': 'Argument', 'text': f"See [evidence:{evidence['id']}]"})
    seen = []
    async def generate(model, instructions, messages, **kwargs):
        seen.append(instructions)
        return 'Draft', {}
    monkeypatch.setattr(api, 'generate', generate)
    client.post(base + '/chat', json={'mode': 'write', 'message': 'Continue'})
    assert 'Original source' in seen[0]
