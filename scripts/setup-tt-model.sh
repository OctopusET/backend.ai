#!/usr/bin/env bash
# Setup Tenstorrent model cache, model spec, and model-definition.yaml
# Run after: make init && make up (storage proxy must be running)
#
# Usage:
#   make model                                              # default: Llama-3.1-8B-Instruct
#   make model MODEL=Qwen/Qwen2.5-7B-Instruct             # custom model
#   HF_TOKEN=hf_xxx make model MODEL=meta-llama/Llama-3.1-8B-Instruct  # gated model
set -euo pipefail

BA_HOME="${BA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/backendai}"
CACHE_DIR="${CACHE_DIR:-${BA_HOME}/cache/tt}"
MODEL_NAME="${MODEL_NAME:-meta-llama/Llama-3.1-8B-Instruct}"
MODEL_SHORT="${MODEL_NAME##*/}"
DEVICE="${DEVICE:-P100}"
VFOLDER_BASE="${VFOLDER_BASE:-${BA_HOME}/vfolders/volume1}"
CONTAINER_CACHE="/home/container_app_user/cache"

echo "=== Setting up TT model: $MODEL_NAME ==="

# --- 1. Download model weights ---
MODEL_DIR="$CACHE_DIR/model_weights/$MODEL_NAME"
mkdir -p "$CACHE_DIR/model_weights" "$CACHE_DIR/tt_metal_cache/$DEVICE" "$CACHE_DIR/logs"

if [ ! -f "$MODEL_DIR/config.json" ]; then
    echo "Downloading $MODEL_NAME..."
    if command -v hf &>/dev/null; then
        hf download "$MODEL_NAME" --local-dir "$MODEL_DIR"
    elif command -v huggingface-cli &>/dev/null; then
        huggingface-cli download "$MODEL_NAME" --local-dir "$MODEL_DIR"
    else
        echo "ERROR: hf or huggingface-cli not found."
        echo "Install with: pip install huggingface-hub"
        exit 1
    fi
else
    echo "Model weights already present at $MODEL_DIR"
fi

# --- 2. Generate model spec JSON ---
CONTAINER_MODEL_DIR="$CONTAINER_CACHE/model_weights/$MODEL_NAME"
cat > "$CACHE_DIR/model_spec.json" << SPECEOF
{
  "model_id": "id_tt-transformers_${MODEL_SHORT}_${DEVICE,,}",
  "hf_model_repo": "$CONTAINER_MODEL_DIR",
  "model_name": "$MODEL_SHORT",
  "inference_engine": "vLLM",
  "device_type": "$DEVICE",
  "device_model_spec": {
    "device": "$DEVICE",
    "max_concurrency": 32,
    "max_context": 2048,
    "vllm_args": {
      "model": "$CONTAINER_MODEL_DIR",
      "block_size": "64",
      "max_model_len": "2048",
      "max_num_seqs": "32",
      "max_num_batched_tokens": "2048",
      "num_scheduler_steps": "10",
      "seed": "9472",
      "override_tt_config": "{\"trace_region_size\": 30000000}"
    },
    "env_vars": {
      "MESH_DEVICE": "$DEVICE",
      "ARCH_NAME": "blackhole"
    }
  },
  "env_vars": {
    "VLLM_CONFIGURE_LOGGING": "1",
    "VLLM_RPC_TIMEOUT": "900000",
    "VLLM_TARGET_DEVICE": "tt",
    "MESH_DEVICE": "$DEVICE",
    "ARCH_NAME": "blackhole"
  },
  "model_type": "LLM"
}
SPECEOF
echo "Model spec: $CACHE_DIR/model_spec.json"

# --- 3. Save HF token ---
if [ -n "${HF_TOKEN:-}" ]; then
    echo "$HF_TOKEN" > "$CACHE_DIR/.hf_token"
    echo "HF token saved"
fi

# --- 4. Generate model-definition.yaml in vfolder ---
# Find the first model vfolder directory (created by WebUI)
VFOLDER_DIR=$(find "$VFOLDER_BASE" -name 'model-definition.yaml' -exec dirname {} \; 2>/dev/null | head -1)

if [ -z "$VFOLDER_DIR" ]; then
    echo ""
    echo "NOTE: No model vfolder found yet."
    echo "Create a Models folder in WebUI first, then run 'make model' again."
    echo "Or create it manually:"
    echo "  mkdir -p $VFOLDER_BASE/models"
    VFOLDER_DIR="$VFOLDER_BASE/models"
    mkdir -p "$VFOLDER_DIR"
fi

cat > "$VFOLDER_DIR/model-definition.yaml" << DEFEOF
models:
  - name: "$MODEL_SHORT"
    model_path: "$CONTAINER_CACHE/model_weights/$MODEL_NAME"
    service:
      start_command: "unset PYTHONHOME && export PATH=/home/container_app_user/tt-metal/python_env/bin:\$PATH && export HF_HUB_OFFLINE=1 && export TT_METAL_HOME=/home/container_app_user/tt-metal && export PYTHONPATH=/home/container_app_user/tt-metal:/home/container_app_user/app/src:/home/container_app_user/app && export CACHE_ROOT=$CONTAINER_CACHE && export TT_CACHE_PATH=$CONTAINER_CACHE/tt_metal_cache/$DEVICE && export MODEL_WEIGHTS_PATH=$CONTAINER_CACHE/model_weights/$MODEL_NAME && export TT_MODEL_SPEC_JSON_PATH=$CONTAINER_CACHE/model_spec.json && export MESH_DEVICE=$DEVICE && export ARCH_NAME=blackhole && export VLLM_TARGET_DEVICE=tt && export VLLM_RPC_TIMEOUT=900000 && cd /home/container_app_user/app/src && /home/container_app_user/tt-metal/python_env/bin/python3 run_vllm_api_server.py"
      port: 8000
DEFEOF
echo "Model definition: $VFOLDER_DIR/model-definition.yaml"

echo ""
echo "=== Model setup complete ==="
echo "  Model:   $MODEL_NAME"
echo "  Device:  $DEVICE"
echo "  Cache:   $CACHE_DIR"
echo ""
echo "Next: Create an inference service in WebUI"
echo "  1. Go to Serving > Start New Service"
echo "  2. Select 'vllm-backendai' image"
echo "  3. Mount the model folder"
echo "  4. Use 'tt-inference' preset"
echo "  5. Enable 'Open To Public' for chat access"
