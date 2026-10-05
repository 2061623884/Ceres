import datetime
import json
import pathlib
import platform
import subprocess
import sys
import time

root = pathlib.Path(__file__).resolve().parent
remote = "set -u; root=/data/amax/services/ceres-kev4b-probe-20261005; printf 'utc_now='; date -u +%Y-%m-%dT%H:%M:%S.%NZ; printf 'pidfile='; cat \"$root/server.pid\"; printf 'process\\n'; ps -p 2701504 -o pid=,stat=,etime=,pcpu=,pmem=,args=; printf 'listener\\n'; ss -ltnp | grep -E '(:|\\])8009[[:space:]]' || true; printf 'gpu1\\n'; nvidia-smi --id=GPU-5165b827-1b01-e6f0-d147-38e565ee823f --query-gpu=index,uuid,memory.used,memory.free,utilization.gpu --format=csv,noheader; nvidia-smi --id=GPU-5165b827-1b01-e6f0-d147-38e565ee823f --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader; printf 'server_log_stat\\n'; stat -c 'size_bytes=%s mtime=%y' \"$root/server.log\"; printf 'server_log_tail\\n'; tail -n 100 \"$root/server.log\"; printf 'server_log_request_error_lines\\n'; grep -nEi 'POST |ERROR|Traceback|timeout|HTTP/[0-9.]+ 5[0-9][0-9]' \"$root/server.log\" | tail -n 100 || true"
argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "amax", remote]
started = datetime.datetime.now(datetime.timezone.utc)
tick = time.perf_counter()
completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
record = {
    "event": "amax_server_and_gpu_status_readonly",
    "command_argv": argv,
    "remote_command": remote,
    "controller": {"cwd": str(pathlib.Path.cwd()), "python": sys.executable, "python_version": sys.version.replace("\n", " "), "platform": platform.platform()},
    "started_utc": started.isoformat(),
    "duration_seconds": round(time.perf_counter() - tick, 3),
    "exit_code": completed.returncode,
    "stdout": completed.stdout,
    "stderr": completed.stderr,
}
(root / "amax-server-gpu-status.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"exit_code": record["exit_code"], "duration_seconds": record["duration_seconds"], "stdout": record["stdout"], "stderr": record["stderr"], "evidence": str(root / "amax-server-gpu-status.json")}, ensure_ascii=False))
raise SystemExit(completed.returncode)
