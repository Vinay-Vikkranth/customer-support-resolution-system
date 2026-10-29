import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .engine import POLICIES, decide, retrieve

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('RESOLVEDESK_DB', ROOT / 'data' / 'resolvedesk.db'))
DB.parent.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get('RESOLVEDESK_TOKEN') or secrets.token_urlsafe(32)
REVIEW_TOKEN = os.environ.get('RESOLVEDESK_REVIEW_TOKEN') or secrets.token_urlsafe(32)
if TOKEN == REVIEW_TOKEN:
    raise RuntimeError('Operator and reviewer credentials must be different')

@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def audit(con, ticket, event, actor, details):
    con.execute('INSERT INTO audit(ticket_id,event,actor,details,created) VALUES(?,?,?,?,?)',
                (ticket,event,actor,json.dumps(details),time.time()))

def initialize():
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT,plan TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY,account_id TEXT,name TEXT,status TEXT,reporting INTEGER);
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,title TEXT,body TEXT,account_id TEXT,member_id TEXT,feature TEXT,status TEXT DEFAULT 'open',created REAL);
        CREATE TABLE IF NOT EXISTS investigations(id INTEGER PRIMARY KEY,ticket_id INTEGER,action TEXT,reason TEXT,evidence TEXT,snapshot TEXT,status TEXT DEFAULT 'pending',created REAL,latency_ms REAL,draft TEXT,model_status TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,ticket_id INTEGER,event TEXT,actor TEXT,details TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        ''')
        if not c.execute('SELECT 1 FROM accounts').fetchone():
            c.executemany('INSERT INTO accounts VALUES(?,?,?,?)', [('acme','Acme Studio','pro','active'),('birch','Birch Works','basic','active'),('cedar','Cedar Labs','enterprise','past_due')])
            c.executemany('INSERT INTO members VALUES(?,?,?,?,?)', [('alex','acme','Alex Morgan','active',0),('jules','acme','Jules Chen','active',1),('sam','birch','Sam Rivera','active',0),('robin','cedar','Robin Lee','active',0),('taylor','acme','Taylor Reed','suspended',0)])
            c.execute("INSERT INTO settings VALUES('incident','false')")
            c.executemany('INSERT INTO tickets(title,body,account_id,member_id,feature,created) VALUES(?,?,?,?,?,?)', [
                ('Reporting disappeared after upgrade','Our Pro subscription is active but Alex cannot open reports.','acme','alex','reporting',time.time()),
                ('Please enable reports','We would like reporting on our Basic plan.','birch','sam','reporting',time.time()),
                ('Cannot view the dashboard','Reporting is unavailable to Robin.','cedar','robin','reporting',time.time())])

initialize()
app = FastAPI(title='ResolveDesk', version='1.0.0', description='Synthetic support resolution pilot. All mutations require explicit reviewer authorization.')

def identity(authorization: str = Header(default='')):
    value = authorization.removeprefix('Bearer ')
    if secrets.compare_digest(value, REVIEW_TOKEN): return 'reviewer'
    if secrets.compare_digest(value, TOKEN): return 'operator'
    raise HTTPException(401, 'Valid operator or reviewer token required')

def reviewer(actor=Depends(identity)):
    if actor != 'reviewer': raise HTTPException(403, 'Reviewer approval required')
    return actor

@app.middleware('http')
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
    response.headers['Cache-Control'] = 'no-store'
    return response

class Ticket(BaseModel):
    title: str = Field(min_length=3,max_length=160)
    body: str = Field(min_length=5,max_length=5000)
    account_id: str = Field(max_length=80)
    member_id: str = Field(max_length=80)
    feature: str = Field(default='reporting',max_length=80)

class Decision(BaseModel):
    decision: Literal['approve','reject']

class Incident(BaseModel):
    active: bool

def row(c, table, key):
    # Table names are internal constants, never request input.
    r = c.execute(f'SELECT * FROM {table} WHERE id=?',(key,)).fetchone()
    return dict(r) if r else None

def snapshot(c,t):
    return {'account':row(c,'accounts',t['account_id']), 'member':row(c,'members',t['member_id']),
            'incident':c.execute("SELECT value FROM settings WHERE key='incident'").fetchone()[0]=='true'}

def digest(s): return hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()

def draft_response(reason, evidence):
    key = os.environ.get('OPENAI_API_KEY')
    fallback = f'Investigation result: {reason} Reference: '+', '.join(p['id'] for p in evidence)+'.'
    if not key: return fallback, 'rules_only'
    try:
        with httpx.Client(timeout=20) as client:
            r=client.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':f'Bearer {key}'},json={
                'model':os.environ.get('OPENAI_MODEL','gpt-4.1-mini'),
                'messages':[{'role':'system','content':'Draft a concise support reply from the supplied verified facts. Cite the policy IDs. Do not claim any action has been executed. You cannot authorize actions.'},
                            {'role':'user','content':json.dumps({'verified_finding':reason,'policies':evidence})}], 'max_completion_tokens':300})
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content'], 'llm_draft'
    except (httpx.HTTPError,KeyError,ValueError,IndexError):
        return fallback, 'llm_unavailable_fallback'

@app.get('/health')
def health(): return {'status':'ok','environment':'synthetic sandbox'}

@app.get('/api/bootstrap')
def bootstrap(actor=Depends(identity)):
    with db() as c:
        return {'role':actor,'accounts':[dict(r) for r in c.execute('SELECT * FROM accounts')],
                'members':[dict(r) for r in c.execute('SELECT * FROM members')], 'policies':POLICIES,
                'incident':c.execute("SELECT value FROM settings WHERE key='incident'").fetchone()[0]=='true'}

@app.get('/api/tickets')
def tickets(actor=Depends(identity)):
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM tickets ORDER BY id DESC')]

@app.post('/api/tickets',status_code=201)
def create_ticket(t:Ticket,actor=Depends(identity)):
    with db() as c:
        a=row(c,'accounts',t.account_id); m=row(c,'members',t.member_id)
        if not a or not m or m['account_id']!=a['id']: raise HTTPException(422,'Account/member mismatch')
        cur=c.execute('INSERT INTO tickets(title,body,account_id,member_id,feature,created) VALUES(?,?,?,?,?,?)',(*t.model_dump().values(),time.time()))
        audit(c,cur.lastrowid,'ticket_created',actor,{})
        return row(c,'tickets',cur.lastrowid)

@app.get('/api/tickets/{tid}')
def detail(tid:int,actor=Depends(identity)):
    with db() as c:
        t=row(c,'tickets',tid)
        if not t: raise HTTPException(404,'Ticket not found')
        runs=[dict(r) for r in c.execute('SELECT * FROM investigations WHERE ticket_id=? ORDER BY id DESC',(tid,))]
        for r in runs: r['evidence']=json.loads(r['evidence'])
        return {'ticket':t,'context':snapshot(c,t),'investigations':runs,'audit':[dict(r) for r in c.execute('SELECT * FROM audit WHERE ticket_id=? ORDER BY id DESC',(tid,))]}

@app.post('/api/tickets/{tid}/investigate')
def investigate(tid:int,actor=Depends(identity)):
    start=time.perf_counter()
    with db() as c:
        t=row(c,'tickets',tid)
        if not t: raise HTTPException(404,'Ticket not found')
        if t['status']=='resolved': raise HTTPException(409,'Ticket already resolved')
        s=snapshot(c,t)
    action,reason,ids=decide(s['account'],s['member'],t['feature'],s['incident'])
    retrieved=retrieve(t['title']+' '+t['body'])
    evidence=[p for p in POLICIES if p['id'] in ids or p in retrieved]
    draft,mode=draft_response(reason,evidence)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if row(c,'tickets',tid)['status']=='resolved': raise HTTPException(409,'Ticket resolved during investigation')
        c.execute("UPDATE investigations SET status='superseded' WHERE ticket_id=? AND status='pending'",(tid,))
        cur=c.execute('INSERT INTO investigations(ticket_id,action,reason,evidence,snapshot,created,latency_ms,draft,model_status) VALUES(?,?,?,?,?,?,?,?,?)',
                      (tid,action,reason,json.dumps(evidence),digest(s),time.time(),round((time.perf_counter()-start)*1000,2),draft,mode))
        c.execute("UPDATE tickets SET status='awaiting_review' WHERE id=?",(tid,))
        audit(c,tid,'investigated',actor,{'action':action,'run_id':cur.lastrowid,'model_status':mode})
        return {'id':cur.lastrowid,'action':action,'reason':reason,'evidence':evidence,'draft':draft,'model_status':mode}

@app.post('/api/investigations/{rid}/decision')
def approve(rid:int,decision:Decision,actor=Depends(reviewer)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        r=row(c,'investigations',rid)
        if not r: raise HTTPException(404,'Investigation not found')
        if r['status'] in ('approved','rejected'): return {'status':r['status'],'replayed':True}
        if r['status']!='pending': raise HTTPException(409,'Run superseded; investigate again')
        t=row(c,'tickets',r['ticket_id'])
        if decision.decision=='reject':
            c.execute("UPDATE investigations SET status='rejected' WHERE id=?",(rid,))
            c.execute("UPDATE tickets SET status='open' WHERE id=?",(t['id'],))
            audit(c,t['id'],'rejected',actor,{'run_id':rid})
            return {'status':'rejected'}
        s=snapshot(c,t)
        if digest(s)!=r['snapshot']: raise HTTPException(409,'Account state changed; investigate again')
        action,_,_=decide(s['account'],s['member'],t['feature'],s['incident'])
        if action!=r['action']: raise HTTPException(409,'Policy decision changed')
        if action=='restore_reporting':
            c.execute('UPDATE members SET reporting=1 WHERE id=?',(t['member_id'],))
            verified=bool(row(c,'members',t['member_id'])['reporting'])
            if not verified: raise HTTPException(500,'Verification failed; transaction rolled back')
            status='resolved'
        else: status='escalated'
        c.execute('UPDATE tickets SET status=? WHERE id=?',(status,t['id']))
        c.execute("UPDATE investigations SET status='approved' WHERE id=?",(rid,))
        audit(c,t['id'],'approved_and_verified' if status=='resolved' else 'escalated',actor,{'run_id':rid,'action':action,'status':status})
        return {'status':'approved','ticket_status':status,'verified':status=='resolved'}

@app.post('/api/sandbox/incident')
def incident(value:Incident,actor=Depends(reviewer)):
    with db() as c:
        c.execute("UPDATE settings SET value=? WHERE key='incident'",('true' if value.active else 'false',))
        audit(c,None,'incident_changed',actor,{'active':value.active})
    return value

@app.get('/api/metrics')
def metrics(actor=Depends(identity)):
    with db() as c:
        return {'tickets':c.execute('SELECT COUNT(*) FROM tickets').fetchone()[0],
                'resolved':c.execute("SELECT COUNT(*) FROM tickets WHERE status='resolved'").fetchone()[0],
                'awaiting_review':c.execute("SELECT COUNT(*) FROM tickets WHERE status='awaiting_review'").fetchone()[0],
                'investigations':c.execute('SELECT COUNT(*) FROM investigations').fetchone()[0],
                'mean_latency_ms':c.execute('SELECT ROUND(AVG(latency_ms),2) FROM investigations').fetchone()[0] or 0}

app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
@app.get('/')
def home(): return FileResponse(ROOT/'web'/'index.html')
