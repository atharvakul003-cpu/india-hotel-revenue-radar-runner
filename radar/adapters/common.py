import json,re
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from lxml import html
from ..models import SourceError

def clean(value): return ' '.join((value or '').split())

def text_at(root,xpath): return clean(' '.join(e.text_content() if hasattr(e,'text_content') else str(e) for e in root.xpath(xpath)))

def canonical(url):
    p=urlsplit(url)
    query=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('source','src','ref','redirect','trid')]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urlencode(query),''))

def document(body):
    if not body.strip(): raise SourceError('empty_response','Empty response')
    try: d=html.fromstring(body)
    except (ValueError,html.etree.ParserError): raise SourceError('parse_error','Invalid source HTML') from None
    title=text_at(d,'(/html/head/title)[1]').lower()
    if any(x in title for x in ('just a moment','access denied','verify you are human','captcha')):
        raise SourceError('challenge','Source returned a challenge page')
    return d

def jobposting(d):
    def visit(item):
        if isinstance(item,list):
            for x in item:
                yield from visit(x)
        elif isinstance(item,dict):
            t=item.get('@type',[])
            if t=='JobPosting' or isinstance(t,list) and 'JobPosting' in t: yield item
            yield from visit(item.get('@graph',[]))
    for raw in d.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            for j in visit(json.loads(raw)): return j
        except (ValueError,TypeError): continue
    return None

def enrich_structured(job,body):
    from ..rules import parse_posted
    d=document(body); j=jobposting(d)
    if not j:
        job.detail_status='no_structured_data'
        job.description=text_at(d,'//*[contains(@class,"job-description")]') or job.summary
        return job
    if clean(j.get('title')): job.title=clean(j['title'])
    job.posted_raw=str(j.get('datePosted') or '')
    job.posted_at,job.posted_precision=parse_posted(job.posted_raw)
    job.employment_type=clean(' '.join(j.get('employmentType',[])) if isinstance(j.get('employmentType'),list) else j.get('employmentType'))
    desc=j.get('description','')
    job.description=clean(html.fromstring('<div>'+desc+'</div>').text_content()) if desc else job.summary
    loc=j.get('jobLocation',{})
    if isinstance(loc,list): loc=loc[0] if len(loc)==1 else {}
    address=loc.get('address',{}) if isinstance(loc,dict) else {}
    country=address.get('addressCountry','')
    if isinstance(country,dict): country=country.get('name','')
    job.country_code=clean(country)
    job.location=clean(', '.join(str(address.get(k) or '') for k in ('addressLocality','addressRegion') if address.get(k))) or job.location
    org=j.get('hiringOrganization',{})
    if not job.hotel and isinstance(org,dict): job.hotel=clean(org.get('name'))
    job.salary=job.salary or clean(j.get('jobBenefits',''))
    ident=j.get('identifier')
    if isinstance(ident,dict) and ident.get('value'): job.raw_identifiers['structured']=str(ident['value'])
    job.detail_status='verified'
    return job

