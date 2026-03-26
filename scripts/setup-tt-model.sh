#!/usr/bin/env bash
# Setup Tenstorrent model cache and model-definition.yaml
# Run after init + storage proxy is up.
# Requires: HF_TOKEN (for gated models), CACHE_DIR, MODEL_NAME
set -euo pipefail

CACHE_DIR="${CACHE_DIR:-/opt/backendai/cache/tt}"
MODEL_NAME="${MODEL_NAME:-meta-llama/Llama-3.1-8B-Instruct}"
MODEL_SHORT="${MODEL_NAME##*/}"
DEVICE="${DEVICE:-P100}"

echo "=== Setting up TT model cache ==="
mkdir -p "$CACHE_DIR/model_weights" "$CACHE_DIR/tt_metal_cache/$DEVICE" "$CACHE_DIR/logs"

# Download model weights if not present
MODEL_DIR="$CACHE_DIR/model_weights/$MODEL_NAME"
if [ ! -f "$MODEL_DIR/config.json" ]; then
    echo "Downloading $MODEL_NAME..."
    if command -v hf &>/dev/null; then
        hf download "$MODEL_NAME" --local-dir "$MODEL_DIR"
    elif command -v huggingface-cli &>/dev/null; then
        huggingface-cli download "$MODEL_NAME" --local-dir "$MODEL_DIR"
    else
        echo "ERROR: hf or huggingface-cli not found. Install with: pip install huggingface-hub"
        exit 1
    fi
else
    echo "Model weights already present at $MODEL_DIR"
fi

# Generate model spec JSON
cat > "$CACHE_DIR/model_spec.json" << SPECEOF
{
  "model_id": "id_tt-transformers_${MODEL_SHORT}_${DEVICE,,}",
  "hf_model_repo": "$MODEL_DIR",
  "model_name": "$MODEL_SHORT",
  "inference_engine": "vLLM",
  "device_type": "$DEVICE",
  "device_model_spec": {
    "device": "$DEVICE",
    "max_concurrency": 32,
    "max_context": 2048,
    "vllm_args": {
      "model": "$MODEL_DIR",
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
echo "Model spec written to $CACHE_DIR/model_spec.json"

# Save HF token if available
if [ -n "${HF_TOKEN:-}" ]; then
    echo "$HF_TOKEN" > "$CACHE_DIR/.hf_token"
    echo "HF token saved"
fi

echo "=== Model setup complete ==="
echo "Model:  $MODEL_NAME"
echo "Cache:  $CACHE_DIR"
echo "Device: $DEVICE"
