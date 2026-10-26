from __future__ import annotations
import asyncio
import json
import os
import xml.etree.ElementTree as ET
import httpx
from typing import Literal
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse
from contextlib import asynccontextmanager, suppress
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from markdown_it import MarkdownIt
import bleach
from .config import ROOT, model_settings, codex_runtime, codex_public
from .db import init_db, one, rows, execute, uid, utcnow, append_evidence, connection, add_run_event
from .prompts import MODE_PROMPTS, DEFAULT_SCIENTIFIC_VOICE
from .research import project_snapshot, research_context, citation_ids, validate_chat_citations
from .providers import pick_model, models_public, generate, ProviderError
from .verification import check, TESTS
from .tools import tools_for_mode
from .papers import list_papers, search_arxiv, import_arxiv, archive_pdf, read_artifact, MAX_PDF_BYTES, search_library
from . import __version__

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield

app = FastAPI(title="PDVL Studio", version=__version__, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
active_chats: dict[str, tuple[str, asyncio.Task]] = {}

@app.middleware("http")
async def restrict_browser_origins(request: Request, call_next):
    # Blocks normal CSRF from cross-origin browsers (not a replacement for multi-user auth).
    origin = request.headers.get("origin", "")
    if origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765",
                                f"http://127.0.0.1:{os.getenv('PDVL_PORT','8765')}",
                                f"http://localhost:{os.getenv('PDVL_PORT','8765')}"):
        return PlainTextResponse("Cross-origin access denied", status_code=403)
    return await call_next(request)

class NewProject(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8000)

class NewMessage(BaseModel):
    mode: Literal["discuss", "investigate", "verify", "write"] = "discuss"
    message: str = Field(min_length=1, max_length=40000)
    model_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list, max_length=2)

class ImportPaper(BaseModel):
    arxiv_id: str = Field(min_length=1, max_length=160)

class NewClaim(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=8000)
    assumptions: list[str] = Field(default_factory=list)
    kind: Literal["general", "rg_identity", "experimental_extraction"] = "general"

class NewEvidence(BaseModel):
    claim_id: str
    kind: Literal["literature", "derivation", "numerical", "note"] = "note"
    verdict: Literal["supporting", "challenging", "unresolved"] = "unresolved"
    description: str = Field(min_length=1, max_length=10000)
    provenance: dict = Field(default_factory=dict)
    artifact_id: str | None = Field(default=None, min_length=1)

class NewRun(BaseModel):
    model_config = {'extra': 'forbid'}
    question: str = Field(min_length=1, max_length=10000)
    title: str = Field(default="Codex investigation", max_length=250)

class ContinueRun(BaseModel):
    message: str = Field(min_length=1, max_length=10000)

class NewDocument(BaseModel):
    model_config = {'extra': 'forbid'}
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=250000)
    document_id: str | None = None

class EditorialStyle(BaseModel):
    style_text: str = Field(min_length=1, max_length=8000)

class NewDecision(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    by_role: Literal["human", "agent"] = "human"


def project_required(pid: str) -> dict:
    project = one("SELECT * FROM projects WHERE id=?", (pid,))
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def codex_required() -> dict:
    if os.getenv('PDVL_CODEX_ENABLED', '0') != '1':
        raise HTTPException(409, 'Codex worker disabled; configure the isolated provider and set PDVL_CODEX_ENABLED=1')
    try:
        runtime = codex_runtime()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if not os.getenv(runtime['env_key']):
        raise HTTPException(409, 'Missing API key for the isolated Codex provider')
    return runtime

@app.get("/")
def home_page():
    return FileResponse(ROOT / "web/index.html")

class MarkdownRender(BaseModel):
    markdown: str = Field(min_length=0, max_length=250000)
    blocked_links: list[str] = Field(default_factory=list, max_length=1000)

@app.post('/api/render')
def render_markdown(body: MarkdownRender):
    # The application never loads third-party JS on the browser page, important for unpublished physics.
    renderer=MarkdownIt('commonmark',{'html':False,'linkify':False})
    tokens=renderer.parse(body.markdown)
    blocked=set(body.blocked_links)
    for block in tokens:
        for token in block.children or []:
            if token.type == 'link_open' and token.attrGet('href') in blocked:
                token.attrs = {'title': '引用未通过校验，请核对读取记录'}
    html=renderer.renderer.render(tokens, renderer.options, {})
    tags={'p','h1','h2','h3','h4','ul','ol','li','em','strong','code','pre','blockquote','a',
          'table','thead','tbody','tr','th','td','hr','br'}
    sanitized=bleach.clean(html,tags=tags,attributes={'a':['href','title']},protocols=['http','https','mailto'],strip=True)
    return {'html':sanitized}

@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version,
            "codex_enabled": os.getenv("PDVL_CODEX_ENABLED", "0") == "1"}

