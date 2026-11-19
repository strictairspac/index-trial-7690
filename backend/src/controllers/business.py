from src.services import workloads,candidates,experiments,telemetry_pages
from src.services.audit import log
def save_workload(data,user,item_id=None):
 row=workloads.save(data,item_id);log(user.email,'workload.save',row['name']);return row
def save_candidate(data,user,item_id=None):
 row=candidates.save(data,item_id);log(user.email,'candidate.save',row['name']);return row
def start_experiment(data,user):
 row=experiments.create(data);log(user.email,'experiment.queue',row['name']);return row
def write_telemetry(record_id,data,user):
 row=telemetry_pages.put(record_id,data);log(user.email,'telemetry.write',f"record={record_id} v{row['version']}");return row
def gc_telemetry(user):
 stats=telemetry_pages.gc();log(user.email,'telemetry.gc',f"deleted={stats['deleted_versions']}");return stats
