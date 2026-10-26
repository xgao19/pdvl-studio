/* Local-first PDVL UI. All science records come from the API, never browser-local inference. */
const $ = id => document.getElementById(id);
let project = null, mode = "discuss", models = [], defaults = {}, lastAnswer = "";
const modelSelections = {};
let projectClaims = [], projectEvidence = [], activeProject = null;
const modes = {
  discuss: ["SCIENTIFIC CONVERSATION", "Discuss <span>the physics</span>", "Ask a physics question, challenge an argument, or develop a new idea…"],
  investigate: ["DEEP SCIENTIFIC RESEARCH", "Investigate <span>with rigor</span>", "Analyze a factorization theorem, an operator, or a hard physical question…"],
  verify: ["PHYSICS VERIFICATION", "Verify <span>the evidence</span>", "Try to falsify a claim, examine implicit assumptions, or find an independent check…"],
  write: ["SCIENTIFIC WRITING STUDIO", "Write <span>with insight</span>", "Develop a PRL narrative, refine a physical argument, or write LaTeX-ready prose…"]
};
async function api(path, opts={}){
  const response=await fetch('/api'+path,{...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}});
  let data;try{data=await response.json()}catch{data={detail:'Invalid server response'}}
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||response.status));
  return data;
}
const post=(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)});
function notify(text){$('alert').textContent=text;$('alert').classList.remove('hidden');setTimeout(()=>$('alert').classList.add('hidden'),8500)}
function text(node,t){node.textContent=t;return node}
function element(tag,cl){const x=document.createElement(tag);if(cl)x.className=cl;return x}
function renderMarkdown(target,body){
 // Immediate safe fallback, then local-server-rendered and sanitized Markdown.
 const fallback=element('pre');fallback.textContent=body;target.appendChild(fallback);
 post('/render',{markdown:body}).then(data=>{target.innerHTML=data.html})
    .catch(()=>{});
}
async function init(){
  try {
    const ms=await api('/models');models=ms.models;defaults=ms.defaults;
    const ps=await api('/projects');
    if(!ps.length){await post('/seed-csk',{});}
    await reloadProjects();
  }catch(e){notify(e.message)}
}
async function reloadProjects(prefer){
 const projects=await api('/projects');$('projects').replaceChildren();
 for(const p of projects){const opt=element('option');opt.value=p.id;opt.textContent=p.title;$('projects').appendChild(opt)}
 project=(prefer&&projects.find(x=>x.id===prefer)?.id)||project&&projects.find(x=>x.id===project)?.id||projects[0]?.id;
 if(project){$('projects').value=project;await switchMode(mode)}
}
function fillModels(){
 const select=$('model');select.replaceChildren();
 for(const m of models){const o=element('option');o.value=m.id;o.textContent=m.title+(!m.available?' (set API key)':'');select.appendChild(o)}
 const best=modelSelections[mode]||defaults[mode];select.value=models.some(m=>m.id===best)?best:defaults[mode];syncModelState();
}
function syncModelState(){const m=models.find(x=>x.id===$('model').value);$('modelState').textContent=m?.available?'Connected':'API key needed';$('modelState').classList.toggle('ok',!!m?.available)}
async function switchMode(next){
 if(activeProject!==project){
   activeProject=project;lastAnswer='';$('docTitle').value='';$('docText').value='';$('documentSources').replaceChildren();
   $('documentSelect').replaceChildren();
 }
 mode=next;
 document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.mode===mode));
 $('modeCaption').textContent=modes[mode][0];$('modeTitle').innerHTML=modes[mode][1];$('question').placeholder=modes[mode][2];
 $('runPanel').classList.toggle('hidden',mode!=='investigate');$('manuscriptPanel').classList.toggle('hidden',mode!=='write');
 fillModels();await refreshMessages();await refreshEvidence();if(mode==='investigate')await refreshRuns();if(mode==='write')await refreshDocuments();
}
async function refreshMessages(){
 if(!project)return;
 const messages=await api(`/projects/${project}/messages?mode=${mode}`);$('timeline').replaceChildren();
 $('intro').classList.toggle('hidden',messages.length>0);
 for(const item of messages)appendMessage(item.role,item.content,item.model_id);
 scrollToBottom();
}
function appendMessage(role,body,modelId){
 const msg=element('article','msg '+role);const avatar=element('div','avatar');avatar.textContent=role==='assistant'?'∇':'U';
 const right=element('div','msg-body');const head=element('div','msg-header');const label=element('strong');label.textContent=role==='assistant'?'PDVL / '+(models.find(x=>x.id===modelId)?.title||'Research model'):'You';head.appendChild(label);
 const content=element('div','message-content');renderMarkdown(content,body);right.append(head,content);msg.append(avatar,right);$('timeline').appendChild(msg);return msg;
}
function scrollToBottom(){const area=document.querySelector('.conversation-area');area.scrollTop=area.scrollHeight}
async function send(){
 const q=$('question').value.trim();if(!project||!q)return;
 $('send').disabled=true;$('question').disabled=true;$('intro').classList.add('hidden');
 const optimistic=appendMessage('user',q);const loading=appendMessage('assistant','Thinking through the physics…');
 scrollToBottom();
 try{
   const result=await post(`/projects/${project}/chat`,{message:q,mode,model_id:$('model').value});
   loading.remove();appendMessage('assistant',result.answer,$('model').value);lastAnswer=result.answer;$('question').value='';
 }catch(e){loading.remove();optimistic.remove();notify(e.message)}
 finally{$('send').disabled=false;$('question').disabled=false;scrollToBottom();$('question').focus()}
}
async function refreshEvidence(){
 if(!project)return;
 const pid=project;
 const [claims,evidence]=await Promise.all([api(`/projects/${pid}/claims`),api(`/projects/${pid}/evidence`)]);
 if(pid!==project)return;
 projectClaims=claims;projectEvidence=evidence;
 $('claimCount').textContent=claims.length;$('evidenceCount').textContent=evidence.length;$('claims').replaceChildren();
 for(const c of claims){
   const box=element('div','claim-card');box.appendChild(text(element('strong'),c.title));box.appendChild(text(element('p'),c.statement));
   box.appendChild(text(element('span','pill '+c.status),c.status.replaceAll('_',' ')));
   if(['rg_identity','experimental_extraction'].includes(c.kind)){
     const b=text(element('button'),'Run scoped physical check');b.onclick=()=>verify(c);box.appendChild(b);
   }
   for(const e of evidence.filter(e=>e.claim_id===c.id))box.appendChild(evidenceCard(e));
   $('claims').appendChild(box);
 }
}
function action(label,handler){const b=text(element('button'),label);b.onclick=()=>Promise.resolve().then(handler).catch(e=>notify(e.message));return b}
async function viewArtifact(id){
 const response=await fetch('/api/artifacts/'+encodeURIComponent(id));
 if(!response.ok)throw new Error('Cannot read archived artifact');
 const body=new TextDecoder('utf-8',{fatal:true}).decode(await response.arrayBuffer());
 openModal('Archived source',body);
}
function evidenceCard(e){
 const card=element('div','evidence-entry');
 card.appendChild(text(element('p'),`${e.verdict} · ${e.description}`));
 card.appendChild(action('Inspect evidence',()=>openModal('Evidence '+e.id,JSON.stringify(e,null,2))));
 if(e.artifact_id)card.appendChild(action('View archived source',()=>viewArtifact(e.artifact_id)));
 if(mode==='write')card.appendChild(action('Cite in manuscript',()=>{
   const editor=$('docText'),marker=`[evidence:${e.id}]`,start=editor.selectionStart,end=editor.selectionEnd;
   editor.setRangeText(marker,start,end,'end');editor.focus();renderDocumentSources();
 }));
 return card;
}
function renderDocumentSources(sources=projectEvidence){
 const ids=[...$('docText').value.matchAll(/\[evidence:([^\]\r\n]*)\]/g)].map(m=>m[1]);
 $('documentSources').replaceChildren();
 for(const id of new Set(ids)){
   const source=sources.find(e=>e.id===id),line=element('div','evidence-entry');
   line.appendChild(text(element('span'),source?`${id} · ${source.verdict} · ${source.description}`:`Unknown citation: ${id}`));
   if(source?.artifact_id)line.appendChild(action('View archived source',()=>viewArtifact(source.artifact_id)));
   $('documentSources').appendChild(line);
 }
}
async function verify(c){
 const test=c.kind==='rg_identity'?'csk_delta_rg':'csk_experimental_overclaim';
 try{const result=await post(`/projects/${project}/claims/${c.id}/verify/${test}`,{});notify(`Verification: ${result.result.verdict} — ${result.result.formal_check}`);await refreshEvidence()}
 catch(e){notify(e.message)}
}
async function saveClaim(){const statement=$('claimStatement').value.trim(),title=$('claimTitle').value.trim()||'New hypothesis';if(!statement)return notify('Enter a physical proposition first');
 try{await post(`/projects/${project}/claims`,{title,statement,kind:'general'});$('claimStatement').value='';$('claimTitle').value='';await refreshEvidence()}catch(e){notify(e.message)}
}
async function saveFromComposer(){const statement=$('question').value.trim();if(!statement)return notify('Write a hypothesis in the composer first');
 try{await post(`/projects/${project}/claims`,{title:statement.slice(0,70),statement});notify('Saved as an unverified research idea');await refreshEvidence()}catch(e){notify(e.message)}
}
async function refreshRuns(){
 const pid=project,runs=await api(`/projects/${pid}/runs`);
 const archives=await Promise.all(runs.map(r=>api(`/runs/${r.id}/artifacts`)));
 if(pid!==project)return;
 $('runs').replaceChildren();
 for(const [index,r] of runs.entries()){
   const box=element('div','run-entry');box.appendChild(text(element('strong'),r.title+` — ${r.state}`));
   box.appendChild(text(element('p'),r.question.slice(0,230)));
   box.appendChild(action('View task context',async()=>{const task=await api('/runs/'+r.id);openModal('Frozen research context',JSON.stringify(JSON.parse(task.context_json),null,2))}));
   if(r.output)box.appendChild(text(element('pre'),r.output));if(r.error)box.appendChild(text(element('pre'),r.error));
   const artifacts=archives[index];
   for(const a of artifacts){
     const line=element('div');line.appendChild(action(a.name,()=>viewArtifact(a.id)));
     const link=text(element('a'),'Download');link.href='/api/artifacts/'+encodeURIComponent(a.id);line.appendChild(link);box.appendChild(line);
   }
   if(artifacts.length&&projectClaims.length){
     const source=element('select'),claim=element('select'),kind=element('select'),verdict=element('select'),description=element('textarea');
     kind.setAttribute('aria-label','Evidence kind');source.setAttribute('aria-label','Source artifact');claim.setAttribute('aria-label','Claim');verdict.setAttribute('aria-label','Evidence verdict');
     for(const a of artifacts){const option=text(element('option'),a.name);option.value=a.id;source.appendChild(option)}
     source.value=(artifacts.find(a=>a.name==='workspace/findings.md')||artifacts[0]).id;
     for(const c of projectClaims){const option=text(element('option'),c.title);option.value=c.id;claim.appendChild(option)}
     for(const value of ['derivation','numerical','note']){const option=text(element('option'),value);option.value=value;kind.appendChild(option)}
     for(const value of ['unresolved','supporting','challenging']){const option=text(element('option'),value);option.value=value;verdict.appendChild(option)}
     description.placeholder='Explain how this source bears on the selected claim';
     box.append(source,claim,kind,verdict,description,action('Record as evidence',async()=>{
       if(!description.value.trim())throw new Error('Describe the evidence before recording it');
       await post(`/projects/${pid}/evidence`,{claim_id:claim.value,artifact_id:source.value,kind:kind.value,verdict:verdict.value,description:description.value.trim()});
       description.value='';await refreshEvidence();notify('Evidence recorded; claim status unchanged');
     }));
   }
   $('runs').appendChild(box);
 }
}
async function startCodex(){const question=$('codexQuestion').value.trim();if(!question)return;try{const r=await post(`/projects/${project}/runs`,{question,model_id:$('codexModel').value||null});notify('Research queued: '+r.id);$('codexQuestion').value='';await refreshRuns()}catch(e){notify(e.message)}}
async function refreshDocuments(){
 const selected=$('documentSelect').value,docs=await api(`/projects/${project}/documents`);$('documentSelect').replaceChildren();
 const none=text(element('option'),'New document');none.value='';$('documentSelect').appendChild(none);
 for(const d of docs){const opt=text(element('option'),d.title+` (v${d.latest_revision})`);opt.value=d.id;$('documentSelect').appendChild(opt)}
 if(docs.some(d=>d.id===selected))$('documentSelect').value=selected;
 renderDocumentSources();
}
async function loadDocument(){
 const id=$('documentSelect').value;
 if(!id){$('docTitle').value='';$('docText').value='';renderDocumentSources();return}
 const d=await api('/documents/'+id);$('docTitle').value=d.document.title;$('docText').value=d.revisions[0]?.text||'';
 renderDocumentSources(d.revisions[0]?.sources||[]);
}
async function saveDocument(){const title=$('docTitle').value.trim()||'Untitled research manuscript';const source=$('docText').value.trim();if(!source)return notify('Enter draft text first');
 try{const result=await post(`/projects/${project}/documents`,{title,text:source,document_id:$('documentSelect').value||null});await refreshDocuments();$('documentSelect').value=result.document.id;renderDocumentSources(result.revisions[0].sources);notify(`Saved revision ${result.document.latest_revision}`)}catch(e){notify(e.message)}}
