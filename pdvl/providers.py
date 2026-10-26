"""Provider-native Responses and Chat Completions with scoped research tools.

Do not assume vendor-hosted tools are portable across APIs. All tool calls are
executed locally under a small allowlist and never promote scientific claims.
"""
from __future__ import annotations
import json
import httpx
from .config import model_settings, provider_key, provider_base
from .tools import execute_research_tool, digest_tool_result

TOOL_ROUNDS = 8


async def call_tool(name, arguments, project_id, tools, trace):
    try:
        args = json.loads(arguments)
    except (ValueError, TypeError):
        args = None
    if not project_id or name not in {tool['name'] for tool in tools or []}:
        result = {'error': 'Tool not allowed in this mode'}
    else:
        result = await execute_research_tool(name, args, project_id)
    record = {'name': name, 'args': args, 'result_sha256': digest_tool_result(result)}
    if name == 'read_research_artifact' and result.get('text'):
        record['source'] = {'artifact_id': result['id'], 'page': result['page'], 'offset': result['offset']}
    trace.append(record)
    return json.dumps(result, ensure_ascii=False)

class ProviderError(RuntimeError):
    pass

def models_public() -> list[dict]:
    return [{**m, "available": bool(provider_key(m))} for m in model_settings()["models"]]

def pick_model(mode: str, model_id: str | None = None) -> dict:
    cfg = model_settings()
    target = model_id or cfg[mode]
    try:
        return next(m for m in cfg["models"] if m["id"] == target)
    except StopIteration:
        raise ValueError(f"unknown model id: {target}")

def extract_output(payload: dict) -> str:
    chunks=[]
    for item in payload.get('output',[]):
        if item.get('type')=='message':
            for piece in item.get('content',[]):
                if piece.get('type') in ('output_text','text'):
                    chunks.append(piece.get('text',''))
    if chunks:
        return '\n'.join(chunks)
    if payload.get('output_text'):
        return payload['output_text']
    raise ProviderError('No assistant text returned; inspect provider capabilities')

async def generate(model: dict, instructions: str, messages: list[dict],
                   project_id: str | None = None, tools: list[dict] | None = None) -> tuple[str,dict]:
    key = provider_key(model)
    if not key:
        env_name={'openai':'OPENAI_API_KEY','deepseek':'DEEPSEEK_API_KEY','custom':'CUSTOM_API_KEY'}[model['provider']]
        raise ProviderError(f'Missing {env_name}: configure .env before using this model')
    if model['api'] == 'chat_completions':
        return await generate_chat_completions(model, instructions, messages, project_id, tools)
    if model['api'] != 'responses':
        raise ProviderError('Unsupported model protocol')
    turns=list(messages)
    trace=[]
    url=provider_base(model).rstrip('/')+'/responses'
    last_usage={}
    last_model=model['model']
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,connect=15)) as client:
            for round_number in range(TOOL_ROUNDS):
                payload={'model':model['model'],'instructions':instructions,'input':turns,'max_output_tokens':6000}
                if model.get('effort'):
                    payload['reasoning']={'effort':model['effort']}
                if tools and project_id and round_number < TOOL_ROUNDS - 1:
                    payload['tools']=tools
                if round_number == TOOL_ROUNDS - 1:
                    payload['instructions'] += '\nTool budget reached. Answer from the pages actually read; identify remaining gaps.'
                response=await client.post(url,headers={'Authorization':f'Bearer {key}',
                          'Content-Type':'application/json'},json=payload)
                response.raise_for_status()
                data=response.json()
                last_usage=data.get('usage',{})
                last_model=data.get('model',model['model'])
                pending=[x for x in data.get('output',[]) if x.get('type')=='function_call']
                if pending:
                    # Stateless replay is essential for DeepSeek, also supported by OpenAI.
                    for item in data.get('output',[]):
                        if item.get('type') in ('function_call','message'):
                            turns.append(item)
                    for call in pending:
                        result=await call_tool(call['name'], call.get('arguments','{}'), project_id,
                                               tools if round_number < TOOL_ROUNDS - 1 else [], trace)
                        turns.append({'type':'function_call_output','call_id':call['call_id'],
                                      'output':result})
                    continue
                answer=extract_output(data)
                return answer, {'model':last_model,'provider':model['provider'],
                                'usage':last_usage,'tools':trace}
    except httpx.HTTPStatusError as exc:
        # Do not leak API authorization headers in exception details.
        raise ProviderError(f"{model['provider']} API returned HTTP {exc.response.status_code}: {exc.response.text[:600]}") from None
    except (httpx.HTTPError,ValueError) as exc:
        raise ProviderError(f"Provider call failed: {type(exc).__name__}: {str(exc)[:300]}") from None
    raise ProviderError('Research tool-call budget exhausted; no final text was produced')


async def generate_chat_completions(model: dict, instructions: str, messages: list[dict],
                                    project_id: str | None, tools: list[dict] | None) -> tuple[str,dict]:
    """Native Chat Completions adapter for the configured provider."""
    turns=[{'role':'system','content':instructions}] + list(messages)
    trace=[]
    url=provider_base(model).rstrip('/')+'/chat/completions'
    key=provider_key(model)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,connect=15)) as client:
            for round_number in range(TOOL_ROUNDS):
                payload={'model':model['model'],'messages':turns,'max_tokens':6000}
                if tools and project_id and round_number < TOOL_ROUNDS - 1:
                    payload['tools']=[{'type':'function','function':{k:v for k,v in item.items() if k!='type'}} for item in tools]
                if round_number == TOOL_ROUNDS - 1:
                    payload['messages'] = turns + [{'role':'system','content':'Tool budget reached. Answer from pages actually read; identify remaining gaps.'}]
                response=await client.post(url,headers={'Authorization':f'Bearer {key}'},json=payload)
                response.raise_for_status()
                data=response.json()
                result=data.get('choices',[{}])[0].get('message',{})
                calls=result.get('tool_calls') or []
                if calls:
                    turns.append(result)
                    for item in calls:
                        function=item['function']
                        output=await call_tool(function['name'],function.get('arguments','{}'),project_id,
                                               tools if round_number < TOOL_ROUNDS - 1 else [],trace)
                        turns.append({'role':'tool','tool_call_id':item['id'],
                                      'content':output})
                    continue
                text=result.get('content')
                if not text: raise ProviderError('Chat Completions returned no assistant text')
                return text, {'model':data.get('model',model['model']), 'provider':model['provider'],
                              'usage':data.get('usage',{}),'tools':trace}
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{model['provider']} Chat Completions HTTP {exc.response.status_code}: {exc.response.text[:600]}") from None
    except (httpx.HTTPError,ValueError) as exc:
        raise ProviderError(f"Provider call failed: {type(exc).__name__}: {str(exc)[:300]}") from None
    raise ProviderError('Tool-call budget exhausted without final answer')
