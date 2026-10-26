"""Small, project-scoped literature library backed by the existing run archive."""
from __future__ import annotations
import asyncio
import hashlib
import io
import json
import re
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import httpx
from pypdf import PdfReader
from .db import connection, one, uid, utcnow, archive_artifacts, ARCHIVE_LIMIT

MAX_PDF_BYTES = 8 * 1024 * 1024
_arxiv_lock = asyncio.Lock()
_arxiv_last = 0.0


def arxiv_id(value: str) -> str:
    value = value.strip()
    if value.lower().startswith('arxiv:'):
        value = value[6:]
    if '://' in value:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or url.netloc != 'arxiv.org' or url.query or url.fragment:
            raise ValueError('Use an arXiv ID or an arxiv.org abs/pdf URL')
        value = re.sub(r'^/(?:abs|pdf)/', '', url.path)
    value = value.removesuffix('.pdf')
    if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?', value):
        raise ValueError('Invalid arXiv ID')
    return value


async def arxiv_entries(params: dict) -> list[dict]:
    """One metadata connection at a time, with arXiv's three-second interval."""
    global _arxiv_last
    async with _arxiv_lock:
        await asyncio.sleep(max(0, 3 - (time.monotonic() - _arxiv_last)))
        _arxiv_last = time.monotonic()
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get('https://export.arxiv.org/api/query', params=params)
            response.raise_for_status()
            if len(response.content) > 1_500_000:
                raise ValueError('arXiv metadata response too large')
        root = ET.fromstring(response.content)
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    result = []
    for entry in root.findall('a:entry', ns):
        def field(name):
            return ' '.join(entry.findtext('a:' + name, default='', namespaces=ns).split())
        ident = arxiv_id(field('id'))
        result.append({'arxiv_id': ident, 'title': field('title'),
                       'authors': [' '.join(a.findtext('a:name', default='', namespaces=ns).split())
                                   for a in entry.findall('a:author', ns)],
                       'date': field('published'), 'url': 'https://arxiv.org/abs/' + ident,
                       'abstract': field('summary')[:1200]})
    return result


async def search_arxiv(query: str) -> dict:
    if not isinstance(query, str) or not 2 <= len(query) <= 130:
        raise ValueError('Search query must have 2–130 characters')
    return {'results': await arxiv_entries({'search_query': 'all:' + query, 'start': 0,
                                           'max_results': 5, 'sortBy': 'relevance'}),
            'warning': 'Abstract-only search; import and read original pages before attributing findings.'}


def paper_records(con, pid: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT a.id,a.run_id,a.sha256,json_extract(a.content,'$.title') AS title,"
        "json_extract(a.content,'$.url') AS url,json_extract(a.content,'$.arxiv_id') AS arxiv_id,"
        "json_extract(a.content,'$.pdf_artifact_id') AS pdf_artifact_id,"
        "json_extract(a.content,'$.pdf_sha256') AS pdf_sha256,"
        "json_array_length(json_extract(a.content,'$.pages')) AS page_count "
        "FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE r.project_id=? "
        "AND r.agent='literature' AND a.name='paper.json' ORDER BY r.rowid", (pid,))]


def list_papers(pid: str) -> list[dict]:
    with connection() as con:
        return paper_records(con, pid)