function openModal(title,body){$('modalTitle').textContent=title;$('modalText').textContent=body;$('modalText').classList.remove('hidden');$('modalEditor').classList.add('hidden');$('saveModal').style.display='none';$('copyModal').style.display='block';$('modal').classList.remove('hidden')}
async function openStyle(){const s=await api(`/projects/${project}/style`);$('modalTitle').textContent='Scientific voice — project style';$('modalText').classList.add('hidden');$('modalEditor').classList.remove('hidden');$('modalEditor').value=s.style_text;$('saveModal').style.display='block';$('copyModal').style.display='none';$('modal').classList.remove('hidden')}
async function saveStyle(){try{await api(`/projects/${project}/style`,{method:'PUT',body:JSON.stringify({style_text:$('modalEditor').value})});closeModal();notify('Scientific voice saved for this research project')}catch(e){notify(e.message)}}
function closeModal(){$('modal').classList.add('hidden')}
$('modes').addEventListener('click',e=>{const b=e.target.closest('[data-mode]');if(b)switchMode(b.dataset.mode).catch(err=>notify(err.message))});
$('model').addEventListener('change',()=>{modelSelections[mode]=$('model').value;syncModelState()});
$('projects').addEventListener('change',e=>{project=e.target.value;switchMode(mode).catch(err=>notify(err.message))});
$('newProject').onclick=async()=>{const title=prompt('Title of your research project:');if(!title?.trim())return;const description=prompt('Scientific scope (optional):')||'';try{const p=await post('/projects',{title,description});await reloadProjects(p.id)}catch(e){notify(e.message)}};
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
$('send').onclick=send;$('saveAsClaim').onclick=saveFromComposer;$('addClaim').onclick=saveClaim;$('launchCodex').onclick=startCodex;
$('refreshEvidence').onclick=()=>refreshEvidence().catch(e=>notify(e.message));
$('refreshRuns').onclick=()=>refreshRuns().catch(e=>notify(e.message));
$('docText').addEventListener('input',()=>renderDocumentSources());
$('openBrief').onclick=async()=>{try{const b=await api(`/projects/${project}/brief`);openModal('Research Brief',b.markdown)}catch(e){notify(e.message)}};
$('seedProject').onclick=async()=>{try{await post('/seed-csk',{});await reloadProjects('csk_seed')}catch(e){notify(e.message)}};
$('saveDocument').onclick=saveDocument;$('editStyle').onclick=()=>openStyle().catch(e=>notify(e.message));$('saveModal').onclick=saveStyle;$('useLastAnswer').onclick=()=>{if(lastAnswer){$('docText').value=lastAnswer;renderDocumentSources();notify('Latest assistant answer copied to manuscript editor')}else notify('Discuss a draft first')};$('documentSelect').onchange=()=>loadDocument().catch(e=>notify(e.message));
$('closeModal').onclick=closeModal;$('modal').onclick=e=>{if(e.target===$('modal'))closeModal()};
$('copyModal').onclick=()=>navigator.clipboard.writeText($('modalText').textContent).then(()=>notify('Copied to clipboard')).catch(e=>notify(e.message));
document.querySelectorAll('.suggestion').forEach(b=>b.onclick=()=>{$('question').value=b.dataset.q;$('question').focus()});
init();
