"""Independent durable SQLite state and transactional alert outbox."""
import json,sqlite3
from pathlib import Path
from .models import stamp
from .rules import relevant,RULE_VERSION

SCHEMA='''
CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, baseline_at TEXT, last_success TEXT, last_error TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0, last_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS jobs(job_key TEXT PRIMARY KEY, external_id TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL, employer TEXT NOT NULL, location TEXT, url TEXT NOT NULL, posted_at TEXT, employment_type TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, payload_json TEXT NOT NULL, relevant INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'live');
CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, checked_at TEXT NOT NULL, outcome TEXT NOT NULL, count INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY, job_key TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, sent_at TEXT, provider_id TEXT, error TEXT);
'''

class State:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(SCHEMA)
    def close(self):self.db.close()
    def fail(self,source,error):
        at=stamp();sid=source['id']
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(source_id) VALUES(?)',(sid,))
            self.db.execute('UPDATE sources SET last_error=?,consecutive_failures=consecutive_failures+1 WHERE source_id=?',(error,sid))
            self.db.execute('INSERT INTO checks(source_id,checked_at,outcome,error) VALUES(?,?,?,?)',(sid,at,'failed',error))
    def ingest(self,source,snapshot):
        if not snapshot.complete or len(snapshot.jobs)!=snapshot.expected_count:raise ValueError('Incomplete source snapshot')
        ids=[j.external_id for j in snapshot.jobs]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate source IDs')
        at=stamp();sid=source['id'];new=[]
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(source_id) VALUES(?)',(sid,))
            baseline=self.db.execute('SELECT baseline_at FROM sources WHERE source_id=?',(sid,)).fetchone()[0] is None
            for job in snapshot.jobs:
                key=job.namespace+':'+job.external_id if job.namespace else sid+':'+job.external_id
                match=int(relevant(job))
                row=self.db.execute('SELECT job_key,status FROM jobs WHERE job_key=?',(key,)).fetchone()
                payload=job.to_dict()
                if row:
                    self.db.execute('UPDATE jobs SET title=?,employer=?,location=?,url=?,posted_at=?,employment_type=?,last_seen=?,payload_json=?,relevant=?,status=? WHERE job_key=?',
                        (job.title,job.employer,job.location,job.url,job.posted_at,job.employment_type,at,json.dumps(payload),match,'live',key))
                else:
                    self.db.execute('INSERT INTO jobs(job_key,external_id,source_id,title,employer,location,url,posted_at,employment_type,first_seen,last_seen,payload_json,relevant) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (key,job.external_id,sid,job.title,job.employer,job.location,job.url,job.posted_at,job.employment_type,at,at,json.dumps(payload),match))
                    if match:
                        new.append(payload)
                        if not baseline:
                            self.db.execute('INSERT OR IGNORE INTO outbox(event_id,job_key,payload_json,created_at) VALUES(?,?,?,?)',(key,key,json.dumps(payload),at))
            self.db.execute('UPDATE sources SET baseline_at=COALESCE(baseline_at,?),last_success=?,last_error=NULL,consecutive_failures=0,last_count=? WHERE source_id=?',(at,at,len(ids),sid))
            self.db.execute('INSERT INTO checks(source_id,checked_at,outcome,count) VALUES(?,?,?,?)',(sid,at,'complete',len(ids)))
        return {'source':sid,'baseline':baseline,'total':len(ids),'relevant_new':len(new),'queued':0 if baseline else len(new)}
    def report(self):
        return [dict(x) for x in self.db.execute('SELECT s.source_id,s.last_success,s.last_error,s.consecutive_failures,s.last_count,(SELECT COUNT(*) FROM jobs j WHERE j.source_id=s.source_id AND j.relevant=1) relevant_jobs,(SELECT COUNT(*) FROM jobs j WHERE j.source_id=s.source_id AND j.relevant=1 AND julianday(j.first_seen)>=julianday("now","-30 days")) new_30_days,(SELECT COUNT(*) FROM jobs j WHERE j.source_id=s.source_id AND j.relevant=1 AND julianday(j.first_seen)>=julianday("now","-90 days")) new_90_days FROM sources s ORDER BY s.source_id')]
