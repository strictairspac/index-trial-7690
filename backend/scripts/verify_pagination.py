"""遥测翻页验收：同时间跨页 / 更正后重试 / 清理时翻页 / 凭据过期 / 重启续读。
默认在临时 SQLite 库上运行，不影响业务库；指向其他库请显式设置 DATABASE_URL。
  cd backend && python3 -m scripts.verify_pagination
"""
import os,sys,time
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('JWT_SECRET','verify-local')
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/verify_pagination.db')
from datetime import datetime,timedelta
from fastapi import HTTPException
from src.config.database import Base,engine,Session
from src.models.telemetry_page import TelemetryVersion
from src.schemas.business import PageBegin,PageNext,TelemetryWrite
from src.services import telemetry_pages as tp
BASE=datetime(2026,11,1)
def ts(i):return (BASE+timedelta(minutes=i)).isoformat(timespec='seconds')
def check(name,cond,detail=''):
 if not cond:raise AssertionError(f'{name} 失败: {detail}')
 print(f'  ✓ {name}')
def reset():
 tp.TTL=600;tp._SECRET=None
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
 tp.ensure_meta()
def write(rid,at,val,sensor=17):
 return tp.put(rid,TelemetryWrite(recorded_at=at,sensor_id=sensor,device_type='pump',value=float(val)))
def drain(items,cursor):
 out=list(items)
 while cursor:
  r=tp.next(PageNext(cursor=cursor));out+=r['items'];cursor=r['next_cursor']
 return out
def version_count():
 with Session() as s:return s.query(TelemetryVersion).count()
def same_timestamp_cross_page():
 print('场景1 同时间跨页（补录挤页）')
 reset()
 for i in range(25):write(1000+i,'2026-11-10T08:00:00',i)
 before=version_count()
 p=tp.begin(PageBegin(page_size=10))
 check('首屏返回10条并给出续页凭据',len(p['items'])==10 and p['next_cursor'])
 check('首屏不复制整份结果（版本表零写入）',version_count()==before)
 write(1099,'2026-11-10T08:00:00',99)
 write(1000,'2026-11-10T08:00:00',-1)
 items=drain(p['items'],p['next_cursor'])
 ids=[x['record_id'] for x in items]
 check('同一时间戳按记录号决胜翻完25条',ids==[1000+i for i in range(25)],ids)
 check('进行中翻页不受补录/更正影响',1099 not in ids and items[0]['value']==0)
 q=tp.begin(PageBegin(page_size=7));fresh=drain(q['items'],q['next_cursor'])
 check('新查询读到补录与更正',[x['record_id'] for x in fresh]==ids+[1099] and fresh[0]['value']==-1)
def correction_retry():
 print('场景2 更正后重试续页')
 reset()
 for i in range(10):write(2000+i,ts(i),i)
 p1=tp.begin(PageBegin(page_size=4));c1=p1['next_cursor']
 p2a=tp.next(PageNext(cursor=c1))
 write(2005,ts(5),555)
 write(2008,ts(8),888)
 p2b=tp.next(PageNext(cursor=c1))
 check('更正不等待翻页，重试拿到同一页',p2b['items']==p2a['items'])
 check('重试读数保持原样',{x['record_id']:x['value'] for x in p2b['items']}[2005]==5)
 p3=tp.next(PageNext(cursor=p2b['next_cursor']))
 check('后续页仍是首屏快照读数',{x['record_id']:x['value'] for x in p3['items']}[2008]==8)
 q=tp.begin(PageBegin(page_size=100))
 vals={x['record_id']:x['value'] for x in q['items']}
 check('新查询读到更正后的值',vals[2005]==555 and vals[2008]==888)
def gc_during_paging():
 print('场景3 清理时翻页')
 reset()
 for i in range(10):write(3000+i,ts(i),i)
 p1=tp.begin(PageBegin(page_size=4))
 write(3005,ts(5),500)
 write(3005,ts(5),555)
 write(3007,ts(7),777)
 stats=tp.gc()
 check('清理只删任何快照都看不到的中间版本',stats['deleted_versions']==1,stats)
 items=drain(p1['items'],p1['next_cursor'])
 vals={x['record_id']:x['value'] for x in items}
 check('清理后被钉住的旧版本仍可翻到',vals[3005]==5 and vals[3007]==7,vals)
 check('清理后版本表只剩可见版本',version_count()==12,version_count())
 q=tp.begin(PageBegin(page_size=100));fresh={x['record_id']:x['value'] for x in q['items']}
 check('清理后新查询读到最新值',fresh[3005]==555 and fresh[3007]==777)
def cursor_expiry():
 print('场景4 凭据过期明确拒绝')
 reset();tp.TTL=1
 for i in range(5):write(4000+i,ts(i),i)
 p=tp.begin(PageBegin(page_size=2))
 time.sleep(1.05)
 try:
  tp.next(PageNext(cursor=p['next_cursor']))
  raise SystemExit('过期凭据未被拒绝')
 except HTTPException as e:check('过期凭据返回410',e.status_code==410,e.status_code)
 bad=p['next_cursor'][:-1]+('0' if p['next_cursor'][-1]!='0' else '1')
 try:
  tp.next(PageNext(cursor=bad))
  raise SystemExit('篡改凭据未被拒绝')
 except HTTPException as e:check('篡改凭据返回400',e.status_code==400,e.status_code)
 write(4000,ts(0),999)
 stats=tp.gc()
 check('凭据过期后其快照版本可被清理',stats['deleted_versions']==1 and stats['pins_alive']==0,stats)
def restart_resume():
 print('场景5 服务重启后续读')
 reset()
 for i in range(8):write(5000+i,ts(i),i)
 p=tp.begin(PageBegin(page_size=3))
 write(5004,ts(4),444)
 tp._SECRET=None;engine.dispose()
 p2=tp.next(PageNext(cursor=p['next_cursor']))
 check('重启后凭据仍可验证续页',len(p2['items'])==3)
 check('重启后读数仍是快照原样',{x['record_id']:x['value'] for x in p2['items']}[5004]==4)
 items=drain(p2['items'],p2['next_cursor'])
 check('重启后翻到末页',[x['record_id'] for x in items]==[5000+i for i in range(8)][3:])
if __name__=='__main__':
 print(f'数据库: {os.environ["DATABASE_URL"]}')
 same_timestamp_cross_page();correction_retry();gc_during_paging();cursor_expiry();restart_resume()
 print('全部场景通过')
