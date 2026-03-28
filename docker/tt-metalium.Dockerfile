FROM ghcr.io/tenstorrent/tt-metal/tt-metalium-ubuntu-22.04-release-models-amd64:latest-rc

# Create mountpoints for Backend.AI krunner injection
RUN mkdir -p /opt/backend.ai/lib/python3.13/site-packages/ai/backend/kernel \
    && mkdir -p /opt/backend.ai/lib/python3.13/site-packages/ai/backend/helpers \
    && mkdir -p /opt/kernel \
    && mkdir -p /home/config \
    && mkdir -p /home/work

# Backend.AI image labels
LABEL ai.backend.kernelspec=1
LABEL ai.backend.features="uid-match"
LABEL ai.backend.base-distro="ubuntu22.04"
LABEL ai.backend.runtime-type="python"
LABEL ai.backend.runtime-path="/opt/venv/bin/python"
LABEL ai.backend.accelerators="tt"
LABEL ai.backend.resource.min.cpu=1
LABEL ai.backend.resource.min.mem=4g
LABEL ai.backend.resource.min.tt.device=1
LABEL ai.backend.service-ports="jupyter:http:8080"
LABEL ai.backend.role="COMPUTE"
