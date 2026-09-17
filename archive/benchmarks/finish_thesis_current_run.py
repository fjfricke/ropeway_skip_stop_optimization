"""Record a supervised in-flight result and leave its campaign paused."""
import argparse
import json
from pathlib import Path
import time
import psutil
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--created',type=float,required=True)
    parser.add_argument('--job',required=True)
    args=parser.parse_args()
    while True:
        try:
            process=psutil.Process(args.pid)
            alive=abs(process.create_time()-args.created)<0.01 and process.status()!=psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive=False
        if not alive:break
        time.sleep(1)
    path=args.campaign/'campaign.json';state=json.loads(path.read_text())
    entry=next(j for j in reversed(state['jobs']) if j['id']==args.job)
    result=Path(entry['result']);supervisor=result.parent/'supervisor.json'
    metrics=json.loads(supervisor.read_text()) if supervisor.exists() else {}
    success=result.exists() and metrics.get('exit_code')==0 and not metrics.get('supervisor_reason')
    entry.update(status='complete' if success else 'failed',exit_code=metrics.get('exit_code'),
        wall_seconds=metrics.get('civil_wall_seconds',time.time()-entry['started_epoch']))
    state.update(status='paused',pause_reason='User requested pause after relative-load series',paused_epoch=time.time(),
        pending_series=['constant_k31_demand'])
    atomic_json(path,state)


if __name__=='__main__':main()
