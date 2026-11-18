"""Atica's official Keka public active-jobs JSON feed."""
import json,re
from .common import clean
from ..models import Job,Snapshot,SourceError
from ..rules import parse_posted

class KekaAdapter:
    version='keka/2'
    def __init__(self,source,client):
        self.source,self.client=source,client
        fid=source.get('feed_id','')
        if not re.fullmatch(r'[a-f0-9-]{36}',fid):raise SourceError('feed_id','Atica feed identifier missing')
        self.feed='https://atica.keka.com/careers/api/embedjobs/default/active/'+fid

    def parse(self,body):
        try:rows=json.loads(body)
        except ValueError:raise SourceError('parse_error','Atica active jobs JSON invalid') from None
        if not isinstance(rows,list) or len(rows)>500:raise SourceError('parse_error','Atica active jobs array missing')
        jobs=[];ids=set()
        for row in rows:
            if not isinstance(row,dict):raise SourceError('malformed_job','Atica job object invalid')
            ident=row.get('id');title=clean(row.get('title',''))
            locations=row.get('jobLocations')
            if not isinstance(ident,int) or ident<=0 or not title or not isinstance(locations,list) or not locations:
                raise SourceError('malformed_job','Atica job identity, title or location missing')
            if ident in ids:raise SourceError('duplicate_id','Atica requisition repeated')
            ids.add(ident)
            if any(not isinstance(x,dict) or not x.get('countryCode') or not x.get('city') for x in locations):
                raise SourceError('country_scope','Atica location lacks a country or city')
            indian=[x for x in locations if x['countryCode'].upper()=='IN']
            if not indian:continue
            loc='; '.join(dict.fromkeys(clean(x['city']+', '+x.get('countryName','India')) for x in indian))
            posted,precision=parse_posted(row.get('publishedOn',''))
            if row.get('publishedOn') and not posted:raise SourceError('date_schema','Atica posted date invalid')
            jobs.append(Job(str(ident),title,f'https://atica.keka.com/careers/jobdetails/{ident}',self.source['source_id'],self.source['name'],
                location=loc,country_code='IN',namespace='atica:keka',
                posted_at=posted,posted_precision=precision,posted_raw=row.get('publishedOn',''),
                salary=clean(row.get('salaryRangeFormat','')),
                employment_type='Full Time' if row.get('jobType')==2 else '',
                summary=clean(row.get('excerpt','')),description=clean(row.get('description','')),
                detail_status='feed_verified'))
        return jobs

    def fetch(self):
        first=self.parse(self.client.get(self.feed))
        again=self.parse(self.client.get(self.feed))
        if [(j.external_id,j.title,j.location) for j in first]!=[(j.external_id,j.title,j.location) for j in again]:
            raise SourceError('listing_changed','Atica active jobs feed changed during check')
        return Snapshot(first,len(first),2,True)

    def enrich(self,job):return job
