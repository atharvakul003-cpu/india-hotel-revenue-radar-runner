"""Revgrow360's public WordPress job listings."""
import re
from urllib.parse import urlsplit
from .common import clean, document
from ..models import Job, Snapshot, SourceError

class RevgrowAdapter:
    version='revgrow/1'
    def __init__(self,source,client):self.source,self.client=source,client
    def fetch(self):
        d=document(self.client.get(self.source['listing_url']))
        cards=d.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," awsm-job-listing-item ")]')
        if not cards:raise SourceError('missing_cards','Revgrow job cards missing')
        jobs=[];ids=set()
        for card in cards:
            match=re.fullmatch(r'awsm-grid-item-(\d+)',card.get('id',''))
            anchors=card.xpath('.//a[contains(concat(" ",normalize-space(@class)," ")," awsm-job-item ")][@href]')
            if not match or not anchors:raise SourceError('malformed_job','Revgrow card identity missing')
            ident=match[1];url=anchors[0].get('href')
            if any(a.get('href')!=url for a in anchors) or urlsplit(url).hostname!='revgrow360.com':
                raise SourceError('id_mismatch','Revgrow card URL changed')
            title=clean(' '.join(card.xpath('.//h2//text()')))
            if not title or ident in ids:raise SourceError('duplicate_id','Revgrow title/ID missing or repeated')
            ids.add(ident)
            jobs.append(Job(ident,title,url,self.source['source_id'],self.source['name'],
                location='India',country_code='IN',namespace='revgrow360:wordpress'))
        return Snapshot(jobs,len(jobs),1,True)
    def enrich(self,job):
        d=document(self.client.get(job.url))
        body=clean(' '.join(d.xpath('//main//text()')))
        if job.title.rstrip('.').lower() not in body.lower():raise SourceError('detail_changed','Revgrow detail title missing')
        job.description=body;job.detail_status='verified';return job
