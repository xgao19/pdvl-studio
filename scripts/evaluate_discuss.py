#!/usr/bin/env python3
"""Source-pinned Discuss baseline. Default is dry-run; --run explicitly calls the configured API."""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from pdvl.api import app
from pdvl.config import ROOT, home
from pdvl.db import execute, init_db, one, uid, utcnow
from pdvl.papers import import_arxiv, search_library
from pdvl.providers import pick_model
from pdvl.tools import digest_tool_result, execute_research_tool

SUITE = ROOT / 'evals/discuss_real_papers.json'
SUPPORT = {'supported', 'partial', 'unsupported', 'unanswered', 'uncertain'}
LIMITS = {'present', 'missing', 'contradicted', 'uncertain'}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split()).casefold()


def pages_digest(pages):
    return hashlib.sha256(json.dumps(pages, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def load_suite():
    suite = json.loads(SUITE.read_text())
    papers = {p['id']: p for p in suite['sources']}
    assert len(papers) == len(suite['sources'])
    ids = [c['id'] for c in suite['cases']]
    assert len(ids) == len(set(ids))
    for source in papers.values():
        assert re.fullmatch(r'\d{4}\.\d{4,5}v[1-9]\d*', source['arxiv_id'])
        for key in ('pdf_sha256', 'pages_sha256'):
            assert re.fullmatch(r'[a-f0-9]{64}', source[key])
    for case in suite['cases']:
        assert 1 <= len(case['question']) <= 150
        for kind in ('facts', 'limitations'):
            items = case[kind]
            assert items and len({x['id'] for x in items}) == len(items)
            for item in items:
                assert item['statement'] and item['references']
                for ref in item['references']:
                    assert ref['paper'] in papers and 1 <= ref['page'] <= papers[ref['paper']]['page_count']
                    assert 1 <= len(ref['anchor']) <= 120
    return suite


def check_sources(suite, papers):
    """Fail on version/content/annotation drift; never silently update labels."""
    for source in suite['sources']:
        paper = papers[source['id']]
        assert paper['arxiv_id'] == source['arxiv_id'] and paper['pdf_sha256'] == source['pdf_sha256'], source['id']
        assert len(paper['pages']) == source['page_count'] and pages_digest(paper['pages']) == source['pages_sha256'], source['id']
    for case in suite['cases']:
        for item in case['facts'] + case['limitations']:
            for ref in item['references']:
                assert normalize(ref['anchor']) in normalize(papers[ref['paper']]['pages'][ref['page']-1]), (case['id'], ref)


def expected_pages(case):
    return {(r['paper'], r['page']) for item in case['facts'] + case['limitations'] for r in item['references']}


def coverage(expected, found):
    matched = expected & found
    return {'matched': [list(p) for p in sorted(matched)], 'expected_count': len(expected),
            'hit': bool(matched), 'recall': len(matched)/len(expected)}


async def measure(case, pid, archived, done):
    """Deterministic access metrics. Semantic judgments are an explicit separate review."""
    by_aid = {p['id']: key for key, p in archived.items()}
    expected = expected_pages(case)
    probe = search_library(pid, case['question'])
    found = {(by_aid[r['artifact_id']], r['page']) for r in probe['results']}
    searched, read, observed = set(), set(), []
    trace = done['meta'].get('tools', [])
    for tool in trace:
        if tool['name'] not in ('search_project_papers', 'read_research_artifact'):
            continue
        result = await execute_research_tool(tool['name'], tool['args'], pid)
        assert digest_tool_result(result) == tool['result_sha256'], 'Tool replay differs from recorded execution'
        observed.append({'name': tool['name'], 'args': tool['args'], 'result': result})
        if tool['name'] == 'search_project_papers':
            searched.update((by_aid[r['artifact_id']], r['page']) for r in result.get('results', []) if r['artifact_id'] in by_aid)
        if tool.get('source') and result['id'] in by_aid:
            read.add((by_aid[result['id']], result['page']))
    anchors = []
    for kind in ('facts', 'limitations'):
        for item in case[kind]:
            exposed = all(any(o['name'] == 'read_research_artifact'
                             and by_aid.get(o['result'].get('id')) == ref['paper']
                             and o['result'].get('page') == ref['page']
                             and normalize(ref['anchor']) in normalize(o['result'].get('text', ''))
                             for o in observed) for ref in item['references'])
            anchors.append({'kind': kind, 'id': item['id'], 'exposed': exposed})
    checks = done['meta'].get('citations', [])
    metrics = {'raw_question_top8': coverage(expected, found), 'tool_search_union': {
                   **coverage(expected, searched), 'called': any(t['name'] == 'search_project_papers' for t in trace)},
               'read_pages': coverage(expected, read), 'anchor_access': anchors,
               'citations': {'valid': sum(c['valid'] for c in checks), 'total': len(checks)},
               'external_search': any(t['name'] in ('search_arxiv', 'import_arxiv_paper') for t in trace)}
    return metrics, probe, observed


@contextmanager
def isolated_home(directory):
    previous = os.environ.get('PDVL_HOME')
    directory.mkdir(parents=True, exist_ok=False)
    os.environ['PDVL_HOME'] = str(directory)
    try:
        yield
    finally:
        if previous is None:os.environ.pop('PDVL_HOME', None)
        else:os.environ['PDVL_HOME'] = previous


async def run(suite):
    model = pick_model('discuss')
    output = home() / 'evals' / ('discuss_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uid('eval')[5:])
    output.mkdir(parents=True)
    (output/'generation-suite.json').write_bytes(SUITE.read_bytes())
    (output/'generation-evaluator.py').write_bytes(Path(__file__).read_bytes())
    harness = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [*sorted((ROOT/'pdvl').glob('*.py')), Path(__file__), SUITE]}
    manifest = {'created_at': utcnow(), 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'harness_sha256': harness, 'suite_sha256': hashlib.sha256(SUITE.read_bytes()).hexdigest(),
                'model': {k: model.get(k) for k in ('id', 'provider', 'model', 'api')}, 'sources': suite['sources'],
                'scope': 'One trial per question; same configured Discuss API and tools; cold conversation; no gold labels in model input.'}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    with isolated_home(output/'research'):
        init_db();pid = uid('p')
        execute('INSERT INTO projects VALUES (?,?,?,?)', (pid, 'Public CS-kernel literature baseline', 'Answer from the archived public papers; no accepted evidence.', utcnow()))
        archived, originals = {}, {}
        for source in suite['sources']:
            paper = await import_arxiv(pid, source['arxiv_id'])
            archived[source['id']] = paper
            originals[source['id']] = json.loads(one('SELECT content FROM artifacts WHERE id=?', (paper['id'],))['content'])
        check_sources(suite, originals)
        with (output/'results.jsonl').open('w') as log:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', timeout=180) as client:
                for case in suite['cases']:
                    # Only this newly-created evaluation DB is reset; no user's research data is touched.
                    execute('DELETE FROM messages WHERE project_id=?', (pid,))
                    prompt = case['question'] + '\n仅依据本项目已归档的三篇原文回答，不做外部搜索。给出可核对的原文页引用，保留关键条件与局限；无法从资料回答时明确说明。请控制在约250字（英文约180词）以内。'
                    started = time.monotonic()
                    try:
                        response = await asyncio.wait_for(client.post(f'/api/projects/{pid}/chat', json={'message': prompt, 'mode': 'discuss'}), 180)
                        response.raise_for_status()
                        events = [json.loads(line) for line in response.text.splitlines() if line]
                        done = events[-1]
                    except (TimeoutError, httpx.HTTPError) as exc:
                        saved = one("SELECT content,meta_json FROM messages WHERE project_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1", (pid,))
                        meta = json.loads(saved['meta_json']) if saved else {'tools': []}
                        meta.update(state='failed', error=f'Evaluation request failed ({type(exc).__name__})')
                        done = {'type': 'done', 'answer': saved['content'] if saved else '', 'meta': meta}
                        events = [done]
                    assert done['type'] == 'done'
                    metrics, probe, observed = await measure(case, pid, archived, done)
                    record = {'id': case['id'], 'question': case['question'], 'elapsed_seconds': round(time.monotonic()-started, 3),
                              'state': done['meta']['state'], 'answer': done['answer'], 'meta': done['meta'],
                              'metrics': metrics, 'probe': probe, 'observed': observed, 'events': events}
                    log.write(json.dumps(record, ensure_ascii=False)+'\n');log.flush()
                    print(case['id'], record['state'], 'raw_recall=', round(metrics['raw_question_top8']['recall'], 2),
                          'read_recall=', round(metrics['read_pages']['recall'], 2), flush=True)
    template = {'reviewer': '', 'review_type': 'source_audit', 'independent_expert_review': False,
                'cases': [{'id': c['id'], 'facts': [{'id': x['id'], 'verdict': None, 'note': ''} for x in c['facts']],
                           'limitations': [{'id': x['id'], 'verdict': None, 'note': ''} for x in c['limitations']]} for c in suite['cases']]}
    (output/'reviews.json').write_text(json.dumps(template, ensure_ascii=False, indent=2)+'\n')
    report(output, suite)
    print('Results:', output)
    return output


def review_case(case, review):
    """Do not infer correctness from citation validity or word/negation matches."""
    if review is None:return {'support': None, 'limitations': None}
    decisions = {}
    for kind, allowed in (('facts', SUPPORT), ('limitations', LIMITS)):
        rubric_ids = {i['id'] for i in case[kind]}
        values = review[kind]
        assert len(values) == len(rubric_ids) and {x['id'] for x in values} == rubric_ids
        for item in values:
            assert item['verdict'] is None or item['verdict'] in allowed
            assert item['verdict'] is None or item['note'].strip(), 'Every judgment needs an explanation'
        decisions[kind] = None if any(x['verdict'] is None for x in values) else all(x['verdict'] == ('supported' if kind == 'facts' else 'present') for x in values)
    return {'support': decisions['facts'], 'limitations': decisions['limitations']}


def report(output, suite):
    manifest = json.loads((output/'manifest.json').read_text())
    assert manifest['suite_sha256'] == hashlib.sha256(SUITE.read_bytes()).hexdigest(), 'Suite changed since execution'
    records = [json.loads(line) for line in (output/'results.jsonl').read_text().splitlines()]
    assert [r['id'] for r in records] == [c['id'] for c in suite['cases']], 'Incomplete or duplicated run'
    reviews = json.loads((output/'reviews.json').read_text())
    assert len(reviews['cases']) == len(records) and {r['id'] for r in reviews['cases']} == {r['id'] for r in records}
    by_id = {r['id']: r for r in reviews['cases']}
    cases = []
    for case, record in zip(suite['cases'], records):
        judgment = review_case(case, by_id[case['id']])
        if any(v is not None for v in judgment.values()):assert reviews['reviewer'].strip()
        cases.append({'id': case['id'], 'question': case['question'], 'category': case['category'],
                      'state': record['state'], 'elapsed_seconds': record['elapsed_seconds'], 'metrics': record['metrics'],
                      'review': by_id[case['id']], **judgment})
    n = len(cases)
    searched = [c for c in cases if c['metrics']['tool_search_union']['called']]
    citation_counts = [c['metrics']['citations'] for c in cases]
    summary = {'manifest': manifest, 'reviewer': reviews['reviewer'], 'review_type': reviews['review_type'],
               'independent_expert_review': reviews['independent_expert_review'], 'n': n,
               'completed': sum(c['state'] == 'completed' for c in cases),
               'raw_hit_at_8': sum(c['metrics']['raw_question_top8']['hit'] for c in cases)/n,
               'raw_page_recall_at_8': sum(c['metrics']['raw_question_top8']['recall'] for c in cases)/n,
               'tool_page_recall': sum(c['metrics']['tool_search_union']['recall'] for c in cases)/n,
               'tool_search_cases': len(searched),
               'tool_page_recall_when_searched': sum(c['metrics']['tool_search_union']['recall'] for c in searched)/len(searched) if searched else None,
               'read_page_recall': sum(c['metrics']['read_pages']['recall'] for c in cases)/n,
               'citation_valid': sum(c['valid'] for c in citation_counts), 'citation_total': sum(c['total'] for c in citation_counts),
               'cases_with_citations': sum(c['total'] > 0 for c in citation_counts),
               'support_counts': dict(Counter('unreviewed' if c['support'] is None else 'pass' if c['support'] else 'needs_work' for c in cases)),
               'limitation_counts': dict(Counter('unreviewed' if c['limitations'] is None else 'pass' if c['limitations'] else 'needs_work' for c in cases)),
               'cases': cases}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    lines = ['# Discuss real-paper baseline', '', manifest['scope'], '',
             f"Model: {manifest['model']['model']}; questions: {n}; completed: {summary['completed']}.",
             f"Raw question hit@8: {summary['raw_hit_at_8']:.1%}; mean labeled-page recall@8: {summary['raw_page_recall_at_8']:.1%}.",
             f"Tool-search union page recall: {summary['tool_page_recall']:.1%}; actual read-page recall: {summary['read_page_recall']:.1%}.",
             f"Tool search used in {summary['tool_search_cases']}/{n} cases; direct reading is allowed and is not a search failure.",
             f"Citation access checks: {summary['citation_valid']}/{summary['citation_total']}; answers with clickable citations: {summary['cases_with_citations']}/{n}.",
             f"Support: {summary['support_counts']}; key limitations: {summary['limitation_counts']}.", '',
             'Source access is not semantic support. Anchors only measure exposure, not entailment. Missing reviews are unreviewed, never passes.',
             'Gold pages are non-exhaustive labels: equivalent support on other original pages is adjudicated in the source audit. Extra unsupported claims downgrade support even when the requested core fact is correct.',
             'The same model is not used to certify its own answers. Source audit is not independent physics validation.', '',
             '| Case | State | Raw labeled-page recall@8 | Read labeled-page recall | Support | Limitations |', '|---|---|---:|---:|---|---|']
    label = lambda x: 'unreviewed' if x is None else 'pass' if x else 'needs work'
    for c in cases:
        lines.append(f"| {c['id']} | {c['state']} | {c['metrics']['raw_question_top8']['recall']:.0%} | {c['metrics']['read_pages']['recall']:.0%} | {label(c['support'])} | {label(c['limitations'])} |")
    for c in cases:
        lines.extend(['', f"## {c['id']}: {c['question']}"])
        for kind in ('facts', 'limitations'):
            for item in c['review'][kind]:lines.append(f"- {kind}/{item['id']}: {item['verdict'] or 'unreviewed'} — {item['note']}")
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true', help='Call the configured Discuss provider on 20 public-paper questions')
    mode.add_argument('--report', type=Path, help='Read saved results/reviews and regenerate report without API calls')
    args = parser.parse_args();suite = load_suite()
    if args.run:asyncio.run(run(suite))
    elif args.report:report(args.report, suite)
    else:
        print('Dry run: no downloads or API calls. --run uses the existing Discuss configuration.')
        for case in suite['cases']:print(case['id'], case['question'])


if __name__ == '__main__':main()
