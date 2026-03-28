#!/bin/bash
# Auto-start vLLM server for Tenstorrent Backend.AI sessions
# Skip if running as inference session (Backend.AI handles startup via model-definition.yaml)
if [ -n "$BACKENDAI_SERVICE_NAME" ]; then
    echo "[tt-vllm] Inference session detected, skipping auto-start (managed by Backend.AI)"
    exit 0
fi

VENV=/home/container_app_user/tt-metal/python_env
APP_DIR=/home/container_app_user/app/src
CACHE=/home/container_app_user/cache
MODEL_SPEC=/home/container_app_user/cache/model_spec.json

# Skip if no model spec
if [ ! -f "$MODEL_SPEC" ]; then
    echo "[tt-vllm] No model spec found at $MODEL_SPEC, skipping vLLM auto-start"
    exit 0
fi

# Setup environment
source "$VENV/bin/activate"
unset PYTHONHOME

# Load HF token from cache if available
if [ -f "$CACHE/.hf_token" ]; then
    export HF_TOKEN=$(cat "$CACHE/.hf_token")
fi
export TT_METAL_HOME=/home/container_app_user/tt-metal
export PYTHONPATH=$TT_METAL_HOME:$APP_DIR:$PYTHONPATH
export CACHE_ROOT=$CACHE
export TT_CACHE_PATH=$CACHE/tt_metal_cache/P100
export MESH_DEVICE=P100
export ARCH_NAME=blackhole
export VLLM_TARGET_DEVICE=tt
export VLLM_RPC_TIMEOUT=900000

# Read model weights path from model spec
export MODEL_WEIGHTS_PATH=$(python3 -c "
import json, os
with open('$MODEL_SPEC') as f:
    spec = json.load(f)
hf_repo = spec['hf_model_repo']
print(f'$CACHE/model_weights/{hf_repo}')
")
export TT_MODEL_SPEC_JSON_PATH=$MODEL_SPEC

mkdir -p "$TT_CACHE_PATH" "$MODEL_WEIGHTS_PATH"

echo "[tt-vllm] Starting vLLM server..."
cd "$APP_DIR"
nohup python3 run_vllm_api_server.py > /tmp/vllm.log 2>&1 &
echo "[tt-vllm] vLLM PID: $!"
