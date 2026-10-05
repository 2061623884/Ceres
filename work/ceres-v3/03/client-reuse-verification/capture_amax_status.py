import datetime, json, pathlib, platform, subprocess, sys, time
out=pathlib.Path(__file__).resolve().parent
remote="set -u; root=/data/amax/services/ceres-kev4b-probe-20261005; printf 'utc_now='; date -u +%Y-%m-%dT%H:%M:%S.%NZ; printf 'pidfile='; cat \"$root/server.pid\"; printf 'process\\n'; ps -p 2701504 -o pid=,stat=,etime=,pcpu=,pmem=,args=; printf 'listener\\n'; ss -ltnp | grep -E '(:|\\])8009[[:space:]]' || true; printf 'gpu1\\n'; nvidia-smi --id=GPU-5165b827-1b01-e6f0-d147-38e565ee823f --query-gpu=index,uuid,memory.used,memory.free,utilization.gpu --format=csv,noheader; nvidia-smi --id=GPU-5165b827-1b01-e6f0-d147-38e565ee823f --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader; printf 'server_log_stat\\n'; stat -c 'size_bytes=%s mtime=%y' \"$root/server.log\"; printf 'post_count='; grep -c 'POST /v1/systemone' \"$root/server.log\" || true; printf 'server_log_tail\\n'; tail -n 30 \"$root/server.log\""
argv=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','amax',remote]
start=datetime.datetime.now(datetime.timezone.utc); tick=time.perf_counter()
r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace')
rec={'event':'amax_service_status_after_shared_provider_validation','argv':argv,'remote_command':remote,'cwd':str(pathlib.Path.cwd()),'python':sys.executable,'platform':platform.platform(),'started_utc':start.isoformat(),'duration_seconds':round(time.perf_counter()-tick,3),'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
(out/'amax-status-after-shared-provider.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'exit_code':rec['exit_code'],'duration_seconds':rec['duration_seconds'],'stdout':rec['stdout'],'stderr':rec['stderr'],'evidence':str(out/'amax-status-after-shared-provider.json')},ensure_ascii=False))
raise SystemExit(r.returncode)
