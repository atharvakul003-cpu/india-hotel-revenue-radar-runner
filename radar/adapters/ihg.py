"""IHG official India search results; listing-only detection with strict pagination checks."""
import math,re
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode,parse_qs,urljoin
from .common import document,clean,canonical
from ..models import Job,Snapshot,SourceError

class IHGAdapter:
    version="ihg/1"
    PER_PAGE=50
    def __init__(self,source,client):
        self.source,self.client=source,client
        p=urlsplit(source["listing_url"]);q=dict(parse_qsl(p.query))
        if p.hostname!="careers.ihg.com" or q.get("area")!="india":
            raise SourceError("india_scope","IHG official India search route is required")

    def url(self,page):
        p=urlsplit(self.source["listing_url"]);q=dict(parse_qsl(p.query))
        if page>1:q["page"]=str(page)
        else:q.pop("page",None)
        return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),""))

    def parse(self,body,page):
        d=document(body);text=clean(" ".join(d.xpath("//body//text()")))
        m=re.search(r"\b(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+jobs?\s+available\b",text,re.I)
        if not m:raise SourceError("missing_total","IHG result range/total missing")
        start,end,total=map(int,m.groups())
        if total<0 or total>2000:raise SourceError("pagination_limit","IHG result total outside safety bound")
        expected=min(self.PER_PAGE,max(0,total-(page-1)*self.PER_PAGE))
        expected_start=(page-1)*self.PER_PAGE+1 if expected else (page-1)*self.PER_PAGE+1
        expected_end=(page-1)*self.PER_PAGE+expected
        if expected and (start!=expected_start or end!=expected_end):
            raise SourceError("page_range","IHG page range differs from expected pagination")
        jobs=[];ids=set();urls=set()
        for a in d.xpath('//a[contains(@href,"/job-details/") and contains(@href,"jobref=")]'):
            href=canonical(urljoin(self.source["listing_url"],a.get("href")))
            if href in urls:continue
            urls.add(href)
            refs=parse_qs(urlsplit(href).query).get("jobref",[])
            if len(refs)!=1:raise SourceError("id_mismatch","IHG job URL lacks one jobref")
            parts=refs[0].split("|")
            if len(parts)<3:raise SourceError("id_mismatch","IHG jobref format changed")
            title=clean("|".join(parts[:-2]));country=parts[-2].strip().upper();external=parts[-1].strip()
            # The middle jobref segment is not a stable ISO country code. The
            # visible card location below is the India scope check.
            if not external.isdigit() or not title:raise SourceError("id_mismatch","IHG requisition identity malformed")
            if external in ids:raise SourceError("duplicate_id","IHG page repeated a requisition ID")
            ids.add(external)
            node=a;card=""
            for _ in range(8):
                candidate=clean(node.text_content())
                if re.search(r"\bLocation\b",candidate,re.I):
                    card=candidate;break
                parent=node.getparent()
                if parent is None:break
                node=parent
            loc=""
            lm=re.search(r"\bLocation\s+(.+?)(?=\s+View\s+Job\b|$)",card,re.I)
            if lm and clean(lm.group(1)):loc=clean(lm.group(1))
            if not re.search(r"\bIndia\b",loc,re.I):raise SourceError("country_scope","India search returned an unverified location")
            jobs.append(Job(external,title,href,self.source["source_id"],self.source["name"],
                location=loc,country_code="IN",requisition_id=external,
                namespace="ihg:careers.ihg.com",raw_identifiers={"jobref":refs[0]}))
        if len(jobs)!=expected:
            raise SourceError("page_size",f"IHG page returned {len(jobs)} unique jobs; expected {expected}")
        return jobs,total

    def fetch(self):
        first,total=self.parse(self.client.get(self.url(1)),1)
        pages=max(1,math.ceil(total/self.PER_PAGE))
        jobs=list(first);ids={j.external_id for j in jobs}
        for page in range(2,pages+1):
            part,count=self.parse(self.client.get(self.url(page)),page)
            if count!=total:raise SourceError("listing_changed","IHG total changed during traversal")
            new={j.external_id for j in part}
            if ids&new:raise SourceError("duplicate_page","IHG pagination repeated requisition IDs")
            ids|=new;jobs.extend(part)
        if len(jobs)!=total:raise SourceError("incomplete","IHG India listing was incomplete")
        again,final_total=self.parse(self.client.get(self.url(1)),1)
        if final_total!=total or [j.external_id for j in again]!=[j.external_id for j in first]:
            raise SourceError("listing_changed","IHG first page changed during traversal")
        return Snapshot(jobs,total,pages+1,True)

    def enrich(self,job):
        job.detail_status="listing_only"
        return job
