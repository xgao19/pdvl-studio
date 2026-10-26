/* Local-first PDVL UI. All science records come from the API, never browser-local inference. */
const $ = id => document.getElementById(id);
let project = null, mode = "discuss", models = [], defaults = {}, lastAnswer = "";
const modelSelections = {};
let projectClaims = [], projectEvidence = [], activeProject = null;
let projectPapers = [], sourceView = null;
const selectedPapers = new Set(), paperChecks = new Map();
const runViews = new Map();
let runEpoch = 0, runTimer = null, runRequest = null;
const activeRun = r => ['queued','running','cancelling'].includes(r.state);
const runLabels = {queued:'排队中',running:'执行中',cancelling:'正在取消',cancelled:'已取消',completed:'已完成',failed:'失败',interrupted:'已中断'};
function stopRunPolling(){clearTimeout(runTimer);runEpoch++;runRequest=null}
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
    const ms=await api('/models');models=ms.models;defaults=ms.defaults;fillCodex(ms.codex);
    const ps=await api('/projects');
    if(!ps.length){await post('/seed-csk',{});}
    await reloadProjects();
  }catch(e){notify(e.message)}
}
function fillCodex(runtime){
 const select=$('codexModel');select.replaceChildren();select.disabled=true;
 const option=element('option');option.value=runtime.model||'';
 option.textContent=runtime.configured?`${runtime.model} (${runtime.title})`:'Configure isolated Codex runtime';select.appendChild(option);select.value=option.value;
 $('launchCodex').disabled=!runtime.available;
 $('codexRuntime').textContent=runtime.configured?(runtime.available?'独立 API 环境 · 不使用 ChatGPT 订阅':'独立 Codex 环境缺少 API key'):runtime.detail;
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
 select.disabled=models.length===1;
 const best=modelSelections[mode]||defaults[mode];select.value=models.some(m=>m.id===best)?best:defaults[mode];syncModelState();
}
function syncModelState(){const m=models.find(x=>x.id===$('model').value);$('modelState').textContent=m?.available?'Connected':'API key needed';$('modelState').classList.toggle('ok',!!m?.available)}
async function switchMode(next){
 stopRunPolling();
 if(activeProject!==project){
   activeProject=project;lastAnswer='';runViews.clear();$('runs').replaceChildren();$('docTitle').value='';$('docText').value='';$('documentSources').replaceChildren();
   $('documentSelect').replaceChildren();
   selectedPapers.clear();projectPapers=[];$('papers').replaceChildren();$('paperSearchResults').replaceChildren();$('paperSearchPanel').classList.add('hidden');$('paperStatus').textContent='';closeModal();
 }
 mode=next;
 document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.mode===mode));
 $('modeCaption').textContent=modes[mode][0];$('modeTitle').innerHTML=modes[mode][1];$('question').placeholder=modes[mode][2];
 $('runPanel').classList.toggle('hidden',mode!=='investigate');$('manuscriptPanel').classList.toggle('hidden',mode!=='write');
 fillModels();await refreshMessages();await refreshEvidence();await refreshPapers();if(mode==='investigate')await refreshRuns();if(mode==='write')await refreshDocuments();
}
async function refreshMessages(){
 if(!project)return;
 const messages=await api(`/projects/${project}/messages?mode=${mode}`);$('timeline').replaceChildren();
 $('intro').classList.toggle('hidden',messages.length>0||mode==='investigate');
 for(const item of messages)appendMessage(item.role,item.content,item.model_id,JSON.parse(item.meta_json||'{}'));
 scrollToBottom();
}
function appendMessage(role,body,modelId,meta={}){
 const msg=element('article','msg '+role);const avatar=element('div','avatar');avatar.textContent=role==='assistant'?'∇':'U';
 const right=element('div','msg-body');const head=element('div','msg-header');const label=element('strong');label.textContent=role==='assistant'?'PDVL / '+(models.find(x=>x.id===modelId)?.title||modelId||'Research model'):'You';head.appendChild(label);
 const content=element('div','message-content');renderMarkdown(content,body);right.append(head,content);
 const reads=(meta.tools||[]).filter(t=>t.source);
 if(reads.length){const details=element('details','source-reads');details.appendChild(text(element('summary'),'原文读取记录'));
   for(const t of reads)details.appendChild(action(`${t.source.artifact_id} · p.${t.source.page} · offset ${t.source.offset}`,()=>viewArtifact(t.source.artifact_id,t.source.page,t.source.offset)));
   right.appendChild(details);
 }
 msg.append(avatar,right);$('timeline').appendChild(msg);return msg;
}
function scrollToBottom(){const area=document.querySelector('.conversation-area');area.scrollTop=area.scrollHeight}
async function send(){
 const q=$('question').value.trim();if(!project||!q)return;
 const pid=project,sentMode=mode,modelId=$('model').value;
 $('send').disabled=true;$('question').disabled=true;$('intro').classList.add('hidden');
 const optimistic=appendMessage('user',q);const loading=appendMessage('assistant','Thinking through the physics…');
 scrollToBottom();
 try{
   const result=await post(`/projects/${pid}/chat`,{message:q,mode:sentMode,model_id:modelId,paper_ids:[...selectedPapers]});
   if(pid!==project||sentMode!==mode)return;
   loading.remove();appendMessage('assistant',result.answer,modelId,result.meta);lastAnswer=result.answer;$('question').value='';await refreshPapers();
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
async function viewArtifact(id,page=1,offset=0){
 const pid=project;
 const source=await api(`/projects/${pid}/artifacts/${encodeURIComponent(id)}/text?page=${page}&offset=${offset}`);
 if(pid!==project)return;
 openModal(source.title||'Archived source',`PDF page ${source.page} / ${source.page_count} · offset ${source.offset}\nSHA-256: ${source.sha256}\n${source.url||''}\n${source.notice||''}\n\n${source.text}${source.truncated?'\n\n[本页未读完，点击“继续本页”]':''}`);
 sourceView={id,pid,...source};$('sourcePage').value=page;$('sourcePage').max=source.page_count;
 $('nextSourceChunk').disabled=source.next_offset===null;
 $('sourcePDF').classList.toggle('hidden',!source.pdf_artifact_id);$('sourcePDF').href='/api/artifacts/'+encodeURIComponent(source.pdf_artifact_id||'');
 $('sourceControls').classList.remove('hidden');
}
function evidencePage(e){return JSON.parse(e.provenance||'{}').paper_source?.pages?.[0]||1}
function evidenceCard(e){
 const card=element('div','evidence-entry');
 card.appendChild(text(element('p'),`${e.verdict} · ${e.description}`));
 card.appendChild(action('Inspect evidence',()=>openModal('Evidence '+e.id,JSON.stringify(e,null,2))));
 if(e.artifact_id)card.appendChild(action('View archived source',()=>viewArtifact(e.artifact_id,evidencePage(e))));
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
   if(source?.artifact_id)line.appendChild(action('View archived source',()=>viewArtifact(source.artifact_id,evidencePage(source))));
   $('documentSources').appendChild(line);
 }
}
async function verify(c){
 const test=c.kind==='rg_identity'?'csk_delta_rg':'csk_experimental_overclaim';
 try{const result=await post(`/projects/${project}/claims/${c.id}/verify/${test}`,{});notify(`Verification: ${result.result.verdict} — ${result.result.formal_check}`);await refreshEvidence()}
 catch(e){notify(e.message)}
}
async function saveClaim(){const statement=$('claimStatement').value.trim(),title=$('claimTitle').value.trim()||'New hypothesis';if(!statement)return notify('Enter a physical proposition first');
 try{await post(`/projects/${project}/claims`,{title,statement,kind:'general'});$('claimStatement').value='';$('claimTitle').value='';await refreshEvidence();await refreshPapers()}catch(e){notify(e.message)}
}
async function saveFromComposer(){const statement=$('question').value.trim();if(!statement)return notify('Write a hypothesis in the composer first');
 try{await post(`/projects/${project}/claims`,{title:statement.slice(0,70),statement});notify('Saved as an unverified research idea');await refreshEvidence();await refreshPapers()}catch(e){notify(e.message)}
}
function createRunView(r,pid){
 const box=element('div','run-entry');box.id='run-'+r.id;
 const header=element('strong'),relation=element('p'),question=text(element('p'),r.question.slice(0,230)),controls=element('div','inline-actions');
 const output=element('pre'),error=element('p','run-error'),details=element('details'),summary=text(element('summary'),'最近执行进度');
 const log=element('ol','run-progress');log.setAttribute('role','log');log.setAttribute('aria-live','polite');details.append(summary,log);
 details.open=activeRun(r);
 const resume=element('div'),instruction=element('textarea');instruction.placeholder='补充下一步问题，或留空继续完成原任务';instruction.setAttribute('aria-label','继续任务说明');
 const view={box,header,relation,output,error,details,log,resume,instruction,state:r.state,cursor:0,eventsDone:false,artifactsLoaded:false};
 view.cancel=action('取消任务',async()=>{
   view.cancel.disabled=true;
   try{await post(`/runs/${r.id}/cancel`,{});stopRunPolling();await refreshRuns()}finally{view.cancel.disabled=view.state==='cancelling'}
 });
 view.continue=action('继续运行',async()=>{
   view.continue.disabled=true;
   try{
     const child=await post(`/runs/${r.id}/continue`,{message:instruction.value.trim()||'继续完成原任务。先检查已恢复的文件和结果，只执行尚未完成的步骤。'});
     instruction.value='';stopRunPolling();await refreshRuns();$('run-'+child.id)?.scrollIntoView({block:'nearest'});
   }finally{view.continue.disabled=false}
 });
 controls.append(view.cancel);resume.append(instruction,view.continue);
 const archives=element('div');view.archives=archives;
 box.append(header,relation,question,action('View task context',async()=>{
   const task=await api('/runs/'+r.id);openModal('Frozen research context',JSON.stringify(JSON.parse(task.context_json),null,2));
 }),controls,details,output,error,archives,resume);
 return view;
}
function renderRunArtifacts(view,artifacts,pid){
 for(const a of artifacts){
   const line=element('div');line.appendChild(action(a.name,()=>viewArtifact(a.id)));
   const link=text(element('a'),'Download');link.href='/api/artifacts/'+encodeURIComponent(a.id);line.appendChild(link);view.archives.appendChild(line);
 }
 if(artifacts.length&&projectClaims.length)view.archives.appendChild(evidenceForm(artifacts,pid));
}
function evidenceForm(artifacts,pid,paper=null){
   const form=element('div');
   const source=element('select'),claim=element('select'),kind=element('select'),verdict=element('select'),description=element('textarea');
   kind.setAttribute('aria-label','Evidence kind');source.setAttribute('aria-label','Source artifact');claim.setAttribute('aria-label','Claim');verdict.setAttribute('aria-label','Evidence verdict');
   for(const a of artifacts){const option=text(element('option'),a.name);option.value=a.id;source.appendChild(option)}
   source.value=(artifacts.find(a=>a.name==='workspace/findings.md')||artifacts[0]).id;
   for(const c of projectClaims){const option=text(element('option'),c.title);option.value=c.id;claim.appendChild(option)}
   for(const value of ['literature','derivation','numerical','note']){const option=text(element('option'),value);option.value=value;kind.appendChild(option)}
   kind.value=paper?'literature':'derivation';
   for(const value of ['unresolved','supporting','challenging']){const option=text(element('option'),value);option.value=value;verdict.appendChild(option)}
   description.placeholder='Explain how this source bears on the selected claim';
   const page=element('input');page.type='number';page.min=1;page.max=paper?.page_count||1;page.value=1;page.setAttribute('aria-label','Source page');
   if(paper){form.append(text(element('span'),'来源页码：'),page)}
   form.append(source,claim,kind,verdict,description,action('Record as evidence',async()=>{
     if(!description.value.trim())throw new Error('Describe the evidence before recording it');
     await post(`/projects/${pid}/evidence`,{claim_id:claim.value,artifact_id:source.value,kind:kind.value,verdict:verdict.value,description:description.value.trim(),provenance:paper?{pages:[Number(page.value)]}:{}});
     description.value='';await refreshEvidence();notify('Evidence recorded; claim status unchanged');
   }));
   return form;
}
function refreshRuns(){
 if(mode!=='investigate'||document.hidden)return Promise.resolve();
 if(runRequest)return runRequest;
 clearTimeout(runTimer);
 const pid=project,epoch=runEpoch;
 const current=()=>epoch===runEpoch&&pid===project&&mode==='investigate'&&!document.hidden;
 runRequest=(async()=>{
   let again=true;
   try{
     const runs=await api(`/projects/${pid}/runs`);
     if(!current())return;
     const parents=new Set(runs.map(r=>r.parent_run_id).filter(Boolean));
     for(const r of [...runs].reverse())if(!runViews.has(r.id)){
       const view=createRunView(r,pid);runViews.set(r.id,view);$('runs').prepend(view.box);
     }
     again=runs.some(activeRun);
     await Promise.all(runs.map(async r=>{
       const view=runViews.get(r.id);view.state=r.state;
       view.header.textContent=r.title+' — '+(runLabels[r.state]||r.state);
       view.relation.textContent=r.runtime_matches?(r.parent_run_id?'继续自任务 '+r.parent_run_id:''):'历史运行环境；请参考归档创建新任务';
       view.output.textContent=r.output;view.output.classList.toggle('hidden',!r.output);
       view.error.textContent=r.error;view.error.classList.toggle('hidden',!r.error);
       view.cancel.classList.toggle('hidden',!activeRun(r));view.cancel.disabled=r.state==='cancelling';
       view.cancel.textContent=r.state==='cancelling'?'正在停止…':'取消任务';
       view.resume.classList.toggle('hidden',!r.runtime_matches||activeRun(r)||!r.thread_id||parents.has(r.id));
       if(!view.eventsDone||activeRun(r)){
         const page=await api(`/runs/${r.id}/events?after=${view.cursor}`);
         if(!current())return;
         for(const event of page.events)if(event.id>view.cursor){
           const entry=element('li');entry.appendChild(text(element('time'),new Date(event.created_at).toLocaleTimeString()));
           entry.appendChild(text(element('pre'),event.message));view.log.appendChild(entry);view.cursor=event.id;
         }
         while(view.log.children.length>200)view.log.firstElementChild.remove();
         view.eventsDone=!activeRun(r)&&!page.has_more;
         if(page.has_more)again=true;
       }
       if(!activeRun(r)&&!view.artifactsLoaded){
         const artifacts=await api(`/runs/${r.id}/artifacts`);
         if(!current())return;
         renderRunArtifacts(view,artifacts,pid);view.artifactsLoaded=true;
       }
     }));
     if(current())$('runConnection').textContent=again?'执行进度自动更新中':'';
   }catch(e){
     if(current())$('runConnection').textContent='暂时无法读取进度，正在重试…';
     throw e;
   }finally{
     if(current()){
       runRequest=null;
       if(again)runTimer=setTimeout(()=>refreshRuns().catch(()=>{}),1000);
     }
   }
 })();
 return runRequest;
}
async function startCodex(){const question=$('codexQuestion').value.trim();if(!question)return;try{const r=await post(`/projects/${project}/runs`,{question});notify('Research queued: '+r.id);$('codexQuestion').value='';stopRunPolling();await refreshRuns()}catch(e){notify(e.message)}}
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
function openModal(title,body){sourceView=null;$('sourceControls').classList.add('hidden');$('modalTitle').textContent=title;$('modalText').textContent=body;$('modalText').classList.remove('hidden');$('modalEditor').classList.add('hidden');$('saveModal').style.display='none';$('copyModal').style.display='block';$('modal').classList.remove('hidden')}
async function openStyle(){const s=await api(`/projects/${project}/style`);openModal('Scientific voice — project style','');$('modalText').classList.add('hidden');$('modalEditor').classList.remove('hidden');$('modalEditor').value=s.style_text;$('saveModal').style.display='block';$('copyModal').style.display='none'}
async function saveStyle(){try{await api(`/projects/${project}/style`,{method:'PUT',body:JSON.stringify({style_text:$('modalEditor').value})});closeModal();notify('Scientific voice saved for this research project')}catch(e){notify(e.message)}}
function closeModal(){$('modal').classList.add('hidden')}

function updatePaperSelection(){
 for(const [id,check] of paperChecks)check.checked=selectedPapers.has(id);
 $('paperSelection').textContent=`已选择 ${selectedPapers.size} 篇 · 选中原文会随问题提供给模型按需读取`;
 $('readSelectedPapers').disabled=!selectedPapers.size;
 $('readSelectedPapers').textContent=selectedPapers.size===2?'对照这两篇':'精读这篇';
}
async function refreshPapers(){
 const pid=project,papers=await api(`/projects/${pid}/papers`);if(pid!==project)return;
 projectPapers=papers;
 for(const id of selectedPapers)if(!papers.some(p=>p.id===id))selectedPapers.delete(id);
 $('papers').replaceChildren();paperChecks.clear();
 for(const paper of papers){
   const card=element('div','paper-card');card.id='paper-'+paper.id;
   const label=element('label'),check=element('input');check.type='checkbox';check.setAttribute('aria-label','选择文献 '+paper.title);paperChecks.set(paper.id,check);
   check.onchange=()=>{if(check.checked){if(selectedPapers.size===2){check.checked=false;return notify('一次选择一篇精读或两篇对照')}selectedPapers.add(paper.id)}else selectedPapers.delete(paper.id);updatePaperSelection()};
   label.append(check,text(element('strong'),paper.title));card.appendChild(label);
   card.appendChild(text(element('p'),`${paper.arxiv_id||'上传 PDF'} · ${paper.page_count} 页 · ${paper.id}`));
   card.appendChild(action('阅读原文',()=>viewArtifact(paper.id)));
   if(projectClaims.length){const details=element('details');details.append(text(element('summary'),'登记为文献证据'),evidenceForm([{id:paper.id,name:paper.title}],pid,paper));card.appendChild(details)}
   else card.appendChild(text(element('p'),'先在右侧保存研究主张，再将相关页登记为证据。'));
   $('papers').appendChild(card);
 }
 updatePaperSelection();
}
async function importPaper(value){
 const pid=project;$('paperStatus').textContent='正在获取原始 PDF 并归档分页文本…';
 try{const paper=await post(`/projects/${pid}/papers`,{arxiv_id:value});if(pid!==project)return;
   if(selectedPapers.size<2)selectedPapers.add(paper.id);await refreshPapers();$('paperSearchPanel').open=false;$('paperStatus').textContent='原文已归档，可选择精读或对照。';
 }catch(e){if(pid===project)$('paperStatus').textContent=e.message}
}
$('openLiterature').onclick=async()=>{try{await switchMode('discuss');$('literaturePanel').open=true;$('paperQuery').focus()}catch(e){notify(e.message)}};
$('searchPapers').onclick=async()=>{
 const pid=project;$('searchPapers').disabled=true;$('paperStatus').textContent='正在搜索 arXiv…';$('paperSearchResults').replaceChildren();$('paperSearchPanel').classList.remove('hidden');$('paperSearchPanel').open=true;
 try{const data=await api(`/projects/${pid}/papers/search?query=${encodeURIComponent($('paperQuery').value.trim())}`);if(pid!==project)return;
   for(const p of data.results){const card=element('div','paper-card');card.append(text(element('strong'),p.title),text(element('p'),`${p.arxiv_id} · ${p.date}`),text(element('p'),p.abstract),action('导入这篇原文',()=>importPaper(p.arxiv_id)));$('paperSearchResults').appendChild(card)}
   $('paperStatus').textContent='搜索仅返回摘要；导入原文后才能精读。';
 }catch(e){if(pid===project)$('paperStatus').textContent=e.message}finally{$('searchPapers').disabled=false}
};
$('importPaper').onclick=()=>importPaper($('arxivId').value.trim());
$('paperPDF').onchange=async()=>{
 const file=$('paperPDF').files[0],pid=project;if(!file)return;
 $('paperStatus').textContent='正在提取 PDF 分页文本…';
 try{if(file.size>8*1024*1024)throw new Error('PDF 最大为 8 MiB');
   const paper=await api(`/projects/${pid}/papers/pdf?title=${encodeURIComponent(file.name.slice(0,200))}`,{method:'POST',headers:{'Content-Type':'application/pdf'},body:await file.arrayBuffer()});
   if(pid!==project)return;if(selectedPapers.size<2)selectedPapers.add(paper.id);await refreshPapers();$('paperStatus').textContent='PDF 原件与分页文本已归档。';
 }catch(e){if(pid===project)$('paperStatus').textContent=e.message}finally{$('paperPDF').value=''}
};
$('readSelectedPapers').onclick=()=>{
 const papers=projectPapers.filter(p=>selectedPapers.has(p.id));if(!papers.length)return;
 const task=papers.length===2?'请对照这两篇论文，围绕共同的物理问题核对定义、约定、假设、方法和结论，指出分歧的来源与尚不能判定之处。':'请精读这篇论文，围绕物理问题、关键定义与假设、推导方法和主要结果展开讨论。';
 $('question').value=task+'必须实际读取相关原文页，并用工具返回的原文页码链接引用。明确已读范围，不能把摘要或局部阅读说成通读全文。\n'+papers.map(p=>`${p.title}（${p.id}）`).join('\n');$('question').focus();
};
$('readSourcePage').onclick=()=>viewArtifact(sourceView.id,Number($('sourcePage').value)).catch(e=>notify(e.message));
$('nextSourceChunk').onclick=()=>viewArtifact(sourceView.id,sourceView.page,sourceView.next_offset).catch(e=>notify(e.message));
$('findSourceText').onclick=async()=>{
 const q=$('sourceQuery').value.trim(),view=sourceView;if(!q||!view)return;
 try{const data=await api(`/projects/${view.pid}/artifacts/${view.id}/text?query=${encodeURIComponent(q)}`);
   if(view!==sourceView||view.pid!==project)return;
   $('modalText').textContent=(data.matches||[]).map(m=>`PDF page ${m.page} · offset ${m.offset}\n${m.excerpt}`).join('\n\n')||'未找到匹配的抽取文本；这不证明原文不存在相关内容。';
 }catch(e){notify(e.message)}
};
$('timeline').addEventListener('click',event=>{
 const link=event.target.closest('a'),match=link?.getAttribute('href')?.match(/^\/api\/artifacts\/(a_\w+)(?:#page=(\d+))?$/);if(!match)return;
 event.preventDefault();viewArtifact(match[1],Number(match[2]||1)).catch(e=>notify(e.message));
});
$('modes').addEventListener('click',e=>{const b=e.target.closest('[data-mode]');if(b)switchMode(b.dataset.mode).catch(err=>notify(err.message))});
$('model').addEventListener('change',()=>{modelSelections[mode]=$('model').value;syncModelState()});
$('projects').addEventListener('change',e=>{project=e.target.value;switchMode(mode).catch(err=>notify(err.message))});
$('newProject').onclick=async()=>{const title=prompt('Title of your research project:');if(!title?.trim())return;const description=prompt('Scientific scope (optional):')||'';try{const p=await post('/projects',{title,description});await reloadProjects(p.id)}catch(e){notify(e.message)}};
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
$('send').onclick=send;$('saveAsClaim').onclick=saveFromComposer;$('addClaim').onclick=saveClaim;$('launchCodex').onclick=startCodex;
$('refreshEvidence').onclick=()=>refreshEvidence().catch(e=>notify(e.message));
$('refreshRuns').onclick=()=>refreshRuns().catch(e=>notify(e.message));
$('docText').addEventListener('input',()=>renderDocumentSources());
document.addEventListener('visibilitychange',()=>{stopRunPolling();if(!document.hidden&&mode==='investigate')refreshRuns().catch(e=>notify(e.message))});
$('openBrief').onclick=async()=>{try{const b=await api(`/projects/${project}/brief`);openModal('Research Brief',b.markdown)}catch(e){notify(e.message)}};
$('seedProject').onclick=async()=>{try{await post('/seed-csk',{});await reloadProjects('csk_seed')}catch(e){notify(e.message)}};
$('saveDocument').onclick=saveDocument;$('editStyle').onclick=()=>openStyle().catch(e=>notify(e.message));$('saveModal').onclick=saveStyle;$('useLastAnswer').onclick=()=>{if(lastAnswer){$('docText').value=lastAnswer;renderDocumentSources();notify('Latest assistant answer copied to manuscript editor')}else notify('Discuss a draft first')};$('documentSelect').onchange=()=>loadDocument().catch(e=>notify(e.message));
$('closeModal').onclick=closeModal;$('modal').onclick=e=>{if(e.target===$('modal'))closeModal()};
$('copyModal').onclick=()=>navigator.clipboard.writeText($('modalText').textContent).then(()=>notify('Copied to clipboard')).catch(e=>notify(e.message));
document.querySelectorAll('.suggestion').forEach(b=>b.onclick=()=>{$('question').value=b.dataset.q;$('question').focus()});
init();