@app.get("/api/models")
def models():
    settings = model_settings()
    return {"models": models_public(), "defaults": {m: settings[m] for m in MODE_PROMPTS},
            "codex": codex_public()}

@app.get("/api/projects")
def list_projects():
    return rows("SELECT * FROM projects ORDER BY created_at DESC")

@app.post("/api/projects", status_code=201)
def create_project(request: NewProject):
    pid = uid("p")
    execute("INSERT INTO projects VALUES (?,?,?,?)", (pid, request.title, request.description, utcnow()))
    return project_required(pid)

@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return project_required(pid)

@app.get("/api/projects/{pid}/messages")
def messages(pid: str, mode: Literal["discuss", "investigate", "verify", "write"] = "discuss"):
    project_required(pid)
    return rows("SELECT * FROM messages WHERE project_id=? AND mode=? ORDER BY created_at, rowid", (pid, mode))

@app.post("/api/projects/{pid}/chat")
async def chat(pid: str, req: NewMessage):
    project_required(pid)
    try:
        model = pick_model(req.mode, req.model_id)
    except ValueError as error:
        raise HTTPException(422, str(error))
    prior = rows("SELECT * FROM messages WHERE project_id=? AND mode=? ORDER BY rowid DESC LIMIT 16", (pid, req.mode))
    conversation = []
    for item in reversed(prior):
        state = json.loads(item['meta_json']).get('state')
        prefix = f'[Previous response {state}; incomplete.]\n' if item['role'] == 'assistant' and state in ('stopped', 'failed') else ''
        conversation.append({'role': item['role'], 'content': prefix + item['content']})
    conversation.append({"role": "user", "content": req.message})
    snapshot = project_snapshot(pid)
    context = research_context(snapshot, req.mode)
    available = {p['id']: p for p in snapshot['papers']}
    selected = []
    for aid in dict.fromkeys(req.paper_ids):
        paper = available.get(aid)
        if not paper:
            raise HTTPException(404, 'Selected paper not found in this project')
        selected.append(paper)
    if selected:
        context += '\n\nPapers selected for this question:\n' + json.dumps(selected, ensure_ascii=False)
        context += '\nRead original pages of every selected paper before analyzing or comparing their findings.'
    if req.mode in ('discuss','write'):
        style=one('SELECT style_text FROM editorial_styles WHERE project_id=?',(pid,))
        context += "\n\nEditorial preference (style guidance, not physical evidence): " + (style['style_text'] if style else DEFAULT_SCIENTIFIC_VOICE)
    # A single request owns its upstream calls. Closing it cancels the producer,
    # including an in-flight model request, tool import or arXiv wait.
    async def events():
        queue = asyncio.Queue(maxsize=32)
        disconnected = False
        trace, draft = [], []
        mid = uid('m')
        previous_reads = [t['source'] for item in prior if item['role'] == 'assistant'
                          for t in json.loads(item['meta_json']).get('tools', []) if t.get('source')]

        async def emit(event):
            if event['type'] == 'progress':
                draft.clear()
            elif event['type'] == 'delta':
                draft.append(event['text'])
            await queue.put(event)

        async def produce():
            answer, state, error = '', 'completed', None
            meta = {'model': model['model'], 'provider': model['provider'], 'tools': trace}
            try:
                answer, meta = await generate(model, MODE_PROMPTS[req.mode] + '\n\n' + context, conversation,
                                              project_id=pid, tools=tools_for_mode(req.mode), emit=emit, trace=trace)
            except asyncio.CancelledError:
                state = 'stopped'
            except ProviderError as exc:
                state, error = 'failed', str(exc)
            except Exception:
                state, error = 'failed', '聊天执行失败，请重试；已保留读取记录'
            finally:
                answer = answer if state == 'completed' else ''.join(draft)
                answer, checks = validate_chat_citations(pid, answer, previous_reads + [t['source'] for t in trace if t.get('source')])
                meta.update(state=state, citations=checks)
                if error:
                    meta['error'] = error
                with connection() as con:
                    timestamp = utcnow()
                    con.execute("INSERT INTO messages(id,project_id,mode,role,content,model_id,created_at,meta_json) VALUES (?,?,?,?,?,?,?,?)",
                                (uid('m'), pid, req.mode, 'user', req.message, None, timestamp, json.dumps({'paper_ids': req.paper_ids})))
                    con.execute("INSERT INTO messages(id,project_id,mode,role,content,model_id,created_at,meta_json) VALUES (?,?,?,?,?,?,?,?)",
                                (mid, pid, req.mode, 'assistant', answer, model['id'], timestamp, json.dumps(meta, ensure_ascii=False)))
            if not disconnected:
                await queue.put({'type': 'done', 'id': mid, 'answer': answer, 'meta': meta, 'mode': req.mode})

        task = asyncio.create_task(produce())
        active_chats[mid] = (pid, task)
        try:
            await asyncio.sleep(0)  # Enter producer cleanup before exposing its stop handle.
            yield json.dumps({'type': 'start', 'id': mid}) + '\n'
            while True:
                waiting = asyncio.create_task(queue.get())
                try:
                    ready, _ = await asyncio.wait((waiting, task), return_when=asyncio.FIRST_COMPLETED)
                    if task in ready:
                        await task  # Surface storage/validation failures instead of hanging on an empty queue.
                    item = await waiting
                finally:
                    waiting.cancel()
                    with suppress(asyncio.CancelledError):
                        await waiting
                yield json.dumps(item, ensure_ascii=False) + '\n'
                if item['type'] == 'done':
                    break
        finally:
            disconnected = True
            task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await task
            finally:
                active_chats.pop(mid, None)

    return StreamingResponse(events(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.post('/api/projects/{pid}/messages/{mid}/stop')
async def stop_chat(pid: str, mid: str):
    project_required(pid)
    message = one("SELECT meta_json FROM messages WHERE id=? AND project_id=? AND role='assistant'", (mid, pid))
    if message:
        return {'state': json.loads(message['meta_json']).get('state', 'completed')}
    active = active_chats.get(mid)
    if active and active[0] == pid:
        if not active[1].cancelling():
            active[1].cancel()
        return {'state': 'stopping'}
    raise HTTPException(404, 'Chat not found in this project')


@app.get("/api/projects/{pid}/claims")
def claims(pid: str):
    project_required(pid)
    return rows("SELECT * FROM claims WHERE project_id=? ORDER BY created_at DESC", (pid,))

@app.post("/api/projects/{pid}/claims", status_code=201)
def add_claim(pid: str, req: NewClaim):
    project_required(pid)
    cid = uid("c")
    execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
            (cid, pid, req.title, req.statement, json.dumps(req.assumptions, ensure_ascii=False),
             "idea", req.kind, utcnow()))
    return one("SELECT * FROM claims WHERE id=?", (cid,))

@app.get("/api/projects/{pid}/evidence")
def evidence(pid: str):
    project_required(pid)
    return rows("SELECT * FROM evidence WHERE project_id=? ORDER BY rowid DESC", (pid,))

@app.post("/api/projects/{pid}/evidence", status_code=201)
def add_evidence(pid: str, req: NewEvidence):
    project_required(pid)
    try:
        return append_evidence(pid, req.claim_id, req.kind, req.verdict, req.description,
                               req.provenance, req.artifact_id)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))


