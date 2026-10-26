"""Real subprocess tests for progress, cancellation, and immutable continuations."""
import concurrent.futures
import json
import subprocess
import sys
import threading
import time

import pytest
from pdvl import worker
from pdvl.db import add_run_event, connection, one
from pdvl.config import home


def wait_for(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for worker progress')


@pytest.fixture()
def bridge(monkeypatch):
    real_popen = subprocess.Popen
    control = {'script': '''
import json, sys
from pathlib import Path
task=json.load(sys.stdin)
w=Path(task['workdir'])
print(json.dumps({'kind':'event','event':{'type':'thread.started','thread_id':'thread-live'}}),flush=True)
print(json.dumps({'kind':'final','text':'Finished','thread_id':'thread-live'}),flush=True)
'''}
    def launch(command, *args, **kwargs):
        if command[0] == 'node':
            command = [sys.executable, '-u', '-c', control['script']]
        return real_popen(command, *args, **kwargs)
    monkeypatch.setattr(worker.subprocess, 'Popen', launch)
    return control


def queue(client, monkeypatch):
    monkeypatch.setenv('PDVL_CODEX_ENABLED', '1')
    pid = client.post('/api/projects', json={'title': 'Task controls'}).json()['id']
    run = client.post(f'/api/projects/{pid}/runs', json={'question': 'A small test', 'model_id': 'test-model'})
    assert run.status_code == 202
    return pid, run.json()['id']


def events(client, rid, after=0):
    return client.get(f'/api/runs/{rid}/events?after={after}').json()


def test_queued_cancel_is_immediate_idempotent_and_never_executes(client, monkeypatch):
    _, rid = queue(client, monkeypatch)
    result = client.post(f'/api/runs/{rid}/cancel')
    assert result.json()['state'] == 'cancelled'
    assert result.json()['ended_at']
    assert client.post(f'/api/runs/{rid}/cancel').status_code == 200
    assert worker.process_one() is None
    assert [e['kind'] for e in events(client, rid)['events']] == ['queued', 'cancelled']
    assert client.post(f'/api/runs/{rid}/continue', json={'message': 'Continue'}).status_code == 409
    assert client.post('/api/runs/missing/cancel').status_code == 404
    assert client.get('/api/runs/missing/events').status_code == 404
    assert client.get(f'/api/runs/{rid}/events?after=-1').status_code == 422


LONG_TASK = '''
import json, sys, subprocess, time
from pathlib import Path
task=json.load(sys.stdin)
w=Path(task['workdir'])
(w/'partial.txt').write_text('original partial result')
print(json.dumps({'kind':'event','event':{'type':'thread.started','thread_id':'thread-live'}}),flush=True)
child_code="import sys,time;from pathlib import Path;p=Path(sys.argv[1]);\\nwhile True:p.write_text(str(time.time()));time.sleep(0.05)"
child=subprocess.Popen([sys.executable,'-u','-c',child_code,str(w/'heartbeat')])
(w/'child.pid').write_text(str(child.pid))
print(json.dumps({'kind':'event','event':{'type':'item.started','item':{'type':'command_execution','command':'long symbolic check'}}}),flush=True)
time.sleep(60)
'''


def test_live_progress_cancel_kills_descendants_and_continue_preserves_sources(client, monkeypatch, bridge):
    pid, rid = queue(client, monkeypatch)
    bridge['script'] = LONG_TASK
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(worker.process_one)
        wait_for(lambda: any(e['kind'] == 'item.started' for e in events(client, rid)['events']))
        current = client.get('/api/runs/' + rid).json()
        assert current['state'] == 'running' and current['thread_id'] == 'thread-live'
        workdir = home() / 'runs' / rid / 'workspace'
        wait_for(lambda: (workdir / 'heartbeat').exists())
        assert client.post(f'/api/runs/{rid}/continue', json={'message': 'Too early'}).status_code == 409
        assert client.post(f'/api/runs/{rid}/cancel').json()['state'] == 'cancelling'
        assert client.post(f'/api/runs/{rid}/cancel').status_code == 200
        cancelled = future.result(timeout=6)
    assert cancelled['state'] == 'cancelled'
    assert cancelled['output'] == ''
    heartbeat = (workdir / 'heartbeat').read_text()
    time.sleep(0.2)
    assert (workdir / 'heartbeat').read_text() == heartbeat
    archive = client.get(f'/api/runs/{rid}/artifacts').json()
    original = next(a for a in archive if a['name'] == 'workspace/partial.txt')
    assert client.get('/api/artifacts/' + original['id']).content == b'original partial result'
    (workdir / 'partial.txt').write_text('Changed workspace after cancellation')
    client.post(f'/api/projects/{pid}/decisions', json={'text': 'A new decision before continuing'})
    continued = client.post(f'/api/runs/{rid}/continue', json={'message': 'Complete the check'})
    assert continued.status_code == 202
    child = continued.json()
    assert child['id'] != rid and child['parent_run_id'] == rid
    assert child['thread_id'] == 'thread-live' and child['model_id'] == 'test-model'
    assert 'A new decision before continuing' in child['context_json']
    assert client.post(f'/api/runs/{rid}/continue', json={'message': 'Duplicate'}).status_code == 409
    bridge['script'] = '''
import json,sys
from pathlib import Path
task=json.load(sys.stdin)
assert task['thread_id']=='thread-live'
w=Path(task['workdir'])
assert (w/'partial.txt').read_text()=='original partial result'
(w/'partial.txt').write_text('continued result')
print(json.dumps({'kind':'event','event':{'type':'thread.started','thread_id':'thread-live'}}),flush=True)
print(json.dumps({'kind':'final','text':'Continued successfully','thread_id':'thread-live'}),flush=True)
'''
    completed = worker.process_one()
    assert completed['id'] == child['id'] and completed['state'] == 'completed'
    assert completed['output'] == 'Continued successfully'
    assert client.get('/api/artifacts/' + original['id']).content == b'original partial result'
    assert client.post(f'/api/runs/{child["id"]}/cancel').status_code == 409
    restored = home() / 'runs' / child['id'] / 'workspace' / 'partial.txt'
    assert restored.read_text() == 'continued result'


def test_progress_cursor_is_scoped_paged_and_survives_reinitialization(client, monkeypatch):
    _, rid = queue(client, monkeypatch)
    _, other = queue(client, monkeypatch)
    with connection() as con:
        for i in range(110):
            add_run_event(con, rid, 'message', f'Progress {i}')
    first = events(client, rid)
    assert len(first['events']) == 100 and first['has_more']
    second = events(client, rid, first['cursor'])
    assert len(second['events']) == 11 and not second['has_more']
    assert not set(e['id'] for e in first['events']) & set(e['id'] for e in second['events'])
    assert all(e['run_id'] == rid for e in first['events'] + second['events'])
    assert len(events(client, other)['events']) == 1
    from pdvl.db import init_db
    init_db()
    assert events(client, rid, second['cursor'])['events'] == []


def test_shutdown_preserves_partial_results_as_interrupted(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    shutdown = threading.Event()
    monkeypatch.setattr(worker, 'STOP', shutdown)
    bridge['script'] = LONG_TASK
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(worker.process_one)
        wait_for(lambda: client.get('/api/runs/' + rid).json()['thread_id'])
        shutdown.set()
        result = future.result(timeout=6)
    assert result['state'] == 'interrupted'
    assert any(a['name'] == 'workspace/partial.txt' for a in client.get(f'/api/runs/{rid}/artifacts').json())


def test_cancel_during_finalization_wins_completion_race(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    collect = worker.collect_artifacts
    def cancel_before_archive(*args, **kwargs):
        assert client.post(f'/api/runs/{rid}/cancel').status_code == 200
        return collect(*args, **kwargs)
    monkeypatch.setattr(worker, 'collect_artifacts', cancel_before_archive)
    result = worker.process_one()
    assert result['state'] == 'cancelled'
    assert events(client, rid)['events'][-1]['kind'] == 'cancelled'


def test_concurrent_continue_creates_one_child(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    assert worker.process_one()['state'] == 'completed'
    with concurrent.futures.ThreadPoolExecutor() as pool:
        responses = list(pool.map(lambda _: client.post(f'/api/runs/{rid}/continue', json={'message': 'Next'}).status_code, range(2)))
    assert sorted(responses) == [202, 409]
    assert one('SELECT count(*) AS n FROM runs WHERE parent_run_id=?', (rid,))['n'] == 1
    assert client.post('/api/runs/missing/continue', json={'message': 'Next'}).status_code == 404
    assert client.post(f'/api/projects/{client.get("/api/runs/"+rid).json()["project_id"]}/runs',
                       json={'question': 'Other', 'thread_id': 'arbitrary-session'}).status_code == 422


def test_cancel_before_launch_avoids_starting_the_agent(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    git = worker.subprocess.run
    def prepare(*args, **kwargs):
        result = git(*args, **kwargs)
        client.post(f'/api/runs/{rid}/cancel')
        return result
    monkeypatch.setattr(worker.subprocess, 'run', prepare)
    assert worker.process_one()['state'] == 'cancelled'
    assert client.get('/api/runs/' + rid).json()['thread_id'] is None


def test_queued_cancelled_continuation_keeps_last_executed_workspace(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    bridge['script'] = bridge['script'].replace("print(json.dumps({'kind':'final'", "(w/'kept.txt').write_text('original')\nprint(json.dumps({'kind':'final'")
    assert worker.process_one()['state'] == 'completed'
    child = client.post(f'/api/runs/{rid}/continue', json={'message': 'Next'}).json()
    client.post(f'/api/runs/{child["id"]}/cancel')
    grandchild = client.post(f'/api/runs/{child["id"]}/continue', json={'message': 'Actually continue'}).json()
    bridge['script'] = bridge['script'].replace("(w/'kept.txt').write_text('original')", "assert (w/'kept.txt').read_text()=='original'")
    result = worker.process_one()
    assert result['id'] == grandchild['id'] and result['state'] == 'completed'


def test_cancel_escalates_when_agent_ignores_sigterm(client, monkeypatch, bridge):
    _, rid = queue(client, monkeypatch)
    bridge['script'] = LONG_TASK.replace('task=json.load(sys.stdin)', 'import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntask=json.load(sys.stdin)')
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(worker.process_one)
        wait_for(lambda: client.get('/api/runs/' + rid).json()['thread_id'])
        client.post(f'/api/runs/{rid}/cancel')
        assert future.result(timeout=6)['state'] == 'cancelled'
