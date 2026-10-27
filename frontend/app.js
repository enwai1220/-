(() => {
'use strict';

if (new URLSearchParams(location.search).get('page')==='things' || location.pathname==='/things') {
 document.title='事情梳理 · 失败免疫练习';
 const message=document.createElement('p');message.textContent='正在打开事情梳理…';message.setAttribute('role','status');message.style.cssText='padding:28px;font:14px Microsoft YaHei,sans-serif';
 document.body.replaceChildren(message);document.body.style.cssText='padding:0;max-width:none;margin:0';
 async function check(url) {
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5000);
  try {const response=await fetch(url+'/api/health',{signal:controller.signal});if(!response.ok)throw Error();const health=await response.json();return health.app==='failure-immunity'&&health.features?.includes('work-life-triage');}
  finally{clearTimeout(timer);}
 }
 (async()=>{
  let origin=location.origin;
  if(!await check(origin)) {origin='http://127.0.0.1:3012';if(!await check(origin))throw Error();}
  const frame=document.createElement('iframe');frame.title='事情梳理';frame.src=origin+'/things';frame.style.cssText='display:block;width:100%;height:100dvh;min-height:100vh;border:0';
  frame.addEventListener('load',()=>message.remove());document.body.append(frame);
 })().catch(()=>{message.textContent='暂时无法连接事情梳理，请从固定入口重新打开。';});
 return;
}
'use strict';
const API=location.port==='3000'?'http://127.0.0.1:3010':'';
if(API)document.querySelectorAll('.tabs a').forEach(link=>link.href=API+link.getAttribute('href'));
const OLD='teacher-failure-immunity-v1',LOCAL='failure-immunity-pending-v3';
const fields=['date','event','category','analysis'];
const blank=()=>({id:crypto.randomUUID(),revision:0,date:'',event:'',category:'',analysis:'',engine:''});
const hasData=r=>fields.some(k=>(r[k]||'').trim());
let entries=[],archived=[],dirty=new Set(),saving=null,timer=null,pending=0,ready=false;
const $=id=>document.getElementById(id),status=text=>$('status').textContent=text;
$('archive').disabled=true;$('export').href=API+'/api/export';
async function request(route,data){
 const response=await fetch(API+route,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});
 const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败，请重试。');return result;
}
function ensureRows(){while(entries.length<3)entries.push(blank());if(hasData(entries.at(-1)))entries.push(blank());}
function localBackup(){try{localStorage.setItem(LOCAL,JSON.stringify(entries.filter(r=>dirty.has(r.id))))}catch{status('浏览器暂存不可用，请等待数据库保存完成后离开。')}}
function schedule(){localBackup();status('正在保存到数据库…');clearTimeout(timer);timer=setTimeout(()=>flush().catch(e=>status(e.message+' 未保存输入仍保留，请勿关闭页面。')),350);}
async function flush(){
 if(saving){await saving;if(dirty.size)return flush();return;}
 saving=(async()=>{
  for(const id of [...dirty]){
   const row=entries.find(r=>r.id===id);if(!row){dirty.delete(id);continue;}
   const snapshot={...row};
   const saved=await request('/api/save',snapshot);
   row.revision=saved.revision;
   if(row.event===snapshot.event){row.category=saved.category;row.analysis=saved.analysis;row.engine=saved.engine;}
   if(row.date===snapshot.date&&row.event===snapshot.event)dirty.delete(id);
   localBackup();
  }
 })();
 try{await saving;}finally{saving=null;}
 if(dirty.size)return flush();
 status('已保存到本机数据库');
}
function renderArchive(){
 $('archived-rows').replaceChildren();$('archive-section').hidden=!archived.length;$('summary').textContent='（'+archived.length+' 条）';
 archived.forEach(row=>{const tr=document.createElement('tr');fields.forEach(k=>{const td=document.createElement('td');td.textContent=row[k]||'—';tr.append(td)});$('archived-rows').append(tr)});
}
function append(row,index){
 const tr=document.createElement('tr');
 fields.forEach(k=>{
  const td=document.createElement('td');
  if(k==='date'||k==='event'){
   const input=document.createElement(k==='date'?'input':'textarea');input.value=row[k];input.setAttribute('aria-label',(k==='date'?'日期':'失败事项')+' 第'+(index+1)+'行');input.placeholder=k==='date'?'如 2026-10-09':'发生了什么？为什么失败？是否擅长、感兴趣？';input.maxLength=k==='date'?100:8000;
   input.addEventListener('input',()=>{row[k]=input.value;if(k==='event'){row.category='';row.analysis='';row.engine='';tr.querySelectorAll('.result').forEach(x=>x.textContent='')};dirty.add(row.id);if(index===entries.length-1&&hasData(row)){entries.push(blank());append(entries.at(-1),entries.length-1)}schedule()});td.append(input);
  }else{
   const button=document.createElement('button');button.type='button';button.textContent=k==='category'?'自动分析':'成长机会分析';const result=document.createElement('p');result.className='result';result.setAttribute('aria-live','polite');result.textContent=row[k];
   button.addEventListener('click',async()=>{
    if(!row.event.trim()){result.textContent='请先填写失败事项。';return;}
    if(row.engine==='ai-v2'&&row[k]){result.textContent=row[k];return;}
    pending++;$('archive').disabled=true;const controls=tr.querySelectorAll('button,input,textarea');controls.forEach(x=>x.disabled=true);
    result.textContent='AI 正在分析，请稍候…';
    try{
     dirty.add(row.id);await flush();const analyzed=await request('/api/analyze',{id:row.id,revision:row.revision});Object.assign(row,analyzed);
     const results=tr.querySelectorAll('.result');results[0].textContent=row.category;results[1].textContent=row.analysis;localBackup();status('AI 分析已保存到本机数据库');
    }catch(e){result.textContent=e.message;}
    finally{pending--;controls.forEach(x=>x.disabled=false);$('archive').disabled=!ready||pending>0;}
   });td.append(button,result);
  }tr.append(td);
 });$('rows').append(tr);
}
function render(){ensureRows();$('rows').replaceChildren();entries.forEach(append);renderArchive();}
$('archive').addEventListener('click',async()=>{
 if(pending)return;
 $('archive').disabled=true;
 try{
  const filled=entries.filter(hasData);if(!filled.length){status('没有可归档的记录。');return;}
  filled.forEach(r=>{if(!r.revision)dirty.add(r.id)});await flush();
  const data=await request('/api/archive',{records:filled.map(r=>({id:r.id,revision:r.revision}))});entries=data.entries;archived=data.archived;dirty.clear();localBackup();render();status('已归档 '+filled.length+' 条记录，完整数据已写入数据库。');
 }catch(e){status(e.message+' 输入未清空。');}finally{$('archive').disabled=!ready||pending>0;}
});
window.addEventListener('beforeunload',e=>{if(dirty.size){localBackup();e.preventDefault();e.returnValue=''}});
window.addEventListener('online',()=>{if(dirty.size)flush().catch(e=>status(e.message))});
setInterval(()=>{if(dirty.size&&!saving)flush().catch(e=>status(e.message+' 当前输入已暂存，等待重试。'))},10000);
async function init(){
 try{
  const old=localStorage.getItem(OLD);
  if(old){
   const snapshot=JSON.parse(old);const result=await request('/api/import',{snapshot});
   localStorage.setItem('failure-immunity-legacy-backed-up',old); // Keep original as well.
   status('旧数据迁移成功；新迁入 '+result.imported+' 条，原始记录已保留备份。');
  }
  const data=await request('/api/state');entries=data.entries;archived=data.archived;
  const recovery=JSON.parse(localStorage.getItem(LOCAL)||'[]');const conflicts=[];
  for(const local of recovery){
   const row=entries.find(r=>r.id===local.id),history=archived.find(r=>r.id===local.id);
   if(history){conflicts.push(local);continue;}
   if(!row||row.revision===local.revision){if(row)Object.assign(row,local);else entries.push(local);dirty.add(local.id)}else if(row.date!==local.date||row.event!==local.event)conflicts.push(local);
  }
  if(conflicts.length){$('recovery').hidden=false;$('recovery').textContent='发现其他页面更新后的未保存草稿，未覆盖数据库。请先复制以下内容后刷新：\n'+JSON.stringify(conflicts,null,2);localStorage.setItem(LOCAL+'-conflicts',JSON.stringify(conflicts));}
  ready=true;render();$('archive').disabled=false;
  if(dirty.size)await flush();else status('已连接本机数据库 · 已归档 '+archived.length+' 条');
 }catch(e){status('无法读取数据库：'+e.message+' 原数据未删除。请从桌面“失败免疫练习”启动后刷新。');}
}
init();

})();
