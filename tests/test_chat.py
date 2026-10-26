from pdvl import api
from pdvl.providers import extract_output, ProviderError
from pdvl.prompts import MODE_PROMPTS


def test_chat_uses_modes_and_persists(client, monkeypatch):
    inputs=[]
    async def fake_generate(model, instructions, messages, **kwargs):
        inputs.append((model, instructions, messages))
        return 'A physically motivated answer with equations.', {'provider':'test', 'model':'mock'}
    monkeypatch.setattr(api, 'generate', fake_generate)
    project=client.post('/api/projects',json={'title':'Pion TMD','description':'Long-distance tails'}).json()
    pid=project['id']
    res=client.post(f'/api/projects/{pid}/chat',json={'mode':'discuss','message':'Can we identify the tail?','model_id':'deepseek-pro'})
    assert res.status_code==200
    assert 'experienced theoretical physicist' in inputs[-1][1]
    assert len(client.get(f'/api/projects/{pid}/messages?mode=discuss').json())==2
    client.post(f'/api/projects/{pid}/claims',json={'title':'Conjecture','statement':'A universal tail exists'})
    res=client.post(f'/api/projects/{pid}/chat',json={'mode':'write','message':'Draft PRL introduction'})
    assert res.status_code==200
    assert 'senior theoretical physicist' in inputs[-1][1]
    assert 'A universal tail exists' in inputs[-1][1]
    # Conversations in write and discuss modes are deliberately independent.
    assert len(client.get(f'/api/projects/{pid}/messages?mode=write').json())==2
    assert len(client.get(f'/api/projects/{pid}/messages?mode=discuss').json())==2


def test_responses_output_extraction():
    assert extract_output({'output':[{'type':'message','content':[{'type':'output_text','text':'correct'}]}]}) == 'correct'


def test_single_model_registry_locks_all_chat_modes(client, monkeypatch, tmp_path):
    import json
    model_id = 'ollama-deepseek-flash'
    registry = {mode: model_id for mode in MODE_PROMPTS}
    registry['models'] = [{'id': model_id, 'provider': 'custom', 'model': '${CUSTOM_MODEL}',
                           'title': 'DeepSeek Flash (Ollama)', 'api': 'chat_completions', 'effort': None}]
    path = tmp_path / 'models.json'
    path.write_text(json.dumps(registry))
    monkeypatch.setenv('PDVL_MODELS_FILE', str(path))
    monkeypatch.setenv('CUSTOM_MODEL', 'deepseek-v4.1-flash:1017')
    monkeypatch.setenv('CUSTOM_API_BASE', 'https://ollama.com/v1')
    monkeypatch.setenv('CUSTOM_API_KEY', 'ollama-test-key')
    picked = []
    async def generate(model, instructions, messages, **kwargs):
        picked.append(model)
        return 'Configured model reply', {'provider': model['provider'], 'model': model['model']}
    monkeypatch.setattr(api, 'generate', generate)
    settings = client.get('/api/models').json()
    assert len(settings['models']) == 1
    assert settings['models'][0]['model'] == 'deepseek-v4.1-flash:1017'
    assert settings['models'][0]['available'] is True
    assert set(settings['defaults'].values()) == {model_id}
    pid = client.post('/api/projects', json={'title': 'Locked model'}).json()['id']
    for mode in MODE_PROMPTS:
        response = client.post(f'/api/projects/{pid}/chat', json={'mode': mode, 'message': 'Hello'})
        assert response.status_code == 200
        assert json.loads(response.text.splitlines()[-1])['meta']['model'] == 'deepseek-v4.1-flash:1017'
    assert len(picked) == 4 and all(model['id'] == model_id for model in picked)
    for unavailable in ('deepseek-flash', 'deepseek-pro', 'gpt-sol'):
        response = client.post(f'/api/projects/{pid}/chat', json={'message': 'Try another', 'model_id': unavailable})
        assert response.status_code == 422
    assert len(picked) == 4
    assert len(client.get(f'/api/projects/{pid}/messages').json()) == 2
