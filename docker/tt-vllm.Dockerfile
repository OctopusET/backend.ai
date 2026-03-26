FROM ghcr.io/tenstorrent/tt-inference-server/vllm-tt-metal-src-release-ubuntu-22.04-amd64:0.10.0-55fd115-aa4ae1e

# Create mountpoints for Backend.AI krunner injection
RUN mkdir -p /opt/backend.ai/lib/python3.13/site-packages/ai/backend/kernel \
    && mkdir -p /opt/backend.ai/lib/python3.13/site-packages/ai/backend/helpers \
    && mkdir -p /opt/kernel \
    && mkdir -p /home/config \
    && mkdir -p /home/work \
    && mkdir -p /home/container_app_user/cache

# Environment for vLLM on Tenstorrent
ENV TT_METAL_HOME=/home/container_app_user/tt-metal
ENV CACHE_ROOT=/home/container_app_user/cache
ENV MESH_DEVICE=P100
ENV ARCH_NAME=blackhole
ENV VLLM_TARGET_DEVICE=tt
ENV VLLM_RPC_TIMEOUT=900000
ENV HF_HUB_OFFLINE=1
ENV PYTHONPATH=/home/container_app_user/tt-metal:/home/container_app_user/app/src:/home/container_app_user/app
ENV TT_CACHE_PATH=/home/container_app_user/cache/tt_metal_cache/P100
ENV MODEL_WEIGHTS_PATH=/home/container_app_user/cache/model_weights/meta-llama/Llama-3.1-8B-Instruct
ENV TT_MODEL_SPEC_JSON_PATH=/home/container_app_user/cache/model_spec.json
ENV PATH=/home/container_app_user/tt-metal/python_env/bin:$PATH

# Backend.AI image labels
LABEL ai.backend.kernelspec=1
LABEL ai.backend.features="uid-match"
LABEL ai.backend.base-distro="ubuntu22.04"
LABEL ai.backend.runtime-type="python"
LABEL ai.backend.runtime-path="/home/container_app_user/tt-metal/python_env/bin/python3"
LABEL ai.backend.accelerators="tt"
LABEL ai.backend.resource.min.cpu=4
LABEL ai.backend.resource.min.mem=32g
LABEL ai.backend.resource.min.tt.device=1
LABEL ai.backend.role="INFERENCE"
LABEL ai.backend.endpoint-ports="Llama-3.1-8B"
LABEL ai.backend.model-path="/home/container_app_user/cache/model_weights"
LABEL ai.backend.model-format="custom"
