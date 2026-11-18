from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib, json

def utcnow():
    return datetime.now(timezone.utc)

def stamp(value=None):
    return (value or utcnow()).astimezone(timezone.utc).isoformat(timespec='seconds')

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

@dataclass
class Job:
    external_id: str
    title: str
    url: str
    source_id: str
    employer: str
    hotel: str = ''
    location: str = ''
    country_code: str = ''
    requisition_id: str = ''
    posted_at: str = ''
    posted_precision: str = ''
    posted_raw: str = ''
    salary: str = ''
    employment_type: str = ''
    description: str = ''
    summary: str = ''
    namespace: str = ''
    detail_status: str = 'not_fetched'
    raw_identifiers: dict = field(default_factory=dict)

    def listing_hash(self):
        return fingerprint({k:getattr(self,k) for k in ('external_id','title','url','hotel','location','salary','summary')})

    def to_dict(self): return asdict(self)

@dataclass
class Snapshot:
    jobs: list[Job]
    expected_count: int
    pages: int
    complete: bool
    properties: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

class SourceError(Exception):
    def __init__(self,code,message,status=None,retry_after=None):
        super().__init__(message)
        self.code,self.status,self.retry_after=code,status,retry_after

class CatalogueInstability(SourceError):
    """Validated identities/pages disagree across a live catalogue traversal."""
    pass
