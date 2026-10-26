import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Small DOM boundary; exercise the actual app polling and button handlers without a UI library.
function setup(){
 const nodes=new Map(),timers=new Map(),calls=[];
 let timerId=0;
 class Element{
   constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.style={};this.dataset={};this.disabled=false;this.classList={toggle(){},add(){},remove(){}};this._text=''}
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
   get firstElementChild(){return this.children[0]}
   remove(){this.parent.children=this.parent.children.filter(c=>c!==this)}
 }
 for(const match of fs.readFileSync(new URL('../web/index.html',import.meta.url),'utf8').matchAll(/id="([^"]+)"/g)){
   const element=new Element();element.id=match[1];
 }
 const document={hidden:false,getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),
   querySelectorAll:()=>[],querySelector:()=>new Element(),addEventListener(){}};
 const data={runs:[],events:new Map(),pending:null};
 async function fetch(url,options={}){
   calls.push({url,options});
   if(url==='/api/models')return new Promise(()=>{}); // Bootstrap is outside this focused UI test.
   if(data.pending&&url==='/api/projects/p/runs')return data.pending;
   let value=[];
   if(url==='/api/projects/p/runs')value=data.runs;
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
function run(id,state){return {id,title:id,question:'A question',state,thread_id:'thread',parent_run_id:null,output:'',error:''}}

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
