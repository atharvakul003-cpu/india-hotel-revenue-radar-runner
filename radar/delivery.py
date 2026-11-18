"""Gmail send-only delivery, with pre-send claim to prevent replay after crashes."""
import base64,hashlib,json,os
from email.message import EmailMessage
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .models import stamp

def message(payload,event_id,sender,recipient,first_detected=None):
    msg=EmailMessage();msg['From']=sender;msg['To']=recipient
    msg['Subject']=f"[India Revenue Radar] New Vacancy — {payload['title']} — {payload['employer']} — {payload.get('location') or 'India'}"
    msg['Message-ID']='<india-radar-'+hashlib.sha256(event_id.encode()).hexdigest()+'@gmail.com>'
    msg['X-India-Revenue-Radar-Event']=hashlib.sha256(event_id.encode()).hexdigest()
    msg.set_content('\n'.join([f"Employer: {payload['employer']}",f"Title: {payload['title']}",f"Location: {payload.get('location') or 'India'}",f"Original posting date: {payload.get('posted_at') or 'Not provided'}",f"First detected: {first_detected or stamp()}",f"Employment type: {payload.get('employment_type') or 'Not provided'}",f"Source: {payload['source_id']}",'',f"Apply: {payload['url']}"]))
    return msg

def send_gmail(msg):
    fields={k:os.environ.get(k) for k in ('GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN')}
    if not all(fields.values()):raise RuntimeError('India Gmail secrets missing')
    body=urlencode({'client_id':fields['GMAIL_CLIENT_ID'],'client_secret':fields['GMAIL_CLIENT_SECRET'],'refresh_token':fields['GMAIL_REFRESH_TOKEN'],'grant_type':'refresh_token'}).encode()
    with urlopen(Request('https://oauth2.googleapis.com/token',data=body),timeout=20) as response:token=json.load(response)['access_token']
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
    req=Request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',data=json.dumps({'raw':raw}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=20) as response:return json.load(response)['id']

def dispatch(state,checkpoint,limit=20):
    sender=os.environ.get('INDIA_RADAR_SENDER','');recipient=os.environ.get('INDIA_RADAR_RECIPIENT','')
    if not sender or not recipient:raise RuntimeError('India sender/recipient not configured')
    pending=list(state.db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY created_at LIMIT ?",(limit,)))
    results=[]
    for row in pending:
        event=row['event_id'];payload=json.loads(row['payload_json'])
        with state.db:state.db.execute("UPDATE outbox SET status='sending' WHERE event_id=? AND status='pending'",(event,))
        checkpoint() # A failed checkpoint prevents send.
        try:
            provider_id=send_gmail(message(payload,event,sender,recipient,row['created_at']))
        except Exception as exc:
            # Ambiguous network responses are held; never automatically resend.
            with state.db:state.db.execute("UPDATE outbox SET status='held',error=? WHERE event_id=?",(type(exc).__name__,event))
            checkpoint();results.append({'event':event,'status':'held'});continue
        with state.db:state.db.execute("UPDATE outbox SET status='sent',sent_at=?,provider_id=? WHERE event_id=?",(stamp(),provider_id,event))
        checkpoint();results.append({'event':event,'status':'sent'})
    return results
