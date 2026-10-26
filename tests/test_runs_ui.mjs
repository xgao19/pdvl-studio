import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Small DOM boundary; exercise the actual app polling and button handlers without a UI library.
function setup(){
 const nodes=new Map(),timers=new Map(),calls=[];
 let timerId=0;
 class Element{
   constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.style={};this.dataset={};this.disabled=false;const classes=new Set();this.classList={toggle(name,on){if(on)classes.add(name);else classes.delete(name)},add(name){classes.add(name)},remove(name){classes.delete(name)},contains(name){return classes.has(name)}};this._text=''}
   set id(value){this._id=value;nodes.set(value,this)}
   get id(){return this._id}
   set textContent(value){this._text=value;this.children=[]}
   get textContent(){return this._text}
   append(...items){this.children.push(...items);for(const child of items)child.parent=this}
   appendChild(child){this.append(child);return child}
   prepend(child){this.children.unshift(child);child.parent=this}
   replaceChildren(...items){this.children=[];this.append(...items)}
   setAttribute(name,value){this[name]=value}
   addEventListener(){}
   scrollIntoView(){}
   focus(){}
   get firstElementChild(){return this.children[0]}
   remove(){this.parent.children=this.parent.children.filter(c=>c!==this)}
 }
 for(const match of fs.readFileSync(new URL('../web/index.html',import.meta.url),'utf8').matchAll(/id="([^"]+)"/g)){
   const element=new Element();element.id=match[1];
 }
 const document={hidden:false,getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),
   querySelectorAll:()=>[],querySelector:()=>new Element(),addEventListener(){}};
 const data={runs:[],events:new Map(),pending:null,papers:[],webSources:[],source:null,chat:{answer:'Scoped comparison',meta:{}}};
 async function fetch(url,options={}){
   calls.push({url,options});
   if(url==='/api/models')return new Promise(()=>{}); // Bootstrap is outside this focused UI test.
   if(data.pending&&url==='/api/projects/p/runs')return data.pending;
   let value=[];
   if(url==='/api/projects/p/runs')value=data.runs;
   else if(url==='/api/projects/p/papers')value=data.papers;
   else if(url==='/api/projects/p/web-sources')value=data.webSources;
   else if(url.match(/\/projects\/[^/]+\/chat$/)){
     const events=data.chatEvents||[{type:'start',id:'m_live'},{type:'done',...data.chat}];
     const bytes=new TextEncoder().encode(events.map(e=>JSON.stringify(e)+'\n').join(''));
     let offset=0;
     return {ok:true,body:{getReader:()=>({read:()=>data.chatRead?data.chatRead(options.signal):Promise.resolve(offset>=bytes.length?{done:true}:{done:false,value:bytes.slice(offset,offset+=7)})})}};
   }else if(url.endsWith('/stop')){data.stopped=true;value={state:'stopping'}}
   else if(url.includes('/artifacts/')&&url.includes('/text?'))value=data.source;
   else if(url.includes('/events?')){
     const [,rid,after]=url.match(/\/runs\/([^/]+)\/events\?after=(\d+)/);
     const entries=(data.events.get(rid)||[]).filter(e=>e.id>Number(after));
     value={events:entries,cursor:entries.at(-1)?.id||Number(after),has_more:false};
   }else if(url.endsWith('/cancel')){data.runs.find(r=>url.includes(r.id)).state='cancelling';value={}}
   else if(url.endsWith('/continue')){
     value={id:'child'};data.runs.unshift({id:'child',title:'Continued',question:'Next',state:'queued',thread_id:'thread',parent_run_id:'done',output:'',error:''});
   }
   return {ok:true,json:async()=>JSON.parse(JSON.stringify(value))};
 }
 const context=vm.createContext({document,fetch,TextDecoder,AbortController,Date,Set,Map,Promise,JSON,
   setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8'),context);
 vm.runInContext("project='p';activeProject='p';mode='investigate';",context);
 return {context,data,timers,calls,document,view:id=>vm.runInContext(`runViews.get('${id}')`,context),run:code=>vm.runInContext(code,context)};
}
function run(id,state){return {id,title:id,question:'A question',state,thread_id:'thread',parent_run_id:null,output:'',error:'',runtime_matches:true}}

test('polling adds progress once and preserves entered continuation text and DOM identity',async()=>{
 const app=setup();app.data.runs=[run('live','running'),run('done','completed')];
 app.data.events.set('live',[{id:1,message:'Starting',created_at:'2026-10-25T12:00:00Z'}]);
 await app.run('refreshRuns()');
 const done=app.view('done'),live=app.view('live');done.instruction.value='Do not erase this draft';
 app.data.events.get('live').push({id:2,message:'Executing a check',created_at:'2026-10-25T12:00:01Z'});
 await app.run('refreshRuns()');
 assert.equal(app.view('done'),done);assert.equal(done.instruction.value,'Do not erase this draft');
 assert.equal(live.log.children.length,2);assert.equal(live.cursor,2);
 await app.run('refreshRuns()');assert.equal(live.log.children.length,2);
 assert.ok([...app.timers.values()].some(t=>t.ms===1000));
 await live.cancel.onclick();assert.equal(app.data.runs[0].state,'cancelling');assert.equal(live.cancel.disabled,true);
 assert.equal(app.calls.filter(c=>c.url.endsWith('/cancel')).length,1);
 await done.continue.onclick();
 assert.equal(JSON.parse(app.calls.find(c=>c.url.endsWith('/continue')).options.body).message,'Do not erase this draft');
 assert.ok(app.view('child'));assert.equal(done.instruction.value,'');
 await app.run("switchMode('discuss')");
 assert.ok(![...app.timers.values()].some(t=>t.ms===1000));
});

test('an in-flight response from the previous project cannot populate the new project or restart polling',async()=>{
 const app=setup();let resolve;
 app.data.pending=new Promise(r=>{resolve=r});
 const request=app.run('refreshRuns()');
 app.run("stopRunPolling();project='other';runViews.clear();");
 resolve({ok:true,json:async()=>[run('stale','running')]});
 await request;
 assert.equal(app.view('stale'),undefined);assert.equal(app.timers.size,0);
});

test('a single-model registry disables model switching and selects its configured default',()=>{
 const app=setup();
 app.run("models=[{id:'ollama-deepseek-flash',title:'DeepSeek Flash (Ollama)',available:true}];defaults={investigate:'ollama-deepseek-flash'};fillModels();");
 const select=app.document.getElementById('model');
 assert.equal(select.disabled,true);assert.equal(select.value,'ollama-deepseek-flash');assert.equal(select.children.length,1);
 app.run("models.push({id:'another',title:'Another',available:true});fillModels();");
 assert.equal(select.disabled,false);
});

test('Codex uses only the configured model and hides continuation from another runtime',async()=>{
 const app=setup();
 app.run("fillCodex({configured:true,available:true,model:'deepseek-v4.1-flash:1017',provider:'pdvl_ollama',title:'Ollama'});");
 const picker=app.document.getElementById('codexModel');
 assert.equal(picker.disabled,true);assert.equal(picker.children.length,1);assert.equal(picker.value,'deepseek-v4.1-flash:1017');
 assert.equal(app.document.getElementById('launchCodex').disabled,false);
 app.data.runs=[run('current','completed'),{...run('old','completed'),runtime_matches:false}];
 await app.run('refreshRuns()');
 assert.equal(app.view('old').resume.classList.contains('hidden'),true);
 assert.equal(app.view('current').resume.classList.contains('hidden'),false);
 assert.match(app.document.getElementById('codexRuntime').textContent,/不使用 ChatGPT 订阅/);
 app.run("fillCodex({configured:false,available:false,detail:'Configure isolated runtime'});");
 assert.equal(app.document.getElementById('launchCodex').disabled,true);assert.equal(picker.value,'');
});

test('literature selection limits comparison to two papers and sends their actual archive IDs',async()=>{
 const app=setup();
 app.data.papers=[1,2,3].map(n=>({id:'a_'+n,title:'Study '+n,page_count:3,arxiv_id:'2301.1234'+n}));
 await app.run('refreshSources()');
 for(const id of ['a_1','a_2','a_3'])app.run(`paperChecks.get('${id}').checked=true;paperChecks.get('${id}').onchange();`);
 assert.deepEqual([...app.run('selectedPapers')],['a_1','a_2']);
 assert.equal(app.run("paperChecks.get('a_3').checked"),false);
 app.document.getElementById('readSelectedPapers').onclick();
 const question=app.document.getElementById('question').value;
 assert.match(question,/Study 1/);assert.match(question,/Study 2/);assert.doesNotMatch(question,/Study 3/);
 await app.run("mode='discuss';send()");
 const request=app.calls.find(c=>c.url==='/api/projects/p/chat');
 assert.deepEqual(JSON.parse(request.options.body).paper_ids,['a_1','a_2']);
});

test('source viewer uses page and offset reading and follows saved evidence page provenance',async()=>{
 const app=setup();
 app.data.source={id:'a_paper',page:2,page_count:4,offset:0,next_offset:7000,truncated:true,
                  text:'Actual original text',sha256:'hash',pdf_artifact_id:'a_pdf',title:'Paper'};
 await app.run("viewArtifact('a_paper',2)");
 assert.match(app.calls.at(-1).url,/page=2&offset=0/);
 assert.equal(app.document.getElementById('sourcePage').value,2);
 assert.equal(app.document.getElementById('nextSourceChunk').disabled,false);
 assert.match(app.document.getElementById('modalText').textContent,/Actual original text/);
 await app.document.getElementById('nextSourceChunk').onclick();
 assert.match(app.calls.at(-1).url,/page=2&offset=7000/);
 assert.equal(app.run("evidencePage({provenance:JSON.stringify({paper_source:{pages:[3]}})})"),3);
 assert.equal(app.run("evidencePage({provenance:'{}'})"),1);
});

test('web snapshots use the shared reader and evidence form with section provenance',async()=>{
 const app=setup();
 app.data.webSources=[{id:'a_web',kind:'webpage',title:'Primary source',url:'https://example.com/',retrieved_at:'2026-10-26T00:00:00Z',page_count:3}];
 app.run("projectClaims=[{id:'c_1',title:'Scoped claim'}]");
 await app.run('refreshSources()');
 const card=app.document.getElementById('webSources').children[0];
 assert.equal(card.children[0].textContent,'Primary source');
 const form=card.children.at(-1).children[1],page=form.children[1];
 page.value=2;form.children.at(-2).value='A limitation from the original section';
 await form.children.at(-1).onclick();
 const saved=JSON.parse(app.calls.find(c=>c.url.endsWith('/evidence')&&c.options.method==='POST').options.body);
 assert.equal(saved.artifact_id,'a_web');assert.deepEqual(saved.provenance,{pages:[2]});
 assert.equal(app.run("evidencePage({provenance:JSON.stringify({web_source:{pages:[2]}})})"),2);
 app.data.source={...app.data.webSources[0],page:2,offset:0,next_offset:null,text:'Original extracted body',
                  sha256:'snapshot-hash',raw_artifact_id:'a_response',notice:'Extracted webpage text, not HTML.'};
 await app.run("viewArtifact('a_web',2)");
 assert.match(app.document.getElementById('modalText').textContent,/网页段 2/);
 assert.match(app.document.getElementById('modalText').textContent,/归档时间/);
 assert.equal(app.document.getElementById('sourceOriginal').href,'/api/artifacts/a_response');
 assert.equal(app.document.getElementById('sourceURL').href,'https://example.com/');
});

test('web source refresh cannot populate another project after an in-flight response',async()=>{
 const app=setup();
 let finish;const response=new Promise(r=>{finish=r});
 app.context.fetch=()=>response;
 const current=app.run('refreshSources()');app.run("project='other'");
 finish({ok:true,json:async()=>[{id:'stale',title:'Stale'}]});await current;
 assert.equal(app.document.getElementById('webSources').children.length,0);
});

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const ndjson=events=>new TextEncoder().encode(events.map(e=>JSON.stringify(e)+'\n').join(''));

test('chat streams text and tool progress before completion, stops on the server, and preserves the next draft',async()=>{
 const app=setup();let finish;
 app.run("mode='discuss'");app.document.getElementById('question').value='Explain the result';
 let reads=0;
 app.data.chatRead=async()=>{
   if(reads++===0)return {done:false,value:ndjson([{type:'start',id:'m_live'},{type:'progress',round:1,message:'Reading'},
     {type:'tool_start',name:'search_project_papers',args:{query:'epsilon'}},
     {type:'tool_end',name:'search_project_papers',args:{query:'epsilon'}},{type:'delta',text:'中间结果🙂'}])};
   if(reads===2)return new Promise(resolve=>{finish=resolve});
   return {done:true};
 };
 const sending=app.run('send()');await tick();
 assert.equal(app.run('activeChat.draft'),'中间结果🙂');
 assert.equal(app.document.getElementById('stopChat').classList.contains('hidden'),false);
 assert.equal(app.document.getElementById('send').disabled,true);
 assert.equal(app.run('activeChat.status.textContent'),'正在生成回答 · 引用将在完成后校验');
 app.document.getElementById('question').value='Next question already drafted';
 await app.document.getElementById('stopChat').onclick();
 assert.equal(app.data.stopped,true);assert.equal(app.document.getElementById('stopChat').disabled,true);
 finish({done:false,value:ndjson([{type:'done',answer:'中间结果🙂',meta:{state:'stopped',tools:[]}}])});
 await sending;
 assert.equal(app.document.getElementById('question').value,'Next question already drafted');
 assert.equal(app.run('lastAnswer'),'');assert.equal(app.run('activeChat'),null);
 assert.equal(app.document.getElementById('send').disabled,false);
 assert.equal(app.document.getElementById('stopChat').classList.contains('hidden'),true);
 const assistant=app.document.getElementById('timeline').children[1];
 assert.ok(assistant.body.children.some(n=>n.textContent.includes('已停止')));
});

test('mode changes abort chat and stale chunks cannot overwrite the new view',async()=>{
 const app=setup();let signal,finish;
 app.run("mode='discuss'");app.document.getElementById('question').value='Old question';
 app.data.chatRead=s=>{signal=s;return new Promise(resolve=>{finish=resolve})};
 const sending=app.run('send()');await tick();
 await app.run("switchMode('write')");assert.equal(signal.aborted,true);
 app.data.chatRead=async()=>({done:true});
 finish({done:false,value:ndjson([{type:'done',answer:'Stale answer',meta:{state:'completed'}}])});
 await sending;
 assert.equal(app.run('lastAnswer'),'');assert.equal(app.document.getElementById('timeline').children.length,0);
 assert.equal(app.document.getElementById('send').disabled,false);
});

test('project fulltext search opens actual matching pages and citation failures remain visible',async()=>{
 const app=setup();app.document.getElementById('paperQuery').value='CASCADE';
 // The shared search handler must target project archives rather than arXiv.
 await app.document.getElementById('searchLibrary').onclick();
 assert.ok(app.calls.some(c=>c.url==='/api/projects/p/papers/fulltext?query=CASCADE'));
 app.run("appendMessage('assistant','A draft','model',{citations:[{target:'/api/artifacts/a_missing#page=9',valid:false,reason:'页码不存在'}]})");
 const msg=app.document.getElementById('timeline').children.at(-1);
 const checks=msg.body.children.at(-1);
 assert.equal(checks.open,true);assert.match(checks.children[0].textContent,/1 处引用未通过校验/);
 assert.match(checks.children[1].textContent,/页码不存在/);
});
