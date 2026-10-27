import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('triage_application',ROOT/'backend/server.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

def response(tasks,offset=0):
 return {'tasks':[{'id':i+1,'quadrant':app.TRIAGE_KEYS[i%4],'priority':90-i+offset,
  'importance_reason':'影响目标的具体交付','urgency_reason':'截止时间待确认','priority_reason':'先处理更高影响事项',
  'next_action':'列出第一个可交付内容','pending':True,'confirmation':'截止时间是什么？'} for i,_ in enumerate(tasks)]}

class TriageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();app.DB=Path(self.temp.name)/'triage.sqlite3';app.TRIAGE_DB=app.DB.with_name('tasks.sqlite3');app.initialize()
 def tearDown(self):self.temp.cleanup()
 def save(self,text,revision=0):
  data={'input':text,'revision':revision};data['revision']=app.save_triage(data)['revision'];return data
 def analyze(self,data,offset=0):
  tasks=app.triage_input(data)[1]
  with patch.object(app,'model_json',return_value=response(tasks,offset)) as model:
   result=app.analyze_triage(data)
  return result,model
 def test_lines_blank_crlf_and_duplicate_names(self):
  data=self.save('  一件事 \r\n\r\n 二件事 \r\n一件事\n  ')
  result,_=self.analyze(data)
  self.assertEqual([x['name'] for x in result['result']['tasks']],['一件事','二件事','一件事'])
  self.assertEqual(len({x['id'] for x in result['result']['tasks']}),3)
 def test_reanalysis_always_calls_model_and_replaces(self):
  data=self.save('甲\n乙\n丙\n丁');first,_=self.analyze(data)
  again,model=self.analyze(data,1);self.assertEqual(model.call_count,1)
  self.assertNotEqual(first['result'],again['result'])
  current=self.save('新任务',data['revision']);final,_=self.analyze(current)
  state=app.triage_state();self.assertEqual(len(state['result']['tasks']),1)
  self.assertEqual(state['resultInput'],'新任务');self.assertEqual(final['result'],state['result'])
 def test_failure_keeps_input_and_last_success(self):
  data=self.save('旧任务');self.analyze(data);old=app.triage_state()
  current=self.save('修改后的任务',data['revision'])
  with patch.object(app,'model_json',side_effect=app.Problem('AI失败',503)):
   with self.assertRaises(app.Problem):app.analyze_triage(current)
  state=app.triage_state();self.assertEqual(state['input'],'修改后的任务')
  self.assertEqual(state['result'],old['result']);self.assertEqual(state['analyzedAt'],old['analyzedAt'])
 def test_partial_duplicate_and_invalid_quadrant_rejected(self):
  data=self.save('甲\n乙');self.analyze(data);old=app.triage_state()
  for kind in ('partial','duplicate','quadrant','no_reason'):
   bad=response(['甲','乙'])
   if kind=='partial':bad['tasks'].pop()
   if kind=='duplicate':bad['tasks'][1]['id']=1
   if kind=='quadrant':bad['tasks'][1]['quadrant']='other'
   if kind=='no_reason':bad['tasks'][1]['next_action']=''
   with patch.object(app,'model_json',return_value=bad):
    with self.assertRaises(app.Problem):app.analyze_triage(data)
   self.assertEqual(app.triage_state()['result'],old['result'])
 def test_edits_during_analysis_do_not_replace_results(self):
  data=self.save('旧任务');self.analyze(data);old=app.triage_state()
  def model(*args):self.save('分析期间编辑',data['revision']);return response(['旧任务'])
  with patch.object(app,'model_json',side_effect=model):
   with self.assertRaises(app.Problem):app.analyze_triage(data)
  self.assertEqual(app.triage_state()['result'],old['result'])
  self.assertEqual(app.triage_state()['input'],'分析期间编辑')
 def test_save_conflict_and_safe_retry(self):
  data=self.save('甲');self.assertEqual(app.save_triage({'input':'甲','revision':0})['revision'],data['revision'])
  with self.assertRaises(app.Problem):self.save('乙',0)
 def test_empty_analysis_clears_both_displays_without_ai(self):
  data=self.save('甲');self.analyze(data);empty=self.save('\n \n',data['revision'])
  result,model=self.analyze(empty);model.assert_not_called()
  self.assertEqual(result['result']['tasks'],[]);self.assertEqual(app.triage_state()['input'],'\n \n')
 def test_backup_and_restart_recover_input_and_result(self):
  data=self.save('待确认事项\n第二件事');self.analyze(data)
  expected=app.triage_state();saved=app.triage_backup('triage-test');app.TRIAGE_DB=saved;app.initialize()
  self.assertEqual(app.triage_state(),expected)
 def test_duplicate_click_rejected(self):
  data=self.save('甲');app.TRIAGE_LOCK.acquire()
  try:
   with self.assertRaises(app.Problem) as error:app.analyze_triage(data)
   self.assertEqual(error.exception.status,429)
  finally:app.TRIAGE_LOCK.release()
 def test_task_result_does_not_change_existing_records(self):
  row=app.save_record({'id':'old','revision':0,'date':'2026-10-27','event':'原记录'})
  app.archive_records({'records':[row]});before=app.state();data=self.save('甲');self.analyze(data)
  self.assertEqual(before,app.state())

 def test_archive_atomic_clear_and_idempotent_retry(self):
  data=self.save('第一批甲\n第一批乙');self.analyze(data);expected=app.triage_state()
  req={**data,'requestId':'batch-one'};saved=app.archive_triage(req)
  self.assertEqual(saved['input'],'');self.assertIsNone(saved['result'])
  self.assertEqual(saved['revision'],data['revision']+1)
  self.assertEqual(saved['archives'][0]['result'],expected['result'])
  self.assertEqual(saved['archives'][0]['input'],expected['input'])
  second=self.save('第二批',saved['revision']);self.analyze(second)
  retry=app.archive_triage(req)
  self.assertEqual(len(retry['archives']),1);self.assertEqual(retry['input'],'第二批')
  app.archive_triage({**second,'requestId':'batch-two'})
  self.assertEqual(len(app.triage_archives()['archives']),2)
  app.initialize();self.assertEqual(len(app.triage_archives()['archives']),2)
 def test_archive_requires_current_successful_analysis(self):
  data=self.save('甲')
  with self.assertRaises(app.Problem):app.archive_triage({**data,'requestId':'one'})
  self.analyze(data);changed=self.save('乙',data['revision'])
  with self.assertRaises(app.Problem):app.archive_triage({**changed,'requestId':'one'})
  self.assertEqual(app.triage_state()['input'],'乙');self.assertEqual(app.triage_archives()['archives'],[])
 def test_storage_is_separate(self):
  data=self.save('甲');self.analyze(data);app.archive_triage({**data,'requestId':'one'})
  with app.connect() as con:
   self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='task_triage'").fetchone())
   self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='triage_archives'").fetchone())
  self.assertNotEqual(app.DB,app.TRIAGE_DB)
 def test_legacy_migration_preserves_fields_and_does_not_repeat(self):
  data=self.save('旧任务');self.analyze(data);before=app.triage_state()
  with app.triage_connect() as source:
   row=source.execute('SELECT * FROM task_triage').fetchone()
  with app.connect() as con:
   con.execute("CREATE TABLE task_triage (id INTEGER PRIMARY KEY,input TEXT,revision INTEGER,result TEXT,result_input TEXT,analyzed_at TEXT)")
   con.execute('INSERT INTO task_triage VALUES(?,?,?,?,?,?)',tuple(row))
  app.TRIAGE_DB=app.DB.with_name('migrated.sqlite3');app.initialize()
  self.assertEqual(app.triage_state(),before)
  changed=self.save('迁移后修改',before['revision']);app.initialize()
  self.assertEqual(app.triage_state()['input'],'迁移后修改')
  with app.connect() as con:self.assertEqual(con.execute('SELECT input FROM task_triage').fetchone()[0],'旧任务')

if __name__=='__main__':unittest.main()
