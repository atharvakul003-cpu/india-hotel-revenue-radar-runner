"""Paradox's official, server-emitted search JSON is authoritative for detection.

Oracle application details are deliberately NOT a catalogue completeness gate.
Two complete traversals must agree before any snapshot can reach ingestion.
"""
import json,re,time
from urllib.parse import urlencode,urlsplit,urljoin
from .common import clean,document,jobposting,text_at
from ..models import Job,Snapshot,SourceError,CatalogueInstability,fingerprint
from ..rules import parse_posted

class ParadoxAdapter:
    version='paradox/1'
    def __init__(self,source,client):
        self.source,self.client=source,client
        self.origin='https://'+urlsplit(source['listing_url']).netloc
        self.page_size=source.get('page_size',10)
        if self.page_size not in (10,20):raise SourceError('page_size','Unsupported Paradox page size')
        self.observation={}

    def page(self,number):
        url=self.source['listing_url']+'?'+urlencode({'filter[country][0]':'India','page_number':number,'page_size':self.page_size})
        body=self.client.get(url)
        root=document(body)
        scripts=root.xpath('//script[not(@src)]/text()')
        matches=[re.search(r'window\.__PRELOAD_STATE__\s*=\s*',s) for s in scripts]
        values=[(s,m) for s,m in zip(scripts,matches) if m]
        try:
            if len(values)!=1:raise ValueError()
            script,match=values[0]
            data=json.JSONDecoder().raw_decode(script[match.end():])[0]['jobSearch']
            params=data['params']
            if params.get('filter')!={'country':['India']} or params.get('page_number',1)!=number:
                raise SourceError('wrong_scope','Paradox ignored country or page number')
            if params.get('page_size',10)!=self.page_size:raise SourceError('wrong_scope','Paradox ignored page size')
            if type(data['totalJob']) is not int or not 0<=data['totalJob']<=2000 or not isinstance(data['jobs'],list):raise ValueError()
            return data
        except (KeyError,ValueError,TypeError):
            raise SourceError('parse_error','Paradox search JSON missing or changed') from None

    def job(self,row):
        try:
            req=row['requisitionID'];ref=row['reference'];path=row['originalURL']
            title=clean(row['title']);locations=row['locations']
            fields={f['cfKey']:f.get('value','') for f in row['customFields']}
            if not isinstance(req,str) or not re.fullmatch(r'\d+',req) or not title:
                raise SourceError('malformed_job','Paradox requisition or title missing')
            if not isinstance(ref,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',ref) or not re.fullmatch(r'[^/?#]+/job/'+re.escape(ref),path):
                raise SourceError('id_mismatch','Paradox reference and canonical path disagree')
            if row.get('isInternal') not in ('false',False) or fields.get('cf_external_posting_status')!='Posted' or fields.get('cf_job_requisition_status')!='Open-Posted':
                raise CatalogueInstability('listing_changed','Paradox listing is not an open external posting')
            if not locations or any(l.get('countryAbbr')!='IN' for l in locations):
                raise SourceError('country_scope','Paradox listing contains an unverified or non-UK location')
            if any(not clean(l.get('locationName')) or not clean(l.get('locationText')) for l in locations):
                raise SourceError('malformed_job','Paradox property/location missing')
            names={clean(l['locationName']) for l in locations}
            hotel=next(iter(names)) if len(names)==1 else ''
            # Corporate vacancies remain monitored, but never count as hotels.
            if re.search(r'\boffice\b|headquarters|shared\s*service',hotel,re.I):hotel=''
            apply=row.get('applyURL','')
            parsed=urlsplit(apply)
            # Some public/open Paradox rows omit the separate ATS apply URL.
            # The verified official vacancy page remains the canonical link.
            if apply and (parsed.scheme!='https' or not parsed.netloc):
                raise SourceError('invalid_apply_url','Paradox application URL is invalid')
            if 'oraclecloud.com' in parsed.netloc and '/job/'+req+'/' not in parsed.path:
                raise SourceError('id_mismatch','Application URL and Paradox requisition disagree')
            return Job(req,title,urljoin(self.origin+'/',path),self.source['source_id'],self.source['name'],
                hotel=hotel,location='; '.join(dict.fromkeys(clean(l['locationText']) for l in locations)),country_code='IN',
                requisition_id=req,namespace='paradox:'+urlsplit(self.origin).netloc,
                employment_type=', '.join(row.get('employmentType',[])),salary=clean(fields.get('cf_pay_range')),
                raw_identifiers={'paradox_reference':ref,'paradox_unique_id':row.get('uniqueID',''),'apply_url':apply,
                    'location_ids':[l.get('locationID','') for l in locations],'location_names':sorted(names),
                    'job_field':fields.get('cf_jobfield',''),'status':'Open-Posted'})
        except (KeyError,TypeError,AttributeError):
            raise SourceError('malformed_job','Paradox listing schema changed') from None

    def traverse(self):
        first=self.page(1);total=first['totalJob'];jobs=[];ids=set();refs=set();pages=max(1,(total+self.page_size-1)//self.page_size)
        for number in range(1,pages+1):
            data=first if number==1 else self.page(number)
            if data['totalJob']!=total:raise CatalogueInstability('listing_changed','Paradox total changed during pagination')
            if len(data['jobs'])!=min(self.page_size,max(0,total-(number-1)*self.page_size)):
                raise CatalogueInstability('incomplete','Paradox page length does not match advertised total')
            for row in data['jobs']:
                job=self.job(row);ref=job.raw_identifiers['paradox_reference']
                if job.external_id in ids or ref in refs:raise SourceError('duplicate_id','Paradox repeated a requisition/reference')
                ids.add(job.external_id);refs.add(ref);jobs.append(job)
        if len(ids)!=total:raise CatalogueInstability('incomplete','Paradox unique total mismatch')
        return jobs,total,pages

    def fetch(self):
        trace={'attempts':[],'retry_performed':False}
        try:
            for attempt in (1,2):
                start=time.monotonic()
                try:
                    jobs,total,pages=self.traverse()
                    again,end,endpages=self.traverse()
                    # Compare every record, not just the first page or total.
                    before={j.external_id:fingerprint(j.to_dict()) for j in jobs}
                    after={j.external_id:fingerprint(j.to_dict()) for j in again}
                    if total!=end or before!=after:
                        raise CatalogueInstability('listing_changed','Paradox complete traversals disagree')
                    trace['attempts'].append({'attempt':attempt,'total_start':total,'total_end':end,'unique_count':len(jobs),
                        'pages':pages+endpages,'complete':True,'seconds':round(time.monotonic()-start,2)})
                    return Snapshot(jobs,total,pages+endpages,True)
                except CatalogueInstability as exc:
                    elapsed=time.monotonic()-start
                    trace['attempts'].append({'attempt':attempt,'complete':False,'error':exc.code,
                        'reason':str(exc),'seconds':round(elapsed,2)})
                    remaining=self.client.deadline-time.monotonic()
                    required=max(20,elapsed*1.1+10)
                    trace.update(retry_required_seconds=round(required,2),remaining_seconds=round(remaining,2))
                    if attempt==1 and remaining>=required:
                        trace['retry_performed']=True
                        continue
                    raise
        finally:
            self.observation=trace
            print(json.dumps({'event':'paradox_snapshot','source':self.source['source_id'],**trace}),flush=True)

    def enrich(self,job):
        # Optional enrichment uses the same official Paradox detail page. An absent
        # Oracle record never prevents detection, baseline, or new-job notification.
        info=jobposting(document(self.client.get(job.url)))
        if not info:raise SourceError('detail_unavailable','Paradox structured detail missing')
        ident=info.get('identifier',{})
        if not isinstance(ident,dict) or str(ident.get('value'))!=job.raw_identifiers['paradox_reference'] or info.get('url')!=job.url or clean(info.get('title'))!=job.title:
            raise SourceError('detail_id_mismatch','Paradox detail identity differs from listing')
        locations=info.get('jobLocation',[])
        if isinstance(locations,dict):locations=[locations]
        if not locations or any(l.get('address',{}).get('addressCountry')!='IN' for l in locations):
            raise SourceError('detail_country_mismatch','Paradox detail country differs from India listing')
        description=info.get('description','')
        job.description=text_at(document('<div>'+description+'</div>'),'.') if description else ''
        raw=info.get('datePosted','');posted,precision=parse_posted(raw)
        if raw and not posted:raise SourceError('detail_date','Paradox posting date invalid')
        job.posted_raw,job.posted_at,job.posted_precision=raw,posted,precision
        job.detail_status='verified'
        return job
