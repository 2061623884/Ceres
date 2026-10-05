#!/usr/bin/env bash
set -euo pipefail
probe_root=/data/amax/services/ceres-kev4b-probe-20261005
cd "$probe_root/upstream"
export CUDA_VISIBLE_DEVICES=GPU-5165b827-1b01-e6f0-d147-38e565ee823f
export KEV_BACKEND=torch
export KEV_DTYPE=fp32
export KEV_CUDA_GRAPHS=0
export KEV_FUSED=0
export KEV_PREFIX_CACHE=0
export HF_HUB_CACHE="$probe_root/amax-direct-download/hub"
export HF_HUB_OFFLINE=1
nohup .venv/bin/python -u -m kev.serve --run jaredpalmer/kev-4b@139fdd94f1b6a6ad80cc15e08fcb99cac885a101 --host 127.0.0.1 --port 8009 > "$probe_root/server.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$probe_root/server.pid"
cat "$probe_root/server.pid"
