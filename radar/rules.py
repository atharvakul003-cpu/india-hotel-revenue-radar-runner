"""India geography and hotel revenue-role matching."""
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
RULE_VERSION = 'india-revenue/1'
INDIA = re.compile(r'\b(india|andhra pradesh|arunachal pradesh|assam|bihar|chhattisgarh|goa|gujarat|haryana|himachal pradesh|jharkhand|karnataka|kerala|madhya pradesh|maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|orissa|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|uttar pradesh|uttarakhand|west bengal|delhi|mumbai|pune|bengaluru|bangalore|hyderabad|kolkata|chennai|gurugram|gurgaon|noida|ahmedabad|jaipur|dehradun|kochi|cochin|bhubaneswar|visakhapatnam|surat|lucknow|chandigarh|nashik|nasik|indore|bhopal|vadodara|goa)\b', re.I)
ABROAD = re.compile(r'\b(united kingdom|great britain|england|scotland|wales|london|united states|usa|canada|singapore|dubai|uae|qatar|nepal|bhutan|thailand|france|germany|australia)\b', re.I)
HOTEL = re.compile(r'\b(hotel|hotels|resort|resorts|hospitality|rooms?|revpar|adr|occupancy|property|properties)\b', re.I)
REVENUE_DUTY = re.compile(r'\b(revpar|adr|occupancy|forecast(?:ing)?|pricing|yield|room\s+inventory|rate\s+strategy|demand|competitor|str\s+report|revenue\s+management|revenue\s+optimis[ae]|revenue\s+optimiz[ae])\b',re.I)
EXCLUDE_TITLE = re.compile(r'\b(sales|reservation|front\s+office|food|beverage|restaurant|account(?:ing|s)?|billing|finance|business\s+development|software|engineering|support|director|head|vice\s+president|chief|intern|trainee|general\s+manager)\b',re.I)
TARGET_TITLE = re.compile(r'\b(revenue|pricing|yield)\b',re.I)
LEVEL = re.compile(r'\b(analyst|associate|executive|specialist|assistant\s+manager|manager|optimisation|optimization)\b',re.I)

def parse_posted(raw):
    raw=(raw or '').strip()
    if not raw:return '',''
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):
            d=date.fromisoformat(raw)
            return (d.isoformat(),'date') if 2000<=d.year and d<=datetime.now(IST).date()+timedelta(days=1) else ('','')
        dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if 2000<=dt.year and dt.date()<=datetime.now(timezone.utc).date()+timedelta(days=1):
            return (dt.astimezone(timezone.utc).isoformat(timespec='seconds'),'timestamp') if dt.tzinfo else (dt.date().isoformat(),'date')
    except ValueError:pass
    return '',''

def india_location(job):
    cc=(job.country_code or '').strip().lower()
    loc=(job.location or '')+' '+(job.hotel or '')
    if cc in ('in','ind','india'):return True
    if cc and cc not in ('unknown','multiple locations'):return False
    if ABROAD.search(loc):return False
    if INDIA.search(loc):return True
    # Remote must explicitly allow an India-based worker.
    return bool(re.search(r'\bremote\b',loc,re.I) and re.search(r'\bindia\b',job.description or job.summary or '',re.I))

def revenue_role(job):
    title=job.title or ''
    if EXCLUDE_TITLE.search(title):return False
    desc=job.description or job.summary or ''
    if TARGET_TITLE.search(title) and LEVEL.search(title):
        if re.search(r'\b(revenue\s+(?:operations|accounting|assurance|cycle|recognition)|tax\s+revenue)\b',title+' '+desc,re.I):return False
        # A hotel employer plus a title explicitly in hotel revenue is enough for listing-only feeds.
        return bool(HOTEL.search(desc+' '+job.employer+' '+job.hotel) or job.source_id in ('marriott','accor','hilton','hyatt','ihg','ihcl','fern','sarovar','suba','nile','aman','revgrow','hospitality_minds','revnomix','atica'))
    if re.search(r'\b(distribution|e[ -]?commerce|commercial|ota)\b',title,re.I):
        return bool(HOTEL.search(desc) and len(REVENUE_DUTY.findall(desc))>=3 and re.search(r'\b(analyst|executive|manager|specialist|associate)\b',title,re.I))
    return False

def relevant(job):return india_location(job) and revenue_role(job)