@app.get('/api/projects/{pid}/papers')
def papers(pid: str):
    project_required(pid)
    return list_papers(pid)


@app.get('/api/projects/{pid}/papers/fulltext')
def search_project_papers(pid: str, query: str = Query(min_length=1, max_length=150)):
    project_required(pid)
    try:
        return search_library(pid, query)
    except ValueError as error:
        raise HTTPException(422, str(error))


@app.get('/api/projects/{pid}/papers/search')
async def search_papers(pid: str, query: str = Query(min_length=2, max_length=130)):
    project_required(pid)
    try:
        return await search_arxiv(query)
    except (httpx.HTTPError, ET.ParseError, ValueError) as error:
        raise HTTPException(502, f'arXiv search failed ({type(error).__name__}); this is not a negative literature finding')


@app.post('/api/projects/{pid}/papers', status_code=201)
async def import_paper(pid: str, req: ImportPaper):
    project_required(pid)
    try:
        return await import_arxiv(pid, req.arxiv_id)
    except ValueError as error:
        raise HTTPException(422, str(error))
    except (httpx.HTTPError, ET.ParseError) as error:
        raise HTTPException(502, f'Cannot retrieve arXiv original ({type(error).__name__})')


@app.post('/api/projects/{pid}/papers/pdf', status_code=201)
async def upload_paper(pid: str, request: Request, title: str = Query(min_length=1, max_length=200)):
    project_required(pid)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(413, 'PDF exceeds 8 MiB')
    try:
        return await archive_pdf(pid, bytes(content), title)
    except ValueError as error:
        raise HTTPException(422, str(error))


