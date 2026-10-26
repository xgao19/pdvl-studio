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
