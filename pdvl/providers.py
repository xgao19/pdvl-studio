"""Native streaming protocols with one scoped, provider-neutral research loop."""
from __future__ import annotations
import json
import httpx
from .config import model_settings, provider_key, provider_base
from .tools import execute_research_tool, digest_tool_result

TOOL_ROUNDS = 8


class ProviderError(RuntimeError):
    pass


def models_public() -> list[dict]:
    return [{**m, 'available': bool(provider_key(m))} for m in model_settings()['models']]


def pick_model(mode: str, model_id: str | None = None) -> dict:
    cfg = model_settings()
    target = model_id or cfg[mode]
    try:
        return next(m for m in cfg['models'] if m['id'] == target)
    except StopIteration:
        raise ValueError(f'unknown model id: {target}')


def extract_output(payload: dict) -> str:
    chunks = [piece.get('text', '') for item in payload.get('output', []) if item.get('type') == 'message'
              for piece in item.get('content', []) if piece.get('type') in ('output_text', 'text')]
    answer = '\n'.join(chunks) or payload.get('output_text')
    if not answer:
        raise ProviderError('No assistant text returned; inspect provider capabilities')
    return answer


async def sse_data(response):
    """Decode complete SSE frames, including multiline data and arbitrary TCP boundaries."""
    data = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield '\n'.join(data)
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].removeprefix(' '))
    if data:
        yield '\n'.join(data)


async def stream_round(client, url, key, payload, protocol, emit):
    text, calls, usage, actual_model = '', {}, {}, payload['model']
    finished = False
    async with client.stream('POST', url, headers={'Authorization': f'Bearer {key}'}, json=payload) as response:
        if response.is_error:
            # Status only: upstream error bodies may echo prompts or credentials.
            raise ProviderError(f'Provider API returned HTTP {response.status_code}')
        async for raw in sse_data(response):
            if raw == '[DONE]':
                break
            data = json.loads(raw)
            if data.get('error') or data.get('type') in ('error', 'response.failed', 'response.incomplete'):
                raise ProviderError('Provider stream failed or was incomplete')
            if protocol == 'responses':
                if data.get('type') == 'response.output_text.delta':
                    delta = data.get('delta', '')
                    text += delta
                    if delta:
                        await emit({'type': 'delta', 'text': delta})
                if data.get('type') == 'response.completed':
                    result = data['response']
                    if result.get('status') != 'completed':
                        raise ProviderError('Provider response did not complete')
                    return result
            else:
                actual_model = data.get('model', actual_model)
                usage = data.get('usage') or usage
                for choice in data.get('choices', []):
                    if choice.get('index', 0) != 0:
                        continue
                    delta = choice.get('delta', {})
                    chunk = delta.get('content') or ''
                    if chunk:
                        text += chunk
                        await emit({'type': 'delta', 'text': chunk})
                    for fragment in delta.get('tool_calls', []):
                        item = calls.setdefault(fragment['index'], {'id': '', 'type': 'function',
                                                                    'function': {'name': '', 'arguments': ''}})
                        item['id'] += fragment.get('id') or ''
                        for field in ('name', 'arguments'):
                            item['function'][field] += fragment.get('function', {}).get(field) or ''
                    reason = choice.get('finish_reason')
                    if reason:
                        if reason not in ('stop', 'tool_calls'):
                            raise ProviderError(f'Provider response ended early ({reason})')
                        finished = True
    if protocol == 'chat_completions' and finished:
        return {'model': actual_model, 'usage': usage, 'choices': [{'message': {
            'role': 'assistant', 'content': text or None, 'tool_calls': [calls[i] for i in sorted(calls)]}}]}
    raise ProviderError('Provider stream disconnected before completion')


