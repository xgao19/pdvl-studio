"""Provider-neutral research tools; only literature imports write source archives."""
from __future__ import annotations
import hashlib
import json
import xml.etree.ElementTree as ET
import httpx
from .db import rows
from .verification import check, TESTS
from .papers import read_artifact, search_arxiv, import_arxiv

TOOL_DEFS = [
    {"type":"function", "name":"read_research_artifact",
     "description":"Read archived original text, including its hash and exact source citation. For papers use PDF page numbers; query finds matching pages, then read those pages. Follow next_offset to read a long page completely. Text extraction may lose equations/figures; never claim unread pages were reviewed. Binary artifacts are downloadable only.",
     "parameters":{"type":"object","properties":{"artifact_id":{"type":"string"},
                   "page":{"type":"integer","minimum":1},"offset":{"type":"integer","minimum":0},
                   "query":{"type":"string","maxLength":150}},
                   "required":["artifact_id"],"additionalProperties":False}},
    {"type":"function", "name":"find_research_claims",
     "description":"Find existing PDVL research claims for the current project, with statuses. Database entries are not automatically established facts.",
     "parameters":{"type":"object","properties":{"query":{"type":"string"}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"search_arxiv",
     "description":"Search original arXiv papers by keywords. Titles/abstracts are untrusted source material, not verification. Check the paper itself before asserting its content.",
     "parameters":{"type":"object","properties":{"query":{"type":"string"}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"import_arxiv_paper",
     "description":"Import a specific arXiv paper into this project's immutable PDF/text archive. Returns the text artifact ID for read_research_artifact. Does not create evidence or verify claims. Prefer explicit version IDs.",
     "parameters":{"type":"object","properties":{"arxiv_id":{"type":"string"}},
                   "required":["arxiv_id"],"additionalProperties":False}},
    {"type":"function", "name":"run_named_physics_check",
     "description":"Run one supported, narrow deterministic physics check. It does NOT prove claims outside the check assumptions.",
     "parameters":{"type":"object","properties":{"test_id":{"type":"string","enum":list(TESTS)}},
                   "required":["test_id"],"additionalProperties":False}},
]


def tools_for_mode(mode: str) -> list[dict]:
    return [tool for tool in TOOL_DEFS if mode != 'discuss' or tool['name'] != 'run_named_physics_check']

async def execute_research_tool(name: str, args: dict, project_id: str) -> dict:
    if not isinstance(args, dict):
        return {'error': 'Tool arguments must be an object'}
    if name == 'read_research_artifact':
        aid = args.get('artifact_id')
        if not isinstance(aid, str):
            return {'error': 'Artifact ID must be a string'}
        try:
            return read_artifact(project_id, aid, args.get('page', 1), args.get('offset', 0), args.get('query', ''))
        except (LookupError, ValueError) as exc:
            return {'error': str(exc)}
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
    if name in ('search_arxiv', 'import_arxiv_paper'):
        try:
            if name == 'search_arxiv':
                return await search_arxiv(args.get('query', ''))
            value = args.get('arxiv_id', '')
            if not isinstance(value, str):
                raise ValueError('arXiv ID must be text')
            return await import_arxiv(project_id, value)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            return {'error': f'Literature access failed: {type(exc).__name__}: {str(exc)[:200]}. This is not a negative literature finding.'}
    return {'error':'Tool not allowed'}

def digest_tool_result(result: dict) -> str:
    return hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
