from sqlalchemy import Column,Float,Index,Integer,String
from src.config.database import Base
class TelemetryVersion(Base):
 __tablename__='telemetry_versions'
 record_id=Column(Integer,primary_key=True)
 version=Column(Integer,primary_key=True)
 recorded_at=Column(String(30),nullable=False)
 sensor_id=Column(Integer,nullable=False)
 device_type=Column(String(40),nullable=False)
 value=Column(Float,nullable=False)
 __table_args__=(Index('ix_telemetry_versions_order','recorded_at','record_id'),)
class PagePin(Base):
 __tablename__='page_pins'
 snapshot=Column(Integer,primary_key=True)
 expires_at=Column(Float,nullable=False)
class MetaKV(Base):
 __tablename__='meta_kv'
 key=Column(String(40),primary_key=True)
 value=Column(String(200),nullable=False)
