"""Offline checks for the evaluator, not a claim that the live model passes its research tasks."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from scripts import evaluate_discuss as evaluation
from pdvl.tools import digest_tool_result, execute_research_tool


def test_real_suite_has_twenty_source_pinned_questions_and_explicit_rubrics():
    suite = evaluation.load_suite()
    assert len(suite['cases']) == 20 and len(suite['sources']) == 3
    assert {p['arxiv_id'] for p in suite['sources']} == {'2206.01105v1','2003.06063v2','2103.16991v3'}
    assert {'paired_en','comparison','conventions','unanswerable'} <= {c['category'] for c in suite['cases']}
    for case in suite['cases']:
        assert case['facts'] and case['limitations']
        assert all(r['page'] >= 1 for i in case['facts']+case['limitations'] for r in i['references'])


def test_source_validation_catches_version_hash_page_and_anchor_drift():
    pages = ['An important definition.', 'A limitation.']
    source = {'id':'paper','arxiv_id':'2301.12345v2','pdf_sha256':'a'*64,
              'pages_sha256':evaluation.pages_digest(pages),'page_count':2}
    suite = {'sources':[source],'cases':[{'id':'Q','facts':[{'references':[{'paper':'paper','page':2,'anchor':'A limitation.'}]}],'limitations':[]}]}
    paper = {'arxiv_id':source['arxiv_id'],'pdf_sha256':'a'*64,'pages':pages}
    evaluation.check_sources(suite, {'paper':paper})
    for changed in ({'arxiv_id':'2301.12345v3'}, {'pdf_sha256':'b'*64}, {'pages':['Changed','A limitation.']}):
        with pytest.raises(AssertionError):evaluation.check_sources(suite, {'paper':{**paper,**changed}})
    suite['cases'][0]['facts'][0]['references'][0]['anchor']='Not in this source'
    with pytest.raises(AssertionError):evaluation.check_sources(suite, {'paper':paper})
    assert evaluation.normalize('A  ﬁnite\nvolume') == 'a finite volume'


def test_isolated_evaluation_home_is_restored_even_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('PDVL_HOME','original-research')
    with pytest.raises(RuntimeError):
        with evaluation.isolated_home(tmp_path/'isolated'):
            assert evaluation.home() == tmp_path/'isolated'
            raise RuntimeError('Failed run')
    assert evaluation.os.environ['PDVL_HOME']=='original-research'
    monkeypatch.delenv('PDVL_HOME')
    with evaluation.isolated_home(tmp_path/'second'):pass
    assert 'PDVL_HOME' not in evaluation.os.environ


def test_retrieval_reading_exposure_and_support_are_separate(client, pdf_factory):
    pid = client.post('/api/projects',json={'title':'Evaluation sandbox'}).json()['id']
    body = 'Beginning ' + 'x'*7100 + ' RAREWORD limitation'
    paper = client.post(f'/api/projects/{pid}/papers/pdf',params={'title':'Paper'},content=pdf_factory('Abstract',body)).json()
    ref = {'paper':'paper','page':2,'anchor':'RAREWORD limitation'}
    case = {'id':'Q','question':'RAREWORD','facts':[{'id':'fact','references':[ref]}],
            'limitations':[{'id':'scope','references':[ref]}]}
    async def run():
        traces=[]
        for name,args in [('search_project_papers',{'query':'RAREWORD'}),('read_research_artifact',{'artifact_id':paper['id'],'page':2})]:
            result=await execute_research_tool(name,args,pid)
            trace={'name':name,'args':args,'result_sha256':digest_tool_result(result)}
            if name=='read_research_artifact':trace['source']={'artifact_id':paper['id'],'page':2}
            traces.append(trace)
        done={'meta':{'tools':traces,'citations':[{'valid':True}]}}
        metrics,probe,observed=await evaluation.measure(case,pid,{'paper':paper},done)
        assert metrics['raw_question_top8']['recall']==1 and metrics['read_pages']['recall']==1
        assert not any(x['exposed'] for x in metrics['anchor_access']) # Matching page, but the relevant chunk was never read.
        assert metrics['citations']=={'valid':1,'total':1}
        assert evaluation.review_case(case,None)=={'support':None,'limitations':None}
        assert 'RAREWORD' not in observed[-1]['result']['text'] and probe['results']
        done['meta']['tools'][0]['result_sha256']='forged'
        with pytest.raises(AssertionError):await evaluation.measure(case,pid,{'paper':paper},done)
    asyncio.run(run())
    assert client.get(f'/api/projects/{pid}/evidence').json()==[]


def test_report_requires_explicit_judgments_and_never_promotes_keywords(tmp_path, monkeypatch):
    case = {'id':'Q','category':'negation','question':'Is the result model independent?',
            'facts':[{'id':'fact'}],'limitations':[{'id':'scope'}]}
    suite={'cases':[case]}
    suite_path=tmp_path/'suite.json';suite_path.write_text(json.dumps(suite));monkeypatch.setattr(evaluation,'SUITE',suite_path)
    manifest={'suite_sha256':hashlib.sha256(suite_path.read_bytes()).hexdigest(),'scope':'Test only','model':{'model':'fake'}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    coverage=evaluation.coverage({('paper',2)},{('paper',2)})
    record={'id':'Q','state':'completed','elapsed_seconds':1,'metrics':{'raw_question_top8':coverage,'tool_search_union':{**coverage,'called':False},'read_pages':coverage,'citations':{'valid':0,'total':0}}}
    (tmp_path/'results.jsonl').write_text(json.dumps(record)+'\n')
    review={'id':'Q','facts':[{'id':'fact','verdict':None,'note':''}],'limitations':[{'id':'scope','verdict':None,'note':''}]}
    reviews={'reviewer':'','review_type':'source_audit','independent_expert_review':False,'cases':[review]}
    path=tmp_path/'reviews.json';path.write_text(json.dumps(reviews))
    summary=evaluation.report(tmp_path,suite)
    assert summary['support_counts']=={'unreviewed':1} and summary['limitation_counts']=={'unreviewed':1}
    reviews['reviewer']='Test source audit'
    review['facts'][0].update(verdict='unsupported',note='The word model appears, but the answer reverses the source meaning.')
    review['limitations'][0].update(verdict='missing',note='The sentence omits the restriction despite containing related keywords.')
    path.write_text(json.dumps(reviews))
    summary=evaluation.report(tmp_path,suite)
    assert summary['support_counts']=={'needs_work':1} and summary['limitation_counts']=={'needs_work':1}
    review['limitations']=[]
    with pytest.raises(AssertionError):evaluation.review_case(case,review)
    (tmp_path/'results.jsonl').write_text('')
    with pytest.raises(AssertionError):evaluation.report(tmp_path,suite)


@pytest.mark.parametrize('fail_first', [False, True])
def test_live_harness_resets_history_and_never_sends_gold_rubrics(client, pdf_factory, tmp_path, monkeypatch, fail_first):
    from pdvl import api, papers
    from pdvl.db import one
    pid=client.post('/api/projects',json={'title':'User project must remain untouched'}).json()['id']
    pdf=pdf_factory('Source keyword')
    source={'id':'paper','arxiv_id':'2301.12345v2','title':'Public paper','url':'https://arxiv.org/abs/2301.12345v2',
            'pdf_sha256':hashlib.sha256(pdf).hexdigest(),'pages_sha256':evaluation.pages_digest(['Source keyword']),'page_count':1}
    ref={'paper':'paper','page':1,'anchor':'keyword'}
    cases=[{'id':str(n),'category':'test','question':'keyword '+str(n),'facts':[{'id':'fact','statement':'PRIVATE_GOLD_RUBRIC','references':[ref]}],
            'limitations':[{'id':'limit','statement':'PRIVATE_LIMIT_RUBRIC','references':[ref]}]} for n in (1,2)]
    suite={'sources':[source],'cases':cases}
    path=tmp_path/'suite.json';path.write_text(json.dumps(suite));monkeypatch.setattr(evaluation,'SUITE',path)
    seen=[]
    async def imported(project, ident):
        return await papers.archive_pdf(project,pdf,source['title'],{'arxiv_id':ident,'url':source['url']})
    async def answer(model,instructions,messages,**kwargs):
        seen.append((instructions,messages))
        assert len(messages)==1 and 'PRIVATE_GOLD_RUBRIC' not in instructions+messages[0]['content']
        assert 'PRIVATE_LIMIT_RUBRIC' not in instructions+messages[0]['content']
        return 'A source-based response',{'tools':[],'model':'fake'}
    monkeypatch.setattr(evaluation,'import_arxiv',imported);monkeypatch.setattr(api,'generate',answer)
    if fail_first:
        original_post=evaluation.httpx.AsyncClient.post
        calls=[]
        async def failed_request(self,*args,**kwargs):
            calls.append(True)
            if len(calls)==1:raise evaluation.httpx.ReadTimeout('must-not-echo-upstream-private-details')
            return await original_post(self,*args,**kwargs)
        monkeypatch.setattr(evaluation.httpx.AsyncClient,'post',failed_request)
    # Test suite path is outside ROOT; production suite is inside it. Freeze only source files here.
    monkeypatch.setattr(evaluation,'ROOT',tmp_path)
    (tmp_path/'pdvl').mkdir()
    # The application root remains unchanged; only evaluator snapshot identity paths are patched.
    monkeypatch.setattr(evaluation,'__file__',str(tmp_path/'evaluator.py'));(tmp_path/'evaluator.py').write_text('# Test evaluator identity')
    # git metadata is unrelated to isolation, and tmp_path intentionally has no repository.
    monkeypatch.setattr(evaluation.subprocess,'check_output',lambda *a,**k:'test-commit\n')
    output=asyncio.run(evaluation.run(suite))
    assert len(seen)==(1 if fail_first else 2) and one('SELECT id FROM projects WHERE id=?',(pid,))
    assert len(client.get('/api/projects').json())==1
    assert json.loads((output/'summary.json').read_text())['support_counts']=={'unreviewed':2}
    assert (output/'generation-suite.json').exists()
    if fail_first:
        raw=(output/'results.jsonl').read_text()
        assert json.loads(raw.splitlines()[0])['state']=='failed'
        assert 'must-not-echo-upstream-private-details' not in raw


def test_default_cli_is_offline_and_never_calls_the_model(monkeypatch, capsys):
    monkeypatch.setattr(evaluation.sys,'argv',['evaluate_discuss.py'])
    def forbidden(*args,**kwargs):pytest.fail('Dry-run must not create an API client or download papers')
    monkeypatch.setattr(evaluation.httpx,'AsyncClient',forbidden)
    monkeypatch.setattr(evaluation,'import_arxiv',forbidden)
    evaluation.main()
    output=capsys.readouterr().out
    assert 'Dry run' in output and 'Q20' in output