@app.get('/api/projects/{pid}/artifacts/{aid}/text')
def artifact_text(pid: str, aid: str, page: int = Query(default=1, ge=1),
                  offset: int = Query(default=0, ge=0), query: str = Query(default='', max_length=150)):
    project_required(pid)
    try:
        return read_artifact(pid, aid, page, offset, query)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))

@app.get("/api/verification-tests")
def list_verification_tests():
    return TESTS

@app.post("/api/projects/{pid}/claims/{cid}/verify/{test_id}")
def run_verification(pid: str, cid: str, test_id: str):
    project_required(pid)
    claim = one("SELECT * FROM claims WHERE id=? AND project_id=?", (cid, pid))
    if not claim:
        raise HTTPException(404, "Claim not found")
    expected = {"csk_delta_rg": "rg_identity", "csk_experimental_overclaim": "experimental_extraction"}
    if expected.get(test_id) is None:
        raise HTTPException(404, "Test not found")
    if expected[test_id] != claim["kind"]:
        raise HTTPException(422, "Test is only valid for its declared class of physical claims")
    outcome = check(test_id)
    item = append_evidence(pid, cid, "deterministic_test", outcome["verdict"],
                           outcome["formal_check"], outcome)
    # Even a passed algebraic check does not automatically certify a newly authored claim.
    # Seed canonical statement has been vetted for exactly the narrow theorem being checked.
    if claim["id"] == "csk_rg_seed" and outcome["verdict"] == "passed_under_assumptions":
        execute("UPDATE claims SET status='verified_under_assumptions' WHERE id=?", (cid,))
    return {"result": outcome, "evidence": item,
            "claim_status": one("SELECT status FROM claims WHERE id=?", (cid,))["status"]}

@app.get("/api/projects/{pid}/runs")
def list_runs(pid: str):
    project_required(pid)
    items = rows("SELECT * FROM runs WHERE project_id=? AND agent!='literature' ORDER BY rowid DESC", (pid,))
    try:
        runtime = codex_runtime()
    except ValueError:
        runtime = None
    for item in items:
        item['runtime_matches'] = runtime is not None and json.loads(item.pop('context_json')).get('codex_runtime') == runtime
    return items

@app.post("/api/projects/{pid}/runs", status_code=202)
def start_run(pid: str, req: NewRun):
    project_required(pid)
    runtime = codex_required()
    rid = uid("r")
    now = utcnow()
    snapshot = json.dumps({**project_snapshot(pid), 'codex_runtime': runtime}, ensure_ascii=False)
    with connection() as con:
        con.execute("INSERT INTO runs(id,project_id,title,question,state,agent,model_id,created_at,updated_at,context_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (rid, pid, req.title, req.question, "queued", "codex-sdk",
                     runtime['model'], now, now, snapshot))
        add_run_event(con, rid, 'queued', '任务已排队')
    return one("SELECT * FROM runs WHERE id=?", (rid,))

@app.get("/api/runs/{rid}")
def get_run(rid: str):
    item = one("SELECT * FROM runs WHERE id=?", (rid,))
    if not item:
        raise HTTPException(404, "Run not found")
    return item

