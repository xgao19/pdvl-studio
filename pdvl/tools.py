"""Provider-neutral research tools; literature and web tools write source archives."""
from __future__ import annotations
import hashlib
import json
import xml.etree.ElementTree as ET
import httpx
from .db import rows
from .verification import check, TESTS
from .papers import read_artifact, search_arxiv, import_arxiv, search_library
from .config import ollama_web_key
from .web_sources import search_web, open_web_page

TOOL_DEFS = [
    {"type":"function", "name":"search_web",
     "description":"Search the public web using Ollama. Returns untrusted title/URL/snippet leads and archives the search response. Snippets are not original reading: open multiple relevant sources before attributing findings. Prefer primary sources. For follow-ups reuse archived sources with read_research_artifact.",
     "parameters":{"type":"object","properties":{"query":{"type":"string","minLength":2,"maxLength":300}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"open_web_page",
     "description":"Fetch a public HTTP(S) webpage through Ollama, archive the extracted body and service response, then read section 1. Returns exact archive citation, source URL, retrieval date, hash and section count. Read other sections with read_research_artifact; sections are text segments, not PDF pages. Does not execute scripts, guarantee complete extraction, or verify claims. Follow-up questions should reread existing artifact IDs unless fresh web information is needed.",
     "parameters":{"type":"object","properties":{"url":{"type":"string","maxLength":2048}},
                   "required":["url"],"additionalProperties":False}},
    {"type":"function", "name":"search_project_papers",
     "description":"Rank keyword matches across all archived papers in this project. Search useful English terminology for English papers. Returns page excerpts, not full-paper reading. Read the relevant original pages before citing; no matches are not negative scientific evidence.",
     "parameters":{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":150}},
                   "required":["query"],"additionalProperties":False}},
    {"type":"function", "name":"read_research_artifact",
     "description":"Read archived original text, including its hash and exact source citation. For papers use PDF page numbers; for webpages page selects a stored section. query is ONE literal case-insensitive substring, e.g. snippet, not a semantic or multi-keyword query; it finds excerpts, then read the matching pages/sections. Follow next_offset to read a long page completely. Extraction may lose content; never claim unread material was reviewed. Search snippets and binary artifacts are downloadable provenance only.",
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
    web_available = bool(ollama_web_key())
    return [tool for tool in TOOL_DEFS
            if (mode != 'discuss' or tool['name'] != 'run_named_physics_check')
            and (web_available or tool['name'] not in ('search_web', 'open_web_page'))]

async def execute_research_tool(name: str, args: dict, project_id: str) -> dict:
    if not isinstance(args, dict):
        return {'error': 'Tool arguments must be an object'}
    if name in ('search_web', 'open_web_page'):
        try:
            return await (search_web(project_id, args.get('query', '')) if name == 'search_web'
                          else open_web_page(project_id, args.get('url', '')))
        except httpx.HTTPError as exc:
            return {'error': f'Web access failed: {type(exc).__name__}; no webpage was read. This is not a negative finding.'}
        except (ValueError, LookupError) as exc:
            return {'error': str(exc)}
    if name == 'search_project_papers':
        try:
            return search_library(project_id, args.get('query', ''))
        except ValueError as exc:
            return {'error': str(exc)}
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
