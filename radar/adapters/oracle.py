"""Oracle Candidate Experience public feed with explicit site and country scope."""
import json,re
from urllib.parse import urlencode,urlsplit
from lxml import html
from .common import clean
from ..models import Job,Snapshot,SourceError
from ..rules import parse_posted,india_location

class OracleAdapter:
    version='oracle/1'
    def __init__(self,source,client): self.source,self.client=source,client
    def fetch(self):
        site=self.source.get('site_number','');location=str(self.source.get('location_id',''))
        if not re.fullmatch(r'[A-Za-z0-9_]+',site) or not location.isdigit(): raise SourceError('missing_tenant','Oracle site/country scope required')
        jobs=[];ids=set();total=None;pages=0
        for offset in range(0,20000,100):
            finder=f'findReqs;siteNumber={site},limit=100,offset={offset},locationId={location}'
            url=self.source['endpoint']+'?'+urlencode({'onlyData':'true','expand':'requisitionList','finder':finder})
            try: data=json.loads(self.client.get(url))['items'][0]
            except (ValueError,KeyError,IndexError,TypeError): raise SourceError('parse_error','Oracle listing response changed') from None
            if str(data.get('LocationId'))!=location or data.get('SiteNumber')!=site or data.get('Offset')!=offset: raise SourceError('wrong_scope','Oracle ignored site, country or pagination')
            count=data.get('TotalJobsCount');rows=data.get('requisitionList')
            if not isinstance(count,int) or count<0 or not isinstance(rows,list): raise SourceError('missing_total','Oracle count missing')
            if total is None: total=count
            if count!=total: raise SourceError('listing_changed','Oracle total changed during retrieval')
            pages+=1
            for row in rows:
                external=str(row.get('Id',''));title=clean(row.get('Title'))
                if not external.isdigit() or not title: raise SourceError('malformed_job','Oracle job identity missing')
                if external in ids: raise SourceError('duplicate_page','Oracle repeated requisition')
                ids.add(external);raw=row.get('PostedDate') or '';posted,precision=parse_posted(raw)
                url=self.source['listing_url'].split('/jobs')[0]+'/job/'+external
                hotel=self.source.get('verified_job_properties',{}).get(external,'')
                jobs.append(Job(external,title,url,self.source['source_id'],self.source['name'],hotel=hotel,location=row.get('PrimaryLocation') or '',
                    country_code=row.get('PrimaryLocationCountry') or '',summary=row.get('ShortDescriptionStr') or '',
                    posted_raw=raw,posted_at=posted,posted_precision=precision,namespace='oracle:'+urlsplit(self.source['endpoint']).netloc+':'+site))
            if len(jobs)==total:
                if any(not india_location(j) for j in jobs):raise SourceError('country_scope','Oracle country facet returned a non-India job')
                return Snapshot(jobs,total,pages,True)
            if len(rows)!=100 or len(jobs)>total: raise SourceError('incomplete','Oracle truncated results')
        raise SourceError('pagination_limit','Oracle scope too broad')
    def enrich(self,job):
        endpoint=self.source['endpoint'].rsplit('/',1)[0]+'/recruitingCEJobRequisitionDetails'
        query={'onlyData':'true','expand':'all','finder':f"ById;Id={job.external_id},siteNumber={self.source['site_number']}"}
        try: data=json.loads(self.client.get(endpoint+'?'+urlencode(query)))['items'][0]
        except (ValueError,KeyError,IndexError,TypeError):raise SourceError('detail_parse','Oracle detail response changed') from None
        if str(data.get('Id'))!=job.external_id:raise SourceError('id_mismatch','Oracle details do not match listing')
        text=' '.join(data.get(k) or '' for k in ('ExternalDescriptionStr','ExternalQualificationsStr','ExternalResponsibilitiesStr'))
        job.description=clean(html.fromstring('<div>'+text+'</div>').text_content())
        raw=data.get('ExternalPostedStartDate') or '';posted,precision=parse_posted(raw)
        if posted:job.posted_raw,job.posted_at,job.posted_precision=raw,posted,precision
        names={clean(x.get('LocationName')) for x in data.get('workLocation',[]) if x.get('LocationName')}
        if len(names)==1:job.hotel=next(iter(names))
        job.employment_type=data.get('JobSchedule') or ''
        for field in data.get('requisitionFlexFields',[]):
            if field.get('Prompt')=='Salary':job.salary=clean(field.get('Value'))
        job.detail_status='verified';return job