@app.get('/api/runs/{rid}/events')
def run_events(rid: str, after: int = Query(default=0, ge=0)):
    run = get_run(rid)
    events = rows('SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id LIMIT 101', (rid, after))
    page = events[:100]
    return {'events': page, 'cursor': page[-1]['id'] if page else after, 'has_more': len(events) > 100,
            'state': run['state'], 'thread_id': run['thread_id']}

@app.post('/api/runs/{rid}/cancel')
def cancel_run(rid: str):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        run = con.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
        if not run:
            raise HTTPException(404, 'Run not found')
        if run['state'] in ('cancelled', 'cancelling'):
            return dict(run)
        if run['state'] not in ('queued', 'running'):
            raise HTTPException(409, 'This task is no longer active')
        state = 'cancelled' if run['state'] == 'queued' else 'cancelling'
        now = utcnow()
        con.execute('UPDATE runs SET state=?,updated_at=?,ended_at=? WHERE id=?',
                    (state, now, now if state == 'cancelled' else None, rid))
        add_run_event(con, rid, state, '已取消排队任务' if state == 'cancelled' else '已请求取消，正在停止执行并归档已有产物')
    return get_run(rid)

@app.post('/api/runs/{rid}/continue', status_code=202)
def continue_run(rid: str, req: ContinueRun):
    runtime = codex_required()
    parent = get_run(rid)
    if parent['agent'] != 'codex-sdk':
        raise HTTPException(409, 'Only Codex tasks can be continued')
    if json.loads(parent['context_json']).get('codex_runtime') != runtime:
        raise HTTPException(409, 'This session belongs to a different Codex runtime; create a new task from its archived findings')
    snapshot = json.dumps({**project_snapshot(parent['project_id']), 'codex_runtime': runtime}, ensure_ascii=False)
    child = uid('r')
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        parent = con.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
        if parent['state'] not in ('completed', 'cancelled', 'failed', 'interrupted'):
            raise HTTPException(409, 'Wait until this task has stopped before continuing it')
        if not parent['thread_id']:
            raise HTTPException(409, 'No Codex session was created; submit a new task')
        if con.execute('SELECT 1 FROM runs WHERE parent_run_id=?', (rid,)).fetchone():
            raise HTTPException(409, 'This task already has a continuation; continue its latest child instead')
        now = utcnow()
        con.execute('INSERT INTO runs(id,project_id,title,question,state,agent,model_id,created_at,updated_at,'
                    'thread_id,context_json,parent_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (child, parent['project_id'], parent['title'], req.message, 'queued', parent['agent'],
                     parent['model_id'], now, now, parent['thread_id'], snapshot, rid))
        add_run_event(con, child, 'queued', '继续任务已排队；将复用会话并恢复上次归档的工作文件')
    return get_run(child)

@app.get('/api/runs/{rid}/artifacts')
def run_artifacts(rid: str):
    get_run(rid)
    return rows('SELECT id,run_id,name,sha256,length(content) AS size,created_at FROM artifacts WHERE run_id=? ORDER BY rowid', (rid,))

@app.get('/api/artifacts/{aid}')
def download_artifact(aid: str):
    artifact = one('SELECT * FROM artifacts WHERE id=?', (aid,))
    if not artifact:
        raise HTTPException(404, 'Artifact not found')
    return Response(bytes(artifact['content']), media_type='application/pdf' if artifact['name'].endswith('.pdf') else 'application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(artifact['name'], safe=''),
        'X-Content-Type-Options': 'nosniff',
    })

@app.get("/api/projects/{pid}/documents")
def documents(pid: str):
    project_required(pid)
    return rows("SELECT * FROM documents WHERE project_id=? ORDER BY rowid DESC", (pid,))

@app.get("/api/documents/{did}")
def get_document(did: str):
    doc = one("SELECT * FROM documents WHERE id=?", (did,))
    if not doc:
        raise HTTPException(404, "Document not found")
    revisions = rows("SELECT * FROM revisions WHERE document_id=? ORDER BY revision DESC", (did,))
    for revision in revisions:
        revision['sources'] = []
        for eid in json.loads(revision['evidence_refs']):
            source = one(
                'SELECT e.*,c.statement,c.assumptions,c.status AS claim_status,a.name AS artifact_name,'
                'a.sha256 AS artifact_sha256,a.run_id FROM evidence e '
                'JOIN claims c ON c.id=e.claim_id LEFT JOIN artifacts a ON a.id=e.artifact_id '
                'WHERE e.id=? AND e.project_id=?', (eid, doc['project_id']))
            if source:
                revision['sources'].append(source)
    return {"document": doc, "revisions": revisions}

