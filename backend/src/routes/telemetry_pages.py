from fastapi import APIRouter,Depends
from src.middlewares.auth import current,writer
from src.schemas.business import PageBegin,PageNext,TelemetryWrite
from src.services import telemetry_pages
from src.controllers.business import gc_telemetry,write_telemetry
router=APIRouter()
@router.put('/telemetry/records/{record_id}')
def write(record_id:int,data:TelemetryWrite,u=Depends(writer)):return write_telemetry(record_id,data,u)
@router.post('/telemetry/pages')
def begin(data:PageBegin,u=Depends(current)):return telemetry_pages.begin(data)
@router.post('/telemetry/pages/next')
def follow(data:PageNext,u=Depends(current)):return telemetry_pages.next(data)
@router.post('/telemetry/pages/gc')
def clean(u=Depends(writer)):return gc_telemetry(u)
