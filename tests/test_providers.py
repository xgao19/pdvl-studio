import asyncio
from pdvl.providers import generate

class FakeResponse:
    def __init__(self, data): self.data=data; self.status_code=200
    def raise_for_status(self): return None
    def json(self): return self.data

class AsyncFakeClient:
    def __init__(self, replies, sent): self.replies=iter(replies);self.sent=sent
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def post(self,url,headers=None,json=None):
        self.sent.append((url,json))
        return FakeResponse(next(self.replies))

def test_deepseek_responses_tool_loop(monkeypatch,tmp_path):
    monkeypatch.setenv('PDVL_HOME',str(tmp_path))
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-key')
    from pdvl.db import init_db,execute,utcnow
    init_db();execute('INSERT INTO projects VALUES (?,?,?,?)',('p','Test','',utcnow()))
    sent=[]
    replies=[
      {'model':'deepseek-v4-pro','output':[{'type':'function_call','name':'run_named_physics_check','arguments':'{"test_id":"csk_delta_rg"}','call_id':'c1'}]},
      {'model':'deepseek-v4-pro','output':[{'type':'message','content':[{'type':'output_text','text':'The difference is RG invariant only under common anomalous dimensions.'}]}]}
    ]
    monkeypatch.setattr('pdvl.providers.httpx.AsyncClient',lambda **kw:AsyncFakeClient(replies,sent))
    model={'provider':'deepseek','model':'deepseek-v4-pro','api':'responses','effort':'high'}
    answer,meta=asyncio.run(generate(model,'Check conditions',[{'role':'user','content':'Check RG'}],project_id='p',allow_tools=True))
    assert 'only under' in answer
    assert len(sent)==2
    assert sent[0][0]=='https://api.deepseek.com/responses'
    assert sent[0][1]['tools'][0]['type']=='function'
    assert sent[1][1]['input'][-1]['call_id']=='c1'
    assert meta['tools'][0]['name']=='run_named_physics_check'

def test_custom_chat_completions(monkeypatch,tmp_path):
    monkeypatch.setenv('CUSTOM_API_KEY','local')
    monkeypatch.setenv('CUSTOM_API_BASE','http://localhost:9090/v1')
    sent=[]
    replies=[{'model':'local-reasoner','choices':[{'message':{'content':'A physical argument.'}}]}]
    monkeypatch.setattr('pdvl.providers.httpx.AsyncClient',lambda **kw:AsyncFakeClient(replies,sent))
    model={'provider':'custom','model':'local-reasoner','api':'chat_completions','effort':None}
    text,meta=asyncio.run(generate(model,'Act as physicist',[{'role':'user','content':'Explain'}]))
    assert text=='A physical argument.'
    assert sent[0][0]=='http://localhost:9090/v1/chat/completions'
    assert sent[0][1]['messages'][0]['role']=='system'
