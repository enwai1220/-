import test_triage as shared
app=shared.app
from unittest.mock import patch
import unittest

class DomainTests(unittest.TestCase):
 setUp=shared.TriageTests.setUp
 tearDown=shared.TriageTests.tearDown
 save=shared.TriageTests.save
 analyze=shared.TriageTests.analyze
 def test_domain_isolation_reanalysis_archive_restart(self):
  work=self.save('工作交付');self.analyze(work);before=app.triage_state()
  with app.triage_domain('life'):
   self.assertEqual(app.triage_state()['input'],'')
   life=self.save('每周运动\n陪家人');self.analyze(life)
   updated=self.save('预约复查',life['revision']);self.analyze(updated)
   self.assertEqual(len(app.triage_state()['result']['tasks']),1)
   archived=app.archive_triage({**updated,'requestId':'life-batch'})
   self.assertEqual(len(archived['archives']),1)
   self.assertEqual(app.archive_triage({**updated,'requestId':'life-batch'}),archived)
   self.save('下批生活任务',archived['revision'])
  self.assertEqual(app.triage_state(),before)
  self.assertEqual(app.triage_archives()['archives'],[])
  app.initialize()
  with app.triage_domain('life'):
   self.assertEqual(app.triage_state()['input'],'下批生活任务')
   self.assertEqual(len(app.triage_archives()['archives']),1)
  self.assertEqual(app.triage_state(),before)
 def test_life_prompt_and_failure_keeps_last_result(self):
  with app.triage_domain('life'):
   data=self.save('安排运动')
   _,model=self.analyze(data)
   self.assertIn('当前板块：生活',model.call_args.args[0])
   before=app.triage_state()
   with patch.object(app,'model_json',side_effect=app.Problem('fail',503)):
    with self.assertRaises(app.Problem):app.analyze_triage(data)
   self.assertEqual(app.triage_state(),before)
 def test_context_restored_and_invalid_rejected(self):
  with self.assertRaises(app.Problem):
   with app.triage_domain('other'):pass
  self.assertEqual(app.DOMAIN.get(),'work')
  with self.assertRaises(RuntimeError):
   with app.triage_domain('life'):raise RuntimeError()
  self.assertEqual(app.DOMAIN.get(),'work')

if __name__=='__main__':unittest.main()

