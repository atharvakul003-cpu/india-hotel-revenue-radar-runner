"""Public Attrax HTML listings. Validate totals/page identity before ingesting."""
import math,re
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode,urljoin
from .common import document,text_at,canonical,enrich_structured
from ..models import Job,Snapshot,SourceError,CatalogueInstability

def cls(value): return 'contains(concat(" ",normalize-space(@class)," ")," '+value+' ")'

class AttraxAdapter:
    version='attrax/1'
    def __init__(self,source,client): self.source,self.client=source,client
    def page(self,body,number):
        d=document(body)
        totals=d.xpath('//*['+cls('attrax-pagination__total-results')+']')
        values={re.sub(r'[^0-9]','',n.text_content()) for n in totals}
        if len(values)!=1 or not next(iter(values),'').isdigit(): raise SourceError('missing_total','Attrax result total missing or inconsistent')
        total=int(next(iter(values)))
        current={text_at(n,'.') for n in d.xpath('//*['+cls('attrax-pagination__page-item--current')+']')}
        jobs=[]
        for card in d.xpath('//*['+cls('attrax-vacancy-tile')+']'):
            external=card.get('data-jobid','')
            links=card.xpath('.//a['+cls('attrax-vacancy-tile__title')+']')
            if not external.isdigit() or len(links)!=1 or not text_at(links[0],'.'): raise SourceError('malformed_job','Attrax job identity missing')
            url=canonical(urljoin(self.source['listing_url'],links[0].get('href','')))
            if urlsplit(url).netloc!=urlsplit(self.source['listing_url']).netloc or not url.endswith('-jid-'+external): raise SourceError('id_mismatch','Attrax URL and ID disagree')
            def value(field): return text_at(card,'.//*['+cls('attrax-vacancy-tile__'+field)+']//*['+cls('attrax-vacancy-tile__item-value')+']')
            location=value('location-freetext')
            hotel=value('option-hotel-name')
            if not hotel and self.source.get('hotel_in_location') and location.count(',')>=2:
                hotel=location.rsplit(',',2)[0].strip()
            jobs.append(Job(external,text_at(links[0],'.'),url,self.source['source_id'],self.source['name'],
                hotel=hotel,location=location,salary=value('salary'),summary=value('description'),
                requisition_id=value('reference'),namespace='attrax:'+urlsplit(url).netloc))
        if total and current!={str(number)} and not (number==1 and not current and len(jobs)==total): raise SourceError('wrong_page',f'Attrax requested page {number}, current marker {sorted(current)}')
        if total and not jobs: raise SourceError('truncated','Attrax nonzero total without jobs')
        if len({j.external_id for j in jobs})!=len(jobs): raise SourceError('duplicate_id','Attrax duplicate cards')
        return jobs,total
    def fetch(self):
        self.observation={'total_start':None,'total_end':None,'unique_count':0,'partition_duplicates':0}
        return self._fetch_attempt()

    def _fetch_attempt(self):
        body=self.client.get(self.source['listing_url'])
        jobs,total=self.page(body,1)
        self.observation.update(total_start=total,unique_count=len(jobs))
        size=len(jobs); pages=math.ceil(total/size) if size else 1
        if self.source.get('partition_category') and pages>25:
            d=document(body); options=set()
            for group in d.xpath('//*['+cls('optionfiltergroup')+']'):
                heading=text_at(group,'.//*['+cls('option-type-header-text')+']')
                if heading!=self.source['partition_category']: continue
                options.update(group.xpath('./ul/li/@data-option-id'))
            if not options: raise SourceError('partition_missing','No complete category partition discovered')
            union={}; fetched_pages=1
            self.observation['unique_count']=0
            for option in sorted(options):
                p=urlsplit(self.source['listing_url']);q=dict(parse_qsl(p.query))
                q['options']=q.get('options','').rstrip(',')+','+option;q['page']='1'
                child=dict(self.source,listing_url=urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),'')),partition_category=None)
                part=AttraxAdapter(child,self.client).fetch();fetched_pages+=part.pages
                for job in part.jobs:
                    if job.external_id in union:
                        self.observation['partition_duplicates']+=1
                        if union[job.external_id].listing_hash()!=job.listing_hash(): raise CatalogueInstability('listing_changed','Conflicting Attrax partition observations')
                    union[job.external_id]=job
                    self.observation['unique_count']=len(union)
            final_jobs,final_total=self.page(self.client.get(self.source['listing_url']),1)
            self.observation['total_end']=final_total
            if len(union)!=total or final_total!=total or not {j.external_id for j in jobs+final_jobs}<=set(union): raise CatalogueInstability('partition_incomplete','Partition union must equal complete unfiltered source total')
            return Snapshot(list(union.values()),total,fetched_pages+1,True)
        if pages>200: raise SourceError('pagination_limit','Attrax source must be scoped more narrowly')
        ids={j.external_id for j in jobs}
        for number in range(2,pages+1):
            p=urlsplit(self.source['listing_url']);q=dict(parse_qsl(p.query));q['page']=str(number)
            part,expected=self.page(self.client.get(urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))),number)
            if expected!=total:
                self.observation['page_total']=expected
                raise CatalogueInstability('listing_changed','Attrax total changed during pagination')
            if ids.intersection(j.external_id for j in part): raise SourceError('duplicate_page','Attrax repeated page')
            if number<pages and len(part)!=size: raise SourceError('truncated','Attrax short intermediate page')
            ids.update(j.external_id for j in part); jobs.extend(part)
            self.observation['unique_count']=len(ids)
        if len(jobs)!=total: raise SourceError('incomplete','Attrax final count mismatch')
        return Snapshot(jobs,total,pages,True)
    def enrich(self,job): return enrich_structured(job,self.client.get(job.url))

