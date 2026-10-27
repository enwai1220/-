"""Single-user loopback application. Python stdlib only; SQLite is the source of truth."""
import argparse, hashlib, json, os, re, shutil, sqlite3, subprocess, tempfile, threading, uuid, socket, time, tomllib, urllib.request, urllib.error, urllib.parse
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'failure-immunity.sqlite3'
TRIAGE_DB=ROOT/'data'/'task-triage.sqlite3'
PORT=3010
FIELDS=('date','event','category','analysis','engine')
LIMITS={'date':100,'event':8000,'category':20000,'analysis':40000,'engine':100}
AI_LOCK=threading.Lock()
BACKUP_LOCK=threading.Lock()

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def database(path):
    con=sqlite3.connect(path,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA synchronous=FULL')
    try:
        with con:yield con
    finally:con.close()

def connect():return database(DB)
def triage_connect():return database(TRIAGE_DB)

def initialize_triage():
    TRIAGE_DB.parent.mkdir(parents=True,exist_ok=True)
    with triage_connect() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript((ROOT/'backend/triage-schema.sql').read_text(encoding='utf-8-sig'))
        if not con.execute('SELECT 1 FROM task_triage WHERE id=1').fetchone():
            with connect() as old:
                exists=old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_triage'").fetchone()
                row=old.execute('SELECT * FROM task_triage WHERE id=1').fetchone() if exists else None
            if row:
                con.execute('INSERT INTO task_triage(id,input,revision,result,result_input,analyzed_at) VALUES(?,?,?,?,?,?)',tuple(row[k] for k in ('id','input','revision','result','result_input','analyzed_at')))
                con.execute('INSERT OR IGNORE INTO migrations VALUES(?,?)',('legacy-task-triage',now()))
    triage_backup('startup')

def triage_backup(reason):
    folder=TRIAGE_DB.parent/'backups'/'task-triage';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'-'+reason+'.sqlite3')
    with BACKUP_LOCK,triage_connect() as source,closing(sqlite3.connect(target)) as dest:source.backup(dest)
    return target

def initialize():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript((ROOT/'backend'/'schema.sql').read_text(encoding='utf-8-sig'))
    backup('startup')
    initialize_triage()

def backup(reason):
    folder=DB.parent/'backups';folder.mkdir(exist_ok=True)
    target=folder/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'-'+reason+'.sqlite3')
    with BACKUP_LOCK,connect() as source,closing(sqlite3.connect(target)) as dest: source.backup(dest)
    return target

