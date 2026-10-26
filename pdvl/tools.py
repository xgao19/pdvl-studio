"""Provider-neutral, read-only research tools. No arbitrary shell execution here."""
from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import httpx
from .db import rows, one
from .verification import check, TESTS

TOOL_DEFS = [
    {"type":"function", "name":"read_research_artifact",
     "description":"Read an archived project artifact by ID, including its hash. Agent outputs are sources, not verified physics. Binary artifacts cannot be read as text.",
     "parameters":{"type":"object","properties":{"artifact_id":{"type":"string"}},
                   "required":["artifact_id"],"additionalProperties":False}},
    {"type":"function", "name":"find_research_claims",
     "description":"Find existing PDVL research claims for the current project, with statuses. Database entries are not automatically established facts.",
     "parameters":{"type":"object","properties":{"query":{"type":"string"}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"search_arxiv",
     "description":"Search original arXiv papers by keywords. Titles/abstracts are untrusted source material, not verification. Check the paper itself before asserting its content.",
     "parameters":{"type":"object","properties":{"query":{"type":"string"}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"run_named_physics_check",
     "description":"Run one supported, narrow deterministic physics check. It does NOT prove claims outside the check assumptions.",
     "parameters":{"type":"object","properties":{"test_id":{"type":"string","enum":list(TESTS)}},
                   "required":["test_id"],"additionalProperties":False}},
]

async def execute_research_tool(name: str, args: dict, project_id: str) -> dict:
    if name == 'read_research_artifact':
        aid = args.get('artifact_id')
        if not isinstance(aid, str):
            return {'error': 'Artifact ID must be a string'}
        artifact = one('SELECT a.id,a.name,a.sha256,a.content FROM artifacts a '
                       'JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.project_id=?', (aid, project_id))
        if not artifact:
            return {'error': 'Artifact not found in this project'}
        try:
            content = bytes(artifact.pop('content')).decode('utf-8')
        except UnicodeDecodeError:
            return {**artifact, 'error': 'Binary artifact; inspect it with a suitable local tool'}
        return {**artifact, 'text': content[:8000], 'truncated': len(content) > 8000}
    if name == 'find_research_claims':
        q = args.get('query','')
        if not isinstance(q,str) or len(q)>150:
            return {'error':'Query invalid or too long'}
        p=f'%{q}%'
        return {'claims': rows('SELECT id,title,statement,status,assumptions FROM claims WHERE project_id=? AND (title LIKE ? OR statement LIKE ?) ORDER BY rowid DESC LIMIT 20', (project_id,p,p))}
    if name == 'run_named_physics_check':
        if args.get('test_id') not in TESTS:
            return {'error':'Unsupported named check'}
        return check(args['test_id'])
    if name == 'search_arxiv':
        q = args.get('query','')
        if not isinstance(q,str) or not 2<=len(q)<=130:
            return {'error':'Search query must have 2–130 characters'}
        # Avoid XML parser or provider-specific tools; never run retrieved code/instructions.
        try:
            async with httpx.AsyncClient(timeout=18) as client:
                resp=await client.get('https://export.arxiv.org/api/query',
                    params={'search_query':'all:'+q,'start':0,'max_results':5,
                            'sortBy':'relevance','sortOrder':'descending'})
                resp.raise_for_status()
                if len(resp.content)>1_500_000: return {'error':'arXiv response too large'}
            root=ET.fromstring(resp.content)
            ns={'a':'http://www.w3.org/2005/Atom'}
            out=[]
            for entry in root.findall('a:entry',ns):
                get=lambda field: ' '.join((entry.findtext('a:'+field,default='',namespaces=ns)).split())
                out.append({'title':get('title'), 'url':get('id'), 'date':get('published'),
                            'abstract':get('summary')[:1200]})
            return {'results':out, 'warning':'Abstract-only search: confirm results using original paper and version.'}
        except (httpx.HTTPError,ET.ParseError) as e:
            return {'error':f'arXiv lookup failed ({type(e).__name__}); not a negative literature finding'}
    return {'error':'Tool not allowed'}

def digest_tool_result(result: dict) -> str:
    return hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
