FROM python:3.13

RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 ca-certificates curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install third-party deps (extracted from python.lock)
COPY docker/requirements-agent.txt /tmp/requirements-agent.txt
RUN pip install --no-cache-dir -r /tmp/requirements-agent.txt

# Copy source tree
COPY . /app

ENV PYTHONPATH="/app/src"
ENV BACKEND_BUILD_ROOT="/app"

CMD ["python", "-m", "ai.backend.cli", "ag", "start-server", "--debug"]
