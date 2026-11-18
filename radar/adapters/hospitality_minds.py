"""Hospitality Minds' official static openings catalogue."""
import re
from urllib.parse import urlsplit,urljoin
from .common import clean,document
from ..models import Job,Snapshot,SourceError

class HospitalityMindsAdapter:
    version='hospitality-minds/1'
    def __init__(self,source,client):self.source,self.client=source,client

    def parse(self,body):
        d=document(body)
        if not d.xpath('//h1[normalize-space()="All Openings"]'):
            raise SourceError('missing_catalogue','Openings heading missing')
        cards=d.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," blog-post ")][.//h4[contains(@class,"post-title")]]')
        if not cards or len(cards)>200:raise SourceError('missing_cards','Openings cards missing or implausible')
        jobs=[];ids=set()
        for card in cards:
            anchors=card.xpath('.//h4[contains(@class,"post-title")]/a[@href]')
            if len(anchors)!=1:raise SourceError('malformed_job','Openings title link missing')
            a=anchors[0];url=urljoin(self.source['listing_url'],a.get('href',''));title=clean(a.text_content())
            path=urlsplit(url).path
            m=re.fullmatch(r'/jobs/([a-z0-9-]+)\.html',path)
            if not m or urlsplit(url).hostname not in ('hospitalityminds.com','www.hospitalityminds.com') or not title:
                raise SourceError('malformed_job',f'Openings URL or title invalid: {url[:140]} / {title[:60]}')
            ident=m[1]
            if ident in ids:raise SourceError('duplicate_id','Opening repeated')
            ids.add(ident)
            summary=clean(' '.join(card.xpath('.//div[contains(@class,"sx-post-text")]//text()')))
            jobs.append(Job(ident,title,url,self.source['source_id'],self.source['name'],
                summary=summary,namespace='hospitality-minds:openings'))
        return jobs

    def fetch(self):
        first=self.parse(self.client.get(self.source['listing_url']))
        again=self.parse(self.client.get(self.source['listing_url']))
        if [(j.external_id,j.title) for j in first]!=[(j.external_id,j.title) for j in again]:
            raise SourceError('listing_changed','Openings changed during check')
        return Snapshot(first,len(first),2,True)

    def enrich(self,job):
        d=document(self.client.get(job.url));body=clean(' '.join(d.xpath('//body//text()')))
        if job.title.lower() not in body.lower():raise SourceError('detail_changed','Opening title missing in detail')
        job.description=body;job.detail_status='verified'
        m=re.search(r'\b(?:Location|Job Location)\s*[:\-]\s*([A-Za-z ,]+)',body,re.I)
        if m:job.location=clean(m[1])
        return job
