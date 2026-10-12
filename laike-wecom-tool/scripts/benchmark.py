"""启动独立临时实例，只压入合成留资，不连接或发送任何外部业务数据。"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import requests


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,default=1000);args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='laike-benchmark-') as directory:
        env={**os.environ,'ADMIN_PASSWORD':'Benchmark-only-20261012!','COOKIE_SECURE':'false'}
        process=subprocess.Popen([sys.executable,'-X','utf8','run.py','--port',str(port),'--data-dir',directory],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        measured=psutil.Process(process.pid);base=f'http://127.0.0.1:{port}';session=requests.Session()
        def tree():
            return [measured,*measured.children(recursive=True)]
        def rss():
            return sum(p.memory_info().rss for p in tree() if p.is_running())
        def cpu_time():
            return sum(p.cpu_times().user+p.cpu_times().system for p in tree() if p.is_running())
        try:
            for _ in range(100):
                try:
                    if session.get(base+'/health',timeout=1).ok:break
                except requests.RequestException:pass
                if process.poll() is not None:raise RuntimeError('独立实例未能启动')
                time.sleep(.1)
            login=session.post(base+'/api/login',json={'username':'admin','password':env['ADMIN_PASSWORD']},timeout=10);login.raise_for_status()
            csrf={'X-CSRF-Token':login.json()['csrf']}
            session.post(base+'/api/enterprises',json={'account_id':'900001','name':'资源检查合成企业','enabled':True},headers=csrf).raise_for_status()
            session.post(base+'/api/stores',json={'enterprise_id':1,'poi_id':'p1','name':'合成门店','group_id':'fixture-group','group_name':'仅供离线压测','enabled':True},headers=csrf).raise_for_status()
            token=session.post(base+'/api/connection-token/ingest',json={},headers=csrf).json()['token']
            cpu_start=cpu_time();idle_start=time.perf_counter();time.sleep(8)
            idle_cpu=(cpu_time()-cpu_start)/(time.perf_counter()-idle_start)*100
            idle_rss=rss();peak=idle_rss
            started=time.perf_counter()
            for i in range(args.count):
                event={'type':'new_lead','account_id':'900001','poi_id':'p1','record_id':f'FIXTURE-{i}', 'event_time':time.time(),
                       'data':{'customer':'合成客户','phone':'13800000000','intent':'合成护理项目'}}
                response=session.post(base+'/api/ingest',json=event,headers={'Authorization':'Bearer '+token},timeout=10)
                response.raise_for_status()
                if i%100==0:peak=max(peak,rss())
            elapsed=time.perf_counter()-started
            latest=session.get(base+'/api/dashboard').json()
            durations=[]
            for _ in range(5):
                before=time.perf_counter();session.get(base+'/api/dashboard').raise_for_status();durations.append((time.perf_counter()-before)*1000)
            traffic=len(session.get(base+'/api/dashboard').content)+len(session.get(base+'/api/messages?page_size=6').content)
            result={'environment':'本机 Windows / Python '+sys.version.split()[0], 'cpu_limit_applied':False,
                    'synthetic_events':args.count,'queued':latest['counts'].get('pending',0),
                    'seconds':round(elapsed,2),'events_per_second':round(args.count/elapsed,1),
                    'idle_rss_mib':round(idle_rss/1048576,1),'observed_peak_rss_mib':round(peak/1048576,1),
                    'idle_cpu_percent':round(idle_cpu,2),'dashboard_average_ms':round(sum(durations)/len(durations),1),
                    'dashboard_poll_bytes_uncompressed':traffic,'database_bytes':latest['db_bytes'],'checked_at':time.strftime('%Y-%m-%d %H:%M:%S')}
            (root/'artifacts').mkdir(exist_ok=True)
            (root/'artifacts'/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2))
        finally:
            members=tree()
            for member in reversed(members):
                try:member.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(members,timeout=10)
            for member in alive:member.kill()
            psutil.wait_procs(alive,timeout=5)
            process.wait(timeout=5)


if __name__=='__main__':main()
