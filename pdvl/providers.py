"""Native Responses adapters, with own read-only research tools.

Do not assume vendor-hosted tools are portable across APIs. All tool calls are
executed locally under a small allowlist and never promote scientific claims.
"""
from __future__ import annotations
import json
import httpx
from .config import model_settings, provider_key, provider_base
from .tools import TOOL_DEFS, execute_research_tool, digest_tool_result

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
                   project_id: str | None = None, allow_tools: bool = False) -> tuple[str,dict]:
    key = provider_key(model)
    if not key:
        env_name={'openai':'OPENAI_API_KEY','deepseek':'DEEPSEEK_API_KEY','custom':'CUSTOM_API_KEY'}[model['provider']]
        raise ProviderError(f'Missing {env_name}: configure .env before using this model')
    if model['api'] == 'chat_completions':
        return await generate_chat_completions(model, instructions, messages, project_id, allow_tools)
    if model['api'] != 'responses':
        raise ProviderError('Unsupported model protocol')
    turns=list(messages)
    trace=[]
    url=provider_base(model).rstrip('/')+'/responses'
    last_usage={}
    last_model=model['model']
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,connect=15)) as client:
            for _ in range(4):  # limit recursive tool use and potential API spending
                payload={'model':model['model'],'instructions':instructions,'input':turns,'max_output_tokens':6000}
                if model.get('effort'):
                    payload['reasoning']={'effort':model['effort']}
                if allow_tools and project_id:
                    payload['tools']=TOOL_DEFS
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
                        try: args=json.loads(call.get('arguments','{}'))
                        except json.JSONDecodeError: args={}
                        result=await execute_research_tool(call['name'], args, project_id)
                        trace.append({'name':call['name'],'args':args,'result_sha256':digest_tool_result(result)})
                        turns.append({'type':'function_call_output','call_id':call['call_id'],
                                      'output':json.dumps(result,ensure_ascii=False)[:10000]})
                    continue
                answer=extract_output(data)
                return answer, {'model':last_model,'provider':model['provider'],
                                'usage':last_usage,'tools':trace}
    except httpx.HTTPStatusError as exc:
        # Do not leak API authorization headers in exception details.
        raise ProviderError(f"{model['provider']} API returned HTTP {exc.response.status_code}: {exc.response.text[:600]}") from None
    except (httpx.HTTPError,ValueError) as exc:
        raise ProviderError(f"Provider call failed: {type(exc).__name__}: {str(exc)[:300]}") from None
    raise ProviderError('Research tool-call budget exhausted (4 rounds); no final text was produced')


async def generate_chat_completions(model: dict, instructions: str, messages: list[dict],
                                    project_id: str | None, allow_tools: bool) -> tuple[str,dict]:
    """Portable fallback for APIs without Responses support (e.g. many local servers)."""
    turns=[{'role':'system','content':instructions}] + list(messages)
    trace=[]
    url=provider_base(model).rstrip('/')+'/chat/completions'
    key=provider_key(model)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,connect=15)) as client:
            for _ in range(4):
                payload={'model':model['model'],'messages':turns,'max_tokens':6000}
                if allow_tools and project_id:
                    payload['tools']=[{'type':'function','function':{k:v for k,v in item.items() if k!='type'}} for item in TOOL_DEFS]
                response=await client.post(url,headers={'Authorization':f'Bearer {key}'},json=payload)
                response.raise_for_status()
                data=response.json()
                result=data.get('choices',[{}])[0].get('message',{})
                calls=result.get('tool_calls') or []
                if calls:
                    turns.append(result)
                    for item in calls:
                        function=item['function']
                        try: args=json.loads(function.get('arguments','{}'))
                        except json.JSONDecodeError: args={}
                        output=await execute_research_tool(function['name'],args,project_id)
                        trace.append({'name':function['name'],'args':args,'result_sha256':digest_tool_result(output)})
                        turns.append({'role':'tool','tool_call_id':item['id'],
                                      'content':json.dumps(output,ensure_ascii=False)[:10000]})
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