class Problem(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status

def values(data):
    if not isinstance(data,dict):raise Problem('记录格式错误。')
    out={}
    for key in FIELDS:
        val=data.get(key,'')
        if not isinstance(val,str) or len(val)>LIMITS[key]:raise Problem('字段过长或格式错误：'+key)
        out[key]=val
    return out

def identifier(data):
    key=data.get('id')
    if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',key):raise Problem('记录编号错误。')
    if type(data.get('revision')) is not int or data['revision']<0:raise Problem('记录版本错误。')
    return key

def state():
    with connect() as con:rows=[dict(x) for x in con.execute('SELECT * FROM records ORDER BY created_at,rowid')]
    return {'entries':[x for x in rows if x['status']=='draft'],'archived':[x for x in rows if x['status']=='archived']}

def save_record(data):
    key=identifier(data);v=values(data);stamp=now()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone()
        if old:
            if old['status']=='draft' and old['revision']!=data['revision'] and old['date']==v['date'] and old['event']==v['event']:return dict(old)  # Safe retry after lost response.
            if old['status']!='draft' or old['revision']!=data['revision']:raise Problem('这条记录已被其他页面修改或归档。请刷新；当前输入仍有本地备份。',409)
            if old['event']!=v['event']:v.update(category='',analysis='',engine='')
            else:
                # Only the AI endpoint writes new model results; clients may retain existing ones.
                v.update(category=old['category'],analysis=old['analysis'],engine=old['engine'])
            con.execute('UPDATE records SET date=?,event=?,category=?,analysis=?,engine=?,revision=revision+1,updated_at=? WHERE id=?',(*(v[k] for k in FIELDS),stamp,key))
        else:
            if data['revision']!=0:raise Problem('记录不存在，请刷新。',409)
            con.execute('INSERT INTO records(id,date,event,created_at,updated_at) VALUES(?,?,?,?,?)',(key,v['date'],v['event'],stamp,stamp))
        return dict(con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone())

def archive_records(data):
    items=data.get('records')
    if not isinstance(items,list) or len(items)>1000:raise Problem('归档请求错误。')
    stamp=now();seen=set()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for item in items:
            key=identifier(item)
            if key in seen:raise Problem('重复归档编号。')
            seen.add(key)
            old=con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone()
            if not old:raise Problem('记录不存在。',409)
            if old['status']=='archived':continue  # Network retry is safe.
            if old['revision']!=item['revision']:raise Problem('记录已更新，请刷新后归档。',409)
            if not any(old[k].strip() for k in FIELDS[:4]):continue
            con.execute("UPDATE records SET status='archived',revision=revision+1,updated_at=?,archived_at=? WHERE id=?",(stamp,stamp,key))
    backup('archive')
    return state()

def import_legacy(data):
    raw=data.get('snapshot')
    if not isinstance(raw,(dict,list)):raise Problem('旧数据格式错误。')
    drafts=raw if isinstance(raw,list) else raw.get('entries',[])
    archived=[] if isinstance(raw,list) else raw.get('archived',[])
    if not isinstance(drafts,list) or not isinstance(archived,list) or len(drafts)+len(archived)>10000:raise Problem('旧数据行数或格式错误。')
    snapshot=json.dumps(raw,ensure_ascii=False,sort_keys=True)
    digest=hashlib.sha256(snapshot.encode()).hexdigest();stamp=now();count=0
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM imports WHERE digest=?',(digest,)).fetchone():return {'imported':0,'alreadyImported':True,**state()}
        occurrence={}
        for status,rows in [('draft',drafts),('archived',archived)]:
            for row in rows:
                v=values(row)
                if not any(v[k].strip() for k in FIELDS[:4]):continue
                content=json.dumps([status,v],ensure_ascii=False,sort_keys=True)
                occurrence[content]=occurrence.get(content,0)+1
                legacy=hashlib.sha256((content+str(occurrence[content])).encode()).hexdigest()
                cur=con.execute('INSERT OR IGNORE INTO records(id,date,event,category,analysis,engine,status,created_at,updated_at,archived_at,legacy_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),*(v[k] for k in FIELDS),status,stamp,stamp,stamp if status=='archived' else None,legacy))
                count+=cur.rowcount
        con.execute('INSERT INTO imports VALUES(?,?,?)',(digest,stamp,snapshot))
    backup('import')
    return {'imported':count,'alreadyImported':False,**state()}

def local_model_json(prompt, schema, url, config):
    """Use the already configured loopback Responses proxy; credentials stay in memory."""
    auth=json.loads((Path(os.environ['USERPROFILE'])/'.codex/auth.json').read_text(encoding='utf-8-sig'))
    tokens=auth.get('tokens') or {}
    key=auth.get('OPENAI_API_KEY') or tokens.get('access_token')
    if not key:raise Problem('Codex 登录已失效，请重新登录后重试。',503)
    payload={'model':config.get('model','gpt-6.1-sol'),'store':False,'stream':True,
        'input':[{'role':'user','content':[{'type':'input_text','text':prompt}]}],
        'text':{'format':{'type':'json_schema','name':'analysis_result','strict':True,'schema':schema}}}
    headers={'Content-Type':'application/json','Accept':'text/event-stream','Authorization':'Bearer '+key}
    if tokens.get('account_id'):headers['ChatGPT-Account-Id']=tokens['account_id']
    req=urllib.request.Request(url.rstrip('/')+'/responses',data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=headers)
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+180;size=0
    try:
        with client.open(req,timeout=180) as response:
            for raw in response:
                size+=len(raw)
                if time.monotonic()>deadline:raise Problem('AI 分析超时，上次结果已保留，请重试。',504)
                if size>8000000:raise Problem('AI 返回内容过多，请精简任务后重试。',503)
                line=raw.decode('utf-8').strip()
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                if not data or data=='[DONE]':continue
                event=json.loads(data)
                if event.get('type') in ('error','response.failed','response.incomplete'):
                    raise Problem('AI 分析未成功完成，上次结果已保留，请重试。',503)
                if event.get('type')=='response.completed':
                    complete=event.get('response',{})
                    if complete.get('status')!='completed':raise Problem('AI 返回不完整，请重试。',503)
                    content=''.join(part.get('text','') for item in complete.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text')
                    return json.loads(content)
    except urllib.error.HTTPError as error:
        if error.code in (401,403):raise Problem('AI 登录已失效，请重新登录 Codex 后重试。',503)
        raise Problem('AI 服务暂不可用，上次结果已保留，请稍后重试。',503)
    except (TimeoutError,socket.timeout):raise Problem('AI 分析超时，上次结果已保留，请重试。',504)
    raise Problem('AI 没有返回完整结果，请重试。',503)

def model_json(prompt, output_schema):
    if not AI_LOCK.acquire(blocking=False):raise Problem('另一项 AI 分析正在进行，请稍后重试。',429)
    try:
        user=Path(os.environ['USERPROFILE'])
        base=user/'AppData'/'Local'/'OpenAI'/'Codex'/'bin'
        candidates=list(base.glob('*/codex.exe'))
        binary=os.environ.get('FAILURE_AI_CODEX_PATH') or (str(max(candidates,key=lambda x:x.stat().st_mtime)) if candidates else shutil.which('codex'))
        if not binary:raise Problem('未找到 Codex CLI，请检查本机安装。',503)
        config=(user/'.codex'/'config.toml').read_text(encoding='utf-8')
        provider=re.search(r'^model_provider\s*=\s*"([^"]+)"',config,re.M)
        url=None
        if provider:
            block=config.split('[model_providers.'+provider[1]+']')[-1].split('\n[')[0]
            match=re.search(r'base_url\s*=\s*"([^"]+)"',block)
            if match:url=match[1]
        settings=tomllib.loads(config)
        if url and urllib.parse.urlparse(url).hostname in ('127.0.0.1','localhost','::1'):
            return local_model_json(prompt,output_schema,url,settings)
        args=[binary,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','-s','read-only']
        if url:
            for option in ['model_provider="workbench"','model_providers.workbench.name="Workbench"','model_providers.workbench.base_url='+json.dumps(url),'model_providers.workbench.wire_api="responses"','model_providers.workbench.requires_openai_auth=true','model_providers.workbench.supports_websockets=false']:
                args.extend(['-c',option])
        work=ROOT/'data'/'ai-temp';work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as folder:
            folder=Path(folder);output=folder/'result.json';schema=folder/'schema.json'
            schema.write_text(json.dumps(output_schema),encoding='utf-8')
            args.extend(['-C',str(folder),'--output-schema',str(schema),'-o',str(output),'-'])
            proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            try:proc.communicate(prompt.encode('utf-8'),timeout=180)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                proc.wait();raise Problem('AI 分析超时，记录已保留，请重试。',504)
            if proc.returncode!=0:raise Problem('AI 连接失败，请检查网络和 Codex 登录后重试。',503)
            return json.loads(output.read_text(encoding='utf-8'))
    except Problem:raise
    except Exception:raise Problem('AI 暂不可用，请检查 Codex 登录和模型转发服务。',503)
    finally:AI_LOCK.release()

def model(event):
    prompt=(ROOT/'backend'/'analysis-prompt.txt').read_text(encoding='utf-8')+'\n事件素材：'+json.dumps(event,ensure_ascii=False)
    schema={'type':'object','properties':{'category':{'type':'string'},'analysis':{'type':'string'}},'required':['category','analysis'],'additionalProperties':False}
    result=values(model_json(prompt,schema))
    if not result['category'].strip() or not result['analysis'].strip():raise Problem('AI 返回不完整，请重试。',503)
    return result

def analyze(data):
    key=identifier(data)
    with connect() as con:old=con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone()
    if not old or old['status']!='draft' or old['revision']!=data['revision']:raise Problem('记录已更新，请保存后重试。',409)
    if not old['event'].strip():raise Problem('请先填写失败事项。')
    if old['engine']=='ai-v2' and old['category'] and old['analysis']:return dict(old)
    result=model(old['event'])
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        # Date edits are allowed during analysis. Changed events or archive invalidate results.
        current=con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone()
        if not current or current['status']!='draft' or current['event']!=old['event']:raise Problem('事项已修改，旧分析未保存，请重新分析。',409)
        con.execute("UPDATE records SET category=?,analysis=?,engine='ai-v2',revision=revision+1,updated_at=? WHERE id=?",(result['category'],result['analysis'],now(),key))
        return dict(con.execute('SELECT * FROM records WHERE id=?',(key,)).fetchone())

TRIAGE_KEYS=('important_urgent','important_not_urgent','urgent_not_important','neither')
TRIAGE_FIELDS=('importance_reason','urgency_reason','priority_reason','next_action','confirmation')
TRIAGE_SCHEMA={
    'type':'object','properties':{'tasks':{'type':'array','items':{
        'type':'object','properties':{
            'id':{'type':'integer'},'quadrant':{'type':'string','enum':list(TRIAGE_KEYS)},
            'priority':{'type':'integer','minimum':0,'maximum':100},
            **{key:{'type':'string'} for key in TRIAGE_FIELDS},'pending':{'type':'boolean'}
        },'required':['id','quadrant','priority','pending',*TRIAGE_FIELDS],'additionalProperties':False
    }}},'required':['tasks'],'additionalProperties':False
}
TRIAGE_LOCK=threading.Lock()

def triage_input(data):
    if not isinstance(data,dict) or not isinstance(data.get('input'),str):raise Problem('任务输入格式错误。')
    text=data['input']
    tasks=[line.strip() for line in text.splitlines() if line.strip()]
    if len(text)>200000 or len(tasks)>100 or any(len(task)>2000 for task in tasks):
        raise Problem('一次最多分析100件事，每行最多2000字；请精简后重试。')
    if type(data.get('revision')) is not int or data['revision']<0:raise Problem('任务版本错误，请刷新重试。')
    return text,tasks

def triage_state():
    with triage_connect() as con:row=con.execute('SELECT * FROM task_triage WHERE id=1').fetchone()
    if not row:return {'input':'','revision':0,'result':None,'resultInput':'','analyzedAt':None}
    return {'input':row['input'],'revision':row['revision'],
        'result':json.loads(row['result']) if row['result'] else None,
        'resultInput':row['result_input'],'analyzedAt':row['analyzed_at']}

def save_triage(data):
    text,_=triage_input(data)
    with triage_connect() as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT * FROM task_triage WHERE id=1').fetchone()
        if old and old['input']==text:return {'revision':old['revision']}
        revision=old['revision'] if old else 0
        if revision!=data['revision']:raise Problem('任务输入已在其他页面修改。当前草稿仍保留，请刷新并核对。',409)
        con.execute('INSERT INTO task_triage(id,input,revision) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET input=excluded.input,revision=excluded.revision',(text,revision+1))
        return {'revision':revision+1}

def validate_triage(result,tasks):
    if not isinstance(result,dict) or not isinstance(result.get('tasks'),list) or len(result['tasks'])!=len(tasks):
        raise Problem('AI 返回的任务数量不完整，上次结果已保留，请重试。',503)
    seen=set();validated=[]
    for item in result['tasks']:
        if not isinstance(item,dict):raise Problem('AI 返回格式错误，请重试。',503)
        ident=item.get('id');priority=item.get('priority')
        if type(ident) is not int or ident<1 or ident>len(tasks) or ident in seen or item.get('quadrant') not in TRIAGE_KEYS:
            raise Problem('AI 返回重复任务或无效象限，上次结果已保留，请重试。',503)
        if type(priority) is not int or not 0<=priority<=100 or type(item.get('pending')) is not bool:
            raise Problem('AI 返回的优先级格式错误，请重试。',503)
        for key in TRIAGE_FIELDS:
            value=item.get(key)
            if not isinstance(value,str) or len(value)>1000 or (key!='confirmation' and not value.strip()):
                raise Problem('AI 返回的理由或下一步不完整，请重试。',503)
        if item['pending'] and not item['confirmation'].strip():raise Problem('AI 未说明待确认信息，请重试。',503)
        seen.add(ident);validated.append({key:item[key] for key in ['id','quadrant','priority','pending',*TRIAGE_FIELDS]})
        validated[-1]['name']=tasks[ident-1]
    return {'tasks':sorted(validated,key=lambda item:(-item['priority'],item['id']))}

def analyze_triage(data):
    text,tasks=triage_input(data)
    if not TRIAGE_LOCK.acquire(blocking=False):raise Problem('事情梳理正在分析，请等待本轮结束。',429)
    try:
        current=triage_state()
        if current['revision']!=data['revision'] or current['input']!=text:
            raise Problem('输入已修改，请保存当前输入后重新分析。',409)
        if tasks:
            stamp=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat()
            prompt=(ROOT/'backend'/'triage-prompt.txt').read_text(encoding='utf-8')
            prompt+='\n本次北京时间：'+stamp+'\n任务素材：'+json.dumps([{'id':i+1,'name':task} for i,task in enumerate(tasks)],ensure_ascii=False)
            result=validate_triage(model_json(prompt,TRIAGE_SCHEMA),tasks)
        else:result={'tasks':[]}
        stamp=now()
        with triage_connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM task_triage WHERE id=1').fetchone()
            if (row['revision'] if row else 0)!=data['revision'] or (row['input'] if row else '')!=text:
                raise Problem('分析期间输入已修改，旧分析未替换原结果，请重新分析。',409)
            con.execute('INSERT INTO task_triage(id,input,revision,result,result_input,analyzed_at) VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET result=excluded.result,result_input=excluded.result_input,analyzed_at=excluded.analyzed_at',
                (text,data['revision'],json.dumps(result,ensure_ascii=False),text,stamp))
        triage_backup('analysis')
        return {'result':result,'resultInput':text,'analyzedAt':stamp}
    finally:TRIAGE_LOCK.release()


def triage_archives():
    with triage_connect() as con:
        rows=con.execute('SELECT id,archived_at,input,result,result_input,analyzed_at FROM triage_archives ORDER BY archived_at DESC,rowid DESC').fetchall()
    return {'archives':[{'id':r['id'],'archivedAt':r['archived_at'],'input':r['input'],'result':json.loads(r['result']),'resultInput':r['result_input'],'analyzedAt':r['analyzed_at']} for r in rows]}

def archive_triage(data):
    text,tasks=triage_input(data)
    ident=data.get('requestId','')
    if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',ident):raise Problem('归档编号错误。')
    if not TRIAGE_LOCK.acquire(blocking=False):raise Problem('正在分析或归档，请稍候。',429)
    try:
        with triage_connect() as con:
            con.execute('BEGIN IMMEDIATE')
            done=con.execute('SELECT id FROM triage_archives WHERE id=?',(ident,)).fetchone()
            if not done:
                row=con.execute('SELECT * FROM task_triage WHERE id=1').fetchone()
                if not row or row['revision']!=data['revision'] or row['input']!=text:raise Problem('输入已更新，请重新分析后归档。',409)
                if not tasks or not row['result'] or row['result_input']!=text:raise Problem('请先分析当前输入，成功后再归档。',409)
                result=json.loads(row['result'])
                if not result.get('tasks'):raise Problem('没有可归档的任务。')
                con.execute('INSERT INTO triage_archives(id,archived_at,input,result,result_input,analyzed_at) VALUES(?,?,?,?,?,?)',(ident,now(),text,row['result'],row['result_input'],row['analyzed_at']))
                con.execute("UPDATE task_triage SET input='',revision=revision+1,result=NULL,result_input='',analyzed_at=NULL WHERE id=1")
        triage_backup('archive')
        return {'archiveId':ident,**triage_state(),**triage_archives()}
    finally:TRIAGE_LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass  # Never log event text.
    def allowed(self):
        host=self.headers.get('Host','')
        origin=self.headers.get('Origin')
        if host not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):return False
        return not origin or origin in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}','http://127.0.0.1:3000','http://localhost:3000','http://127.0.0.1:3010','http://localhost:3010')
    def send(self,value,status=200,mime='application/json; charset=utf-8'):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        origin=self.headers.get('Origin')
        if origin and self.allowed():self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def do_OPTIONS(self):
        if not self.allowed():self.send({'error':'只允许本机工作台访问。'},403);return
        self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin',''));self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type');self.end_headers()
    def do_GET(self):
        if not self.allowed():self.send({'error':'只允许本机访问。'},403);return
        route=self.path.split('?')[0]
        if route=='/api/health':self.send({'app':'failure-immunity','database':'sqlite','schema':3,'features':['task-triage','triage-archives','separate-triage-database']})
        elif route=='/api/state':self.send(state())
        elif route=='/api/triage/state':self.send(triage_state())
        elif route=='/api/triage/archives':self.send(triage_archives())
        elif route in ('/','/app.js','/style.css','/things','/things/','/triage.js'):
            file={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/things':'things.html','/things/':'things.html','/triage.js':'triage.js'}[route]
            mime='text/javascript' if file.endswith('.js') else 'text/css' if file.endswith('.css') else 'text/html'
            self.send((ROOT/'frontend'/file).read_bytes(),mime=mime+'; charset=utf-8')
        elif route=='/api/export':
            self.send({'format':3,'exportedAt':now(),**state(),'taskTriage':triage_state(),'taskTriageArchives':triage_archives()['archives']})
        else:self.send({'error':'页面不存在。'},404)
    def do_POST(self):
        if not self.allowed():self.send({'error':'只允许本机工作台访问。'},403);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>5000000:raise Problem('请求大小错误。')
            data=json.loads(self.rfile.read(length));routes={'/api/save':save_record,'/api/archive':archive_records,'/api/import':import_legacy,'/api/analyze':analyze,'/api/triage/save':save_triage,'/api/triage/analyze':analyze_triage,'/api/triage/archive':archive_triage}
            if self.path not in routes:raise Problem('接口不存在。',404)
            self.send(routes[self.path](data))
        except Problem as error:self.send({'error':error.message},error.status)
        except (ValueError,TypeError,AttributeError):self.send({'error':'请求格式错误。'},400)
        except Exception:self.send({'error':'数据库操作失败，输入仍保留。请重试或检查磁盘。'},500)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=3010);parser.add_argument('--db');parser.add_argument('--triage-db');args=parser.parse_args()
    PORT=args.port
    if args.db:
        DB=Path(args.db).resolve()
        TRIAGE_DB=DB.with_name(DB.stem+'-triage.sqlite3')
    if args.triage_db:TRIAGE_DB=Path(args.triage_db).resolve()
    initialize();ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
