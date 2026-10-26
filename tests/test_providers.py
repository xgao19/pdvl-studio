import asyncio
import json
import pytest
from pdvl.providers import generate
from pdvl.tools import tools_for_mode

def test_deepseek_responses_tool_loop(monkeypatch,tmp_path,model_stream):
    monkeypatch.setenv('PDVL_HOME',str(tmp_path))
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-key')
    from pdvl.db import init_db,execute,utcnow
    init_db();execute('INSERT INTO projects VALUES (?,?,?,?)',('p','Test','',utcnow()))
    sent=[]
    replies=[
      {'model':'deepseek-v4-pro','output':[{'type':'function_call','name':'run_named_physics_check','arguments':'{"test_id":"csk_delta_rg"}','call_id':'c1'}]},
      {'model':'deepseek-v4-pro','output':[{'type':'message','content':[{'type':'output_text','text':'The difference is RG invariant only under common anomalous dimensions.'}]}]}
    ]
    sent = model_stream(replies)
    model={'provider':'deepseek','model':'deepseek-v4-pro','api':'responses','effort':'high'}
    answer,meta=asyncio.run(generate(model,'Check conditions',[{'role':'user','content':'Check RG'}],project_id='p',tools=tools_for_mode('verify')))
    assert 'only under' in answer
    assert len(sent)==2
    assert sent[0][0]=='https://api.deepseek.com/responses'
    assert sent[0][1]['tools'][0]['type']=='function'
    assert sent[1][1]['input'][-1]['call_id']=='c1'
    assert meta['tools'][0]['name']=='run_named_physics_check'

def test_custom_chat_completions(monkeypatch,tmp_path,model_stream):
    monkeypatch.setenv('CUSTOM_API_KEY','local')
    monkeypatch.setenv('CUSTOM_API_BASE','http://localhost:9090/v1')
    sent=[]
    replies=[{'model':'local-reasoner','choices':[{'message':{'content':'A physical argument.'}}]}]
    sent = model_stream(replies)
    model={'provider':'custom','model':'local-reasoner','api':'chat_completions','effort':None}
    text,meta=asyncio.run(generate(model,'Act as physicist',[{'role':'user','content':'Explain'}]))
    assert text=='A physical argument.'
    assert sent[0][0]=='http://localhost:9090/v1/chat/completions'
    assert sent[0][1]['messages'][0]['role']=='system'


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
def test_mode_allowlist_is_enforced_and_last_round_requires_an_answer(monkeypatch, protocol, model_stream):
    monkeypatch.setenv('CUSTOM_API_KEY', 'test')
    monkeypatch.setenv('CUSTOM_API_BASE', 'http://localhost/v1')
    sent = []
    forbidden = {'name': 'run_named_physics_check', 'arguments': '{"test_id":"csk_delta_rg"}'}
    if protocol == 'responses':
        call = {'output': [{'type': 'function_call', 'call_id': 'c1', **forbidden}]}
        final = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Reading incomplete.'}]}]}
    else:
        call = {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'c1', 'type': 'function', 'function': forbidden}]}}]}
        final = {'choices': [{'message': {'content': 'Reading incomplete.'}}]}
    from pdvl.providers import TOOL_ROUNDS
    sent = model_stream([call]*(TOOL_ROUNDS-1)+[final])
    async def forbidden_execution(*args):
        pytest.fail('Discuss may not execute unadvertised physics checks')
    monkeypatch.setattr('pdvl.providers.execute_research_tool', forbidden_execution)
    answer, meta = asyncio.run(generate({'provider': 'custom', 'api': protocol, 'model': 'test'},
                                       'Read sources', [], project_id='p', tools=tools_for_mode('discuss')))
    assert answer == 'Reading incomplete.' and len(meta['tools']) == TOOL_ROUNDS-1
    assert len(sent) == TOOL_ROUNDS and 'tools' not in sent[-1][1]
    if protocol == 'responses':
        outputs = [m['output'] for m in sent[-1][1]['input'] if m.get('type') == 'function_call_output']
    else:
        outputs = [m['content'] for m in sent[-1][1]['messages'] if m.get('role') == 'tool']
    assert all(json.loads(output)['error'] == 'Tool not allowed in this mode' for output in outputs)


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
def test_native_streams_handle_tcp_utf8_and_multiline_sse(monkeypatch, protocol):
    import httpx
    monkeypatch.setenv('CUSTOM_API_KEY', 'test');monkeypatch.setenv('CUSTOM_API_BASE', 'http://localhost/v1')
    if protocol == 'responses':
        events = [{'type': 'response.output_text.delta', 'delta': '物理🙂'},
                  {'type': 'response.completed', 'response': {'status': 'completed', 'model': 'actual', 'usage': {'x': 1},
                   'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '物理🙂'}]}]}}]
    else:
        events = [{'choices': [{'delta': {'content': '物理🙂'}}]},
                  {'model': 'actual', 'usage': {'x': 1}, 'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
    raw = ': heartbeat\r\n\r\n' + ''.join('event: message\r\n' + '\r\n'.join('data: '+s for s in json.dumps(e, ensure_ascii=False, indent=1).splitlines()) + '\r\n\r\n' for e in events)
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            data = raw.encode()
            for i in range(0, len(data), 5):
                yield data[i:i+5]
    real_client = httpx.AsyncClient
    monkeypatch.setattr('pdvl.providers.httpx.AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Bytes())), **kw))
    received = []
    async def emit(event):received.append(event)
    answer, meta = asyncio.run(generate({'provider': 'custom', 'api': protocol, 'model': 'test'}, 'Explain', [], emit=emit))
    assert answer == '物理🙂' and meta['model'] == 'actual' and meta['usage'] == {'x': 1}
    assert [e['text'] for e in received if e['type'] == 'delta'] == ['物理🙂']


@pytest.mark.parametrize('body', ['data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n',
                                 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n',
                                 'data: invalid JSON\n\n'])
def test_truncated_or_malformed_streams_fail_explicitly(monkeypatch, body):
    import httpx
    from pdvl.providers import ProviderError
    monkeypatch.setenv('CUSTOM_API_KEY', 'test');monkeypatch.setenv('CUSTOM_API_BASE', 'http://localhost/v1')
    real_client = httpx.AsyncClient
    monkeypatch.setattr('pdvl.providers.httpx.AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)), **kw))
    with pytest.raises(ProviderError):
        asyncio.run(generate({'provider': 'custom', 'api': 'chat_completions', 'model': 'test'}, '', []))


def test_cancellation_closes_upstream_http_stream(monkeypatch):
    import httpx
    monkeypatch.setenv('CUSTOM_API_KEY', 'test');monkeypatch.setenv('CUSTOM_API_BASE', 'http://localhost/v1')
    closed = []
    class Blocking(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n'
            await asyncio.Event().wait()
        async def aclose(self):closed.append(True)
    real_client = httpx.AsyncClient
    monkeypatch.setattr('pdvl.providers.httpx.AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Blocking())), **kw))
    async def run():
        seen = asyncio.Event()
        async def emit(event):
            if event['type'] == 'delta':seen.set()
        task = asyncio.create_task(generate({'provider': 'custom', 'api': 'chat_completions', 'model': 'test'}, '', [], emit=emit))
        await asyncio.wait_for(seen.wait(), 1);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert closed == [True]