async def call_tool(name, arguments, project_id, tools, trace, emit):
    try:
        args = json.loads(arguments)
    except (ValueError, TypeError):
        args = None
    await emit({'type': 'tool_start', 'name': name, 'args': args})
    if not project_id or name not in {tool['name'] for tool in tools or []}:
        result = {'error': 'Tool not allowed in this mode'}
    else:
        result = await execute_research_tool(name, args, project_id)
    record = {'name': name, 'args': args, 'result_sha256': digest_tool_result(result)}
    if result.get('error'):
        record['error'] = result['error']
    if result.get('search_artifact_id'):
        record['search_artifact_id'] = result['search_artifact_id']
    if name in ('read_research_artifact', 'open_web_page') and result.get('text'):
        record['source'] = {'artifact_id': result['id'], 'page': result['page'],
                            'offset': result['offset'], 'length': len(result['text']), 'sha256': result['sha256'],
                            'kind': result['kind'], 'title': result.get('title', result['name'])}
    trace.append(record)
    await emit({'type': 'tool_end', **record})
    return json.dumps(result, ensure_ascii=False)


async def generate(model: dict, instructions: str, messages: list[dict], project_id: str | None = None,
                   tools: list[dict] | None = None, *, emit=None, trace=None) -> tuple[str, dict]:
    """All callers use streaming upstream; batch evaluations simply collect the result."""
    if emit is None:
        async def emit(_event):
            pass
    key = provider_key(model)
    if not key:
        raise ProviderError('Missing API key: configure the selected provider before chatting')
    protocol = model['api']
    if protocol not in ('responses', 'chat_completions'):
        raise ProviderError('Unsupported model protocol')
    trace = [] if trace is None else trace
    turns = list(messages) if protocol == 'responses' else [{'role': 'system', 'content': instructions}] + list(messages)
    url = provider_base(model).rstrip('/') + ('/responses' if protocol == 'responses' else '/chat/completions')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=15)) as client:
            for number in range(TOOL_ROUNDS):
                await emit({'type': 'progress', 'round': number + 1, 'message': '正在分析问题与已读取资料'})
                allowed = tools if project_id and number < TOOL_ROUNDS - 1 else []
                budget = '\nTool budget reached. Answer from pages actually read; identify remaining gaps.'
                payload = {'model': model['model'], 'stream': True}
                if protocol == 'responses':
                    payload.update(instructions=instructions + (budget if number == TOOL_ROUNDS - 1 else ''),
                                   input=turns, max_output_tokens=6000)
                    if model.get('effort'):
                        payload['reasoning'] = {'effort': model['effort']}
                    if allowed:
                        payload['tools'] = allowed
                else:
                    payload.update(messages=turns + ([{'role': 'system', 'content': budget}] if number == TOOL_ROUNDS - 1 else []),
                                   max_tokens=6000, stream_options={'include_usage': True})
                    if allowed:
                        payload['tools'] = [{'type': 'function', 'function': {k: v for k, v in t.items() if k != 'type'}} for t in allowed]
                data = await stream_round(client, url, key, payload, protocol, emit)
                if protocol == 'responses':
                    pending = [x for x in data.get('output', []) if x.get('type') == 'function_call']
                    if pending:
                        turns.extend(x for x in data['output'] if x.get('type') in ('function_call', 'message'))
                    else:
                        answer = extract_output(data)
                else:
                    result = data['choices'][0]['message']
                    pending = result.get('tool_calls') or []
                    if pending:
                        turns.append(result)
                    else:
                        answer = result.get('content')
                        if not answer:
                            raise ProviderError('Provider returned no assistant text')
                if not pending:
                    return answer, {'model': data.get('model', model['model']), 'provider': model['provider'],
                                    'usage': data.get('usage', {}), 'tools': trace}
                for item in pending:
                    function = item if protocol == 'responses' else item['function']
                    output = await call_tool(function['name'], function.get('arguments', '{}'), project_id, allowed, trace, emit)
                    turns.append({'type': 'function_call_output', 'call_id': item['call_id'], 'output': output}
                                 if protocol == 'responses' else {'role': 'tool', 'tool_call_id': item['id'], 'content': output})
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ProviderError(f'Provider stream failed ({type(exc).__name__})') from None
    raise ProviderError('Research tool-call budget exhausted; no final text was produced')
