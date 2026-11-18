"""Public HTTP client. No credentials, challenge solving or access-control bypass."""
from urllib.request import Request,build_opener,HTTPCookieProcessor
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse
from http.cookiejar import CookieJar
from email.utils import parsedate_to_datetime
from datetime import timedelta
import json,time,socket
from .models import SourceError,utcnow,stamp

class HttpClient:
    def __init__(self,hosts,timeout=30,pace=0.6,max_requests=600,max_run_seconds=720):
        self.deadline=time.monotonic()+max_run_seconds
        self.hosts=set(hosts); self.timeout=timeout; self.pace=pace; self.max_requests=max_requests
        self.opener=build_opener(HTTPCookieProcessor(CookieJar()))
        self.last={}; self.records=[]; self.cache={}

    def get(self,url): return self.request(url)

    def request(self,url,method='GET',body=None,headers=None):
        if time.monotonic()>=self.deadline: raise SourceError('run_deadline','Source run exceeded bounded runtime')
        host=urlparse(url).hostname
        if urlparse(url).scheme!='https' or host not in self.hosts:
            raise SourceError('unapproved_host','Source attempted an unconfigured host')
        if len(self.records)>=self.max_requests: raise SourceError('request_budget','Per-run request budget exceeded')
        elapsed=time.monotonic()-self.last.get(host,0)
        if elapsed<self.pace: time.sleep(self.pace-elapsed)
        hdr={'User-Agent':'IndiaHotelRevenueRadar/0.1 (public careers monitoring)','Accept':'text/html,application/json','Accept-Encoding':'identity'}
        hdr.update(headers or {})
        encoded=json.dumps(body).encode() if isinstance(body,(dict,list)) else body
        if isinstance(body,(dict,list)): hdr['Content-Type']='application/json'
        for attempt in range(3):
            started=time.monotonic(); rec={'host':host,'path':urlparse(url).path,'method':method,'started_at':stamp()}
            try:
                with self.opener.open(Request(url,data=encoded,headers=hdr,method=method),timeout=self.timeout) as r:
                    if urlparse(r.url).hostname not in self.hosts: raise SourceError('redirect_host','Unconfigured redirect host')
                    raw=r.read(8_000_001)
                    if len(raw)>8_000_000: raise SourceError('oversized','Source response exceeds safety limit')
                    rec.update(status=r.status,bytes=len(raw),date=r.headers.get('Date'),age=r.headers.get('Age'),last_modified=r.headers.get('Last-Modified'),etag=r.headers.get('ETag'))
                    if r.headers.get('Age','').isdigit() and int(r.headers['Age'])>900:
                        raise SourceError('stale_cache','Source reports cached data over 15 minutes old')
                    return raw.decode('utf-8',errors='replace')
            except HTTPError as e:
                rec['status']=e.code
                if e.code==429:
                    value=e.headers.get('Retry-After','60')
                    try: retry=stamp(utcnow()+timedelta(seconds=int(value)))
                    except ValueError:
                        try: retry=stamp(parsedate_to_datetime(value))
                        except (ValueError,TypeError): retry=stamp(utcnow()+timedelta(minutes=5))
                    raise SourceError('rate_limited','Source rate limit; deferred until Retry-After',429,retry) from None
                if e.code in (401,403): raise SourceError('access_denied','Source denied public access',e.code) from None
                if e.code>=500 and attempt<2: time.sleep(0.5*(2**attempt)); continue
                raise SourceError('http_error',f'Source returned HTTP {e.code}',e.code) from None
            except (URLError,TimeoutError,socket.timeout) as e:
                rec['status']=0
                if attempt<2: time.sleep(0.5*(2**attempt)); continue
                raise SourceError('network_error','Source request failed after bounded retries') from None
            finally:
                rec['duration_ms']=round((time.monotonic()-started)*1000)
                self.last[host]=time.monotonic(); self.records.append(rec)

    def metrics(self):
        return {'request_count':len(self.records),'bytes_received':sum(r.get('bytes',0) for r in self.records),'duration_ms':sum(r['duration_ms'] for r in self.records),'hosts':{h:sum(r['host']==h for r in self.records) for h in self.hosts},'responses':self.records}
