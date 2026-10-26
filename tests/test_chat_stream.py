"""Exercise real loopback streaming: TestClient intentionally buffers responses."""
import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from pdvl import api
from pdvl.db import one
from pdvl.providers import ProviderError


@pytest.fixture()
def live_api(client):
    sock = socket.socket();sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(api.app, log_level='critical', lifespan='off', ws='none'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True);thread.start()
    until = time.monotonic() + 5
    while not server.started and time.monotonic() < until:
        time.sleep(.01)
    assert server.started
    with httpx.Client(base_url=f'http://127.0.0.1:{sock.getsockname()[1]}', timeout=3) as remote:
        yield remote
    server.should_exit = True;thread.join(5);sock.close()
    assert not thread.is_alive()


def test_stop_cancels_inflight_work_and_preserves_partial_and_read_records(live_api, monkeypatch):
    pid = live_api.post('/api/projects', json={'title': 'Cancellation acceptance'}).json()['id']
    other = live_api.post('/api/projects', json={'title': 'Other'}).json()['id']
    cancelled = threading.Event()
    async def blocked(model, instructions, messages, **kw):
        try:
            await kw['emit']({'type': 'progress', 'round': 1, 'message': 'Reading'})
            kw['trace'].append({'name': 'search_project_papers', 'args': {'query': 'epsilon'}, 'result_sha256': 'digest'})
            await kw['emit']({'type': 'delta', 'text': '这是尚未完成的回答。'})
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(api, 'generate', blocked)
    with live_api.stream('POST', f'/api/projects/{pid}/chat', json={'message': 'Read and explain'}) as response:
        lines = response.iter_lines()
        start = json.loads(next(lines));mid = start['id']
        assert start['type'] == 'start'
        assert json.loads(next(lines))['type'] == 'progress'
        assert json.loads(next(lines))['type'] == 'delta'  # Arrives while producer is blocked.
        assert live_api.post(f'/api/projects/{other}/messages/{mid}/stop').status_code == 404
        assert not cancelled.is_set()
        assert live_api.post(f'/api/projects/{pid}/messages/{mid}/stop').status_code == 200
        done = json.loads(next(lines))
        assert done['type'] == 'done' and done['meta']['state'] == 'stopped'
        assert done['answer'] == '这是尚未完成的回答。'
        assert done['meta']['tools'][0]['name'] == 'search_project_papers'
        assert cancelled.wait(1)
    saved = live_api.get(f'/api/projects/{pid}/messages').json()
    assert len(saved) == 2 and saved[1]['content'] == done['answer']
    assert json.loads(saved[1]['meta_json'])['state'] == 'stopped'
    assert live_api.post(f'/api/projects/{pid}/messages/{mid}/stop').json()['state'] == 'stopped'
    assert mid not in api.active_chats


def test_disconnect_cancels_producer_and_does_not_leave_a_running_chat(live_api, monkeypatch):
    pid = live_api.post('/api/projects', json={'title': 'Disconnect'}).json()['id']
    cancelled = threading.Event()
    async def blocked(*args, **kw):
        try:
            await kw['emit']({'type': 'delta', 'text': 'Partial'})
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(api, 'generate', blocked)
    with live_api.stream('POST', f'/api/projects/{pid}/chat', json={'message': 'Question'}) as response:
        lines = response.iter_lines();mid = json.loads(next(lines))['id']
        assert json.loads(next(lines))['text'] == 'Partial'
    assert cancelled.wait(2)
    until = time.monotonic() + 2
    while mid in api.active_chats and time.monotonic() < until:
        time.sleep(.01)
    saved = one('SELECT content,meta_json FROM messages WHERE id=?', (mid,))
    assert saved['content'] == 'Partial' and json.loads(saved['meta_json'])['state'] == 'stopped'
    assert mid not in api.active_chats


def test_failure_is_terminal_and_never_presented_as_a_completed_answer(client, monkeypatch):
    pid = client.post('/api/projects', json={'title': 'Failure'}).json()['id']
    async def broken(*args, **kw):
        await kw['emit']({'type': 'delta', 'text': 'Partial'})
        raise ProviderError('Provider stream disconnected before completion')
    monkeypatch.setattr(api, 'generate', broken)
    events = [json.loads(line) for line in client.post(f'/api/projects/{pid}/chat', json={'message': 'Question'}).text.splitlines()]
    done = events[-1]
    assert done['type'] == 'done' and done['meta']['state'] == 'failed'
    assert done['answer'] == 'Partial' and 'disconnected' in done['meta']['error']
    assert not api.active_chats