def search_library(pid: str, query: str) -> dict:
    """Literal words, ranked across this project's archived PDF pages (not semantic search)."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 150:
        raise ValueError('Library query must have 1–150 characters')
    terms = re.findall(r'[^\W_]+', query, re.UNICODE)
    if not terms:
        raise ValueError('Library query needs searchable words')
    # Quoting words prevents the question from becoming FTS operators or SQL.
    match = ' OR '.join('"' + term + '"' for term in dict.fromkeys(terms))
    with connection() as con:
        results = [dict(row) for row in con.execute(
            "SELECT artifact_id,page,title,snippet(paper_fts,4,'[',']',' … ',48) AS excerpt "
            "FROM paper_fts WHERE paper_fts MATCH ? AND project_id=? "
            "ORDER BY bm25(paper_fts),artifact_id,CAST(page AS INTEGER) LIMIT 8", (match, pid))]
    return {'results': results, 'notice': 'Keyword retrieval over archived PDF text, not semantic search. '
            'Excerpts are leads: read original pages with read_research_artifact before citing. '
            'No matches do not establish absence of a scientific result.'}


def extract_pdf(content: bytes) -> list[str]:
    if not content.startswith(b'%PDF-') or len(content) > MAX_PDF_BYTES:
        raise ValueError('Upload a PDF of at most 8 MiB')
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError('Encrypted PDFs are not supported')
        if not 1 <= len(reader.pages) <= 150:
            raise ValueError('A paper must contain 1–150 PDF pages')
        pages, extracted_bytes = [], len(content)
        for page in reader.pages:
            stream = page.get_contents()
            if stream and len(stream.get_data()) > 8 * 1024 * 1024:
                raise ValueError('PDF page content stream is too large')
            pages.append((page.extract_text() or '').strip())
            extracted_bytes += len(pages[-1].encode())
            if extracted_bytes > ARCHIVE_LIMIT:
                raise ValueError('PDF and extracted text exceed the 10 MiB archive limit')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Cannot extract PDF text: ' + type(exc).__name__) from exc
    if not any(pages):
        raise ValueError('No readable text layer; scanned PDFs need OCR before import')
    return pages


async def archive_pdf(pid: str, content: bytes, title: str, metadata: dict | None = None) -> dict:
    from .research import project_snapshot
    snapshot = json.dumps(project_snapshot(pid), ensure_ascii=False)
    # Cancellation cannot kill Python parsing in a thread, but it prevents all
    # subsequent archival writes. No detached thread owns a DB transaction.
    pages = await asyncio.to_thread(extract_pdf, content)
    digest = hashlib.sha256(content).hexdigest()
    paper = {**(metadata or {}), 'title': title[:200], 'pdf_sha256': digest, 'pages': pages}
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        existing = con.execute("SELECT a.run_id FROM artifacts a JOIN runs r ON r.id=a.run_id "
                               "WHERE r.project_id=? AND r.agent='literature' AND a.name='original.pdf' "
                               "AND a.sha256=?", (pid, digest)).fetchone()
        if existing:
            return next(p for p in paper_records(con, pid) if p['run_id'] == existing['run_id'])
        rid, now = uid('r'), utcnow()
        con.execute('INSERT INTO runs(id,project_id,title,question,state,agent,created_at,updated_at,'
                    'started_at,ended_at,output,context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (rid, pid, title[:200], paper.get('url') or title, 'completed', 'literature',
                     now, now, now, now, 'Original PDF and extracted pages archived', snapshot))
        pdf = archive_artifacts(con, rid, {'original.pdf': content}, now)
        paper['pdf_artifact_id'] = pdf['original.pdf']
        archive_artifacts(con, rid, {'paper.json': json.dumps(paper, ensure_ascii=False).encode()}, now)
        return next(p for p in paper_records(con, pid) if p['run_id'] == rid)


async def import_arxiv(pid: str, value: str) -> dict:
    ident = arxiv_id(value)
    # Only explicit versions are reused without checking the current arXiv metadata.
    if re.search(r'v\d+$', ident):
        existing = next((p for p in list_papers(pid) if p['arxiv_id'] == ident), None)
        if existing:
            return existing
    entries = await arxiv_entries({'id_list': ident})
    if len(entries) != 1 or re.sub(r'v\d+$', '', entries[0]['arxiv_id']) != re.sub(r'v\d+$', '', ident):
        raise ValueError('arXiv paper not found')
    metadata = entries[0]
    if re.search(r'v\d+$', ident) and ident != metadata['arxiv_id']:
        raise ValueError('arXiv returned a different version; import the intended version explicitly')
    existing = next((p for p in list_papers(pid) if p['arxiv_id'] == metadata['arxiv_id']), None)
    if existing:
        return existing
    async with httpx.AsyncClient(timeout=45) as client:
        async with client.stream('GET', 'https://arxiv.org/pdf/' + metadata['arxiv_id']) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_PDF_BYTES:
                    raise ValueError('PDF exceeds 8 MiB')
    return await archive_pdf(pid, bytes(content), metadata['title'], metadata)


def read_artifact(pid: str, aid: str, page: int = 1, offset: int = 0, query: str = '') -> dict:
    """The canonical reader for both model tools and the UI source viewer."""
    if type(page) is not int or page < 1 or type(offset) is not int or offset < 0:
        raise ValueError('Page must be positive and offset nonnegative')
    if not isinstance(query, str) or len(query) > 150:
        raise ValueError('Text query must be at most 150 characters')
    artifact = one('SELECT a.id,a.name,a.sha256,a.content,r.agent FROM artifacts a '
                   'JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.project_id=?', (aid, pid))
    if not artifact:
        raise LookupError('Artifact not found in this project')
    try:
        content = bytes(artifact.pop('content')).decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Binary artifact; download the original file instead') from exc
    paper = json.loads(content) if artifact.pop('agent') == 'literature' and artifact['name'] == 'paper.json' else None
    pages = paper['pages'] if paper else [content]
    if page > len(pages):
        raise ValueError('Page outside the archived document')
    source = {**artifact, 'page_count': len(pages)}
    if paper:
        source.update({key: paper.get(key) for key in ('title', 'url', 'arxiv_id', 'pdf_artifact_id', 'pdf_sha256')})
        source['notice'] = 'Extracted PDF text only; equations/figures may need checking in the original PDF. Page numbers are PDF page positions.'
    if query:
        matches = []
        for number, body in enumerate(pages, 1):
            start = body.lower().find(query.lower())
            if start >= 0:
                matches.append({'page': number, 'offset': max(0, start - 200),
                                'excerpt': body[max(0, start - 200):start + 500]})
        return {**source, 'matches': matches[:8], 'truncated': len(matches) > 8}
    body = pages[page - 1]
    if paper and not body:
        source['notice'] += ' This page has no extractable text; inspect the original PDF.'
    if offset > len(body):
        raise ValueError('Offset outside the archived text')
    end = offset + 7000  # Keep serialized tool results intact within the model context budget.
    return {**source, 'page': page, 'offset': offset, 'text': body[offset:end],
            'truncated': len(body) > end, 'next_offset': end if len(body) > end else None,
            'citation': f'[原文 p.{page}](/api/artifacts/{aid}#page={page})'}
