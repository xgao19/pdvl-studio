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
 const data={runs:[],events:new Map(),pending:null,papers:[],source:null,chat:{answer:'Scoped comparison',meta:{}}};
 async function fetch(url,options={}){
   calls.push({url,options});
   if(url==='/api/models')return new Promise(()=>{}); // Bootstrap is outside this focused UI test.
   if(data.pending&&url==='/api/projects/p/runs')return data.pending;
   let value=[];
   if(url==='/api/projects/p/runs')value=data.runs;
   else if(url==='/api/projects/p/papers')value=data.papers;
   else if(url==='/api/projects/p/chat')value=data.chat;
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
 const context=vm.createContext({document,fetch,TextDecoder,Date,Set,Map,Promise,JSON,
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
 await app.run('refreshPapers()');
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
