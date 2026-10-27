import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('application',ROOT/'backend/server.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
class StorageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=Path(self.tmp.name)/'test.sqlite3';app.TRIAGE_DB=app.DB.with_name('tasks.sqlite3');app.initialize()
 def tearDown(self):self.tmp.cleanup()
 def row(self,id='test'):
  return {'id':id,'revision':0,'date':'20261009','event':'样例','category':'','analysis':'','engine':''}
 def test_migration_idempotence_preserves_duplicates_and_full_fields(self):
  r={'date':'20261009','event':'海报','category':'外部设备','analysis':'备用打印','engine':'ai-v2'}
  data={'snapshot':{'entries':[{},{}],'archived':[r,r]}}
  self.assertEqual(app.import_legacy(data)['imported'],2)
  self.assertEqual(app.import_legacy(data)['imported'],0)
  self.assertEqual(len(app.state()['archived']),2)
  self.assertEqual(app.state()['archived'][0]['analysis'],'备用打印')
 def test_edit_and_optimistic_conflict(self):
  r=app.save_record(self.row());self.assertEqual(r['revision'],1)
  self.assertEqual(app.save_record(self.row())['revision'],1)
  stale=self.row();stale['event']='冲突内容'
  with self.assertRaises(app.Problem):app.save_record(stale)
  r['event']='新事项';updated=app.save_record(r);self.assertEqual(updated['revision'],2)
 def test_archive_atomic_and_retry(self):
  a=app.save_record(self.row('a'));b=app.save_record(self.row('b'))
  b['revision']=99
  with self.assertRaises(app.Problem):app.archive_records({'records':[a,b]})
  self.assertEqual(len(app.state()['entries']),2)
  b['revision']=1;request={'records':[a,b]};app.archive_records(request);app.archive_records(request)
  self.assertEqual(len(app.state()['archived']),2)
 def test_analysis_save_and_edit_invalidation(self):
  r=app.save_record(self.row());original=app.model
  try:
   app.model=lambda event:{'category':'低级错误','analysis':'先核对'}
   analyzed=app.analyze(r);self.assertEqual(analyzed['engine'],'ai-v2')
   analyzed['date']='20261010';dated=app.save_record(analyzed);self.assertEqual(dated['analysis'],'先核对')
   dated['event']='另一个事件';edited=app.save_record(dated);self.assertEqual(edited['analysis'],'')
  finally:app.model=original
 def test_stale_analysis_discarded(self):
  r=app.save_record(self.row());original=app.model
  def model(event):
   update=dict(r);update['event']='修改后的事件';app.save_record(update);return {'category':'旧分类','analysis':'旧结果'}
  try:
   app.model=model
   with self.assertRaises(app.Problem):app.analyze(r)
   self.assertEqual(app.state()['entries'][0]['analysis'],'')
  finally:app.model=original
 def test_persistence_backup(self):
  app.save_record(self.row());copy=app.backup('test');old=app.DB;app.DB=copy
  self.assertEqual(app.state()['entries'][0]['event'],'样例');app.DB=old
if __name__=='__main__':unittest.main()