@app.post("/api/projects/{pid}/documents", status_code=201)
def save_document(pid: str, req: NewDocument):
    project_required(pid)
    now = utcnow()
    did = req.document_id or uid("d")
    refs = citation_ids(req.text)
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        for eid in refs:
            if not con.execute('SELECT 1 FROM evidence WHERE id=? AND project_id=?', (eid, pid)).fetchone():
                raise HTTPException(422, f'Unknown evidence citation in this project: {eid}')
        if req.document_id:
            item = con.execute("SELECT * FROM documents WHERE id=? AND project_id=?", (did,pid)).fetchone()
            if not item:
                raise HTTPException(404, "Document not found in project")
            revision = item["latest_revision"] + 1
            con.execute("UPDATE documents SET title=?,latest_revision=? WHERE id=?", (req.title,revision,did))
        else:
            revision = 1
            con.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (did,pid,req.title,revision,now))
        con.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?)",
                    (uid("rev"),did,revision,req.text,json.dumps(refs),now))
    return get_document(did)

@app.get('/api/projects/{pid}/style')
def get_style(pid: str):
    project_required(pid)
    saved=one('SELECT * FROM editorial_styles WHERE project_id=?',(pid,))
    return saved or {'project_id':pid,'style_text':DEFAULT_SCIENTIFIC_VOICE,'revision':0,'updated_at':None}

@app.put('/api/projects/{pid}/style')
def save_style(pid: str, req: EditorialStyle):
    project_required(pid)
    with connection() as con:
        con.execute("INSERT INTO editorial_styles(project_id,style_text,revision,updated_at) VALUES (?,?,1,?) "
                    "ON CONFLICT(project_id) DO UPDATE SET style_text=excluded.style_text,revision=revision+1,updated_at=excluded.updated_at",
                    (pid, req.style_text, utcnow()))
    return get_style(pid)

@app.get("/api/projects/{pid}/decisions")
def decisions(pid: str):
    project_required(pid)
    return rows("SELECT * FROM decisions WHERE project_id=? ORDER BY rowid DESC", (pid,))

@app.post("/api/projects/{pid}/decisions", status_code=201)
def record_decision(pid: str, req: NewDecision):
    project_required(pid)
    did = uid("dec")
    execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (did,pid,req.text,req.by_role,utcnow()))
    return one("SELECT * FROM decisions WHERE id=?", (did,))

@app.get("/api/projects/{pid}/brief")
def scientific_brief(pid: str):
    project_required(pid)
    snapshot = project_snapshot(pid)
    return {'markdown': research_context(snapshot, 'discuss'), **snapshot}

@app.post("/api/seed-csk", status_code=201)
def seed_csk():
    """Real deterministic demonstration; idempotent for demos, not a claim of discovery."""
    with connection() as con:
        if not con.execute("SELECT 1 FROM projects WHERE id='csk_seed'").fetchone():
            con.execute("INSERT INTO projects VALUES (?,?,?,?)", (
                "csk_seed", "CS Kernel — Discovery Testbed",
                "RG-invariant kernel differences, universality and experimental identifiability", utcnow()))
        for cid, title, statement, kind in [
            ("csk_rg_seed", "Kernel difference RG invariance",
             "Under a common anomalous dimension and evolution convention, the difference K(b1,mu)-K(b2,mu) is independent of mu.", "rg_identity"),
            ("csk_eec_seed", "Overstrong EEC-extraction inference",
             "RG invariance alone makes Delta K directly measurable from any two-scale EEC comparison without additional nonperturbative inputs.", "experimental_extraction")
        ]:
            if not con.execute("SELECT 1 FROM claims WHERE id=?", (cid,)).fetchone():
                con.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)", (
                    cid,"csk_seed",title,statement,"[]","idea",kind,utcnow()))
    return {"project": project_required("csk_seed"),
            "claims": rows("SELECT * FROM claims WHERE project_id='csk_seed'")}
