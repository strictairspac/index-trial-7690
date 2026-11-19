import base64,hashlib,hmac,json,os,secrets,time
from fastapi import HTTPException
from sqlalchemy import and_,func,or_,tuple_,update
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.models.telemetry_page import MetaKV,PagePin,TelemetryVersion
TTL=int(os.getenv('PAGE_CURSOR_TTL','600'))
SEQ_KEY='telemetry_seq'
SECRET_KEY='page_cursor_secret'
_SECRET=None
def ensure_meta():
 with Session() as s:_ensure(s);s.commit()
def _ensure(s):
 for key,default in ((SEQ_KEY,'0'),(SECRET_KEY,secrets.token_hex(32))):
  if not s.get(MetaKV,key):
   try:
    with s.begin_nested():s.add(MetaKV(key=key,value=default))
   except IntegrityError:pass
def _seq(s):return int(s.get(MetaKV,SEQ_KEY).value)
def _lock(s):
 s.execute(update(MetaKV).where(MetaKV.key==SEQ_KEY).values(value=MetaKV.value))
def _get_secret():
 global _SECRET
 if not _SECRET:
  with Session() as s:_SECRET=s.get(MetaKV,SECRET_KEY).value
 return _SECRET
def _encode(payload):
 body=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode().rstrip('=')
 sig=hmac.new(bytes.fromhex(_get_secret()),body.encode(),hashlib.sha256).hexdigest()
 return body+'.'+sig
def _decode(token):
 try:body,sig=token.split('.')
 except ValueError:raise HTTPException(400,'翻页凭据无法识别，请重新发起首屏查询')
 expect=hmac.new(bytes.fromhex(_get_secret()),body.encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(sig,expect):raise HTTPException(400,'翻页凭据无法识别，请重新发起首屏查询')
 try:p=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
 except Exception:raise HTTPException(400,'翻页凭据无法识别，请重新发起首屏查询')
 ok=isinstance(p,dict) and isinstance(p.get('v'),int) and isinstance(p.get('n'),int) and isinstance(p.get('x'),(int,float)) and (p.get('p') is None or isinstance(p.get('p'),list)) and all(k in p for k in ('s','e'))
 if not ok:raise HTTPException(400,'翻页凭据无法识别，请重新发起首屏查询')
 return p
def _fetch(s,snap,start,end,last,size):
 visible=(s.query(TelemetryVersion.record_id,func.max(TelemetryVersion.version).label('v'))
  .filter(TelemetryVersion.version<=snap).group_by(TelemetryVersion.record_id).subquery())
 q=s.query(TelemetryVersion).join(visible,and_(TelemetryVersion.record_id==visible.c.record_id,TelemetryVersion.version==visible.c.v))
 if start:q=q.filter(TelemetryVersion.recorded_at>=start)
 if end:q=q.filter(TelemetryVersion.recorded_at<=end)
 if last:q=q.filter(or_(TelemetryVersion.recorded_at>last[0],and_(TelemetryVersion.recorded_at==last[0],TelemetryVersion.record_id>last[1])))
 rows=q.order_by(TelemetryVersion.recorded_at,TelemetryVersion.record_id).limit(size+1).all()
 return rows[:size],len(rows)>size
def _item(r):
 return {'record_id':r.record_id,'recorded_at':r.recorded_at,'sensor_id':r.sensor_id,'device_type':r.device_type,'value':r.value,'version':r.version}
def _page(snap,start,end,size,rows,more,exp):
 cursor=None
 if more:cursor=_encode({'v':snap,'p':[rows[-1].recorded_at,rows[-1].record_id],'s':start,'e':end,'n':size,'x':exp})
 return {'snapshot_version':snap,'expires_at':exp,'items':[_item(r) for r in rows],'next_cursor':cursor}
def begin(data):
 exp=time.time()+TTL
 with Session() as s:
  _ensure(s);_lock(s)
  snap=_seq(s)
  pin=s.get(PagePin,snap)
  if pin:pin.expires_at=max(pin.expires_at,exp)
  else:s.add(PagePin(snapshot=snap,expires_at=exp))
  s.commit()
 with Session() as s:rows,more=_fetch(s,snap,data.start_at,data.end_at,None,data.page_size)
 return _page(snap,data.start_at,data.end_at,data.page_size,rows,more,exp)
def next(data):
 p=_decode(data.cursor)
 if time.time()>=p['x']:raise HTTPException(410,'翻页凭据已过期，请重新发起首屏查询')
 snap=p['v'];exp=time.time()+TTL
 with Session() as s:
  _lock(s)
  pin=s.get(PagePin,snap)
  if not pin or pin.expires_at<=time.time():raise HTTPException(410,'翻页凭据已过期，请重新发起首屏查询')
  pin.expires_at=max(pin.expires_at,exp);s.commit()
 with Session() as s:rows,more=_fetch(s,snap,p['s'],p['e'],p['p'],p['n'])
 return _page(snap,p['s'],p['e'],p['n'],rows,more,exp)
def put(record_id,data):
 with Session() as s:
  _ensure(s)
  row=s.get(MetaKV,SEQ_KEY)
  ver=int(row.value)+1;row.value=str(ver)
  s.add(TelemetryVersion(record_id=record_id,version=ver,recorded_at=data.recorded_at,sensor_id=data.sensor_id,device_type=data.device_type,value=data.value))
  s.commit()
 return {'record_id':record_id,'version':ver}
def gc():
 with Session() as s:
  _lock(s)
  now=time.time()
  s.query(PagePin).filter(PagePin.expires_at<=now).delete(synchronize_session=False)
  pins=s.query(PagePin).all()
  snaps={p.snapshot for p in pins};snaps.add(_seq(s))
  keep=set()
  for snap in snaps:keep.update((r[0],r[1]) for r in s.query(TelemetryVersion.record_id,func.max(TelemetryVersion.version)).filter(TelemetryVersion.version<=snap).group_by(TelemetryVersion.record_id).all())
  obsolete=sorted({(r[0],r[1]) for r in s.query(TelemetryVersion.record_id,TelemetryVersion.version).all()}-keep)
  for i in range(0,len(obsolete),500):
   s.query(TelemetryVersion).filter(tuple_(TelemetryVersion.record_id,TelemetryVersion.version).in_(obsolete[i:i+500])).delete(synchronize_session=False)
  s.commit()
 return {'deleted_versions':len(obsolete),'active_snapshots':sorted(snaps),'pins_alive':len(pins)}
