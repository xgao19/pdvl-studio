from pdvl.db import one


def test_seed_and_scoped_physics_checks(client):
    demo = client.post('/api/seed-csk').json()
    assert demo['project']['id'] == 'csk_seed'
    assert len(demo['claims']) == 2
    rg = client.post('/api/projects/csk_seed/claims/csk_rg_seed/verify/csk_delta_rg')
    assert rg.status_code == 200
    assert rg.json()['result']['formal_check'].endswith('= 0')
    assert rg.json()['claim_status'] == 'verified_under_assumptions'
    eec = client.post('/api/projects/csk_seed/claims/csk_eec_seed/verify/csk_experimental_overclaim')
    assert eec.status_code == 200
    assert eec.json()['result']['verdict'] == 'not_established'
    assert eec.json()['claim_status'] == 'idea'
    assert client.post('/api/projects/csk_seed/claims/csk_rg_seed/verify/csk_experimental_overclaim').status_code == 422
    brief = client.get('/api/projects/csk_seed/brief').json()
    assert 'verified_under_assumptions' in brief['markdown']
    assert 'not_established' in brief['markdown']


def test_project_claim_and_evidence_separation(client):
    p = client.post('/api/projects',json={'title':'EMT research','description':'full EMT'}).json()
    q = client.post(f"/api/projects/{p['id']}/claims",json={'title':'A physical conjecture', 'statement':'A finite-flow relation might hold'}).json()
    assert q['status']=='idea'
    assert client.get(f"/api/projects/{p['id']}/evidence").json()==[]
    e = client.post(f"/api/projects/{p['id']}/evidence",json={'claim_id':q['id'], 'kind':'note','description':'Need matching proof','verdict':'unresolved'}).json()
    assert e['claim_id']==q['id']
    # User notes never auto-promote conjecture to a proved physical result.
    assert client.get(f"/api/projects/{p['id']}/claims").json()[0]['status']=='idea'
    other = client.post('/api/projects',json={'title':'Another project'}).json()
    assert client.post(f"/api/projects/{other['id']}/evidence",json={'claim_id':q['id'],'description':'cross-project bad link'}).status_code==404


def test_models_and_missing_api_key(client):
    models=client.get('/api/models').json()['models']
    assert {'gpt-astra','deepseek-pro','local'} <= {m['id'] for m in models}
    assert not next(m for m in models if m['id']=='deepseek-pro')['available']
    p=client.post('/api/projects',json={'title':'Private research'}).json()
    r=client.post(f"/api/projects/{p['id']}/chat",json={'message':'What is the anomaly?','model_id':'deepseek-pro'})
    assert r.status_code==503
    assert 'DEEPSEEK_API_KEY' in r.json()['detail']
    assert client.get(f"/api/projects/{p['id']}/messages").json()==[]


def test_manuscript_revisions_and_codex_guard(client):
    p=client.post('/api/projects',json={'title':'TMD manuscript'}).json()
    base=f"/api/projects/{p['id']}"
    assert client.post(base+'/runs',json={'question':'Compute or derive something'}).status_code==409
    d=client.post(base+'/documents',json={'title':'Phenomenological implications','text':'First draft'}).json()['document']
    v2=client.post(base+'/documents',json={'title':'Phenomenological implications','text':'Second draft','document_id':d['id']}).json()
    assert v2['document']['latest_revision']==2
    assert [v['text'] for v in v2['revisions']]==['Second draft','First draft']
    dec=client.post(base+'/decisions',json={'text':'Do not assert experimental extraction without checking factorization.'})
    assert dec.status_code==201
    assert 'factorization' in client.get(base+'/brief').json()['markdown']


def test_scientific_voice_persists_across_projects(client):
    p=client.post('/api/projects',json={'title':'Author voice'}).json()
    q=client.post('/api/projects',json={'title':'Second'}).json()
    style=client.get(f"/api/projects/{p['id']}/style").json()
    assert style['revision']==0
    new=client.put(f"/api/projects/{p['id']}/style",json={'style_text':'Prioritize sharp physical arguments over engineering prose.'}).json()
    assert new['revision']==1
    new=client.put(f"/api/projects/{p['id']}/style",json={'style_text':'More concise PRL tone.'}).json()
    assert new['revision']==2
    assert client.get(f"/api/projects/{q['id']}/style").json()['revision']==0


def test_local_origin_guard(client):
    assert client.post('/api/render',json={'markdown':'test'},headers={'Origin':'https://malicious.example'}).status_code==403
