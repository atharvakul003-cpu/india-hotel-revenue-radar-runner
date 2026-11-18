"""Probe, baseline and monitor India-specific sources without UK state or secrets."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit
from .http import HttpClient
from .models import SourceError
from .rules import revenue_role,relevant
from .state import State
from .delivery import dispatch

ROOT=Path(__file__).resolve().parents[1]
ADAPTERS={'paradox':'ParadoxAdapter','ihg':'IHGAdapter','ihcl':'IHCLAdapter','revgrow':'RevgrowAdapter','keka':'KekaAdapter','hospitality_minds':'HospitalityMindsAdapter','attrax':'AttraxAdapter','oracle':'OracleAdapter','hyatt_taleo':'HyattTaleoAdapter'}
MODULES={'paradox':'paradox','ihg':'ihg','ihcl':'ihcl','revgrow':'revgrow','keka':'keka','hospitality_minds':'hospitality_minds','attrax':'attrax','oracle':'oracle','hyatt_taleo':'hyatt_taleo'}

def configured():return json.loads((ROOT/'config/sources.json').read_text())

def fetch(source):
    from importlib import import_module
    entry=dict(source,source_id=source['id'],source_key=source['id'])
    host=urlsplit(source['listing_url']).hostname
    client=HttpClient([host],max_run_seconds=source.get('max_run_seconds',90),max_requests=250)
    adapter=getattr(import_module('.adapters.'+MODULES[source['adapter']],__package__),ADAPTERS[source['adapter']])(entry,client)
    snapshot=adapter.fetch()
    if not snapshot.complete or len(snapshot.jobs)!=snapshot.expected_count:raise SourceError('incomplete','Snapshot count invalid')
    for job in snapshot.jobs:
        if revenue_role(job):
            # Detail enrichment is necessary for ambiguous geography and duties.
            try:adapter.enrich(job)
            except SourceError as exc:
                if not job.country_code or not job.location:raise
                job.detail_status='unavailable:'+exc.code
    return snapshot,client.metrics()

def checkpoint(state_dir,db):
    state_dir=Path(state_dir)
    if not (state_dir/'.git').exists():raise RuntimeError('Independent state checkout missing')
    tmp=state_dir/'radar.sqlite.next'
    target=__import__('sqlite3').connect(tmp)
    with target:db.db.backup(target)
    target.close();tmp.replace(state_dir/'radar.sqlite')
    # The state branch inherits a repository-wide *.sqlite ignore rule. Only
    # this dedicated, non-secret checkpoint is intentionally force-added.
    cmds=[['git','add','-f','radar.sqlite'],['git','-c','user.name=India Revenue Radar','-c','user.email=india-radar@users.noreply.github.com','commit','-m','Checkpoint India radar state'],['git','push','origin','HEAD:radar-state']]
    for cmd in cmds:
        p=subprocess.run(cmd,cwd=state_dir,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if p.returncode and not (cmd[1]=='-c' and 'nothing to commit' in p.stdout+p.stderr):
            raise RuntimeError('State checkpoint failed: '+p.stderr[-500:])

def run(mode,only=None):
    sources=[s for s in configured() if s.get('adapter') and (s.get('candidate') if mode=='probe' else s.get('enabled')) and (not only or s['id']==only)]
    if not sources:print(json.dumps({'status':'no_eligible_sources'}));return 0
    if mode=='monitor':
        directory=os.environ.get('INDIA_RADAR_STATE_DIR')
        if not directory:raise RuntimeError('Separate India state checkout required')
        state=State(Path(directory)/'radar.sqlite')
        with state.db:state.db.execute("UPDATE outbox SET status='held',error='ambiguous_after_restart' WHERE status='sending'")
    else:state=None
    failures=[]
    try:
        for source in sources:
            try:
                snapshot,metrics=fetch(source)
                matches=[j for j in snapshot.jobs if relevant(j)]
                result=state.ingest(source,snapshot) if state else {'source':source['id'],'total':snapshot.expected_count,'relevant':len(matches),'sample':[{'title':j.title,'location':j.location,'url':j.url} for j in matches[:20]]}
                print(json.dumps({'event':'source_check','result':result,'requests':metrics['request_count']}),flush=True)
            except Exception as exc:
                code=exc.code if isinstance(exc,SourceError) else type(exc).__name__
                failures.append(source['id']+':'+code)
                if state:state.fail(source,code)
                print(json.dumps({'event':'source_failure','source':source['id'],'error':code,'detail':str(exc)[:240]}),flush=True)
        if state:
            save=lambda:checkpoint(directory,state)
            save()
            if os.environ.get('INDIA_RADAR_DELIVERY_ENABLED')=='true':
                print(json.dumps({'event':'delivery','results':dispatch(state,save)}),flush=True)
            print(json.dumps({'event':'health','sources':state.report()}),flush=True)
    finally:
        if state:state.close()
    return 1 if failures else 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['probe','monitor']);p.add_argument('--source')
    a=p.parse_args();sys.exit(run(a.mode,a.source))
