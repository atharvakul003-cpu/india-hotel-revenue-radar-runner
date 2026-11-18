"""Hyatt official Taleo India catalogue using the public India location facet."""
import json,math
from datetime import datetime
from urllib.parse import quote
from .common import clean
from ..models import Job,Snapshot,SourceError

class HyattTaleoAdapter:
    version="hyatt_taleo/3"

    def __init__(self,source,client):
        self.source,self.client=source,client
        self.section=str(source.get("taleo_section") or "")
        self.portal=str(source.get("portal_id") or "")
        self.india_location=str(source.get("country_location_id") or "")
        if not self.section or not self.portal.isdigit() or not self.india_location.isdigit():
            raise SourceError("configuration","Hyatt Taleo section/portal/India location facet missing")
        self.shell=f"https://hyatt.taleo.net/careersection/{self.section}/jobsearch.ftl?lang=en"
        self.endpoint=f"https://hyatt.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal={self.portal}"

    def body(self,page,selection=None,axis=None):
        return {
            "multilineEnabled":False,
            "sortingSelection":{"sortBySelectionParam":"3","ascendingSortingOrder":"false"},
            "fieldData":{"fields":{"KEYWORD":"","LOCATION":"","CATEGORY":"","JOB_NUMBER":"","JOB_TITLE":""},"valid":True},
            "filterSelectionParam":{"searchFilterSelections":[
                {"id":"POSTING_DATE","selectedValues":[]},
                {"id":"LOCATION","selectedValues":[self.india_location]},
                {"id":"JOB_FIELD","selectedValues":[selection] if axis=="JOB_FIELD" else []},
                {"id":"JOB_SCHEDULE","selectedValues":[]},
                {"id":"JOB_LEVEL","selectedValues":[selection] if axis=="JOB_LEVEL" else []},
            ]},
            "advancedSearchFiltersSelectionParam":{"searchFilterSelections":[]},
            "pageNo":page,
        }

    def request_page(self,page,selection=None,axis=None):
        headers={
            "Accept":"application/json, text/javascript, */*; q=0.01",
            "X-Requested-With":"XMLHttpRequest",
            "tz":"GMT+00:00","tzname":"Europe/London",
            "Referer":self.shell,
        }
        try:data=json.loads(self.client.request(self.endpoint,method="POST",body=self.body(page,selection,axis),headers=headers))
        except (ValueError,TypeError):raise SourceError("parse_error","Hyatt Taleo JSON schema changed") from None
        paging=data.get("pagingData") or {};rows=data.get("requisitionList")
        try:total=int(paging["totalCount"]);current=int(paging["currentPageNo"]);size=int(paging["pageSize"])
        except (KeyError,TypeError,ValueError):raise SourceError("missing_total","Hyatt Taleo paging data missing") from None
        if not isinstance(rows,list) or current!=page or size<=0 or size>100 or total<0 or total>2000:
            raise SourceError("pagination","Hyatt Taleo paging contract invalid")
        return rows,total,size,data.get("facetResults")

    def parse_rows(self,rows):
        jobs=[];ids=set()
        for row in rows:
            ext=clean(str(row.get("contestNo") or ""))
            internal=clean(str(row.get("jobId") or ""))
            cols=row.get("column")
            loccols=row.get("locationsColumns")
            if not ext or not internal.isdigit() or not isinstance(cols,list) or len(cols)<5 or row.get("linkedColumn")!=0:
                raise SourceError("malformed_job","Hyatt Taleo row identity/layout changed")
            if ext in ids:raise SourceError("duplicate_id","Hyatt Taleo page repeated requisition")
            ids.add(ext)
            title=clean(str(cols[0] or ""));hotel=clean(str(cols[1] or ""));category=clean(str(cols[2] or ""))
            if not title:raise SourceError("malformed_job","Hyatt title missing")
            if not isinstance(loccols,list) or len(loccols)!=1 or loccols[0]>=len(cols):
                raise SourceError("location_schema","Hyatt Taleo location column changed")
            rawloc=str(cols[loccols[0]] or "")
            try:
                values=json.loads(rawloc)
                if not isinstance(values,list) or not values:raise ValueError
                locations=[clean(str(x)) for x in values if clean(str(x))]
            except (ValueError,TypeError):
                raise SourceError("location_schema","Hyatt Taleo location payload changed") from None
            # The query itself is constrained to Hyatt's verified India location facet.
            # Taleo may display "Multiple Locations" when India is one of several locations.
            if locations==["Multiple Locations"]:
                location="India (Multiple Locations)"
            else:
                if any(not x.startswith("IN-") for x in locations):
                    raise SourceError("country_scope","Hyatt India facet returned a non-IN location")
                location=", ".join(x.replace("IN-","",1).replace("-",", ",1) for x in locations)
            rawdate=clean(str(cols[4] or ""));posted=""
            if rawdate:
                try:posted=datetime.strptime(rawdate,"%b %d, %Y").date().isoformat()
                except ValueError:raise SourceError("date_schema","Hyatt posting date format changed") from None
            url=f"https://hyatt.taleo.net/careersection/{self.section}/jobdetail.ftl?job={quote(ext)}&lang=en"
            jobs.append(Job(ext,title,url,self.source["source_id"],self.source["name"],hotel=hotel,
                location=location,country_code="IN",requisition_id=ext,posted_at=posted,
                posted_precision="date" if posted else "",posted_raw=rawdate,summary=category,
                namespace="taleo:hyatt.taleo.net:"+self.section,
                raw_identifiers={"contestNo":ext,"jobId":internal,"portal":self.portal,"india_location_facet":self.india_location}))
        return jobs

    def fetch(self):
        # Establish the Taleo session cookie before public JSON requests.
        self.client.get(self.shell)
        first_rows,total,size,facets=self.request_page(1)
        def groups_for(axis,values):
            groups=next((f.get("facetValueResults") for f in values or [] if f.get("id")==axis),None)
            if not isinstance(groups,list) or not groups:
                raise SourceError("missing_facets",f"Hyatt {axis} facets missing")
            try:
                items=[(str(g["id"]),int(g["quantity"])) for g in groups
                       if axis=="JOB_LEVEL" or g.get("level")==1]
            except (KeyError,TypeError,ValueError):
                raise SourceError("missing_facets",f"Hyatt {axis} facet counts malformed") from None
            if len(set(i for i,_ in items))!=len(items) or sum(n for _,n in items)!=total or any(n<0 for _,n in items):
                raise SourceError("facet_mismatch",f"Hyatt {axis} facets do not partition India total")
            return items
        levels=groups_for("JOB_LEVEL",facets)
        fields=groups_for("JOB_FIELD",facets)
        union={};requests=1;axis_counts={}
        for axis,groups in (("JOB_LEVEL",levels),("JOB_FIELD",fields)):
            axis_ids=set();axis_counts[axis]=0
            for selection,expected in groups:
                if expected==0:continue
                pages=math.ceil(expected/size)
                if pages>20:raise SourceError("pagination_limit","Hyatt partition exceeds safe page limit")
                for page in range(1,pages+1):
                    rows,count,page_size,_=self.request_page(page,selection,axis)
                    requests+=1
                    if count!=expected or page_size!=size:
                        raise SourceError("listing_changed",f"Hyatt {axis} count changed during traversal")
                    for job in self.parse_rows(rows):
                        if job.external_id in axis_ids:
                            raise SourceError("duplicate_page",f"Hyatt {axis} pages overlap")
                        axis_ids.add(job.external_id)
                        old=union.get(job.external_id)
                        if old and old.listing_hash()!=job.listing_hash():
                            raise SourceError("listing_changed","Hyatt requisition changed across partitions")
                        union[job.external_id]=job
            axis_counts[axis]=len(axis_ids)
            if len(union)==total:break
        if len(union)!=total:
            raise SourceError("incomplete",f"Hyatt India Taleo union returned {len(union)}/{total} rows; partitions {axis_counts}")
        again,final_total,final_size,final_facets=self.request_page(1)
        again_jobs=self.parse_rows(again)
        if final_total!=total or final_size!=size or groups_for("JOB_LEVEL",final_facets)!=levels or groups_for("JOB_FIELD",final_facets)!=fields or not {j.external_id for j in again_jobs}<=union.keys():
            raise SourceError("listing_changed","Hyatt India catalogue changed during traversal")
        return Snapshot(list(union.values()),total,requests+1,True)

    def enrich(self,job):
        job.detail_status="listing_only"
        return job

