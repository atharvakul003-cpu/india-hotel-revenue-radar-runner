import json,tempfile,unittest
from pathlib import Path
from radar.models import Job,Snapshot
from radar.rules import relevant,india_location,revenue_role
from radar.state import State
from radar.delivery import message

def job(title='Assistant Revenue Manager',location='Mumbai, India',country='IN',source='marriott',desc='Hotel pricing, forecasting, occupancy, ADR and RevPAR'):
    return Job('123',title,'https://example.org/job/123',source,'Hotel employer',location=location,country_code=country,description=desc,namespace='verified:123')

class IndiaRulesTest(unittest.TestCase):
    def test_revenue_only(self):
        self.assertTrue(relevant(job()))
        for title in ['Sales Manager','Reservations Executive','Revenue Accounting Manager','Director of Revenue','Front Office Manager','Food and Beverage Revenue Manager']:
            with self.subTest(title=title):self.assertFalse(relevant(job(title=title)))
    def test_geography(self):
        for loc,country in [('London, UK','GB'),('Dubai, UAE',''),('Remote, global',''),('Colombo, Sri Lanka','LK')]:
            with self.subTest(loc=loc):self.assertFalse(relevant(job(location=loc,country=country)))
        self.assertTrue(relevant(job(location='Remote, India',country='')))
    def test_distribution_requires_duties(self):
        self.assertFalse(relevant(job(title='Distribution Executive',desc='OTA reservation uploads')))
        self.assertTrue(relevant(job(title='Distribution Revenue Analyst',desc='Hotel dynamic pricing, forecasting, occupancy and RevPAR strategy')))

class StateTest(unittest.TestCase):
    def test_quiet_baseline_repeat_and_new_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'india.sqlite'
            s=State(path)
            source={'id':'marriott'}
            snap=Snapshot([job()],1,1,True)
            self.assertEqual(s.ingest(source,snap)['queued'],0)
            self.assertEqual(s.ingest(source,snap)['queued'],0)
            new=job();new.external_id='124';new.url='https://example.org/job/124';new.namespace='verified:124'
            result=s.ingest(source,Snapshot([job(),new],2,1,True))
            self.assertEqual(result['queued'],1)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],1)
            s.close()
            s=State(path)
            self.assertEqual(s.ingest(source,Snapshot([job(),new],2,1,True))['queued'],0)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],1)
            s.close()
    def test_failure_does_not_erase_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            s=State(Path(directory)/'state.sqlite');source={'id':'marriott'}
            s.ingest(source,Snapshot([job()],1,1,True));s.fail(source,'temporary')
            self.assertEqual(s.db.execute('SELECT baseline_at FROM sources').fetchone()[0] is None,False)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            with self.assertRaises(ValueError):s.ingest(source,Snapshot([],1,1,False))
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            s.close()
    def test_email_identity(self):
        m=message(job().to_dict(),'verified:123:123','sender@example.org','recipient@example.org')
        self.assertIn('[India Revenue Radar]',m['Subject'])
        self.assertIn('example.org/job/123',m.get_content())
        self.assertEqual(m['X-India-Revenue-Radar-Event'],__import__('hashlib').sha256(b'verified:123:123').hexdigest())

if __name__=='__main__':unittest.main()
