"""IHCL official SuccessFactors job-tile search (all departments, India scope)."""
import math,re
from datetime import datetime
from urllib.parse import urljoin,urlsplit,urlunsplit,parse_qsl,urlencode
from .common import clean,document
from ..models import Job,Snapshot,SourceError

class IHCLAdapter:
    version='ihcl/1'
    PAGE_SIZE=25
    def __init__(self,source,client):self.source,self.client=source,client
    def url(self,page):
        p=urlsplit(self.source['listing_url']);q=dict(parse_qsl(p.query))
        q['startrow']=str((page-1)*self.PAGE_SIZE) if page>1 else '0'
        return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))
    def parse(self,body,page):
        d=document(body)
        label=clean(' '.join(d.xpath('//*[@id="tile-search-results-label"]/text()')))
        m=re.search(r'Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+Jobs',label,re.I)
        if not m:raise SourceError('missing_total','IHCL listing total missing')
        start,end,total=map(int,m.groups())
        if total>3000 or (total and start!=(page-1)*self.PAGE_SIZE+1):
            raise SourceError('page_range','IHCL pagination changed')
        rows=d.xpath('//li[contains(concat(" ",normalize-space(@class)," ")," job-tile ")]')
        jobs=[];ids=set()
        for row in rows:
            anchors=row.xpath('.//a[contains(concat(" ",normalize-space(@class)," ")," jobTitle-link ")][@href]')
            if not anchors:raise SourceError('malformed_job','IHCL title link missing')
            url=urljoin('https://careers.ihcltata.com',row.get('data-url',''))
            title=clean(anchors[0].text_content())
            match=re.search(r'/(\d+)/?$',urlsplit(url).path)
            tile=re.search(r'\bjob-id-(\d+)\b',row.get('class',''))
            if not match or not tile or match[1]!=tile[1] or not title or urlsplit(url).hostname!='careers.ihcltata.com':
                raise SourceError('malformed_job',f'IHCL URL/title/tile invalid on page {page}')
            ident=match[1]
            if ident in ids:raise SourceError('duplicate_id','IHCL job repeated')
            ids.add(ident)
            bodytext=clean(row.text_content())
            # The official category may include Colombo; detail geography must be verified before alerting.
            units=[clean(x) for x in row.xpath('.//*[contains(@class,"section-field businessunit")]//div/text()')]
            business=next((x for x in units if x), '')
            city=urlsplit(url).path.split('/job/')[-1].split('-')[0].replace('_',' ')
            loc=clean(business+' '+city)
            dates=clean(' '.join(row.xpath('.//*[contains(@class,"section-field date")]//div/text()')))
            try:posted=datetime.strptime(dates,'%d %b %Y').date().isoformat()
            except ValueError:posted=''
            jobs.append(Job(ident,title,url,self.source['source_id'],self.source['name'],
                location=loc,hotel=business,posted_at=posted,posted_raw=dates,
                posted_precision='date' if posted else '',summary=bodytext,namespace='ihcl:successfactors'))
        # SuccessFactors currently renders "Showing 26 to 25" on page two:
        # use the total, starting offset and actual returned rows instead.
        if len(jobs)!=min(self.PAGE_SIZE,max(0,total-(page-1)*self.PAGE_SIZE)):
            raise SourceError('page_size','IHCL row count differs from advertised total')
        return jobs,total
    def fetch(self):
        first,total=self.parse(self.client.get(self.url(1)),1)
        pages=max(1,math.ceil(total/self.PAGE_SIZE))
        jobs=list(first);ids={j.external_id for j in jobs}
        for page in range(2,pages+1):
            part,count=self.parse(self.client.get(self.url(page)),page)
            new={j.external_id for j in part}
            if count!=total or ids&new:raise SourceError('listing_changed','IHCL pagination changed or repeated')
            ids|=new;jobs.extend(part)
        again,end=self.parse(self.client.get(self.url(1)),1)
        if len(jobs)!=total or end!=total or [j.external_id for j in again]!=[j.external_id for j in first]:
            raise SourceError('incomplete','IHCL listing incomplete/unstable')
        return Snapshot(jobs,total,pages+1,True)
    def enrich(self,job):
        d=document(self.client.get(job.url));body=clean(' '.join(d.xpath('//body//text()')))
        if job.title.lower() not in body.lower():raise SourceError('detail_changed','IHCL detail title missing')
        job.description=body;job.detail_status='verified'
        return job
