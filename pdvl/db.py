from __future__ import annotations
import json
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import home

ARCHIVE_LIMIT = 10 * 1024 * 1024


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"

def db_path():
    return home() / "pdvl.sqlite3"

@contextmanager
def connection():
    con = sqlite3.connect(str(db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def rows(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]

def one(sql: str, params: tuple = ()) -> dict | None:
    with connection() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None

def execute(sql: str, params: tuple = ()): 
    with connection() as con:
        con.execute(sql, params)

def init_db():
    with connection() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, mode TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, model_id TEXT,
            created_at TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}' , FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE INDEX IF NOT EXISTS idx_messages ON messages(project_id,mode,created_at);
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            statement TEXT NOT NULL, assumptions TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'idea', kind TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, claim_id TEXT NOT NULL,
            kind TEXT NOT NULL, verdict TEXT NOT NULL, description TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(claim_id) REFERENCES claims(id));
        CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_id,created_at);
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            question TEXT NOT NULL, state TEXT NOT NULL, agent TEXT NOT NULL,
            model_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            started_at TEXT, ended_at TEXT, output TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', thread_id TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            latest_revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS revisions (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL, revision INTEGER NOT NULL,
            text TEXT NOT NULL, evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            UNIQUE(document_id,revision), FOREIGN KEY(document_id) REFERENCES documents(id));
        CREATE TABLE IF NOT EXISTS editorial_styles (
            project_id TEXT PRIMARY KEY, style_text TEXT NOT NULL,
            revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, text TEXT NOT NULL,
            by_role TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL,
            content BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(run_id,name), FOREIGN KEY(run_id) REFERENCES runs(id));
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(id));
        CREATE INDEX IF NOT EXISTS idx_run_events ON run_events(run_id,id);
        """)
        if 'meta_json' not in {r['name'] for r in con.execute('PRAGMA table_info(messages)')}:
            con.execute("ALTER TABLE messages ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")
        if 'context_json' not in {r['name'] for r in con.execute('PRAGMA table_info(runs)')}:
            con.execute("ALTER TABLE runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
        if 'artifact_id' not in {r['name'] for r in con.execute('PRAGMA table_info(evidence)')}:
            con.execute("ALTER TABLE evidence ADD COLUMN artifact_id TEXT REFERENCES artifacts(id)")
        if 'parent_run_id' not in {r['name'] for r in con.execute('PRAGMA table_info(runs)')}:
            con.execute('ALTER TABLE runs ADD COLUMN parent_run_id TEXT REFERENCES runs(id)')
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_run_parent ON runs(parent_run_id) WHERE parent_run_id IS NOT NULL')
        # Rebuildable page index; archived bytes remain the source of truth.
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5("
                    "project_id UNINDEXED,artifact_id UNINDEXED,page UNINDEXED,title,text,tokenize='unicode61')")
        index_sql = """INSERT INTO paper_fts(project_id,artifact_id,page,title,text)
            SELECT r.project_id,a.id,CAST(p.key AS INTEGER)+1,json_extract(a.content,'$.title'),p.value
            FROM artifacts a JOIN runs r ON r.id=a.run_id,json_each(a.content,'$.pages') p
            WHERE a.name='paper.json' AND r.agent='literature'
            AND NOT EXISTS (SELECT 1 FROM paper_fts f WHERE f.artifact_id=a.id)"""
        con.execute('CREATE TRIGGER IF NOT EXISTS index_paper AFTER INSERT ON artifacts '
                    "WHEN new.name='paper.json' BEGIN " + index_sql + ' AND a.id=new.id; END')
        con.execute('CREATE TRIGGER IF NOT EXISTS unindex_paper AFTER DELETE ON artifacts BEGIN '
                    'DELETE FROM paper_fts WHERE artifact_id=old.id; END')
        con.execute(index_sql)


def add_run_event(con, rid: str, kind: str, message: str):
    con.execute('INSERT INTO run_events(run_id,kind,message,created_at) VALUES (?,?,?,?)',
                (rid, kind, message[:6000], utcnow()))


def archive_artifacts(con, rid: str, files: dict[str, bytes], now: str) -> dict[str, str]:
    stored = con.execute('SELECT coalesce(sum(length(content)),0) FROM artifacts WHERE run_id=?', (rid,)).fetchone()[0]
    if stored + sum(map(len, files.values())) > ARCHIVE_LIMIT:
        raise ValueError('Run artifacts exceed the 10 MiB archive limit')
    ids = {}
    for name, content in files.items():
        ids[name] = uid('a')
        con.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?)',
                    (ids[name], rid, name, content, hashlib.sha256(content).hexdigest(), now))
    return ids


def append_evidence(project_id: str, claim_id: str, kind: str, verdict: str,
                    description: str, provenance: dict | None = None,
                    artifact_id: str | None = None) -> dict:
    eid = uid("e")
    with connection() as con:
        if not con.execute("SELECT 1 FROM claims WHERE id=? AND project_id=?", (claim_id, project_id)).fetchone():
            raise LookupError("claim not found in project")
        if artifact_id:
            artifact = con.execute(
                "SELECT a.id,a.run_id,a.name,a.sha256,a.content,r.agent,r.model_id,r.context_json FROM artifacts a "
                "JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.project_id=?",
                (artifact_id, project_id)).fetchone()
            if not artifact:
                raise LookupError("artifact not found in project")
            # Source identity comes from our archive, never caller-supplied metadata.
            provenance = {**(provenance or {}), 'artifact': {
                key: artifact[key] for key in ('id', 'run_id', 'name', 'sha256', 'model_id')},
                'context_sha256': hashlib.sha256(artifact['context_json'].encode()).hexdigest()}
            if artifact['agent'] == 'literature' and artifact['name'] == 'paper.json':
                paper = json.loads(artifact['content'])
                pages = provenance.pop('pages', [])
                if not isinstance(pages, list) or any(type(p) is not int or not 1 <= p <= len(paper['pages']) for p in pages):
                    raise ValueError('Evidence pages must be PDF page numbers from this paper')
                provenance['paper_source'] = {key: paper.get(key) for key in
                                              ('title', 'url', 'arxiv_id', 'pdf_artifact_id', 'pdf_sha256')}
                provenance['paper_source']['pages'] = sorted(set(pages))
        con.execute("INSERT INTO evidence(id,project_id,claim_id,kind,verdict,description,provenance,created_at,artifact_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (eid, project_id, claim_id, kind, verdict, description,
                     json.dumps(provenance or {}, ensure_ascii=False), utcnow(), artifact_id))
    return one("SELECT * FROM evidence WHERE id=?", (eid,))
