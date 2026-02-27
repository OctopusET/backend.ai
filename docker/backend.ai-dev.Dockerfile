FROM python:3.13

RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 \
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
