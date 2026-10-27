'use strict';
(() => {
 const $ = id => document.getElementById(id);
 const domain=new URLSearchParams(location.search).get('domain')==='life'?'life':'work';
 const CACHE = domain==='work'?'failure-immunity-triage-v1':'failure-immunity-triage-life-v1';
 const domainName=domain==='life'?'生活':'工作';
 document.title=domainName+'事情梳理 · 失败免疫练习';
 $('input-title').textContent=domainName+'任务输入';
 $('domain-description').textContent=domainName+'事项独立保存、分析与归档，切换板块不会混合数据。';
 $('domain-'+domain).setAttribute('aria-pressed','true');
 $('domain-'+(domain==='work'?'life':'work')).setAttribute('aria-pressed','false');
 if(domain==='life')$('task-input').placeholder='例如：\n明天预约复查，医生要求本周完成\n每周安排两次运动，改善长期健康\n今晚前确认家庭聚餐人数\n有空整理相册';
 if(window.top!==window.self){document.querySelectorAll('.tabs a').forEach(link=>{link.href='http://127.0.0.1:3010/'+(link.getAttribute('aria-current')==='page'?'?page=things':'');link.target='_top';});}
 const groups = [
  {key:'important_urgent',name:'重要且紧急',action:'优先处理',number:'01'},
  {key:'important_not_urgent',name:'重要不紧急',action:'安排时间推进',number:'02'},
  {key:'urgent_not_important',name:'紧急不重要',action:'考虑委托或简化处理',number:'03'},
  {key:'neither',name:'不重要不紧急',action:'考虑暂缓或取消',number:'04'}
 ];
 let revision=0, savedInput='', result=null, resultInput='', analyzedAt=null;
 let ready=false, busy=false, saving=null, timer=null, cacheOK=true, conflict=false;
 let archives=[], pendingArchive=null;
 const input=$('task-input');
 const lines=text=>text.split(/\r\n|[\n\r\u0085\u2028\u2029\v\f\x1c-\x1e]/).map(line=>line.trim()).filter(Boolean);
 function node(tag, className, text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
 function message(text, error=false){$('analysis-message').textContent=text;$('analysis-message').classList.toggle('error',error);}
 function cache(){
  try{localStorage.setItem(CACHE,JSON.stringify({input:input.value,revision,savedInput,result,resultInput,analyzedAt,pendingArchive}));cacheOK=true;}
  catch{cacheOK=false;$('save-status').textContent='浏览器暂存不可用，请等待数据库保存完成。';}
 }
 function updateInput(){
  $('input-count').textContent=lines(input.value).length+' 件事';
  $('result-stale').hidden=!result||input.value===resultInput;
  $('archive').disabled=!ready||busy||!result?.tasks?.length||input.value!==resultInput||input.value!==savedInput;
 }
 async function request(route,data){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),route.endsWith('/analyze')?200000:20000);
  try{
   const response=await fetch(route+'?domain='+domain,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),signal:controller.signal});
   const value=await response.json();
   if(!response.ok){const error=Error(value.error||'请求失败，请重试。');error.status=response.status;throw error;}
   return value;
  }catch(error){if(error.name==='AbortError')throw Error('请求超时，请重试。');throw error;}
  finally{clearTimeout(timeout);}
 }
 async function flush(){
  if(!ready)throw Error('尚未连接本机数据库，请重新连接。');
  if(conflict)throw Error('输入存在其他页面的修改，请刷新并核对草稿。');
  if(saving){await saving;if(input.value!==savedInput)return flush();return;}
  saving=(async()=>{
   while(input.value!==savedInput){
    const snapshot=input.value;
    try{
     const data=await request('/api/triage/save',{input:snapshot,revision});
     revision=data.revision;savedInput=snapshot;cache();updateInput();
    }catch(error){if(error.status===409)conflict=true;throw error;}
   }
   $('save-status').textContent='已保存到本机数据库';
  })();
  try{await saving;}finally{saving=null;}
 }
 function schedule(){
  pendingArchive=null;cache();updateInput();clearTimeout(timer);
  $('save-status').textContent=ready?'正在保存输入…':'输入已暂存在当前浏览器';
  if(ready)timer=setTimeout(()=>flush().catch(error=>{$('save-status').textContent=error.message+' 输入已在浏览器保留。';}),350);
 }
 function detail(label,text){const p=node('p','task-detail');p.append(node('strong','',label+' '),document.createTextNode(text));return p;}
 function taskCard(task,group,index,top){
  const item=node(top?'li':'article',top?'top-task':'quadrant-task');
  item.dataset.taskId=String(task.id);
  const heading=node('div','task-heading');
  if(top)heading.append(node('span','rank',String(index+1).padStart(2,'0')));
  heading.append(node('h4','',task.name));item.append(heading);
  const labels=node('div','task-labels');
  if(top)labels.append(node('span','tag',group.name));
  if(task.pending)labels.append(node('span','tag pending','待确认'));
  if(labels.childNodes.length)item.append(labels);
  if(top){item.append(detail('优先原因',task.priority_reason),detail('下一步',task.next_action));}
  else{item.append(detail('重要性',task.importance_reason),detail('紧急性',task.urgency_reason));}
  if(task.pending&&task.confirmation)item.append(detail('待确认',task.confirmation));
  return item;
 }
 function render(){
  $('top-groups').replaceChildren();$('quadrant-groups').replaceChildren();
  const tasks=result?.tasks||[];
  for(const group of groups){
   const items=tasks.filter(task=>task.quadrant===group.key).sort((a,b)=>b.priority-a.priority||a.id-b.id);
   const top=node('section','top-group');top.dataset.quadrant=group.key;
   const head=node('div','group-heading');head.append(node('h3','',group.name),node('span','meta',Math.min(items.length,3)+' 件'));top.append(head);
   const list=node('ol','top-list');items.slice(0,3).forEach((task,index)=>list.append(taskCard(task,group,index,true)));top.append(list);
   if(!items.length)top.append(node('p','empty',result?'暂无此类任务':'分析后展示优先事项'));
   $('top-groups').append(top);
   const quadrant=node('section','quadrant');quadrant.dataset.quadrant=group.key;
   const title=node('div','group-heading');title.append(node('h3','',group.number+'  '+group.name),node('span','count',items.length+' 件'));quadrant.append(title,node('p','quadrant-action',group.action));
   items.forEach((task,index)=>quadrant.append(taskCard(task,group,index,false)));
   if(!items.length)quadrant.append(node('p','empty',result?'暂无此类任务':'等待分析'));
   $('quadrant-groups').append(quadrant);
  }
  const stamp=analyzedAt?new Date(analyzedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'';
  $('result-summary').textContent=result?'最近成功分析：'+stamp+'（北京时间） · 共 '+tasks.length+' 件事':'还没有分析结果';
  updateInput();
 }
 let switching=false;
 function setDomainButtons(disabled){$('domain-work').disabled=disabled;$('domain-life').disabled=disabled;}
 async function switchDomain(next){
  if(next===domain||busy||switching)return;
  switching=true;setDomainButtons(true);clearTimeout(timer);cache();
  try{if(!ready)throw Error('请先重新连接并保存输入。');await flush();const url=new URL(location.href);url.searchParams.set('domain',next);location.assign(url.href);}
  catch(error){message('切换失败：'+error.message+' 当前输入已保留。',true);switching=false;setDomainButtons(busy);}
 }
 $('domain-work').addEventListener('click',()=>switchDomain('work'));
 $('domain-life').addEventListener('click',()=>switchDomain('life'));
 input.addEventListener('input',schedule);
 $('analyze').addEventListener('click',async()=>{
  if(busy||!ready)return;
  busy=true;setDomainButtons(true);updateInput();$('analyze').disabled=true;$('analyze').textContent='分析中…';$('analysis-results').setAttribute('aria-busy','true');
  message('正在统一分析全部任务，请稍候。你仍可以修改输入。');clearTimeout(timer);
  try{
   await flush();const snapshot=input.value;const currentRevision=revision;
   const data=await request('/api/triage/analyze',{input:snapshot,revision:currentRevision});
   if(!data.result||!Array.isArray(data.result.tasks))throw Error('分析结果格式异常，请重试。');
   result=data.result;resultInput=data.resultInput;analyzedAt=data.analyzedAt;cache();render();
   message(input.value===snapshot?'分析完成，TOP 3 和四象限已同步更新。':'本轮分析已保存；输入在分析期间有修改，请再次分析以更新结果。');
  }catch(error){message('分析失败：'+error.message+' 输入和上次成功结果已保留，点击「分析」重试。',true);}
  finally{busy=false;setDomainButtons(false);$('analyze').disabled=!ready;$('analyze').textContent='分析';$('analysis-results').setAttribute('aria-busy','false');updateInput();}
 });

 function renderArchives(){
  $('archive-count').textContent=archives.length+' 批';$('archive-list').replaceChildren();
  if(!archives.length){$('archive-list').append(node('p','empty','还没有归档。分析成功后，点击「归档」保存这一批事情。'));return;}
  for(const archive of archives){
   const box=node('details','archive-batch');box.dataset.archiveId=archive.id;
   const stamp=new Date(archive.archivedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
   box.append(node('summary','',stamp+' · '+archive.result.tasks.length+' 件事'));
   const body=node('div','archive-body');
   body.append(node('p','note','分析时间：'+new Date(archive.analyzedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）'));
   for(const group of groups){
    const tasks=archive.result.tasks.filter(task=>task.quadrant===group.key).sort((a,b)=>b.priority-a.priority||a.id-b.id);
    const part=node('section','archived-quadrant');part.append(node('h3','',group.name+' · '+tasks.length+' 件'));
    tasks.forEach((task,index)=>{const card=taskCard(task,group,index,index<3);if(index<3)card.append(detail('重要性',task.importance_reason),detail('紧急性',task.urgency_reason));else card.append(detail('下一步',task.next_action));part.append(card);});
    if(!tasks.length)part.append(node('p','empty','暂无此类任务'));
    body.append(part);
   }
   box.append(body);$('archive-list').append(box);
  }
 }
 async function loadArchives(){archives=(await request('/api/triage/archives')).archives;renderArchives();}
 $('archive').addEventListener('click',async()=>{
  if(busy||!ready)return;
  busy=true;setDomainButtons(true);input.disabled=true;$('analyze').disabled=true;$('archive').textContent='归档中…';updateInput();clearTimeout(timer);
  message('正在将本批任务及分析结果写入归档…');
  try{
   await flush();pendingArchive=pendingArchive||crypto.randomUUID();cache();
   const data=await request('/api/triage/archive',{input:input.value,revision,requestId:pendingArchive});
   revision=data.revision;savedInput=data.input;input.value=data.input;result=data.result;resultInput=data.resultInput;analyzedAt=data.analyzedAt;
   archives=data.archives;pendingArchive=null;cache();render();renderArchives();
   $('save-status').textContent='本批已归档到独立数据库，可以输入新的事情';
   message('归档成功，输入区已清空。历史归档中可随时查看本批结果。');
  }catch(error){message('归档未确认：'+error.message+' 当前内容已保留，请重试；重复提交不会重复归档。',true);}
  finally{busy=false;setDomainButtons(false);input.disabled=false;$('analyze').disabled=!ready;$('archive').textContent='归档';updateInput();}
 });
 async function init(){
  ready=false;updateInput();$('analyze').disabled=true;$('reconnect').hidden=true;
  let local=null;
  try{
   local=JSON.parse(localStorage.getItem(CACHE)||'null');
   if(local&&typeof local.input==='string'){
    input.value=local.input;savedInput=typeof local.savedInput==='string'?local.savedInput:'';
    revision=Number.isInteger(local.revision)?local.revision:0;pendingArchive=local.pendingArchive||null;
    if(local.result&&Array.isArray(local.result.tasks)){result=local.result;resultInput=local.resultInput||'';analyzedAt=local.analyzedAt;}
   }
  }catch{local=null;}
  render();
  try{
   const data=await request('/api/triage/state');
   const unsaved=local&&local.input!==local.savedInput;
   const typed=input.value!==String(local?.input||'');
   const draft=input.value;
   revision=data.revision;savedInput=data.input;result=data.result;resultInput=data.resultInput;analyzedAt=data.analyzedAt;
   if((unsaved||typed)&&draft!==data.input){
    if(typed||local.savedInput===data.input||local.revision===data.revision)input.value=draft;
    else{$('draft-conflict').hidden=false;$('conflict-text').textContent=draft;input.value=data.input;}
   }else input.value=data.input;
   ready=true;conflict=false;$('analyze').disabled=busy;$('save-status').textContent='已恢复本机保存的输入与最近结果';
   render();cache();if(input.value!==savedInput)await flush();
   await loadArchives();
  }catch(error){
   $('save-status').textContent='连接失败：'+error.message+' 浏览器暂存内容仍保留。';$('reconnect').hidden=false;
  }
 }
 $('reconnect').addEventListener('click',init);
 window.addEventListener('beforeunload',event=>{cache();if(!cacheOK&&input.value!==savedInput){event.preventDefault();event.returnValue='';}});
 window.addEventListener('online',()=>{if(!ready)init();else if(input.value!==savedInput)flush().catch(error=>{$('save-status').textContent=error.message;});});
 setInterval(()=>{if(ready&&!conflict&&input.value!==savedInput&&!saving)flush().catch(error=>{$('save-status').textContent=error.message+' 输入已在浏览器保留。';});},10000);
 init();
})();
